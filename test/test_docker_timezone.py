from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class DockerTimezoneTest(unittest.TestCase):
    def test_dockerfile_defaults_to_shanghai_timezone(self) -> None:
        """Docker 镜像必须默认使用上海时区。"""
        content = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn(
            "TZ=Asia/Shanghai",
            content,
            "Dockerfile 缺少 TZ=Asia/Shanghai，容器可能按 UTC 解析相对日期",
        )

    def test_compose_explicitly_uses_shanghai_timezone(self) -> None:
        """Compose 部署必须显式指定上海时区。"""
        content = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")

        self.assertIn(
            "TZ: Asia/Shanghai",
            content,
            "compose.yaml 缺少上海时区配置，部署环境可能与本地日期不一致",
        )
