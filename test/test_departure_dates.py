from __future__ import annotations

import unittest
from datetime import date

from hiking_chatbi.departure_dates import resolve_departure_date


class DepartureDateTest(unittest.TestCase):
    def test_plain_saturday_keeps_distinct_wording_from_current_week(self) -> None:
        """无前缀“周六”应说明为最近周六，不得冒充自然周中的“本周六”。"""
        result = resolve_departure_date("周六想去爬山", date(2026, 7, 5))

        self.assertEqual("周六", result["expression"])
        self.assertEqual("2026-07-11", result["candidates"][0]["date"])
        self.assertEqual("从参考日期起最近的星期六", result["interpretation"])

    def test_current_week_saturday_remains_in_reference_calendar_week(self) -> None:
        """“本周六”必须严格落在参考日期所在自然周，过期时不得顺延。"""
        result = resolve_departure_date("本周六", date(2026, 7, 5))

        self.assertEqual("2026-07-04", result["candidates"][0]["date"])
        self.assertTrue(
            result["candidates"][0]["is_before_reference_date"],
            "本周六已经过去时必须明确标记",
        )
    def test_current_weekend_uses_reference_calendar_week(self) -> None:
        """本周末应返回参考日期所在自然周的星期六和星期日。"""
        result = resolve_departure_date("本周末", date(2026, 6, 13))

        self.assertEqual(
            ["2026-06-13", "2026-06-14"],
            [item["date"] for item in result["candidates"]],
            "不得把本周末错误顺延为六月十四日和十五日",
        )
        self.assertEqual(
            ["星期六", "星期日"],
            [item["weekday_name"] for item in result["candidates"]],
            "候选日期应返回正确星期",
        )

    def test_next_weekend_uses_next_calendar_week(self) -> None:
        """下周末应返回下一自然周的星期六和星期日。"""
        result = resolve_departure_date("下周末", date(2026, 6, 13))

        self.assertEqual(
            ["2026-06-20", "2026-06-21"],
            [item["date"] for item in result["candidates"]],
            "下周末应落在下一自然周",
        )

    def test_day_after_tomorrow_returns_verified_weekday(self) -> None:
        """后天应基于参考日期返回由程序核验的正确星期。"""
        result = resolve_departure_date("后天", date(2026, 6, 18))

        self.assertEqual(
            ["2026-06-20"],
            [item["date"] for item in result["candidates"]],
            "2026-06-18 的后天应为 2026-06-20",
        )
        self.assertEqual(
            ["星期六"],
            [item["weekday_name"] for item in result["candidates"]],
            "不得把 2026-06-20 错写为星期五",
        )

    def test_unsupported_expression_raises_clear_error(self) -> None:
        """不支持的相对日期表达不得由工具猜测。"""
        with self.assertRaisesRegex(ValueError, "不支持的相对日期表达"):
            resolve_departure_date("过阵子", date(2026, 6, 13))

    def test_natural_phrase_extracts_single_relative_date(self) -> None:
        """中文测试：自然短句中的唯一相对日期应被正确提取。"""
        result = resolve_departure_date("本周日出发", date(2026, 7, 2))

        self.assertEqual("本周日", result["expression"])
        self.assertEqual("2026-07-05", result["candidates"][0]["date"])

    def test_natural_phrase_rejects_multiple_relative_dates(self) -> None:
        """中文测试：一句话包含多个相对日期时不得擅自选择。"""
        with self.assertRaisesRegex(ValueError, "包含多个相对日期"):
            resolve_departure_date("本周六或者本周日出发", date(2026, 7, 2))
