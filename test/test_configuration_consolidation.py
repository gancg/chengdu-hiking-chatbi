from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConfigurationConsolidationTest(unittest.TestCase):
    def test_environment_can_override_collector_configuration(self) -> None:
        """采集模型、接口和超时应能通过统一环境配置覆盖。"""
        environment = os.environ.copy()
        environment.update(
            {
                "CHATBI_COLLECTOR_MODEL": "test-model",
                "CHATBI_DASHSCOPE_BASE_URL": "https://api.example.test/chat",
                "CHATBI_COLLECTOR_REQUEST_TIMEOUT_SECONDS": "77",
            }
        )
        command = [
            sys.executable,
            "-c",
            (
                "import json; from hiking_chatbi import config; "
                "print(json.dumps([config.COLLECTOR_MODEL, "
                "config.DASHSCOPE_CHAT_COMPLETIONS_URL, "
                "config.COLLECTOR_REQUEST_TIMEOUT_SECONDS]))"
            ),
        ]

        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            ["test-model", "https://api.example.test/chat", 77],
            json.loads(completed.stdout),
            "统一配置应完整采用采集环境变量",
        )

    def test_holiday_calendar_is_maintained_as_data(self) -> None:
        """节假日日历应放在数据文件中，不再嵌入 Python 源码。"""
        calendar_path = ROOT / "data" / "holidays.json"

        self.assertTrue(calendar_path.is_file(), "应提供可独立维护的节假日数据文件")
        payload = json.loads(calendar_path.read_text(encoding="utf-8"))
        self.assertIn("2026", payload["calendars"], "数据文件应保留 2026 年节假日")

    def test_environment_example_documents_configuration(self) -> None:
        """示例环境文件应列出关键配置且不得填写真实密钥。"""
        content = (ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("CHATBI_QWEN_MODEL=", content, "应说明主对话模型配置")
        self.assertIn("CHATBI_COLLECTOR_MODEL=", content, "应说明采集模型配置")
        self.assertIn("DASHSCOPE_API_KEY=", content, "应说明 DashScope 密钥名称")
        self.assertNotIn("sk-", content, "示例文件不得包含疑似真实密钥")


if __name__ == "__main__":
    unittest.main()
