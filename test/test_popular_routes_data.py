from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_data import SAMPLE_DATA_PATH
from hiking_chatbi.db import get_route
from hiking_chatbi.importer import import_file, load_import_file


POPULAR_ROUTE_IDS = {
    "wenchuan-yunzhongling": "卧龙云中岭高山牧场线",
    "wenchuan-balangshan-panda-peak": "巴朗山熊猫王国之巅线",
    "pengzhou-panlong-valley": "彭州蟠龙谷瀑布群线",
}


class PopularRoutesDataTests(unittest.TestCase):
    def test_sample_data_contains_three_reviewed_high_confidence_routes(self) -> None:
        """样例数据应包含三条已审核且高置信度的热门路线。"""
        items = load_import_file(SAMPLE_DATA_PATH)
        routes = {item["route"]["id"]: item for item in items}

        for route_id, expected_name in POPULAR_ROUTE_IDS.items():
            with self.subTest(route_id=route_id):
                self.assertIn(route_id, routes, f"缺少热门路线：{route_id}")
                item = routes[route_id]
                route = item["route"]
                self.assertEqual(route["name"], expected_name, "路线中文名称不正确")
                self.assertTrue(route["reviewed"], "热门路线必须经过人工审核")
                self.assertGreaterEqual(route["confidence"], 0.8, "路线置信度必须不低于 0.8")
                self.assertGreaterEqual(
                    item["traffic"]["confidence"], 0.8, "交通置信度必须不低于 0.8"
                )
                self.assertNotIn("example.org", route["source_url"], "不得使用演示来源")

    def test_three_popular_routes_can_be_imported_and_queried(self) -> None:
        """三条热门路线应能导入临时数据库并按 ID 查询。"""
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "热门路线.db"
            imported = import_file(db_path, SAMPLE_DATA_PATH)
            self.assertGreaterEqual(imported, len(POPULAR_ROUTE_IDS), "导入数量不足")

            for route_id, expected_name in POPULAR_ROUTE_IDS.items():
                with self.subTest(route_id=route_id):
                    route = get_route(db_path, route_id)
                    self.assertIsNotNone(route, f"数据库中缺少路线：{route_id}")
                    assert route is not None
                    self.assertEqual(route["name"], expected_name, "数据库路线名称不正确")
                    self.assertGreaterEqual(route["confidence"], 0.8, "数据库路线置信度不足")
                    self.assertGreaterEqual(
                        route["traffic_confidence"], 0.8, "数据库交通置信度不足"
                    )


if __name__ == "__main__":
    unittest.main()
