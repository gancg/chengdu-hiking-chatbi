from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
import logging
from pathlib import Path
import subprocess
import sys
import time as time_module
from typing import Callable, Protocol

from .config import DB_PATH, ROOT, SAMPLE_DATA_PATH
from .importer import import_file


DEFAULT_LOG_PATH = ROOT / "data" / "youxiake_route_scheduler.log"
logger = logging.getLogger(__name__)


class JobLogger(Protocol):
    def info(self, message: str, *args: object) -> None: ...

    def error(self, message: str, *args: object) -> None: ...

    def exception(self, message: str, *args: object) -> None: ...


def parse_daily_time(value: str) -> time:
    """解析严格的 24 小时制 HH:MM 时间。"""
    try:
        if len(value) != 5 or value[2] != ":":
            raise ValueError
        hour = int(value[:2])
        minute = int(value[3:])
        return time(hour, minute)
    except ValueError as exc:
        raise ValueError(f"每日执行时间必须使用有效的 HH:MM 24小时制格式: {value}") from exc


def calculate_next_run(now: datetime, daily_time: time) -> datetime:
    """根据带时区的当前时间计算下一次本地执行时间。"""
    if now.tzinfo is None:
        raise ValueError("当前时间必须包含时区")
    candidate = datetime.combine(now.date(), daily_time, tzinfo=now.tzinfo)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def build_pipeline_command(
    count: int,
    python_executable: str | None = None,
) -> list[str]:
    """构造每日重新抓取候选并更新路线的子进程命令。"""
    if count <= 0:
        raise ValueError("count 必须为正整数")
    return [
        python_executable or sys.executable,
        "-m",
        "hiking_chatbi.youxiake_route_pipeline",
        "--count",
        str(count),
        "--refresh-links",
    ]


def execute_pipeline(
    count: int,
    subprocess_runner: Callable[..., subprocess.CompletedProcess[object]] = subprocess.run,
) -> int:
    """在仓库根目录同步执行一次路线更新并返回退出码。"""
    command = build_pipeline_command(count)
    logger.info(
        "启动游侠客路线流水线 command=%s cwd=%s count=%s",
        subprocess.list2cmdline(command),
        ROOT,
        count,
    )
    completed = subprocess_runner(
        command,
        cwd=ROOT,
        check=False,
    )
    return_code = int(completed.returncode)
    logger.info(
        "游侠客路线流水线进程结束 return_code=%s count=%s",
        return_code,
        count,
    )
    return return_code


def import_updated_routes(
    source_path: Path = SAMPLE_DATA_PATH,
    db_path: Path = DB_PATH,
) -> int:
    """完整校验路线文件后，将全部有效路线增量导入数据库。"""
    logger.info(
        "开始校验并导入更新后的路线 source_path=%s db_path=%s",
        source_path,
        db_path,
    )
    imported_count = import_file(db_path, source_path)
    logger.info(
        "更新后的路线导入完成 source_path=%s db_path=%s imported_count=%s",
        source_path,
        db_path,
        imported_count,
    )
    return imported_count


def run_scheduled_job(
    count: int,
    job_runner: Callable[[int], int],
    job_logger: JobLogger = logger,
    route_importer: Callable[[], int] = import_updated_routes,
) -> bool:
    """运行路线更新和数据库导入；记录失败但不向调度循环传播。"""
    job_logger.info("开始执行每日游侠客路线更新 count=%s", count)
    try:
        return_code = job_runner(count)
    except Exception:
        job_logger.exception("每日游侠客路线更新发生异常，调度器将在下一周期重试")
        return False
    if return_code != 0:
        job_logger.error(
            "每日游侠客路线更新失败 count=%s return_code=%s，调度器将在下一周期重试",
            count,
            return_code,
        )
        return False
    try:
        imported_count = route_importer()
    except Exception:
        job_logger.exception(
            "sample_routes.json 完整性校验或数据库导入失败，调度器将在下一周期重试"
        )
        return False
    job_logger.info(
        "每日游侠客路线更新并导入数据库完成 update_count=%s imported_count=%s "
        "source_path=%s db_path=%s",
        count,
        imported_count,
        SAMPLE_DATA_PATH,
        DB_PATH,
    )
    return True


def wait_until(
    target: datetime,
    now_provider: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    sleeper: Callable[[float], None] = time_module.sleep,
) -> None:
    """分段等待到目标时间，以便响应系统时钟变化和 Ctrl+C。"""
    while True:
        remaining_seconds = (target - now_provider()).total_seconds()
        if remaining_seconds <= 0:
            return
        sleeper(min(remaining_seconds, 60.0))


def run_daily_scheduler(
    daily_time: time,
    count: int,
    is_run_now: bool = False,
    job_runner: Callable[[int], int] = execute_pipeline,
    now_provider: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    sleeper: Callable[[float], None] = time_module.sleep,
    job_logger: JobLogger = logger,
) -> None:
    """常驻运行每日调度循环，单次任务完成后再安排下一次。"""
    if count <= 0:
        raise ValueError("count 必须为正整数")
    if is_run_now:
        run_scheduled_job(count, job_runner, job_logger)
    while True:
        next_run = calculate_next_run(now_provider(), daily_time)
        job_logger.info(
            "下一次游侠客路线更新时间为 %s count=%s",
            next_run.isoformat(),
            count,
        )
        wait_until(next_run, now_provider, sleeper)
        run_scheduled_job(count, job_runner, job_logger)


def configure_scheduler_logging(log_path: Path) -> None:
    """配置同时写控制台和文件的调度日志。"""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"无法创建调度日志文件 {log_path}: {exc}") from exc
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


def build_argument_parser() -> argparse.ArgumentParser:
    """构建每日路线更新调度器命令行参数。"""
    parser = argparse.ArgumentParser(description="每日定时更新游侠客成都一日徒步路线")
    parser.add_argument("--time", required=True, dest="daily_time", help="每日执行时间，格式 HH:MM")
    parser.add_argument("--count", required=True, type=int, help="每天更新的路线数量")
    parser.add_argument("--run-now", action="store_true", help="启动后立即执行一次")
    parser.add_argument(
        "--log-file",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="调度日志文件路径",
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    if args.count <= 0:
        raise ValueError("count 必须为正整数")
    daily_time = parse_daily_time(args.daily_time)
    configure_scheduler_logging(args.log_file)
    logger.info(
        "游侠客每日路线调度器启动 daily_time=%s count=%s log_file=%s python=%s",
        daily_time.strftime("%H:%M"),
        args.count,
        args.log_file,
        sys.executable,
    )
    try:
        run_daily_scheduler(daily_time, args.count, args.run_now)
    except KeyboardInterrupt:
        logger.info("收到中断信号，游侠客每日路线调度器已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
