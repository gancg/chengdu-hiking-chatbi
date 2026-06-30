from __future__ import annotations

import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from qwen_agent.agents import Assistant
from qwen_agent.llm.base import ModelServiceError

from hiking_chatbi.qwen_chatbi import GuidedHikingAssistant


class QwenConversationLoggingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assistant = object.__new__(GuidedHikingAssistant)
        self.assistant.llm = SimpleNamespace(model="qwen-plus")

    def test_conversation_failure_logs_diagnostics_without_user_content(self) -> None:
        """对话流失败时应记录调用信息和堆栈，但不得打印用户原文。"""
        user_content = "这是不得出现在日志里的用户路线偏好"

        def broken_stream():
            raise ModelServiceError(code="429", message="rate limited")
            yield []

        with patch.object(Assistant, "_run", return_value=broken_stream()):
            with self.assertLogs("hiking_chatbi.qwen_chatbi", level="INFO") as logs:
                with self.assertRaises(ModelServiceError):
                    list(self.assistant._run([
                        {"role": "user", "content": user_content},
                    ]))

        output = "\n".join(logs.output)
        self.assertIn("Qwen Agent 对话调用开始", output)
        self.assertIn("Qwen Agent 对话调用失败", output)
        self.assertIn("model=qwen-plus", output)
        self.assertIn("message_count=1", output)
        self.assertIn("user_turns=1", output)
        self.assertIn(f"last_user_chars={len(user_content)}", output)
        self.assertIn("exception_type=ModelServiceError", output)
        self.assertIn("exception_code=429", output)
        self.assertIn("exception_message=rate limited", output)
        self.assertNotIn(user_content, output, "错误日志不得包含完整用户输入")
        call_ids = re.findall(r"call_id=([0-9a-f]+)", output)
        self.assertEqual(1, len(set(call_ids)), "开始和失败日志应使用同一 call_id")

    def test_conversation_success_logs_batch_count_and_elapsed_time(self) -> None:
        """对话流正常完成时应记录响应批次数和耗时。"""
        with patch.object(Assistant, "_run", return_value=iter([["first"], ["second"]])):
            with self.assertLogs("hiking_chatbi.qwen_chatbi", level="INFO") as logs:
                responses = list(self.assistant._run([
                    {"role": "user", "content": "周六出发"},
                ]))

        self.assertEqual([["first"], ["second"]], responses)
        output = "\n".join(logs.output)
        self.assertIn("Qwen Agent 对话调用完成", output)
        self.assertIn("output_batches=2", output)
        self.assertRegex(output, r"elapsed_ms=\d+")


if __name__ == "__main__":
    unittest.main()
