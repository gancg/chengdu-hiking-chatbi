from __future__ import annotations

import copy
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from test_data import SAMPLE_DATA_PATH
from hiking_chatbi.db import connect, initialize
from hiking_chatbi.importer import load_import_file
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider
from hiking_chatbi.validation import validate_import_item
from hiking_chatbi.weather import NoAlertProvider


class ParkingPointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.service = ChatBIService(
            self.db_path,
            NoTrafficProvider(),
            NoAlertProvider(),
        )
        self.item = copy.deepcopy(load_import_file(SAMPLE_DATA_PATH)[0])
        self.item["parking_points"] = [
            {
                "name": "青城后山游客中心停车场",
                "latitude": 30.9131,
                "longitude": 103.4891,
                "note": "停车后步行约五分钟到徒步入口，以现场管制为准",
                "is_recommended": True,
                "is_reviewed": True,
                "source_url": "https://example.org/parking/qingcheng",
                "updated_at": "2026-07-03T09:00:00+08:00",
            },
            {
                "name": "待核验备用停车点",
                "latitude": 30.914,
                "longitude": 103.49,
                "note": None,
                "is_recommended": False,
                "is_reviewed": False,
                "source_url": "https://example.org/parking/qingcheng-backup",
                "updated_at": "2026-07-03T09:00:00+08:00",
            },
        ]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_initialize_creates_parking_point_table(self) -> None:
        """中文测试：初始化数据库应创建带外键和审核字段的停车点表。"""
        initialize(self.db_path)

        with closing(connect(self.db_path)) as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(route_parking_points)")
            }
        self.assertEqual(
            {
                "id", "route_id", "name", "latitude", "longitude", "note",
                "is_recommended", "is_reviewed", "source_url", "updated_at",
            },
            columns,
            "停车点表字段应完整且职责明确",
        )

    def test_import_returns_only_reviewed_parking_points(self) -> None:
        """中文测试：导入停车点后只能向用户返回已审核的数据。"""
        self.service.import_items([self.item])

        route = next(
            route for route in self.service.routes()
            if route["id"] == self.item["route"]["id"]
        )
        self.assertEqual(1, len(route["parking_points"]), "未审核停车点不得对外展示")
        self.assertEqual(
            "青城后山游客中心停车场",
            route["parking_points"][0]["name"],
            "应返回经过审核的首选停车点",
        )

    def test_import_without_parking_points_preserves_existing_points(self) -> None:
        """中文测试：历史格式再次导入时不得误删已维护的停车点。"""
        self.service.import_items([self.item])
        legacy_item = copy.deepcopy(self.item)
        legacy_item.pop("parking_points")

        self.service.import_items([legacy_item])

        route = next(
            route for route in self.service.routes()
            if route["id"] == self.item["route"]["id"]
        )
        self.assertEqual(1, len(route["parking_points"]), "旧格式导入应保留停车点")

    def test_validation_rejects_invalid_parking_points(self) -> None:
        """中文测试：非法坐标、重复名称和多个首选点必须给出明确异常。"""
        invalid_cases = []

        invalid_coordinate = copy.deepcopy(self.item)
        invalid_coordinate["parking_points"][0]["latitude"] = 91
        invalid_cases.append((invalid_coordinate, "latitude"))

        duplicate_name = copy.deepcopy(self.item)
        duplicate_name["parking_points"][1]["name"] = duplicate_name["parking_points"][0]["name"]
        invalid_cases.append((duplicate_name, "名称不得重复"))

        multiple_recommended = copy.deepcopy(self.item)
        multiple_recommended["parking_points"][1]["is_recommended"] = True
        invalid_cases.append((multiple_recommended, "最多一个首选"))

        for item, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_import_item(item)

    def test_self_drive_recommendation_contains_navigation_links(self) -> None:
        """中文测试：明确选择自驾时推荐结果应提供停车点及地图导航链接。"""
        self.service.import_items([self.item])
        departure = (datetime.now().astimezone() + timedelta(days=7)).replace(
            hour=6, minute=0, second=0, microsecond=0
        )

        result = self.service.recommendations({
            "route_id": self.item["route"]["id"],
            "departure_at": departure.isoformat(),
            "transport_modes": ["self_drive"],
        })[0]

        parking_point = result["parking_points"][0]
        amap_url = parking_point["navigation_links"]["amap"]
        baidu_url = parking_point["navigation_links"]["baidu"]
        self.assertIn("uri.amap.com/navigation", amap_url)
        self.assertIn("api.map.baidu.com/direction", baidu_url)
        amap_query = parse_qs(urlparse(amap_url).query)
        baidu_query = parse_qs(urlparse(baidu_url).query)
        self.assertEqual(["car"], amap_query["mode"], "高德必须显式使用驾车模式 car")
        self.assertEqual(["gaode"], amap_query["coordinate"], "高德必须声明高德坐标")
        self.assertEqual(["1"], amap_query["callnative"], "高德移动端应尝试调起客户端")
        self.assertEqual(["driving"], baidu_query["mode"], "百度必须使用驾车模式 driving")
        self.assertEqual(["gcj02"], baidu_query["coord_type"], "百度必须声明输入为 GCJ-02 坐标")
        self.assertEqual(["html"], baidu_query["output"], "百度 Web URI 必须输出 HTML")
        self.assertIn("以现场管制为准", parking_point["note"])

    def test_non_self_drive_recommendation_hides_parking_points(self) -> None:
        """中文测试：未选择自驾时推荐结果不得推断或展示停车导航。"""
        self.service.import_items([self.item])
        departure = (datetime.now().astimezone() + timedelta(days=7)).replace(
            hour=6, minute=0, second=0, microsecond=0
        )

        result = self.service.recommendations({
            "route_id": self.item["route"]["id"],
            "departure_at": departure.isoformat(),
            "transport_modes": ["public_transit"],
        })[0]

        self.assertNotIn("parking_points", result, "非自驾推荐不应返回停车导航")


if __name__ == "__main__":
    unittest.main()
