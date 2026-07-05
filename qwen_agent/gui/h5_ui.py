from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Iterator
from html import escape
from typing import Any, List

from qwen_agent.gui.utils import convert_fncall_to_text, convert_history_to_chatbot
from qwen_agent.llm.schema import Message

from .web_ui import WebUI


logger = logging.getLogger(__name__)

H5_HISTORY_VERSION = 1
H5_HISTORY_TTL_SECONDS = 12 * 60 * 60
H5_HISTORY_MAX_MESSAGES = 100
H5_HISTORY_MAX_BYTES = 512 * 1024
H5_HISTORY_STORAGE_KEY = "chengdu-hiking-chatbi-h5-history-v1"


def collapse_h5_suggestions() -> dict[str, Any]:
    """返回用于收起 H5 快捷提问面板的组件更新。"""
    return {"open": False, "__type__": "update"}


def empty_h5_history_state() -> dict[str, Any]:
    """返回可覆盖浏览器缓存的空 H5 会话状态。"""
    return {"version": H5_HISTORY_VERSION, "saved_at": 0, "history": []}


def _normalize_h5_history(history: Any) -> list[dict[str, Any]]:
    """将 H5 历史转换为可安全写入 BrowserState 的 JSON 数据。"""
    if not isinstance(history, list):
        raise ValueError("H5 聊天历史必须是列表")
    normalized: list[dict[str, Any]] = []
    for item in history:
        if isinstance(item, Message):
            message = item
        elif isinstance(item, dict):
            message = Message.model_validate(item)
        else:
            raise ValueError("H5 聊天历史包含无效消息")
        normalized.append(message.model_dump(mode="json"))
    return normalized


def _history_state_size(history: list[dict[str, Any]], saved_at: int) -> int:
    state = {
        "version": H5_HISTORY_VERSION,
        "saved_at": saved_at,
        "history": history,
    }
    return len(json.dumps(state, ensure_ascii=False).encode("utf-8"))


def _trim_h5_history(
    history: list[dict[str, Any]], saved_at: int
) -> list[dict[str, Any]]:
    """按完整用户轮次裁剪 H5 历史，使其满足消息数和容量限制。"""
    trimmed = list(history)
    first_user_index = next(
        (index for index, item in enumerate(trimmed) if item.get("role") == "user"),
        None,
    )
    if first_user_index is None:
        return []
    trimmed = trimmed[first_user_index:]

    while (
        len(trimmed) > H5_HISTORY_MAX_MESSAGES
        or _history_state_size(trimmed, saved_at) > H5_HISTORY_MAX_BYTES
    ):
        next_user_index = next(
            (
                index
                for index, item in enumerate(trimmed[1:], start=1)
                if item.get("role") == "user"
            ),
            None,
        )
        if next_user_index is None:
            return []
        trimmed = trimmed[next_user_index:]
    return trimmed


def _h5_message_text(message: dict[str, Any]) -> str:
    """提取 H5 历史消息中的纯文本内容。"""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join(
        str(item.get("text", ""))
        for item in content
        if isinstance(item, dict) and item.get("text")
    )


def _h5_transport_choice(
    user_content: str, previous_assistant_content: str
) -> str | None:
    """识别用户唯一明确选择的自驾或报团方式。"""
    normalized = user_content.replace(" ", "")
    modes = {
        mode
        for labels, mode in ((('自驾',), "self_drive"), (("报团", "抱团"), "group_tour"))
        if any(label in normalized for label in labels)
    }
    if len(modes) == 1:
        mode = next(iter(modes))
        labels = ("自驾",) if mode == "self_drive" else ("报团", "抱团")
        if not any(
            re.search(rf"(?:不|不要|不想|并非|不是|取消).{{0,2}}{label}", normalized)
            for label in labels
        ):
            return mode

    selected = re.fullmatch(r"\s*(\d+)\s*", user_content)
    if selected is None:
        return None
    selected_number = int(selected.group(1))
    option_markers = list(
        re.finditer(r"(?<!\d)(\d+)\s*[.、．)）:：]\s*", previous_assistant_content)
    )
    for index, marker in enumerate(option_markers):
        if int(marker.group(1)) != selected_number:
            continue
        end = (
            option_markers[index + 1].start()
            if index + 1 < len(option_markers)
            else len(previous_assistant_content)
        )
        option = previous_assistant_content[marker.end():end]
        option_modes = {
            mode
            for label, mode in (("自驾", "self_drive"), ("报团", "group_tour"), ("抱团", "group_tour"))
            if label in option
        }
        return next(iter(option_modes)) if len(option_modes) == 1 else None
    return None


