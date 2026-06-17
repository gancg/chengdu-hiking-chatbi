from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .commercial_tours import validate_commercial_tour_product
from .db import import_commercial_tours, import_routes
from .validation import validate_import_item


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


def load_commercial_tour_file(path: Path) -> list[dict[str, Any]]:
    logger.info("开始读取商团产品导入文件 path=%s", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("商团产品文件根节点必须是数组")
    for item in data:
        validate_commercial_tour_product(item)
    logger.info("商团产品导入文件校验完成 path=%s count=%s", path, len(data))
    return data


def import_commercial_tour_file(db_path: Path, source_path: Path) -> int:
    count = import_commercial_tours(db_path, load_commercial_tour_file(source_path))
    logger.info("商团产品文件导入数据库完成 source=%s count=%s", source_path, count)
    return count
