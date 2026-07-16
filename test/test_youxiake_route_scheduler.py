from __future__ import annotations

import copy
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from hiking_chatbi.db import list_routes
from hiking_chatbi.youxiake_route_scheduler import (
    build_argument_parser,
    build_pipeline_command,
    calculate_next_run,
    execute_pipeline,
    import_updated_routes,
    parse_daily_time,
    run_scheduled_job,
)


ROOT = Path(__file__).resolve().parents[1]


class YouxiakeRouteSchedulerTest(unittest.TestCase):
    def test_compose_starts_scheduler_with_configured_parameters(self) -> None:
        """中文测试：Compose应随应用启动Python调度器并注入时间与条数。"""
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        for fragment in (
            "route-scheduler:",
            "hiking_chatbi.youxiake_route_scheduler",
            "${CHATBI_ROUTE_SCHEDULE_TIME:-18:21}",
            "${CHATBI_ROUTE_SCHEDULE_COUNT:-1}",
            "restart: unless-stopped",
            "disable: true",
        ):
            self.assertIn(fragment, compose, f"Compose 调度服务缺少配置: {fragment}")

    def test_compose_shares_route_data_and_scheduler_logs(self) -> None:
        """中文测试：应用和调度容器必须共享路线文件及运行日志卷。"""
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            compose.count("chatbi-data:/app/data"),
            2,
            "两个服务都必须挂载共享路线数据卷",
        )
        self.assertGreaterEqual(
            compose.count("chatbi-runtime:/app/runtime"),
            2,
            "两个服务都必须挂载共享运行卷",
        )
        self.assertGreaterEqual(
            compose.count("CHATBI_DB_PATH: /app/data/chatbi.db"),
            2,
            "调度器必须与应用显式使用共享数据卷中的同一个数据库",
        )
        self.assertIn("chatbi-data:", compose, "Compose 必须声明路线数据命名卷")

    def test_environment_example_documents_schedule_parameters(self) -> None:
        """中文测试：环境示例应说明每日更新时间和路线条数。"""
        content = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("CHATBI_ROUTE_SCHEDULE_TIME=18:21", content)
        self.assertIn("CHATBI_ROUTE_SCHEDULE_COUNT=1", content)

    def test_required_time_and_count_arguments(self) -> None:
        """中文测试：调度命令必须明确提供每日时间和路线数量。"""
        with self.assertRaises(SystemExit):
            build_argument_parser().parse_args([])

    def test_parses_valid_daily_time(self) -> None:
        """中文测试：每日时间应按24小时制解析。"""
        self.assertEqual(time(3, 5), parse_daily_time("03:05"))

    def test_rejects_invalid_daily_time_with_chinese_error(self) -> None:
        """中文测试：无效时间必须输出含义明确的中文异常。"""
        for value in ("3点", "24:00", "03:60", "03:05:00"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "HH:MM"):
                    parse_daily_time(value)

    def test_next_run_uses_today_before_target_time(self) -> None:
        """中文测试：目标时间尚未到达时应安排在当天。"""
        now = datetime(2026, 7, 14, 2, 0, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(
            datetime(2026, 7, 14, 3, 0, tzinfo=now.tzinfo),
            calculate_next_run(now, time(3, 0)),
        )

    def test_next_run_uses_tomorrow_after_target_time(self) -> None:
        """中文测试：当天时间已经过去时应安排到下一天。"""
        now = datetime(2026, 7, 14, 4, 0, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(
            datetime(2026, 7, 15, 3, 0, tzinfo=now.tzinfo),
            calculate_next_run(now, time(3, 0)),
        )

    def test_pipeline_command_refreshes_links(self) -> None:
        """中文测试：每日任务必须重新抓取网站并使用指定条数。"""
        command = build_pipeline_command(10, python_executable="python-test")
        self.assertEqual(
            [
                "python-test", "-m", "hiking_chatbi.youxiake_route_pipeline",
                "--count", "10", "--refresh-links",
            ],
            command,
        )

    def test_execute_pipeline_uses_repository_as_working_directory(self) -> None:
        """中文测试：子进程应在仓库根目录运行并继承当前环境。"""
        runner = Mock(return_value=subprocess.CompletedProcess([], 0))
        result = execute_pipeline(10, subprocess_runner=runner)
        self.assertEqual(0, result)
        call = runner.call_args
        self.assertTrue(Path(call.kwargs["cwd"]).is_absolute())
        self.assertNotIn("env", call.kwargs, "子进程应直接继承调度器环境变量")
        self.assertFalse(call.kwargs["check"])

    def test_scheduled_job_reports_failure_without_raising(self) -> None:
        """中文测试：单次路线更新失败不得导致常驻调度器退出。"""
        logger = Mock()
        importer = Mock()
        is_success = run_scheduled_job(10, lambda _count: 2, logger, importer)
        self.assertFalse(is_success)
        logger.error.assert_called_once()
        importer.assert_not_called()

    def test_successful_pipeline_imports_updated_routes_once(self) -> None:
        """中文测试：路线文件更新成功后必须校验并导入数据库一次。"""
        logger = Mock()
        importer = Mock(return_value=23)

        is_success = run_scheduled_job(10, lambda _count: 0, logger, importer)

        self.assertTrue(is_success)
        importer.assert_called_once_with()
        self.assertTrue(
            any("数据库" in str(call) and "23" in str(call) for call in logger.info.call_args_list),
            "导入成功日志必须包含数据库导入数量",
        )

    def test_invalid_updated_routes_are_not_written_to_database(self) -> None:
        """中文测试：全部路线均无效时应逐条跳过且不得创建数据库。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "sample_routes.json"
            db_path = root / "chatbi.db"
            source_path.write_text('[{"route": {"id": "broken"}}]', encoding="utf-8")

            with self.assertLogs("hiking_chatbi.importer", level="WARNING") as logs:
                imported_count = import_updated_routes(source_path, db_path)

            self.assertEqual(0, imported_count)
            self.assertTrue(any("broken" in message for message in logs.output))
            self.assertFalse(db_path.exists(), "完整性校验失败前不得创建或修改数据库")

    def test_invalid_hiking_minutes_is_skipped_before_database_import(self) -> None:
        """中文测试：徒步时长不大于零的路线应跳过，其余路线继续导入。"""
        source_items = json.loads(
            (ROOT / "test" / "fixtures" / "sample_routes.json").read_text(
                encoding="utf-8"
            )
        )
        valid_item = copy.deepcopy(source_items[0])
        invalid_item = copy.deepcopy(source_items[1])
        invalid_item["route"]["id"] = "invalid-zero-hiking-minutes"
        invalid_item["route"]["hiking_minutes"] = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "sample_routes.json"
            db_path = root / "chatbi.db"
            source_path.write_text(
                json.dumps([invalid_item, valid_item], ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertLogs("hiking_chatbi.importer", level="WARNING") as logs:
                imported_count = import_updated_routes(source_path, db_path)

            routes = list_routes(db_path, reviewed_only=False)
            self.assertEqual(1, imported_count)
            self.assertEqual([valid_item["route"]["id"]], [route["id"] for route in routes])
            self.assertTrue(
                any(
                    "invalid-zero-hiking-minutes" in message
                    and "hiking_minutes 必须为正整数" in message
                    for message in logs.output
                )
            )

    def test_valid_updated_routes_are_imported_to_database(self) -> None:
        """中文测试：完整样例路线应在校验后全部增量导入目标数据库。"""
        source_path = ROOT / "data" / "sample_routes.json"
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "chatbi.db"

            imported_count = import_updated_routes(source_path, db_path)

            self.assertGreater(imported_count, 0, "完整样例路线不应导入为空")
            self.assertEqual(
                imported_count,
                len(list_routes(db_path, reviewed_only=False)),
                "数据库中的路线数量应与完整校验后的导入数量一致",
            )

    def test_database_import_failure_is_reported_without_stopping_scheduler(self) -> None:
        """中文测试：数据库导入失败应记录异常并留待下一周期重试。"""
        logger = Mock()

        def broken_importer() -> int:
            raise RuntimeError("模拟数据库写入失败")

        self.assertFalse(
            run_scheduled_job(10, lambda _count: 0, logger, broken_importer)
        )
        logger.exception.assert_called_once()

    def test_scheduled_job_catches_unexpected_exception(self) -> None:
        """中文测试：子任务异常应记录堆栈并留待下一天重试。"""
        logger = Mock()

        def broken_runner(_count: int) -> int:
            raise RuntimeError("模拟网络失败")

        importer = Mock()
        self.assertFalse(run_scheduled_job(10, broken_runner, logger, importer))
        logger.exception.assert_called_once()
        importer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
