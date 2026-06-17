from __future__ import annotations

from datetime import date
from typing import Any


CALENDAR_SOURCE = "本地维护的中国大陆全国性节假日日历"
WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

HOLIDAYS_2026 = [
    {
        "name": "元旦",
        "aliases": ["元旦节"],
        "festival_date": "2026-01-01",
        "start_date": "2026-01-01",
        "end_date": "2026-01-03",
    },
    {
        "name": "春节",
        "aliases": ["农历新年", "过年"],
        "festival_date": "2026-02-17",
        "start_date": "2026-02-15",
        "end_date": "2026-02-23",
    },
    {
        "name": "清明节",
        "aliases": ["清明"],
        "festival_date": "2026-04-05",
        "start_date": "2026-04-04",
        "end_date": "2026-04-06",
    },
    {
        "name": "劳动节",
        "aliases": ["五一", "五一劳动节"],
        "festival_date": "2026-05-01",
        "start_date": "2026-05-01",
        "end_date": "2026-05-05",
    },
    {
        "name": "端午节",
        "aliases": ["端午"],
        "festival_date": "2026-06-19",
        "start_date": "2026-06-19",
        "end_date": "2026-06-21",
    },
    {
        "name": "中秋节",
        "aliases": ["中秋"],
        "festival_date": "2026-09-25",
        "start_date": "2026-09-25",
        "end_date": "2026-09-27",
    },
    {
        "name": "国庆节",
        "aliases": ["国庆", "十一"],
        "festival_date": "2026-10-01",
        "start_date": "2026-10-01",
        "end_date": "2026-10-07",
    },
]

HOLIDAY_CALENDARS = {2026: HOLIDAYS_2026}


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
    """Resolve a named public holiday or determine whether a date is a holiday."""
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
