from __future__ import annotations

import unittest
from pathlib import Path

from hiking_chatbi.qwen_chatbi import WEB_CHATBOT_CONFIG


ROOT = Path(__file__).resolve().parents[1]


class QwenWebHikingThemeTest(unittest.TestCase):
    def test_hiking_branding_uses_project_avatar_and_title(self) -> None:
        """徒步页面应配置项目内的徒步头像和简洁标题。"""
        avatar_path = Path(WEB_CHATBOT_CONFIG["agent.avatar"])

        self.assertTrue(avatar_path.is_file(), "徒步助手头像文件必须存在")
        self.assertIn("成都", WEB_CHATBOT_CONFIG["header.title"])
        self.assertIn("山野", WEB_CHATBOT_CONFIG["header.title"])
        self.assertIn("助手", WEB_CHATBOT_CONFIG["header.title"])
        self.assertIn("徒步", WEB_CHATBOT_CONFIG["header.subtitle"])

    def test_theme_css_contains_clean_responsive_styles(self) -> None:
        """页面主题应包含清爽配色、卡片圆角和移动端适配。"""
        css = (ROOT / "qwen_agent" / "gui" / "assets" / "appBot.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("--hiking-sky", css, "主题应定义天空蓝色变量")
        self.assertIn("border-radius: 20px", css, "主要卡片应采用柔和圆角")
        self.assertIn("@media (max-width: 900px)", css, "主题应适配窄屏")


if __name__ == "__main__":
    unittest.main()