def _has_completed_h5_transport_confirmation(
    history: list[dict[str, Any]],
) -> bool:
    """判断最近一次明确出行方式选择是否已经得到助手文本回答。"""
    previous_assistant_content = ""
    is_waiting_for_assistant = False
    has_completed_confirmation = False
    for message in history:
        role = message.get("role")
        content = _h5_message_text(message)
        if role == "assistant":
            if is_waiting_for_assistant and content.strip():
                has_completed_confirmation = True
                is_waiting_for_assistant = False
            previous_assistant_content = content
            continue
        if role != "user":
            continue
        if _h5_transport_choice(content, previous_assistant_content) is not None:
            has_completed_confirmation = False
            is_waiting_for_assistant = True
    return has_completed_confirmation


def save_h5_history(history: Any, now: float | None = None) -> dict[str, Any]:
    """仅为已回答的明确出行方式选择构建浏览器聊天缓存。"""
    normalized = _normalize_h5_history(history)
    if not _has_completed_h5_transport_confirmation(normalized):
        return empty_h5_history_state()
    saved_at = int(time.time() if now is None else now)
    return {
        "version": H5_HISTORY_VERSION,
        "saved_at": saved_at,
        "history": _trim_h5_history(normalized, saved_at),
    }


def _convert_h5_history_to_chatbot(
    history: list[dict[str, Any]],
) -> list[list[Any]] | None:
    """从完整 Agent 历史重建只包含用户和助手气泡的聊天框。"""
    display_messages = convert_fncall_to_text(history)
    chatbot: list[list[Any]] = []
    for message in display_messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "user":
            chatbot.append([content, None])
        elif role == "assistant":
            if not chatbot or chatbot[-1][1] is not None:
                chatbot.append([None, content])
            else:
                chatbot[-1][1] = content
    return chatbot or None


