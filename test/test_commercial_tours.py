from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from hiking_chatbi.config import SAMPLE_COMMERCIAL_TOURS_PATH, SAMPLE_DATA_PATH
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider


class CommercialTourTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "test.db"
        self.service = ChatBIService(db_path, NoTrafficProvider())
        self.service.seed(SAMPLE_DATA_PATH, SAMPLE_COMMERCIAL_TOURS_PATH)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_imports_reviewed_commercial_tours_for_reviewed_routes(self) -> None:
        """商团产品导入后，应只返回已审核路线关联的已审核产品。"""
        results = self.service.commercial_tours({}, current_date=date(2026, 6, 17))

        self.assertGreaterEqual(len(results), 1, "应至少返回一条已审核商团产品")
        self.assertTrue(
            all(item["product"]["reviewed"] for item in results),
            "商团推荐不得返回未审核产品",
        )
        self.assertTrue(
            all(item["route"]["id"] for item in results),
            "每条商团产品都应关联路线摘要",
        )

    def test_without_departure_date_keeps_only_future_departures(self) -> None:
        """未指定出发日期时，应过滤当前日期之前的历史团期。"""
        results = self.service.commercial_tours({}, current_date=date(2026, 6, 17))

        for item in results:
            self.assertNotIn(
                "2026-06-15",
                item["available_departure_dates"],
                "历史团期不应出现在无日期查询结果中",
            )
            self.assertTrue(
                all(day >= "2026-06-17" for day in item["available_departure_dates"]),
                "无日期查询只应保留未来可用团期",
            )

    def test_departure_date_matches_strictly(self) -> None:
        """指定出发日期时，只应返回当天有团期的商团产品。"""
        matched = self.service.commercial_tours(
            {"departure_date": "2026-06-20"},
            current_date=date(2026, 6, 17),
        )
        missing = self.service.commercial_tours(
            {"departure_date": "2026-06-18"},
            current_date=date(2026, 6, 17),
        )

        self.assertGreater(len(matched), 0, "当天有收录团期时应返回结果")
        self.assertTrue(
            all(item["available_departure_dates"] == ["2026-06-20"] for item in matched),
            "指定日期查询不得返回其他日期",
        )
        self.assertEqual([], missing, "当天无收录团期时应返回空列表")

    def test_party_size_expands_budget_filter(self) -> None:
        """预算过滤应使用人数乘以单人最高套餐价。"""
        affordable = self.service.commercial_tours(
            {"party_size": 2, "max_budget_cny": 400},
            current_date=date(2026, 6, 17),
        )
        too_expensive = self.service.commercial_tours(
            {"party_size": 2, "max_budget_cny": 300},
            current_date=date(2026, 6, 17),
        )

        self.assertTrue(
            any(item["product"]["id"] == "tour-qionglai-nanbaoshan-lite" for item in affordable),
            "两人总预算覆盖最高价时应保留该商团",
        )
        self.assertFalse(
            any(item["product"]["id"] == "tour-qionglai-nanbaoshan-lite" for item in too_expensive),
            "两人总预算低于最高价合计时应过滤该商团",
        )

    def test_defaults_to_single_day_routes(self) -> None:
        """商团推荐默认仍只返回单日路线，显式放宽后才返回多日路线。"""
        default_results = self.service.commercial_tours({}, current_date=date(2026, 6, 17))
        multi_day_results = self.service.commercial_tours(
            {"max_duration_days": 2},
            current_date=date(2026, 6, 17),
        )

        self.assertTrue(
            all(item["route"]["duration_days"] <= 1 for item in default_results),
            "默认商团推荐应保持单日路线边界",
        )
        self.assertTrue(
            any(item["route"]["duration_days"] == 2 for item in multi_day_results),
            "显式允许两日时应可返回已收录多日商团",
        )

    def test_no_result_returns_empty_list(self) -> None:
        """没有符合条件的商团产品时，应返回空列表而不是抛出异常。"""
        results = self.service.commercial_tours(
            {"max_budget_cny": 1},
            current_date=date(2026, 6, 17),
        )

        self.assertEqual([], results, "无结果查询应稳定返回空列表")


if __name__ == "__main__":
    unittest.main()
