from __future__ import annotations

import logging
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from hiking_chatbi.db import connect


class SqlDebugLoggingTest(unittest.TestCase):
    def test_connect_logs_sql_statements_when_debug_enabled(self) -> None:
        """DEBUG 模式下执行 SQL 时应输出实际 SQL 语句。"""
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "test.db"

            with self.assertLogs("hiking_chatbi.db", level="DEBUG") as logs:
                with closing(connect(db_path)) as connection:
                    connection.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT)")
                    connection.execute("INSERT INTO demo (name) VALUES (?)", ("龙泉山",))
                    connection.execute("SELECT name FROM demo WHERE id = ?", (1,)).fetchone()

        output = "\n".join(logs.output)
        self.assertIn("SQL: CREATE TABLE demo", output, "DEBUG 日志应包含建表 SQL")
        self.assertIn("SQL: INSERT INTO demo", output, "DEBUG 日志应包含写入 SQL")
        self.assertIn("SQL: SELECT name FROM demo", output, "DEBUG 日志应包含查询 SQL")
        self.assertIn("'龙泉山'", output, "SQL 日志应包含 SQLite 实际执行的参数值")

    def test_connect_does_not_trace_sql_when_debug_disabled(self) -> None:
        """非 DEBUG 模式下不应注册 SQL trace 日志。"""
        logger = logging.getLogger("hiking_chatbi.db")
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        self.addCleanup(logger.setLevel, previous_level)

        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "test.db"

            with closing(connect(db_path)) as connection:
                with self.assertNoLogs("hiking_chatbi.db", level="DEBUG"):
                    connection.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY)")
