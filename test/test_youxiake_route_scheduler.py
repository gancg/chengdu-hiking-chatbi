from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

from hiking_chatbi.youxiake_route_scheduler import (
    build_argument_parser,
    build_pipeline_command,
    calculate_next_run,
    execute_pipeline,
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
        is_success = run_scheduled_job(10, lambda _count: 2, logger)
        self.assertFalse(is_success)
        logger.error.assert_called_once()

    def test_scheduled_job_catches_unexpected_exception(self) -> None:
        """中文测试：子任务异常应记录堆栈并留待下一天重试。"""
        logger = Mock()

        def broken_runner(_count: int) -> int:
            raise RuntimeError("模拟网络失败")

        self.assertFalse(run_scheduled_job(10, broken_runner, logger))
        logger.exception.assert_called_once()


if __name__ == "__main__":
    unittest.main()
