from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from hiking_chatbi.db import connect, initialize
from hiking_chatbi.parking_points_enricher import (
    build_parking_prompt,
    normalize_parking_response,
    replace_unreviewed_parking_points,
)


class ParkingPointsEnricherTest(unittest.TestCase):
    def test_prompt_forbids_using_trailhead_as_parking_location(self) -> None:
        """中文测试：模型提示必须禁止把徒步起点坐标冒充停车点。"""
        prompt = build_parking_prompt([{
            "id": "route-1",
            "name": "测试路线",
            "start_location": "测试徒步起点",
            "end_location": "测试终点",
            "parking": "附近可能停车",
            "latitude": 30.1,
            "longitude": 103.1,
            "source_url": "https://example.org/route-1",
        }])

        self.assertIn("不得把路线起点坐标当作停车点坐标", prompt)
        self.assertIn("找不到可核验", prompt)
        self.assertIn("qwen3.7-max", prompt)

    def test_response_is_forced_to_unreviewed_candidates(self) -> None:
        """中文测试：模型候选必须标记为未审核并拒绝未知路线。"""
        payload = {
            "routes": [{
                "route_id": "route-1",
                "parking_points": [{
                    "name": "测试停车场",
                    "latitude": 30.2,
                    "longitude": 103.2,
                    "note": "停车后步行前往入口",
                    "is_recommended": True,
                    "source_url": "https://example.org/parking",
                }],
            }],
        }

        normalized = normalize_parking_response(payload, {"route-1"}, "2026-07-03T10:00:00+08:00")

        self.assertFalse(normalized["route-1"][0]["is_reviewed"])
        unknown = {"routes": [{"route_id": "unknown", "parking_points": []}]}
        with self.assertRaisesRegex(ValueError, "未知路线"):
            normalize_parking_response(unknown, {"route-1"}, "2026-07-03T10:00:00+08:00")

    def test_replacement_preserves_reviewed_parking_points(self) -> None:
        """中文测试：刷新模型候选时不得删除人工审核停车点。"""
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "test.db"
            initialize(db_path)
            with closing(connect(db_path)) as connection:
                connection.execute(
                    "INSERT INTO routes (id,name,start_location,end_location,distance_km,ascent_m,highest_altitude_m,hiking_minutes,difficulty,duration_days,route_type,is_traverse,traverse_transfer_minutes,best_seasons_json,scenery_json,risks_json,transport_modes_json,group_tour_search_terms_json,cost_min_cny,cost_max_cny,has_toilet,has_supply_shop,source_url,source_name,collected_at,updated_at,confidence,reviewed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("route-1", "测试路线", "起点", "终点", 5, 100, 500, 120, "easy", 1, "loop", 0, 0, "[]", "[]", "[]", '["self_drive"]', "[]", 0, 0, 0, 0, "https://example.org", "测试", "2026-07-03T10:00:00+08:00", "2026-07-03T10:00:00+08:00", 0.8, 1),
                )
                connection.execute(
                    "INSERT INTO route_parking_points (route_id,name,latitude,longitude,note,is_recommended,is_reviewed,source_url,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    ("route-1", "人工停车场", 30.1, 103.1, None, 1, 1, "https://example.org/manual", "2026-07-03T10:00:00+08:00"),
                )
                replace_unreviewed_parking_points(connection, {"route-1": [{
                    "name": "模型停车场", "latitude": 30.2, "longitude": 103.2,
                    "note": None, "is_recommended": False, "is_reviewed": False,
                    "source_url": "https://example.org/model", "updated_at": "2026-07-03T10:00:00+08:00",
                }]})
                connection.commit()
                rows = connection.execute(
                    "SELECT name,is_reviewed FROM route_parking_points ORDER BY is_reviewed DESC"
                ).fetchall()

        self.assertEqual([("人工停车场", 1), ("模型停车场", 0)], [tuple(row) for row in rows])


if __name__ == "__main__":
    unittest.main()
