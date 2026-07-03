from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qwen_agent.llm.schema import ASSISTANT, Message

from hiking_chatbi.config import SAMPLE_DATA_PATH
from hiking_chatbi.qwen_chatbi import (
    build_qwen_agent,
    trim_completed_trip_context,
)
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider


class QwenCallStabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.service = ChatBIService(
            Path(self.temp.name) / "test.db",
            NoTrafficProvider(),
        )
        self.service.seed(SAMPLE_DATA_PATH)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_new_user_message_resets_completed_trip_context(self) -> None:
        """中文测试：路线和交通方式确认后的下一条消息应开启全新上下文。"""
        messages = [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "我选择青城后山环线"},
            {"role": "assistant", "content": "请选择交通方式：1. 自驾 2. 报团"},
            {"role": "user", "content": "自驾"},
            {"role": "assistant", "content": "已给出停车点和最终方案"},
            {"role": "user", "content": "我想重新找一条看雪山的路线"},
        ]

        trimmed = trim_completed_trip_context(messages, self.service.routes())

        self.assertEqual("system", trimmed[0]["role"])
        self.assertEqual("我想重新找一条看雪山的路线", trimmed[1]["content"])
        self.assertEqual(2, len(trimmed), "新任务不得携带旧路线、交通方式或工具结果")

    def test_transport_confirmation_itself_keeps_current_context(self) -> None:
        """中文测试：确认交通方式的当前轮仍需保留路线选择上下文。"""
        messages = [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "我选择青城后山环线"},
            {"role": "assistant", "content": "请选择交通方式：1. 自驾 2. 报团"},
            {"role": "user", "content": "自驾"},
        ]

        self.assertEqual(
            messages,
            trim_completed_trip_context(messages, self.service.routes()),
            "当前确认轮需要旧路线才能调用停车点工具",
        )

    def test_agent_uses_configured_retry_limit(self) -> None:
        """中文测试：聊天模型重试上限应可配置且默认不再放大为三次。"""
        with patch("hiking_chatbi.qwen_chatbi.QWEN_MAX_RETRIES", 2):
            agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertEqual(2, agent.llm.max_retries)

    def test_single_turn_has_model_call_limit(self) -> None:
        """中文测试：模型持续请求工具时，单轮调用也必须在配置上限处停止。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")
        tool_output = [Message(
            role=ASSISTANT,
            content="",
            function_call={"name": "resolve_departure_date", "arguments": "{}"},
        )]
        model_call_count = 0

        def call_llm(**kwargs: object) -> object:
            nonlocal model_call_count
            model_call_count += 1
            return iter([tool_output])

        with (
            patch("hiking_chatbi.qwen_chatbi.QWEN_MAX_LLM_CALLS", 2),
            patch.object(agent, "_call_llm", side_effect=call_llm),
            patch.object(agent, "_call_tool", return_value="{}"),
        ):
            list(agent._run_one_tool_at_a_time([], "zh"))

        self.assertEqual(2, model_call_count, "模型调用次数不得突破单轮硬上限")
        self.assertEqual(2, agent._last_tool_call_count, "工具调用次数应被同一上限约束")


if __name__ == "__main__":
    unittest.main()
