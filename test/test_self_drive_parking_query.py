from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from test_data import SAMPLE_DATA_PATH
from hiking_chatbi.db import connect
from hiking_chatbi.qwen_chatbi import (
    FindRouteParkingPointsTool,
    build_interview_guidance,
    build_route_search_terms,
)
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider


class SelfDriveParkingQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.service = ChatBIService(self.db_path, NoTrafficProvider())
        self.service.seed(SAMPLE_DATA_PATH)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_current_self_drive_choice_queries_weather_before_parking(self) -> None:
        """中文测试：选定路线并确认自驾后应先查询天气，再查询停车点。"""
        routes = self.service.routes()
        messages = [
            {"role": "user", "content": "我选择青城后山环线"},
            {"role": "assistant", "content": "请选择交通方式：\n1. 自驾\n2. 报团"},
            {"role": "user", "content": "自驾"},
        ]

        guidance = build_interview_guidance(
            messages,
            build_route_search_terms(routes),
            routes,
        )

        self.assertIn("先调用 estimate_route_weather", guidance)
        self.assertIn("天气返回后再调用 find_route_parking_points", guidance)
        self.assertIn("route_id=qingcheng-back-mountain", guidance)

    def test_parking_tool_returns_position_note_and_navigation(self) -> None:
        """中文测试：停车点工具应返回已审核位置、说明和导航链接。"""
        with closing(connect(self.db_path)) as connection:
            connection.execute(
                """INSERT INTO route_parking_points
                (route_id,name,latitude,longitude,note,is_recommended,is_reviewed,source_url,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    "qingcheng-back-mountain", "游客中心停车场", 30.9131, 103.4891,
                    "停车后步行五分钟到入口", 1, 1,
                    "https://example.org/parking", "2026-07-03T09:00:00+08:00",
                ),
            )
            connection.commit()

        result = json.loads(FindRouteParkingPointsTool(self.service).call({
            "route_id": "qingcheng-back-mountain",
        }))

        self.assertEqual(1, result["count"])
        point = result["items"][0]
        self.assertEqual("游客中心停车场", point["name"])
        self.assertEqual("停车后步行五分钟到入口", point["note"])
        self.assertEqual(30.9131, point["latitude"])
        self.assertIn("uri.amap.com/navigation", point["navigation_links"]["amap"])

    def test_parking_tool_rejects_unknown_or_unreviewed_route(self) -> None:
        """中文测试：停车点工具不得查询不存在或未审核的路线。"""
        with self.assertRaisesRegex(ValueError, "路线不存在或未审核"):
            FindRouteParkingPointsTool(self.service).call({"route_id": "missing-route"})

    def test_parking_tool_returns_trailhead_reference_when_no_parking_exists(self) -> None:
        """中文测试：没有停车场数据时应返回徒步起点参考，并明确它不代表可停车。"""
        result = json.loads(FindRouteParkingPointsTool(self.service).call({
            "route_id": "qingcheng-back-mountain",
        }))

        self.assertEqual(0, result["count"], "起点参考不得计入停车场数量")
        self.assertEqual([], result["items"], "起点参考不得混入停车场列表")
        reference = result["trailhead_reference"]
        self.assertEqual("都江堰市青城后山", reference["name"])
        self.assertEqual(30.913, reference["latitude"])
        self.assertFalse(reference["is_parking_point"], "必须明确起点不是停车场")
        self.assertTrue(reference["reference_only"], "必须明确该位置仅供参考")
        self.assertIn("仅为徒步起点参考", result["warning"])
        self.assertIn("不代表可以停车", result["warning"])
        self.assertIn("uri.amap.com/navigation", reference["navigation_links"]["amap"])

    def test_real_parking_does_not_return_trailhead_fallback(self) -> None:
        """中文测试：存在已审核停车场时，不应再返回徒步起点兜底。"""
        with closing(connect(self.db_path)) as connection:
            connection.execute(
                """INSERT INTO route_parking_points
                (route_id,name,latitude,longitude,note,is_recommended,is_reviewed,source_url,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    "qingcheng-back-mountain", "游客中心停车场", 30.9131, 103.4891,
                    "停车后步行五分钟到入口", 1, 1,
                    "https://example.org/parking", "2026-07-03T09:00:00+08:00",
                ),
            )
            connection.commit()

        result = json.loads(FindRouteParkingPointsTool(self.service).call({
            "route_id": "qingcheng-back-mountain",
        }))

        self.assertEqual(1, result["count"])
        self.assertNotIn("trailhead_reference", result, "真实停车场存在时不得返回起点兜底")


if __name__ == "__main__":
    unittest.main()
