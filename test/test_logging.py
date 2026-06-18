from __future__ import annotations

import logging
import os
import unittest
from unittest.mock import patch

from hiking_chatbi.logging_config import configure_logging
from hiking_chatbi.weather import MockAlertProvider, estimate_route_weather
from datetime import datetime, timedelta


class LoggingTest(unittest.TestCase):
    def test_configure_logging_uses_environment_level(self) -> None:
        """日志配置应读取环境变量中的日志级别。"""
        with patch.dict(os.environ, {"CHATBI_LOG_LEVEL": "DEBUG"}):
            configure_logging(force=True)

        self.assertEqual(logging.DEBUG, logging.getLogger().level, "根日志级别应为 DEBUG")
        self.addCleanup(configure_logging, True)

    def test_alert_provider_failure_writes_warning_log(self) -> None:
        """预警服务降级时应输出包含异常原因的警告日志。"""
        start = datetime.now().astimezone() + timedelta(days=1)
        route = {
            "id": "test-route",
            "difficulty": "easy",
            "latitude": 30.0,
            "longitude": 103.0,
        }

        with self.assertLogs("hiking_chatbi.weather", level="WARNING") as logs:
            estimate_route_weather(
                route,
                start,
                start + timedelta(hours=2),
                MockAlertProvider(error=RuntimeError("预警服务超时")),
            )

        self.assertIn("预警服务超时", "\n".join(logs.output), "日志应包含降级原因")

    def test_configure_logging_limits_third_party_debug_noise(self) -> None:
        """DEBUG 模式下第三方网络库默认不应输出底层连接调试日志。"""
        with patch.dict(os.environ, {"CHATBI_LOG_LEVEL": "DEBUG"}, clear=False):
            configure_logging(force=True)

        self.assertEqual(logging.DEBUG, logging.getLogger().level, "根日志级别应为 DEBUG")
        self.assertEqual(logging.WARNING, logging.getLogger("httpcore").level, "httpcore 默认应压到 WARNING")
        self.assertEqual(logging.WARNING, logging.getLogger("httpx").level, "httpx 默认应压到 WARNING")
        self.assertEqual(
            logging.WARNING,
            logging.getLogger("huggingface_hub").level,
            "huggingface_hub 默认应压到 WARNING",
        )
        self.addCleanup(configure_logging, True)

    def test_configure_logging_allows_third_party_debug_override(self) -> None:
        """需要排查第三方库时应允许显式打开第三方 DEBUG 日志。"""
        with patch.dict(
            os.environ,
            {"CHATBI_LOG_LEVEL": "DEBUG", "CHATBI_THIRD_PARTY_LOG_LEVEL": "DEBUG"},
            clear=False,
        ):
            configure_logging(force=True)

        self.assertEqual(logging.DEBUG, logging.getLogger("httpcore").level, "应允许显式打开 httpcore DEBUG")
        self.addCleanup(configure_logging, True)


if __name__ == "__main__":
    unittest.main()
