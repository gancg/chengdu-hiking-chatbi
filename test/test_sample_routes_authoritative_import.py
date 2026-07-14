from __future__ import annotations

import copy
from contextlib import closing
from pathlib import Path
import tempfile
import unittest

from hiking_chatbi.db import connect, import_routes, list_routes
from hiking_chatbi.importer import load_import_file, replace_file


SAMPLE_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_routes.json"


class SampleRoutesAuthoritativeImportTest(unittest.TestCase):
    def test_replace_file_removes_old_routes_and_related_data(self) -> None:
        """中文测试：权威导入前应清除旧路线及其所有关联数据。"""
        expected_count = len(load_import_file(SAMPLE_PATH))
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            old_item = copy.deepcopy(load_import_file(SAMPLE_PATH)[0])
            old_item["route"]["id"] = "only-in-old-database"
            import_routes(db_path, [old_item])
            with closing(connect(db_path)) as connection:
                with connection:
                    connection.execute(
                        """INSERT INTO trip_feedback
                        (route_id,traveled_at,direction,actual_minutes,congestion_level,source,notes,created_at)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            "only-in-old-database",
                            "2026-07-01T08:00:00+08:00",
                            "outbound",
                            120,
                            "low",
                            "test",
                            None,
                            "2026-07-01T12:00:00+08:00",
                        ),
                    )

            imported = replace_file(db_path, SAMPLE_PATH)

            route_ids = {item["id"] for item in list_routes(db_path, reviewed_only=False)}
            with closing(connect(db_path)) as connection:
                feedback_count = connection.execute(
                    "SELECT COUNT(*) FROM trip_feedback"
                ).fetchone()[0]
            self.assertEqual(
                expected_count,
                imported,
                "应完整导入权威样例文件中的全部路线",
            )
            self.assertNotIn(
                "only-in-old-database", route_ids, "旧数据库独有路线必须被清除"
            )
            self.assertEqual(0, feedback_count, "旧路线的关联反馈必须级联清除")


if __name__ == "__main__":
    unittest.main()
