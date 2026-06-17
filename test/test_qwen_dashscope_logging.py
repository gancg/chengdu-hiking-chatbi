from __future__ import annotations

import unittest
from types import SimpleNamespace

from qwen_agent.llm.base import ModelServiceError
from qwen_agent.llm.qwen_dashscope import QwenChatAtDS


class QwenDashScopeLoggingTest(unittest.TestCase):
    def test_stream_error_logs_dashscope_diagnostics(self) -> None:
        """DashScope 流式错误应记录状态码、错误码、request_id 和 chunk 位置。"""
        chunk = SimpleNamespace(
            status_code=500,
            code="InternalError",
            message="upstream failed",
            request_id="req-123",
        )

        with self.assertLogs("qwen_agent_logger", level="ERROR") as logs:
            with self.assertRaises(ModelServiceError):
                list(QwenChatAtDS._full_stream_output(
                    [chunk],
                    context={
                        "model": "qwen-plus",
                        "stream": True,
                        "delta_stream": False,
                    },
                ))

        output = "\n".join(logs.output)
        self.assertIn("DashScope model call failed", output, "应明确标识 DashScope 调用失败")
        self.assertIn("model=qwen-plus", output, "应记录模型名称")
        self.assertIn("status_code=500", output, "应记录 HTTP 状态码")
        self.assertIn("code=InternalError", output, "应记录 DashScope 错误码")
        self.assertIn("request_id=req-123", output, "应记录 request_id 方便排查服务端日志")
        self.assertIn("chunk_index=0", output, "应记录失败 chunk 位置")
        self.assertIn("received_chunks=0", output, "应记录失败前成功收到的 chunk 数")

    def test_stream_iteration_exception_logs_exception_details(self) -> None:
        """DashScope SDK 直接抛异常时应记录异常类型、异常文本和流式位置。"""

        def broken_stream():
            raise ConnectionError("connection reset by peer")
            yield

        with self.assertLogs("qwen_agent_logger", level="ERROR") as logs:
            with self.assertRaises(ConnectionError):
                list(QwenChatAtDS._full_stream_output(
                    broken_stream(),
                    context={
                        "model": "qwen-plus",
                        "stream": True,
                        "delta_stream": False,
                    },
                ))

        output = "\n".join(logs.output)
        self.assertIn("DashScope model call raised", output, "应明确标识 DashScope SDK 异常")
        self.assertIn("model=qwen-plus", output, "应记录模型名称")
        self.assertIn("stream=True", output, "应记录是否为流式调用")
        self.assertIn("exception_type=ConnectionError", output, "应记录异常类型")
        self.assertIn("exception_message=connection reset by peer", output, "应记录异常文本")
        self.assertIn("chunk_index=0", output, "应记录异常发生时的 chunk 位置")
        self.assertIn("received_chunks=0", output, "应记录异常前成功收到的 chunk 数")


if __name__ == "__main__":
    unittest.main()
