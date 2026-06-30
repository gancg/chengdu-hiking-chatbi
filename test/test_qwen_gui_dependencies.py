from __future__ import annotations

import unittest
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class QwenGuiDependenciesTest(unittest.TestCase):
    def test_requirements_enable_qwen_gui_extra(self) -> None:
        """依赖清单应启用固定版本的 Qwen Agent GUI 扩展。"""
        requirements = {
            line.strip().lower()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn(
            "qwen-agent[gui]==0.0.34",
            requirements,
            "requirements.txt 应声明 qwen-agent[gui]==0.0.34",
        )
        self.assertIn(
            "soundfile==0.13.1",
            requirements,
            "requirements.txt 应声明 Qwen Agent 运行时需要的 soundfile",
        )

    def test_installed_qwen_gui_versions_are_compatible(self) -> None:
        """当前 Python 环境中的 Qwen GUI 关键依赖版本应完全兼容。"""
        expected_versions = {
            "qwen-agent": "0.0.34",
            "gradio": "5.23.1",
            "gradio-client": "1.8.0",
            "modelscope-studio": "1.1.7",
            "pydantic": "2.9.2",
            "pydantic-core": "2.23.4",
            "soundfile": "0.13.1",
        }

        for package_name, expected_version in expected_versions.items():
            with self.subTest(package_name=package_name):
                try:
                    installed_version = version(package_name)
                except PackageNotFoundError as exc:
                    self.fail(f"缺少 Qwen GUI 依赖 {package_name}: {exc}")
                self.assertEqual(
                    expected_version,
                    installed_version,
                    f"{package_name} 版本不兼容，应为 {expected_version}，"
                    f"实际为 {installed_version}",
                )


if __name__ == "__main__":
    unittest.main()
