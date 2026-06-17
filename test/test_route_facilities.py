from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from hiking_chatbi.config import SAMPLE_DATA_PATH
from hiking_chatbi.importer import load_import_file
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider
from hiking_chatbi.validation import validate_import_item


class RouteFacilitiesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.service = ChatBIService(self.db_path, NoTrafficProvider())
        self.service.seed(SAMPLE_DATA_PATH)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_routes_return_toilet_and_supply_shop_flags(self) -> None:
        """路线列表应返回卫生间和小卖部布尔字段。"""
        routes = {route["id"]: route for route in self.service.routes()}

        self.assertIs(routes["qingcheng-back-mountain"]["has_toilet"], True)
        self.assertIs(routes["qingcheng-back-mountain"]["has_supply_shop"], True)
        self.assertIs(routes["zhaogong-mountain"]["has_toilet"], False)
        self.assertIs(routes["zhaogong-mountain"]["has_supply_shop"], True)

    def test_route_facility_flags_must_be_boolean(self) -> None:
        """导入路线时，设施标记必须为布尔值。"""
        item = copy.deepcopy(load_import_file(SAMPLE_DATA_PATH)[0])
        item["route"]["has_toilet"] = "有"

        with self.assertRaisesRegex(ValueError, "has_toilet 必须为布尔值"):
            validate_import_item(item)

    def test_route_facility_flags_are_required(self) -> None:
        """导入路线时，卫生间和小卖部字段均为必填。"""
        item = copy.deepcopy(load_import_file(SAMPLE_DATA_PATH)[0])
        del item["route"]["has_supply_shop"]

        with self.assertRaisesRegex(ValueError, "has_supply_shop"):
            validate_import_item(item)


if __name__ == "__main__":
    unittest.main()
