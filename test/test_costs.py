from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from test_data import SAMPLE_DATA_PATH
from hiking_chatbi.importer import load_import_file
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider
from hiking_chatbi.validation import validate_import_item


class CostModelTest(unittest.TestCase):
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

    def test_route_costs_are_returned_as_separate_items(self) -> None:
        """路线费用与交通费用应作为独立明细返回。"""
        route = next(
            item for item in self.service.routes()
            if item["id"] == "qingcheng-back-mountain"
        )

        self.assertNotIn("cost_min_cny", route, "路线主体不应继续暴露旧最低费用字段")
        self.assertNotIn("cost_max_cny", route, "路线主体不应继续暴露旧最高费用字段")
        self.assertEqual(
            {"ticket", "shuttle"},
            {item["cost_type"] for item in route["route_fees"]},
            "应返回青城后山的门票与中转车费用",
        )
        self.assertEqual(
            {"self_drive", "public_transit", "carpool"},
            {item["transport_mode"] for item in route["transport_options"]},
            "应按交通方式返回交通费用",
        )

    def test_budget_is_calculated_for_each_transport_mode(self) -> None:
        """预算过滤应使用所选交通方式的完整行程费用。"""
        common_query = {
            "departure_at": self.departure,
            "max_distance_km": 13,
            "max_ascent_m": 800,
            "max_budget_cny": 120,
            "traffic_tolerance": "high",
        }

        public_transit = self.service.recommendations({
            **common_query,
            "transport_modes": ["public_transit"],
        })
        self_drive = self.service.recommendations({
            **common_query,
            "transport_modes": ["self_drive"],
        })

        self.assertEqual(
            ["qingcheng-back-mountain"],
            [item["route"]["id"] for item in public_transit],
            "公共交通最高费用不超过预算时应保留路线",
        )
        self.assertEqual([], self_drive, "自驾最高费用超过预算时应过滤路线")
        self.assertEqual(
            110,
            public_transit[0]["cost_estimates"][0]["total_max_cny"],
            "应返回所选交通方式的总费用上限",
        )

    def test_party_size_changes_per_person_costs(self) -> None:
        """人数增加时，按人收取的路线与交通费用应同步增加。"""
        results = self.service.recommendations({
            "departure_at": self.departure,
            "transport_modes": ["public_transit"],
            "party_size": 4,
            "max_distance_km": 13,
            "max_ascent_m": 800,
            "max_budget_cny": 500,
            "traffic_tolerance": "high",
        })

        estimate = results[0]["cost_estimates"][0]
        self.assertEqual(200, estimate["route_fee_min_cny"], "路线按人费用应乘以人数")
        self.assertEqual(440, estimate["total_max_cny"], "交通按人费用也应乘以人数")

    def test_transport_cost_rejects_unsupported_route_mode(self) -> None:
        """交通费用不得引用路线不支持的交通方式。"""
        item = copy.deepcopy(load_import_file(SAMPLE_DATA_PATH)[0])
        item["costs"]["transport_options"][0]["transport_mode"] = "group_tour"

        with self.assertRaisesRegex(ValueError, "路线不支持"):
            validate_import_item(item)


if __name__ == "__main__":
    unittest.main()
