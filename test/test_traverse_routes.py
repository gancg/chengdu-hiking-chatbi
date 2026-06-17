from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from hiking_chatbi.config import SAMPLE_DATA_PATH
from hiking_chatbi.importer import load_import_file
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider
from hiking_chatbi.validation import validate_import_item


class TraverseRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.service = ChatBIService(self.db_path, NoTrafficProvider())
        self.service.seed(SAMPLE_DATA_PATH)
        self.departure = (datetime.now().astimezone() + timedelta(days=1)).replace(
            hour=6, minute=0, second=0, microsecond=0
        ).isoformat()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_self_drive_traverse_route_adds_parking_transfer_time(self) -> None:
        """自驾穿越线应增加打车或包车返回停车点的预估时长。"""
        item = copy.deepcopy(load_import_file(SAMPLE_DATA_PATH)[0])
        item["route"]["is_traverse"] = True
        item["route"]["traverse_transfer_minutes"] = 45
        self.service.import_items([item])
        query = {
            "departure_at": self.departure,
            "max_distance_km": 13,
            "max_ascent_m": 800,
            "max_budget_cny": 500,
            "traffic_tolerance": "high",
        }

        self_drive = self.service.recommendations({
            **query,
            "transport_modes": ["self_drive"],
        })[0]
        public_transit = self.service.recommendations({
            **query,
            "transport_modes": ["public_transit"],
        })[0]

        self.assertEqual(45, self_drive["estimated_parking_transfer_minutes"])
        self.assertEqual(0, public_transit["estimated_parking_transfer_minutes"])
        self.assertEqual(
            45,
            self_drive["estimated_total_minutes"] - public_transit["estimated_total_minutes"],
            "自驾穿越线总耗时应增加返回停车点的接驳时间",
        )

    def test_non_traverse_route_rejects_transfer_time(self) -> None:
        """非穿越线不得配置返回停车点接驳时长。"""
        item = copy.deepcopy(load_import_file(SAMPLE_DATA_PATH)[0])
        item["route"]["traverse_transfer_minutes"] = 30

        with self.assertRaisesRegex(ValueError, "非穿越线"):
            validate_import_item(item)

    def test_parking_fee_supports_vehicle_billing(self) -> None:
        """停车费应支持按车辆计费。"""
        item = copy.deepcopy(load_import_file(SAMPLE_DATA_PATH)[0])
        item["costs"]["route_fees"].append({
            "name": "停车费",
            "cost_type": "parking",
            "billing_unit": "vehicle",
            "min_cny": 10,
            "max_cny": 20,
            "source_url": "https://example.org/routes/qingcheng",
            "updated_at": "2026-06-10T10:00:00+08:00",
        })

        validate_import_item(item)
        self.service.import_items([item])
        result = self.service.recommendations({
            "departure_at": self.departure,
            "transport_modes": ["self_drive"],
            "vehicle_count": 2,
            "max_distance_km": 13,
            "max_ascent_m": 800,
            "max_budget_cny": 500,
            "traffic_tolerance": "high",
        })[0]

        self.assertEqual(
            90,
            result["cost_estimates"][0]["route_fee_max_cny"],
            "两辆车的停车费上限应计入路线费用",
        )


if __name__ == "__main__":
    unittest.main()
