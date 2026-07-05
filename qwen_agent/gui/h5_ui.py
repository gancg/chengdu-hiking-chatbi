from __future__ import annotations

import json
import logging
import os
import time
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


def save_h5_history(history: Any, now: float | None = None) -> dict[str, Any]:
    """构建带时间、版本和容量限制的浏览器聊天缓存。"""
    saved_at = int(time.time() if now is None else now)
    normalized = _normalize_h5_history(history)
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
                        self.agent_run,
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
