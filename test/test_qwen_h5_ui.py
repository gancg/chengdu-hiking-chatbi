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
        self.assertIn("gr.BrowserState", source, "H5 必须使用浏览器本地状态保存聊天记录")
        self.assertIn("restore_h5_history", source, "页面加载时必须恢复有效聊天记录")
        self.assertIn("save_h5_history", source, "用户和助手消息完成后必须保存聊天记录")
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

    def test_h5_external_links_open_in_new_window(self) -> None:
        """H5 的 HTTP 外链应在新窗口打开，避免替换当前聊天页面。"""
        source = (ROOT / "qwen_agent" / "gui" / "h5_ui.py").read_text(encoding="utf-8")

        self.assertIn("setExternalLinkTargets", source, "必须处理动态生成的外部链接")
        self.assertIn("target', '_blank'", source, "外链必须在新窗口打开")
        self.assertIn("noopener noreferrer", source, "外链必须隔离 opener")

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

    def test_h5_chat_content_wrap_uses_more_horizontal_space(self) -> None:
        """聊天内容包装层应横向铺满，并减少两侧无效留白。"""
        source = (ROOT / "qwen_agent" / "gui" / "h5_ui.py").read_text(
            encoding="utf-8"
        )
        css = (ROOT / "qwen_agent" / "gui" / "assets" / "appH5.css").read_text(
            encoding="utf-8"
        )

        self.assertIn(".h5-chatbot .wrap", css, "包装层规则必须限定在 H5 Chatbot 内")
        self.assertIn("max-width: none !important", css, "包装层不得保留最大宽度限制")
        self.assertIn("padding-inline: 5px !important", css, "聊天内容两侧留白必须压缩")
        self.assertIn(
            ".gradio-container main.fillable",
            css,
            "主内容区留白规则必须限定在 H5 Gradio 页面",
        )
        self.assertIn(
            "padding-inline: 8px !important",
            css,
            "主内容区左右默认留白必须压缩",
        )
        self.assertIn("bubble_full_width=True", source, "机器人气泡必须启用完整可用宽度")
        self.assertIn(
            ".h5-chatbot .bot-row.bubble > .avatar-container",
            css,
            "头像间距规则必须仅作用于 H5 机器人消息",
        )
        self.assertIn("margin-right: 5px", css, "机器人头像与气泡的间距必须压缩")
        self.assertIn(
            "max-width: calc(100% - 53px)",
            css,
            "机器人气泡最大宽度必须占满头像之外的剩余空间",
        )

    def test_h5_suggestions_are_collapsible_and_close_after_submit(self) -> None:
        """快捷提问应默认展开，并在用户提交问题后自动收缩。"""
        source = (ROOT / "qwen_agent" / "gui" / "h5_ui.py").read_text(
            encoding="utf-8"
        )
        css = (ROOT / "qwen_agent" / "gui" / "assets" / "appH5.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("gr.Accordion(", source, "快捷提问必须使用可点击的折叠面板")
        self.assertIn('label="快捷提问"', source, "折叠面板必须保留快捷提问标题")
        self.assertIn("open=True", source, "快捷提问初始化时必须展开")
        self.assertIn(
            "collapse_h5_suggestions",
            source,
            "用户提交问题后必须触发快捷提问收缩",
        )
        self.assertIn(
            '"open": False',
            source,
            "提交后的组件更新必须关闭快捷提问面板",
        )
        self.assertIn(".h5-suggestions", css, "折叠面板必须保留 H5 专用样式")
        self.assertIn(
            "min-height: 32px",
            css,
            "快捷提问折叠标题必须使用紧凑高度",
        )
        self.assertIn(
            "padding-block: 2px",
            css,
            "快捷提问折叠标题必须压缩纵向内边距",
        )

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
        self.assertIn(
            "padding: max(2px, env(safe-area-inset-top))",
            css,
            "页面顶部必须贴近安全区域，为聊天框释放空间",
        )
        self.assertIn("gap: 4px !important", css, "标题与聊天框之间必须使用紧凑间距")

    def test_h5_input_and_submit_button_share_one_row(self) -> None:
        """输入框和提交按钮应在同一行，以释放聊天框纵向空间。"""
        source = (ROOT / "qwen_agent" / "gui" / "h5_ui.py").read_text(
            encoding="utf-8"
        )
        css = (ROOT / "qwen_agent" / "gui" / "assets" / "appH5.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('elem_classes="h5-input"', source, "H5 输入组件必须有独立样式类")
        self.assertIn(".h5-input", css, "必须提供 H5 输入组件样式")
        self.assertIn(
            "grid-template-columns: minmax(0, 1fr) auto",
            css,
            "输入框和提交按钮必须使用弹性双列布局",
        )
        self.assertIn("margin-top: 0 !important", css, "提交按钮区不得保留默认上边距")
        self.assertIn(".input-tools:empty", css, "空工具区不得占用横向空间")

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
