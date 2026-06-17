from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from hiking_chatbi.config import SAMPLE_DATA_PATH
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider


class RecommendationDurationDefaultTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.service = ChatBIService(Path(self.temp.name) / "test.db", NoTrafficProvider())
        self.service.seed(SAMPLE_DATA_PATH)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_recommendations_default_to_single_day_routes(self) -> None:
        """未指定行程天数时，推荐结果应默认只包含单日往返路线。"""
        departure = (datetime.now().astimezone() + timedelta(days=10)).replace(
            hour=6,
            minute=0,
            second=0,
            microsecond=0,
        )

        results = self.service.recommendations({
            "departure_at": departure.isoformat(),
            "max_budget_cny": 1000,
            "max_one_way_minutes": 600,
            "traffic_tolerance": "severe",
        })

        self.assertGreater(len(results), 0, "宽松条件下应返回至少一条单日路线")
        self.assertTrue(
            all(item["route"]["duration_days"] == 1 for item in results),
            "默认推荐不得包含多日游路线",
        )


if __name__ == "__main__":
    unittest.main()