def restore_h5_history(
    state: Any, now: float | None = None
) -> tuple[list[Any] | None, list[dict[str, Any]], dict[str, Any]]:
    """恢复未过期的 H5 会话；无效状态返回并写回空缓存。"""
    current_time = int(time.time() if now is None else now)
    cleared_state = empty_h5_history_state()
    try:
        if not isinstance(state, dict) or state.get("version") != H5_HISTORY_VERSION:
            raise ValueError("H5 聊天缓存版本无效")
        saved_at = state.get("saved_at")
        if isinstance(saved_at, bool) or not isinstance(saved_at, (int, float)):
            raise ValueError("H5 聊天缓存时间无效")
        if saved_at <= 0 or current_time - saved_at > H5_HISTORY_TTL_SECONDS:
            raise ValueError("H5 聊天缓存已过期")
        history = _normalize_h5_history(state.get("history"))
        if not _has_completed_h5_transport_confirmation(history):
            raise ValueError("H5 聊天缓存缺少已回答的明确出行方式")
        if _history_state_size(history, int(saved_at)) > H5_HISTORY_MAX_BYTES:
            raise ValueError("H5 聊天缓存超过容量限制")
        if len(history) > H5_HISTORY_MAX_MESSAGES:
            raise ValueError("H5 聊天缓存超过消息数限制")
        restored_state = {
            "version": H5_HISTORY_VERSION,
            "saved_at": int(saved_at),
            "history": history,
        }
        return _convert_h5_history_to_chatbot(history), history, restored_state
    except (AssertionError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.info("H5 聊天缓存不可恢复，已清空: %s", exc)
        return convert_history_to_chatbot([]), [], cleared_state


H5_PAGE_JS = r"""
() => {
  const removeFooter = () => {
    document.querySelectorAll('footer').forEach((element) => element.remove());
  };
  const removeMobileQueueWarning = () => {
    document.querySelectorAll('.toast-body.warning').forEach((element) => {
      const text = element.textContent || '';
      const isMobileQueueWarning =
        text.includes('队列中失去位置') ||
        text.includes('连接可能会中断') ||
        text.includes('connection can break');
      if (isMobileQueueWarning) {
        element.parentElement?.remove();
      }
    });
  };
  const setExternalLinkTargets = () => {
    document.querySelectorAll('a[href]').forEach((element) => {
      const href = element.getAttribute('href') || '';
      if (/^https?:\/\//i.test(href)) {
        element.setAttribute('target', '_blank');
        element.setAttribute('rel', 'noopener noreferrer');
      }
    });
  };
  const cleanPage = () => {
    removeFooter();
    removeMobileQueueWarning();
    setExternalLinkTargets();
  };
  cleanPage();
  const observer = new MutationObserver(cleanPage);
  observer.observe(document.body, { childList: true, subtree: true });
  return [];
}
"""


class H5WebUI(WebUI):
    """Mobile-first chat page with no agent sidebar or plugin controls."""

    def run_h5_agent_safely(
        self, chatbot: list[Any], history: list[Any]
    ) -> Iterator[tuple[list[Any], list[Any]]]:
        """运行 H5 Agent，并在模型失败时返回可继续交互的组件状态。"""
        try:
            yield from self.agent_run(chatbot, history)
        except Exception as exc:
            logger.warning(
                "H5 模型调用失败，已恢复页面交互 exception_type=%s",
                type(exc).__name__,
            )
            error_message = "服务暂时无法完成回答，请稍后重新提交这个问题。"
            agent_count = max(1, len(self.agent_list))
            if chatbot:
                chatbot[-1][1] = [error_message] + [None] * (agent_count - 1)
            else:
                chatbot.append([None, [error_message] + [None] * (agent_count - 1)])
            agent_name = (
                getattr(self.agent_list[0], "name", None)
                if self.agent_list
                else None
            )
            error_response = {"role": "assistant", "content": error_message}
            if agent_name:
                error_response["name"] = agent_name
            history.append(error_response)
            yield chatbot, history

    def run(
        self,
        messages: List[Message] | None = None,
        share: bool = False,
        server_name: str | None = None,
        server_port: int | None = None,
        concurrency_limit: int = 10,
        **kwargs: Any,
    ) -> Any:
        self.run_kwargs = kwargs

        from qwen_agent.gui.gradio_dep import gr, mgr, ms

        theme = gr.themes.Default(
            primary_hue=gr.themes.utils.colors.sky,
            neutral_hue=gr.themes.utils.colors.slate,
            radius_size=gr.themes.utils.sizes.radius_lg,
        )
        css_path = os.path.join(os.path.dirname(__file__), "assets", "appH5.css")

        with gr.Blocks(css_paths=css_path, theme=theme, js=H5_PAGE_JS) as demo:
            history = gr.State([])
            browser_history = gr.BrowserState(
                default_value=empty_h5_history_state(),
                storage_key=H5_HISTORY_STORAGE_KEY,
                secret=os.getenv("CHATBI_H5_STORAGE_SECRET") or None,
            )
            with ms.Application():
                with gr.Column(elem_classes="h5-shell"):
                    if self.header_title:
                        gr.HTML(
                            '<header class="h5-header">'
                            '<div class="h5-header__text">'
                            f'<h1>{escape(self.header_title)}</h1>'
                            f'<p>{escape(self.header_subtitle)}</p>'
                            "</div>"
                            "</header>"
                        )

                    chatbot = mgr.Chatbot(
                        value=convert_history_to_chatbot(messages=messages),
                        avatar_images=[self.user_config, self.agent_config_list],
                        height=640,
                        avatar_image_width=48,
                        flushing=False,
                        bubble_full_width=True,
                        show_copy_button=True,
                        elem_classes="h5-chatbot",
                    )

                    with gr.Column(elem_classes="h5-composer"):
                        input_box = mgr.MultimodalInput(
                            placeholder=self.input_placeholder,
                            sources=[],
                            elem_classes="h5-input",
                        )
                        suggestions = None
                        if self.prompt_suggestions:
                            with gr.Accordion(
                                label="快捷提问",
                                open=True,
                                elem_classes="h5-suggestions",
                            ) as suggestions:
                                gr.Examples(
                                    label=None,
                                    examples=self.prompt_suggestions[:3],
                                    inputs=[input_box],
                                )

                    audio_input = gr.State(None)
                    input_promise = input_box.submit(
                        fn=self.add_text,
                        inputs=[input_box, audio_input, chatbot, history],
                        outputs=[input_box, audio_input, chatbot, history],
                        queue=False,
                    )
                    if suggestions is not None:
                        input_promise = input_promise.then(
                            collapse_h5_suggestions,
                            outputs=[suggestions],
                            queue=False,
                        )
                    input_promise = input_promise.then(
                        save_h5_history,
                        [history],
                        [browser_history],
                        queue=False,
                    )
                    input_promise = input_promise.then(
                        self.run_h5_agent_safely,
                        [chatbot, history],
                        [chatbot, history],
                    )
                    input_promise = input_promise.then(
                        save_h5_history,
                        [history],
                        [browser_history],
                        queue=False,
                    )
                    input_promise.then(self.flushed, None, [input_box])

            demo.load(
                restore_h5_history,
                inputs=[browser_history],
                outputs=[chatbot, history, browser_history],
                queue=False,
            )

        demo.queue(default_concurrency_limit=concurrency_limit).launch(
            share=share,
            server_name=server_name,
            server_port=server_port,
        )
        return demo
