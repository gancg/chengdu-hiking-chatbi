from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from hiking_chatbi.config import SAMPLE_DATA_PATH
from hiking_chatbi.qwen_chatbi import (
    EstimateRouteTrafficTool,
    EstimateRouteWeatherTool,
    ListHikingRoutesTool,
    RecommendHikingRoutesTool,
    ResolveDepartureDateTool,
    ResolvePublicHolidayTool,
    build_departure_date_guidance,
    build_interview_guidance,
    build_qwen_agent,
)
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider


class QwenChatBITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "test.db"
        self.service = ChatBIService(db_path, NoTrafficProvider())
        self.service.seed(SAMPLE_DATA_PATH)
        self.departure = (datetime.now().astimezone() + timedelta(days=1)).replace(
            hour=6, minute=0, second=0, microsecond=0
        ).isoformat()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_list_tool_returns_reviewed_routes(self) -> None:
        """路线查询工具应返回已审核路线的结构化信息。"""
        result = json.loads(ListHikingRoutesTool(self.service).call({}))

        self.assertEqual(13, result["count"], "应返回十三条样例路线")
        self.assertIn("has_toilet", result["items"][0], "应包含路线设施字段")
        self.assertIn("route_fees", result["items"][0], "应包含路线费用明细")

    def test_recommend_tool_uses_existing_recommendation_service(self) -> None:
        """自然语言代理使用的推荐工具应复用现有推荐规则。"""
        result = json.loads(RecommendHikingRoutesTool(self.service).call({
            "departure_at": self.departure,
            "transport_modes": ["public_transit"],
            "max_distance_km": 13,
            "max_ascent_m": 800,
            "max_budget_cny": 120,
            "traffic_tolerance": "high",
        }))

        self.assertEqual(1, result["count"], "符合条件时应返回一条路线")
        self.assertEqual("qingcheng-back-mountain", result["items"][0]["route"]["id"])

    def test_traffic_tool_reports_missing_required_field(self) -> None:
        """交通工具缺少必填字段时应返回明确异常。"""
        with self.assertRaisesRegex(ValueError, "缺少 departure_at"):
            EstimateRouteTrafficTool(self.service).call({
                "route_id": "qingcheng-back-mountain",
            })

    def test_build_agent_registers_hiking_tools(self) -> None:
        """Qwen Agent 应注册受控的徒步业务工具。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertEqual(
            {
                "list_hiking_routes",
                "recommend_hiking_routes",
                "estimate_route_traffic",
                "estimate_route_weather",
                "resolve_departure_date",
                "resolve_public_holiday",
            },
            set(agent.function_map),
            "Agent 只能注册受控的徒步查询工具",
        )

    def test_weather_tool_reports_missing_required_field(self) -> None:
        """天气工具缺少必填字段时应返回明确异常。"""
        with self.assertRaisesRegex(ValueError, "缺少 departure_at"):
            EstimateRouteWeatherTool(self.service).call({
                "route_id": "qingcheng-back-mountain",
            })

    def test_interview_guidance_changes_with_conversation_rounds(self) -> None:
        """访谈提示应随用户轮次从探索逐步进入推荐阶段。"""
        first_round = build_interview_guidance([
            {"role": "user", "content": "周末想去徒步"},
        ])
        third_round = build_interview_guidance([
            {"role": "user", "content": "周末想去徒步"},
            {"role": "assistant", "content": "更偏向自驾还是公共交通？"},
            {"role": "user", "content": "自驾"},
            {"role": "assistant", "content": "平时徒步经验怎么样？"},
            {"role": "user", "content": "走过几次"},
        ])
        fifth_round = build_interview_guidance([
            {"role": "user", "content": str(index)}
            for index in range(5)
        ])

        self.assertIn("探索阶段", first_round)
        self.assertIn("一次只问一个", first_round)
        self.assertIn("收敛阶段", third_round)
        self.assertIn("推荐阶段", fifth_round)
        self.assertIn("不要继续机械追问", fifth_round)

    def test_agent_uses_guided_interview_prompt(self) -> None:
        """Qwen Agent 系统提示应允许带假设给出初步推荐。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("引导式需求访谈", agent.system_message)
        self.assertIn("默认值或假设", agent.system_message)

    def test_departure_date_guidance_uses_current_year_for_dates_without_year(self) -> None:
        """用户未说明年份时，出发日期应解释为当前年度。"""
        guidance = build_departure_date_guidance(date(2026, 6, 13))

        self.assertIn("当前日期是 2026-06-13", guidance, "应告诉模型当前日期")
        self.assertIn("2026-06-15", guidance, "无年份日期示例应使用当前年度")
        self.assertIn("不要自行推断为下一年度", guidance, "不得把无年份日期顺延到下一年")

    def test_agent_prompt_contains_dynamic_departure_date_guidance(self) -> None:
        """Qwen Agent 系统提示应包含动态的无年份日期解释规则。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")
        current_year = str(datetime.now().astimezone().year)

        self.assertIn("当前日期上下文", agent.system_message)
        self.assertIn(f"当前年度是 {current_year}", agent.system_message)

    def test_agent_prompt_hides_internal_query_language_from_users(self) -> None:
        """Qwen Agent 面向用户回答时不应暴露内部查询字段和筛选逻辑。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("不得向用户展示内部字段名", agent.system_message)
        self.assertIn("目前没有同时有厕所和补给点的路线", agent.system_message)
        self.assertIn("不得补充工具结果没有提供的原因", agent.system_message)

    def test_holiday_tool_resolves_named_holiday(self) -> None:
        """节假日工具应根据节日名称返回可核验日期。"""
        result = json.loads(ResolvePublicHolidayTool(self.service).call({
            "name": "端午节",
            "year": 2026,
        }))

        self.assertTrue(result["is_known"], "2026 年端午节应已收录")
        self.assertEqual("2026-06-19", result["festival_date"], "不得错误回答为六月一日")
        self.assertEqual("星期五", result["festival_weekday_name"], "节日星期应由工具返回")

    def test_agent_prompt_requires_holiday_tool_before_holiday_inference(self) -> None:
        """Qwen Agent 不得凭模型记忆推断法定节假日。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("必须先调用节假日查询工具", agent.system_message)
        self.assertIn("不得凭记忆推断节日日期", agent.system_message)

    def test_agent_prompt_requires_numbered_next_action_options(self) -> None:
        """Qwen Agent 提供多个下一步动作时应使用数字编号。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("使用连续数字编号", agent.system_message)
        self.assertIn("直接回复数字", agent.system_message)
        self.assertIn("不得列出当前工具或数据无法完成的动作", agent.system_message)

    def test_holiday_tool_returns_verified_weekday_and_day_type(self) -> None:
        """节假日工具按日期查询时应返回星期和交通日期类型。"""
        result = json.loads(ResolvePublicHolidayTool(self.service).call({
            "date": "2026-06-15",
        }))

        self.assertEqual("星期一", result["weekday_name"], "日期对应星期必须由工具计算")
        self.assertEqual("weekday", result["day_type"], "工作日类型必须由工具返回")

    def test_agent_prompt_requires_date_tool_for_weekday_classification(self) -> None:
        """Qwen Agent 不得自行计算星期或交通日期类型。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("必须使用具体出发日期调用节假日查询工具", agent.system_message)
        self.assertIn("不得自行计算星期", agent.system_message)
        self.assertIn("不得声称景区人流或补给点开放遵循相同规则", agent.system_message)

    def test_departure_date_tool_resolves_current_weekend(self) -> None:
        """相对日期工具应正确解析本周末。"""
        result = json.loads(ResolveDepartureDateTool(self.service).call({
            "expression": "本周末",
            "reference_date": "2026-06-13",
        }))

        self.assertEqual(
            ["2026-06-13", "2026-06-14"],
            [item["date"] for item in result["candidates"]],
            "本周末不得错误解析为六月十四日和十五日",
        )

    def test_agent_prompt_requires_relative_date_tool(self) -> None:
        """Qwen Agent 不得自行推算本周末等相对日期。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("必须先调用相对出发日期查询工具", agent.system_message)
        self.assertIn("不得自行推算具体日期", agent.system_message)


if __name__ == "__main__":
    unittest.main()
