from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hiking_chatbi.config as config
import hiking_chatbi.qwen_chatbi as qwen_chatbi
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider


class QwenStreamTimeoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.service = ChatBIService(
            Path(self.temp.name) / "test.db",
            NoTrafficProvider(),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_agent_uses_explicit_stream_request_timeout(self) -> None:
        """Qwen 流式调用必须显式设置读取超时，避免页面无限等待。"""
        with patch.object(qwen_chatbi, "QWEN_REQUEST_TIMEOUT_SECONDS", 20):
            agent = qwen_chatbi.build_qwen_agent(self.service, model="qwen-plus")

        self.assertEqual(20, agent.llm.generate_cfg["request_timeout"])

    def test_request_timeout_can_be_configured_from_environment(self) -> None:
        """Qwen 流式读取超时应允许通过环境变量覆盖。"""
        with patch.dict(
            os.environ,
            {"CHATBI_QWEN_REQUEST_TIMEOUT_SECONDS": "35"},
        ):
            reloaded_config = importlib.reload(config)
        self.addCleanup(importlib.reload, config)

        self.assertEqual(35, reloaded_config.QWEN_REQUEST_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
