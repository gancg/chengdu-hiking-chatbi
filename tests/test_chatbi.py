from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from hiking_chatbi.config import SAMPLE_DATA_PATH
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import MockTrafficProvider, NoTrafficProvider, historical_estimate


class ChatBITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.service = ChatBIService(self.db_path, NoTrafficProvider())
        self.service.seed(SAMPLE_DATA_PATH)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def route(self, route_id: str = "qingcheng-back-mountain") -> dict:
        return next(route for route in self.service.routes() if route["id"] == route_id)

    def test_weekend_and_holiday_raise_traffic_estimate(self) -> None:
        route = self.route()
        weekday = historical_estimate(route, datetime.fromisoformat("2026-06-11T06:00:00+08:00"), "outbound")
        weekend = historical_estimate(route, datetime.fromisoformat("2026-06-13T06:00:00+08:00"), "outbound")
        holiday = historical_estimate(route, datetime.fromisoformat("2026-06-13T06:00:00+08:00"), "outbound", True)
        self.assertLess(weekday["max_minutes"], weekend["max_minutes"])
        self.assertLess(weekend["max_minutes"], holiday["max_minutes"])

    def test_realtime_provider_is_used_for_near_departure(self) -> None:
        service = ChatBIService(self.db_path, MockTrafficProvider())
        now = datetime.now().astimezone()
        result = service.traffic({
            "route_id": "qingcheng-back-mountain",
            "departure_at": now.isoformat(),
        })
        self.assertEqual("realtime", result["data_type"])

    def test_realtime_unavailable_falls_back_explicitly(self) -> None:
        now = datetime.now().astimezone()
        result = self.service.traffic({
            "route_id": "qingcheng-back-mountain",
            "departure_at": now.isoformat(),
        })
        self.assertIn(result["data_type"], {"historical", "base"})
        self.assertIn("历史估算", result["fallback_reason"])

    def test_recommendation_respects_constraints_and_latest_return(self) -> None:
        departure = (datetime.now().astimezone() + timedelta(days=1)).replace(
            hour=6, minute=0, second=0, microsecond=0
        )
        query = {
            "origin": "成都",
            "departure_at": departure.isoformat(),
            "transport_modes": ["self_drive"],
            "max_distance_km": 13,
            "max_ascent_m": 800,
            "max_budget_cny": 300,
            "max_one_way_minutes": 180,
            "latest_return_at": departure.replace(hour=20).isoformat(),
            "traffic_tolerance": "high",
            "scenery_preferences": ["森林"],
        }
        results = self.service.recommendations(query)
        self.assertEqual(
            ["qingcheng-back-mountain", "pengzhou-panlong-valley"],
            [item["route"]["id"] for item in results],
        )

    def test_severe_holiday_traffic_can_filter_all_routes(self) -> None:
        departure = (datetime.now().astimezone() + timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0
        )
        results = self.service.recommendations({
            "departure_at": departure.isoformat(),
            "transport_modes": ["self_drive"],
            "max_one_way_minutes": 500,
            "traffic_tolerance": "low",
            "is_holiday": True,
        })
        self.assertEqual([], results)

    def test_feedback_changes_historical_estimate_after_three_samples(self) -> None:
        for minutes in (180, 190, 200):
            self.service.record_feedback({
                "route_id": "qingcheng-back-mountain",
                "traveled_at": "2026-06-07T09:00:00+08:00",
                "direction": "outbound",
                "actual_minutes": minutes,
                "congestion_level": "high",
                "source": "user",
            })
        estimate = historical_estimate(
            self.route(), datetime.fromisoformat("2026-06-13T06:00:00+08:00"), "outbound"
        )
        self.assertEqual("historical_feedback", estimate["data_type"])
        self.assertEqual(3, estimate["feedback_samples"])


if __name__ == "__main__":
    unittest.main()
