from __future__ import annotations

from pathlib import Path
import sqlite3
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DockerDatabasePackagingTest(unittest.TestCase):
    def test_docker_context_includes_only_packaged_database_exception(self) -> None:
        """中文测试：构建上下文必须包含指定数据库，同时继续排除其他数据库。"""
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("*.db", dockerignore, "Docker 构建上下文必须默认排除本地数据库")
        self.assertIn(
            "!data/chatbi.db",
            dockerignore,
            "Docker 构建上下文没有放行需要打包的 data/chatbi.db",
        )

    def test_dockerfile_copies_database_to_runtime_and_backup_paths(self) -> None:
        """中文测试：镜像必须包含运行数据库及不受数据卷遮挡的初始副本。"""
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "COPY data/chatbi.db /app/data/chatbi.db",
            dockerfile,
            "Dockerfile 未把数据库复制到 /app/data/chatbi.db",
        )
        self.assertIn(
            "COPY data/chatbi.db /app/image-data/chatbi.db",
            dockerfile,
            "镜像缺少不受运行卷遮挡的初始数据库副本",
        )

    def test_entrypoint_restores_missing_database_without_overwriting_existing_one(self) -> None:
        """中文测试：入口脚本只恢复缺失数据库，不得覆盖持久化数据库。"""
        entrypoint = (ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn(
            'if [ ! -f "/app/data/chatbi.db" ]; then',
            entrypoint,
            "入口脚本未检测运行数据库是否缺失",
        )
        self.assertIn(
            'cp "/app/image-data/chatbi.db" "/app/data/chatbi.db"',
            entrypoint,
            "入口脚本未从镜像初始副本恢复数据库",
        )

    def test_packaged_database_is_valid_and_contains_routes_table(self) -> None:
        """中文测试：被打包的数据库必须是有效 SQLite 文件并包含 routes 表。"""
        db_path = ROOT / "data" / "chatbi.db"
        try:
            with sqlite3.connect(db_path) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                routes_table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='routes'"
                ).fetchone()
        except sqlite3.Error as error:
            self.fail(f"读取待打包数据库失败：{error}")
        self.assertEqual(("ok",), integrity, "待打包数据库未通过 SQLite 完整性检查")
        self.assertEqual(("routes",), routes_table, "待打包数据库缺少 routes 表")


if __name__ == "__main__":
    unittest.main()
