from __future__ import annotations

import unittest

from hiking_chatbi.holidays import resolve_public_holiday


class PublicHolidayTest(unittest.TestCase):
    def test_resolve_dragon_boat_holiday_by_name(self) -> None:
        """按名称查询端午节时应返回节日当天和完整假期。"""
        result = resolve_public_holiday(name="端午节", year=2026)

        self.assertTrue(result["is_known"], "2026 年端午节应已收录")
        self.assertEqual("2026-06-19", result["festival_date"], "应返回正确的端午节日期")
        self.assertEqual("星期五", result["festival_weekday_name"], "应返回正确的节日星期")
        self.assertEqual("2026-06-19", result["start_date"], "应返回端午假期开始日期")
        self.assertEqual("2026-06-21", result["end_date"], "应返回端午假期结束日期")

    def test_resolve_holiday_by_date(self) -> None:
        """按日期查询时应判断该日期是否处于法定节假日假期。"""
        result = resolve_public_holiday(date_value="2026-06-20")

        self.assertTrue(result["is_known"], "已收录年份的日期判断应有明确结果")
        self.assertTrue(result["is_holiday"], "端午假期内日期应判定为节假日")
        self.assertEqual("端午节", result["name"], "应返回对应节日名称")

    def test_unknown_year_returns_unknown_result(self) -> None:
        """未收录年份不得猜测节假日日期。"""
        result = resolve_public_holiday(name="端午节", year=2027)

        self.assertFalse(result["is_known"], "未收录年份应返回未知")
        self.assertIn("未收录", result["reason"], "未知结果应说明原因")

    def test_resolve_date_returns_verified_weekday_and_day_type(self) -> None:
        """按日期查询应返回可核验的星期和交通日期类型。"""
        result = resolve_public_holiday(date_value="2026-06-15")

        self.assertEqual("星期一", result["weekday_name"], "不得把星期一回答为星期日")
        self.assertEqual("weekday", result["day_type"], "星期一应按工作日处理")
        self.assertFalse(result["is_holiday"], "普通工作日不应判定为法定节假日")
