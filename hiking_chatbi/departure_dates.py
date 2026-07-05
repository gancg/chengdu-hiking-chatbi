from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .holidays import WEEKDAY_NAMES, resolve_public_holiday


def _candidate(target: date, reference_date: date) -> dict[str, Any]:
    holiday = resolve_public_holiday(date_value=target.isoformat())
    return {
        "date": target.isoformat(),
        "weekday_name": WEEKDAY_NAMES[target.weekday()],
        "is_before_reference_date": target < reference_date,
        "is_not_after_reference_date": target <= reference_date,
        "requires_future_time_confirmation": target <= reference_date,
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
    weekday_indexes = {
        "一": 0,
        "二": 1,
        "三": 2,
        "四": 3,
        "五": 4,
        "六": 5,
        "日": 6,
        "天": 6,
    }
    weekday_expressions = {
        f"{prefix}周{weekday}"
        for prefix in ("", "本", "下")
        for weekday in weekday_indexes
    }
    supported_expressions = {
        *single_offsets,
        *weekday_expressions,
        "本周末",
        "下周末",
    }
    if normalized not in supported_expressions:
        matches = re.findall(
            r"本周末|下周末|[本下]?周[一二三四五六日天]|今天|明天|后天",
            normalized,
        )
        unique_matches = list(dict.fromkeys(matches))
        if len(unique_matches) > 1:
            raise ValueError(
                f"相对日期表达包含多个相对日期，无法确定出发日: {normalized}"
            )
        if len(unique_matches) == 1:
            normalized = unique_matches[0]

    interpretation = normalized
    if normalized in single_offsets:
        targets = [reference_date + timedelta(days=single_offsets[normalized])]
    elif re.fullmatch(r"周[一二三四五六日天]", normalized):
        target_weekday = weekday_indexes[normalized[-1]]
        days_ahead = (target_weekday - reference_date.weekday()) % 7
        targets = [reference_date + timedelta(days=days_ahead)]
        interpretation = f"从参考日期起最近的星期{WEEKDAY_NAMES[target_weekday][-1]}"
    elif re.fullmatch(r"本周[一二三四五六日天]", normalized):
        targets = [week_start + timedelta(days=weekday_indexes[normalized[-1]])]
        interpretation = "参考日期所在自然周的" + WEEKDAY_NAMES[weekday_indexes[normalized[-1]]]
    elif re.fullmatch(r"下周[一二三四五六日天]", normalized):
        targets = [
            week_start + timedelta(days=7 + weekday_indexes[normalized[-1]])
        ]
        interpretation = "参考日期下一自然周的" + WEEKDAY_NAMES[weekday_indexes[normalized[-1]]]
    elif normalized == "本周末":
        targets = [week_start + timedelta(days=5), week_start + timedelta(days=6)]
    elif normalized == "下周末":
        targets = [week_start + timedelta(days=12), week_start + timedelta(days=13)]
    else:
        raise ValueError(f"不支持的相对日期表达: {normalized}")

    return {
        "expression": normalized,
        "interpretation": interpretation,
        "reference_date": reference_date.isoformat(),
        "candidates": [_candidate(target, reference_date) for target in targets],
    }
