from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .db import import_routes, replace_routes
from .validation import validate_database_import_item, validate_import_item


logger = logging.getLogger(__name__)


def load_import_file(path: Path) -> list[dict[str, Any]]:
    logger.info("开始读取路线导入文件 path=%s", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("导入文件根节点必须是数组")
    for item in data:
        validate_import_item(item)
    logger.info("路线导入文件校验完成 path=%s count=%s", path, len(data))
    return data


def import_file(db_path: Path, source_path: Path) -> int:
    count = import_routes(db_path, load_import_file(source_path))
    logger.info("路线文件导入数据库完成 source=%s count=%s", source_path, count)
    return count


def import_valid_file(db_path: Path, source_path: Path) -> int:
    """逐条跳过无法满足数据库约束的路线并导入其余有效记录。"""
    logger.info("开始读取待筛选路线导入文件 path=%s", source_path)
    data = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("导入文件根节点必须是数组")
    valid_items: list[dict[str, Any]] = []
    for index, item in enumerate(data, 1):
        route = item.get("route", {}) if isinstance(item, dict) else {}
        route_id = str(route.get("id", "")).strip() or "<unknown>"
        try:
            validate_database_import_item(item)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "跳过数据库预检不合格路线 index=%s route_id=%s reason=%s",
                index,
                route_id,
                exc,
            )
            continue
        valid_items.append(item)
    skipped_count = len(data) - len(valid_items)
    logger.info(
        "路线数据库预检完成 path=%s total_count=%s valid_count=%s skipped_count=%s",
        source_path,
        len(data),
        len(valid_items),
        skipped_count,
    )
    if not valid_items:
        logger.warning("没有通过数据库预检的路线，跳过数据库写入 path=%s", source_path)
        return 0
    count = import_routes(db_path, valid_items)
    logger.info(
        "有效路线文件导入数据库完成 source=%s count=%s skipped_count=%s",
        source_path,
        count,
        skipped_count,
    )
    return count


def replace_file(db_path: Path, source_path: Path) -> int:
    """Replace existing route data with one fully validated import file."""
    items = load_import_file(source_path)
    count = replace_routes(db_path, items)
    logger.info("路线权威数据替换完成 source=%s count=%s", source_path, count)
    return count
