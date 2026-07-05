from __future__ import annotations

import unittest

from qwen_agent.gui.h5_ui import (
    H5_HISTORY_MAX_BYTES,
    H5_HISTORY_MAX_MESSAGES,
    H5_HISTORY_TTL_SECONDS,
    restore_h5_history,
    save_h5_history,
)


class H5HistoryPersistenceTest(unittest.TestCase):
    def test_save_and_restore_recent_history(self) -> None:
        """12 小时内应恢复用户消息、助手回复和 Agent 上下文。"""
        history = [
            {"role": "user", "content": "想去巴朗山"},
            {"role": "assistant", "content": "你计划哪一天出发？", "name": "徒步助手"},
        ]

        state = save_h5_history(history, now=1_000)
        chatbot, restored_history, restored_state = restore_h5_history(
            state, now=1_000 + H5_HISTORY_TTL_SECONDS - 1
        )

        self.assertEqual(history, restored_history, "恢复后的 Agent 历史必须保持一致")
        self.assertEqual(state, restored_state, "有效缓存不应被改写")
        self.assertIn("想去巴朗山", str(chatbot), "聊天框必须恢复用户消息")
        self.assertIn("你计划哪一天出发", str(chatbot), "聊天框必须恢复助手回复")

    def test_expired_history_is_cleared(self) -> None:
        """超过 12 小时的缓存必须清空。"""
        state = save_h5_history([{"role": "user", "content": "旧消息"}], now=1_000)

        chatbot, history, cleared_state = restore_h5_history(
            state, now=1_000 + H5_HISTORY_TTL_SECONDS + 1
        )

        self.assertEqual([], history, "过期历史不得恢复")
        self.assertNotIn("旧消息", str(chatbot), "聊天框不得显示过期消息")
        self.assertEqual([], cleared_state["history"], "浏览器中的过期缓存必须被清空")

    def test_invalid_or_incompatible_history_is_cleared(self) -> None:
        """损坏或版本不兼容的缓存不得导致页面加载失败。"""
        invalid_states = [
            "broken",
            {"version": 999, "saved_at": 1_000, "history": []},
            {"version": 1, "saved_at": 1_000, "history": [{"role": "unknown", "content": "x"}]},
        ]

        for state in invalid_states:
            with self.subTest(state=state):
                _chatbot, history, cleared_state = restore_h5_history(state, now=1_001)
                self.assertEqual([], history, "无效缓存必须回退为空会话")
                self.assertEqual([], cleared_state["history"], "无效缓存必须被覆盖清理")

    def test_history_is_trimmed_from_complete_user_turn(self) -> None:
        """消息数超限时应保留最近会话，并从完整用户轮次开始。"""
        history = []
        for index in range(H5_HISTORY_MAX_MESSAGES + 10):
            role = "user" if index % 2 == 0 else "assistant"
            history.append({"role": role, "content": f"消息 {index}"})

        state = save_h5_history(history, now=1_000)

        self.assertLessEqual(len(state["history"]), H5_HISTORY_MAX_MESSAGES)
        self.assertEqual("user", state["history"][0]["role"], "裁剪后必须从用户轮次开始")
        self.assertEqual("消息 109", state["history"][-1]["content"], "必须保留最新消息")

    def test_history_is_trimmed_below_storage_size_limit(self) -> None:
        """缓存 JSON 必须限制在 512 KB 以内。"""
        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": "川" * 30_000}
            for index in range(30)
        ]

        state = save_h5_history(history, now=1_000)
        encoded = __import__("json").dumps(state, ensure_ascii=False).encode("utf-8")

        self.assertLessEqual(len(encoded), H5_HISTORY_MAX_BYTES, "缓存不得超过容量上限")
        if state["history"]:
            self.assertEqual("user", state["history"][0]["role"])


if __name__ == "__main__":
    unittest.main()

