from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QwenH5UiTest(unittest.TestCase):
    def test_h5_uses_an_independent_minimal_component_tree(self) -> None:
        """H5 应使用独立页面，并且不创建助手侧栏和插件列表。"""
        source = (ROOT / "qwen_agent" / "gui" / "h5_ui.py").read_text(encoding="utf-8")

        self.assertIn("class H5WebUI", source, "必须提供独立 H5 页面类")
        self.assertIn("prompt_suggestions[:3]", source, "H5 最多展示前三条快捷问题")
        self.assertNotIn("visible=False", source, "对话后必须继续显示快捷问题")
        self.assertNotIn("_add_h5_text", source, "H5 应直接复用提交逻辑，不得隐藏快捷问题")
        self.assertIn("H5_PAGE_JS", source, "必须在页面加载后移除 Gradio 页脚")
        self.assertIn(
            "removeMobileQueueWarning",
            source,
            "H5 必须移除 Gradio 的移动端队列通用警告",
        )
        self.assertIn(
            ".toast-body.warning",
            source,
            "只能在 Warning 提示中识别移动端队列警告",
        )
        self.assertIn(
            "队列中失去位置",
            source,
            "必须按警告文本精确识别，不得隐藏所有业务警告",
        )
        self.assertNotIn("_create_agent_plugins_block", source, "H5 不得创建插件列表")
        self.assertNotIn("_create_agent_info_block", source, "H5 不得创建助手侧栏")

    def test_h5_header_uses_short_title_without_agent_logo(self) -> None:
        """H5 应使用短标题，并且不在右上角展示助手图标。"""
        ui_source = (ROOT / "qwen_agent" / "gui" / "h5_ui.py").read_text(
            encoding="utf-8"
        )
        app_source = (ROOT / "hiking_chatbi" / "qwen_chatbi.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"header.title": "成都徒步ChatBI助手"', app_source, "H5 必须使用短标题")
        self.assertNotIn("h5-header__logo", ui_source, "H5 顶部不得创建助手图标")
        self.assertNotIn(
            'agent_config_list[0]["avatar"]',
            ui_source,
            "H5 顶部不得读取助手头像",
        )
        self.assertIn("css_paths=css_path", ui_source, "H5 必须通过 Gradio CSS 路径参数加载样式")

        css = (ROOT / "qwen_agent" / "gui" / "assets" / "appH5.css").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(".h5-header__logo", css, "H5 样式不得保留顶部图标规则")

    def test_h5_suggestions_use_one_full_width_row_per_question(self) -> None:
        """快捷提问应纵向排列，每个问题独占一整行。"""
        css = (ROOT / "qwen_agent" / "gui" / "assets" / "appH5.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("flex-direction: column", css, "快捷提问必须纵向排列")
        self.assertIn("width: 100% !important", css, "每条快捷提问必须占满一行")

    def test_h5_chatbot_grows_and_keeps_suggestions_at_bottom(self) -> None:
        """聊天框应填满剩余高度，输入框和快捷提问整体位于底部。"""
        css = (ROOT / "qwen_agent" / "gui" / "assets" / "appH5.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("display: grid !important", css, "H5 主容器必须使用网格布局")
        self.assertIn(
            "grid-template-rows: auto minmax(0, 1fr) auto",
            css,
            "聊天框必须占用标题和底部输入区域之间的剩余高度",
        )
        self.assertIn("flex: 0 0 auto !important", css, "底部输入区域不得参与拉伸")

    def test_h5_css_is_mobile_first_and_hides_gradio_footer(self) -> None:
        """H5 独立样式应适配动态视口、安全区域和长内容。"""
        css = (ROOT / "qwen_agent" / "gui" / "assets" / "appH5.css").read_text(
            encoding="utf-8"
        )

        for marker in (
            "100dvh",
            "env(safe-area-inset-bottom)",
            "overflow-x: hidden",
            "footer",
            'footer[class*="svelte-"]',
            "display: none",
        ):
            self.assertIn(marker, css, f"H5 样式缺少：{marker}")

    def test_existing_web_css_has_no_h5_rules(self) -> None:
        """现有 Web 样式不得混入 H5 专用规则。"""
        css = (ROOT / "qwen_agent" / "gui" / "assets" / "appBot.css").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("h5-shell", css, "Web 样式不应包含 H5 页面规则")


if __name__ == "__main__":
    unittest.main()
