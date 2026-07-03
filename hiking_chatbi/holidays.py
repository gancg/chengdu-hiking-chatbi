from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .config import HOLIDAY_DATA_PATH


WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def load_holiday_calendars(path: Path) -> tuple[str, dict[int, list[dict[str, Any]]]]:
    """从数据文件加载并校验节假日日历。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"节假日数据文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"节假日数据文件不是有效 JSON: {path}: {exc}") from exc

    source = payload.get("source")
    calendars = payload.get("calendars")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("节假日数据 source 必须是非空字符串")
    if not isinstance(calendars, dict):
        raise ValueError("节假日数据 calendars 必须是对象")

    normalized: dict[int, list[dict[str, Any]]] = {}
    required_fields = {"name", "aliases", "festival_date", "start_date", "end_date"}
    for raw_year, raw_items in calendars.items():
        try:
            year = int(raw_year)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"节假日年份必须是整数: {raw_year}") from exc
        if not isinstance(raw_items, list):
            raise ValueError(f"{year} 年节假日数据必须是数组")
        for item in raw_items:
            if not isinstance(item, dict) or not required_fields <= item.keys():
                raise ValueError(f"{year} 年节假日记录缺少必要字段")
            for field in ("festival_date", "start_date", "end_date"):
                try:
                    parsed_date = date.fromisoformat(str(item[field]))
                except ValueError as exc:
                    raise ValueError(f"{year} 年节假日 {field} 不是 ISO 日期") from exc
                if parsed_date.year != year:
                    raise ValueError(f"{year} 年节假日 {field} 年份不一致")
        normalized[year] = raw_items
    return source.strip(), normalized


CALENDAR_SOURCE, HOLIDAY_CALENDARS = load_holiday_calendars(HOLIDAY_DATA_PATH)


def _unknown_result(reason: str) -> dict[str, Any]:
    return {
        "is_known": False,
        "is_holiday": None,
        "reason": reason,
        "source": CALENDAR_SOURCE,
    }


def _public_result(
    item: dict[str, Any],
    target: date | None = None,
    is_holiday: bool = True,
) -> dict[str, Any]:
    festival = date.fromisoformat(item["festival_date"])
    start = date.fromisoformat(item["start_date"])
    end = date.fromisoformat(item["end_date"])
    result = {
        "is_known": True,
        "is_holiday": is_holiday,
        "day_type": "holiday",
        "name": item["name"],
        "festival_date": item["festival_date"],
        "festival_weekday_name": WEEKDAY_NAMES[festival.weekday()],
        "start_date": item["start_date"],
        "start_weekday_name": WEEKDAY_NAMES[start.weekday()],
        "end_date": item["end_date"],
        "end_weekday_name": WEEKDAY_NAMES[end.weekday()],
        "source": CALENDAR_SOURCE,
    }
    if target is not None:
        result.update(
            date=target.isoformat(),
            weekday_name=WEEKDAY_NAMES[target.weekday()],
        )
    return result


def resolve_public_holiday(
    name: str | None = None,
    year: int | None = None,
    date_value: str | None = None,
) -> dict[str, Any]:
    """解析节假日名称，或判断指定日期是否属于法定节假日。"""
    if not name and not date_value:
        raise ValueError("节假日查询必须提供 name 或 date")

    if date_value:
        try:
            target = date.fromisoformat(date_value)
        except ValueError as exc:
            raise ValueError("date 必须是 ISO 8601 日期，例如 2026-06-19") from exc
        calendar = HOLIDAY_CALENDARS.get(target.year)
        if calendar is None:
            return _unknown_result(f"未收录 {target.year} 年节假日日历")
        for item in calendar:
            start = date.fromisoformat(item["start_date"])
            end = date.fromisoformat(item["end_date"])
            if start <= target <= end:
                return _public_result(item, target)
        day_type = "weekend" if target.weekday() >= 5 else "weekday"
        return {
            "is_known": True,
            "is_holiday": False,
            "day_type": day_type,
            "date": target.isoformat(),
            "weekday_name": WEEKDAY_NAMES[target.weekday()],
            "source": CALENDAR_SOURCE,
        }

    target_year = year or date.today().year
    calendar = HOLIDAY_CALENDARS.get(target_year)
    if calendar is None:
        return _unknown_result(f"未收录 {target_year} 年节假日日历")
    normalized_name = str(name).strip()
    for item in calendar:
        if normalized_name == item["name"] or normalized_name in item["aliases"]:
            return _public_result(item)
    return _unknown_result(f"{target_year} 年日历未收录节日“{normalized_name}”")
