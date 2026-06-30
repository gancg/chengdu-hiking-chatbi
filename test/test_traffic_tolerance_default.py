from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hiking_chatbi.config import SAMPLE_DATA_PATH
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider


class TrafficToleranceDefaultTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.service = ChatBIService(Path(self.temp.name) / "test.db", NoTrafficProvider())
        self.service.seed(SAMPLE_DATA_PATH)
        self.query = {
            "departure_at": "2026-06-19T08:00:00+08:00",
            "transport_modes": ["self_drive"],
            "max_distance_km": 10,
            "max_ascent_m": 1000,
            "is_holiday": True,
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_missing_traffic_tolerance_keeps_holiday_congested_route(self) -> None:
        """未明确限制拥堵等级时，节假日严重拥堵路线不应被默认过滤。"""
        results = self.service.recommendations(self.query)

        routes = {item["route"]["id"]: item for item in results}
        self.assertIn(
            "bipenggou-panyang-lake",
            routes,
            "未传拥堵容忍度时应保留符合条件的节假日严重拥堵路线",
        )
        self.assertEqual(
            "severe",
            routes["bipenggou-panyang-lake"]["outbound_traffic"]["congestion_level"],
            "返回结果仍应展示实际估算出的严重拥堵等级",
        )

    def test_explicit_traffic_tolerance_still_filters_holiday_route(self) -> None:
        """明确限制拥堵等级时，仍应按用户给定容忍度硬过滤。"""
        results = self.service.recommendations({
            **self.query,
            "traffic_tolerance": "high",
        })

        self.assertEqual(
            [],
            results,
            "显式只接受 high 及以下拥堵时，severe 路线应被过滤",
        )


if __name__ == "__main__":
    unittest.main()
