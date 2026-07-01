from __future__ import annotations

import unittest

from hiking_chatbi.youxiake_collector import (
    PlaywrightFetcher,
    collect_routes,
    deduplicate_candidates,
    merge_site_and_model,
    validate_output,
)


class YouxiakeCollectorTest(unittest.TestCase):
    def test_close_does_not_hide_disconnected_driver_error(self) -> None:
        """中文测试：浏览器驱动已断开时清理操作不得再次抛错。"""
        class BrokenResource:
            def close(self) -> None:
                raise RuntimeError("Connection closed while reading from the driver")

            def stop(self) -> None:
                raise RuntimeError("driver already stopped")

        fetcher = PlaywrightFetcher.__new__(PlaywrightFetcher)
        fetcher._browser = BrokenResource()
        fetcher._playwright = BrokenResource()
        fetcher.close()

    def test_deduplicate_candidates_keeps_first_hiking_item(self) -> None:
        """中文测试：徒步候选应按链接和名称去重并排除非徒步产品。"""
        items = [
            {"name": "别立牧场徒步", "url": "/lines.html?id=59172"},
            {"name": "别立牧场徒步", "url": "https://m.youxiake.com/lines.html?id=59172"},
            {"name": "古镇纯玩", "url": "/lines.html?id=1"},
        ]
        self.assertEqual(
            deduplicate_candidates(items),
            [{"name": "别立牧场徒步", "url": "https://m.youxiake.com/lines.html?id=59172"}],
            "候选筛选或去重结果不符合预期",
        )

    def test_site_value_has_priority_over_model_value(self) -> None:
        """中文测试：网页事实必须优先，模型只能补充空字段。"""
        merged = merge_site_and_model(
            {"distance_km": 12.0, "ascent_m": None},
            {"distance_km": 9.0, "ascent_m": 600},
        )
        self.assertEqual(merged["distance_km"], 12.0, "模型错误覆盖了网页距离")
        self.assertEqual(merged["ascent_m"], 600, "模型没有补充网页缺失字段")

    def test_output_rejects_wrong_count_with_clear_error(self) -> None:
        """中文测试：最终文件数量不足时应输出明确错误信息。"""
        with self.assertRaisesRegex(ValueError, "路线数量必须为 40，实际为 0"):
            validate_output({"routes": []})

    def test_output_rejects_extra_root_field(self) -> None:
        """中文测试：根对象包含额外字段时应明确拒绝。"""
        with self.assertRaisesRegex(ValueError, "根对象必须只包含 routes 数组"):
            validate_output({"routes": [], "extra": True})

    def test_collection_reports_insufficient_candidates(self) -> None:
        """中文测试：翻页结束后候选不足应报告实际成功数量。"""
        with self.assertRaisesRegex(RuntimeError, "路线不足 40 条，实际 0 条"):
            collect_routes(lambda page: [], lambda url: "", lambda text, site: {})

    def test_collection_stops_when_captcha_is_present(self) -> None:
        """中文测试：详情页出现验证码时必须停止且不得尝试绕过。"""
        candidates = [{"name": "青城山徒步", "url": "/lines.html?id=123"}]
        with self.assertRaisesRegex(RuntimeError, "页面出现验证码，已停止采集"):
            collect_routes(
                lambda page: candidates if page == 1 else [],
                lambda url: "安全验证码",
                lambda text, site: {},
                count=1,
            )


if __name__ == "__main__":
    unittest.main()
