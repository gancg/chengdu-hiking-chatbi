from __future__ import annotations

import unittest

from hiking_chatbi.qwen_chatbi import WEB_CHATBOT_CONFIG


class QwenWebTextInputTest(unittest.TestCase):
    def test_hiking_web_ui_disables_upload_and_audio(self) -> None:
        """徒步 WebUI 应只保留文本输入，不展示上传和音频组件。"""
        self.assertFalse(
            WEB_CHATBOT_CONFIG["input.upload.enabled"],
            "业务界面必须关闭文件上传入口",
        )
        self.assertFalse(
            WEB_CHATBOT_CONFIG["input.audio.enabled"],
            "业务界面必须关闭麦克风录音组件",
        )


if __name__ == "__main__":
    unittest.main()
