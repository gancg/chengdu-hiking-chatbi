from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .holidays import WEEKDAY_NAMES, resolve_public_holiday


def _candidate(target: date, reference_date: date) -> dict[str, Any]:
    holiday = resolve_public_holiday(date_value=target.isoformat())
    return {
        "date": target.isoformat(),
        "weekday_name": WEEKDAY_NAMES[target.weekday()],
        "is_before_reference_date": target < reference_date,
        "is_holiday": holiday["is_holiday"],
        "day_type": holiday.get("day_type"),
        "holiday_name": holiday.get("name"),
    }


def resolve_departure_date(expression: str, reference_date: date) -> dict[str, Any]:
    """Resolve a supported Chinese relative departure-date expression."""
    normalized = expression.strip()
    week_start = reference_date - timedelta(days=reference_date.weekday())
    single_offsets = {
        "今天": 0,
        "明天": 1,
        "后天": 2,
    }
    week_offsets = {
        "本周六": 5,
        "本周日": 6,
        "下周六": 12,
        "下周日": 13,
    }

    if normalized in single_offsets:
        targets = [reference_date + timedelta(days=single_offsets[normalized])]
    elif normalized in week_offsets:
        targets = [week_start + timedelta(days=week_offsets[normalized])]
    elif normalized == "本周末":
        targets = [week_start + timedelta(days=5), week_start + timedelta(days=6)]
    elif normalized == "下周末":
        targets = [week_start + timedelta(days=12), week_start + timedelta(days=13)]
    else:
        raise ValueError(f"不支持的相对日期表达: {normalized}")

    return {
        "expression": normalized,
        "reference_date": reference_date.isoformat(),
        "candidates": [_candidate(target, reference_date) for target in targets],
    }
