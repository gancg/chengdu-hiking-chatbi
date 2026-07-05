from __future__ import annotations

import unittest
from pathlib import Path

from hiking_chatbi import config


ROOT = Path(__file__).resolve().parents[1]


class H5ConfigurationTest(unittest.TestCase):
    def test_h5_has_an_independent_default_address(self) -> None:
        """H5 默认地址应与 WebUI 端口分离。"""
        self.assertEqual("127.0.0.1", config.H5_HOST)
        self.assertEqual(7861, config.H5_PORT)
        self.assertNotEqual(config.WEB_PORT, config.H5_PORT)

    def test_runtime_files_publish_the_h5_port(self) -> None:
        """环境示例、镜像和 Compose 应声明 H5 端口。"""
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

        self.assertIn("CHATBI_H5_PORT=7861", env_example)
        self.assertIn("EXPOSE 8000 7860 7861", dockerfile)
        self.assertIn('"7861:7861"', compose)


if __name__ == "__main__":
    unittest.main()
