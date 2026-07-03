from __future__ import annotations

import unittest
from pathlib import Path

from hiking_chatbi.qwen_chatbi import WEB_CHATBOT_CONFIG


class QwenWebUserAvatarTest(unittest.TestCase):
    def test_user_uses_akita_avatar_from_project_assets(self) -> None:
        """Gradio 用户应使用项目内的秋田犬头像。"""
        avatar_path = Path(WEB_CHATBOT_CONFIG["user.avatar"])

        self.assertTrue(avatar_path.is_file(), "秋田犬用户头像文件必须存在")
        self.assertEqual("akita-user-avatar.png", avatar_path.name)
        self.assertNotEqual(
            WEB_CHATBOT_CONFIG["agent.avatar"],
            WEB_CHATBOT_CONFIG["user.avatar"],
            "用户头像和徒步助手头像应分别配置",
        )


if __name__ == "__main__":
    unittest.main()
