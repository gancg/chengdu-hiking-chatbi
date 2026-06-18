from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from hiking_chatbi.config import SAMPLE_COMMERCIAL_TOURS_PATH, SAMPLE_DATA_PATH, optional_int_from_env
import hiking_chatbi.qwen_chatbi as qwen_chatbi
from hiking_chatbi.qwen_chatbi import (
    RecommendCommercialToursTool,
    EstimateRouteTrafficTool,
    EstimateRouteWeatherTool,
    ListHikingRoutesTool,
    RecommendHikingRoutesTool,
    ResolveDepartureDateTool,
    ResolvePublicHolidayTool,
    build_departure_date_guidance,
    build_interview_guidance,
    build_public_holiday_guidance,
    build_qwen_agent,
)
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider


class QwenChatBITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "test.db"
        self.service = ChatBIService(db_path, NoTrafficProvider())
        self.service.seed(SAMPLE_DATA_PATH, SAMPLE_COMMERCIAL_TOURS_PATH)
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
                "recommend_commercial_tours",
                "resolve_departure_date",
                "resolve_public_holiday",
            },
            set(agent.function_map),
            "Agent 只能注册受控的徒步查询工具",
        )

    def test_build_agent_uses_stable_default_seed(self) -> None:
        """Qwen Agent 默认应使用稳定 seed，避免调试启动方式造成随机分叉。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertEqual(42, agent.llm.generate_cfg["seed"], "默认 seed 应固定为 42")

    def test_build_agent_allows_random_seed_when_disabled(self) -> None:
        """显式禁用 seed 时应保留原有随机生成行为。"""
        with patch.object(qwen_chatbi, "QWEN_SEED", None):
            agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertNotIn("seed", agent.llm.generate_cfg, "禁用 seed 后不应传入固定 seed")

    def test_optional_int_from_env_allows_empty_value(self) -> None:
        """空字符串环境变量应解析为 None，便于恢复随机 seed。"""
        with patch.dict("os.environ", {"CHATBI_QWEN_SEED": ""}):
            result = optional_int_from_env("CHATBI_QWEN_SEED", 42)

        self.assertIsNone(result, "空 seed 应解析为 None")

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

        self.assertIn("当前日期是 2026-06-13（星期六）", guidance, "应告诉模型当前日期和星期")
        self.assertIn("后天是 2026-06-15（星期一）", guidance, "应给出程序核验的后天日期和星期")
        self.assertIn("2026-06-15", guidance, "无年份日期示例应使用当前年度")
        self.assertIn("不要自行推断为下一年度", guidance, "不得把无年份日期顺延到下一年")

    def test_departure_date_guidance_verifies_day_after_tomorrow_weekday(self) -> None:
        """当前日期上下文应直接核验后天的正确星期。"""
        guidance = build_departure_date_guidance(date(2026, 6, 18))

        self.assertIn("当前日期是 2026-06-18（星期四）", guidance, "不得把 2026-06-18 写成星期三")
        self.assertIn("后天是 2026-06-20（星期六）", guidance, "不得把 2026-06-20 写成星期五")

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

    def test_public_holiday_guidance_contains_verified_dragon_boat_dates(self) -> None:
        """节假日摘要应给出已收录的端午节正确日期，防止模型凭记忆编造。"""
        guidance = build_public_holiday_guidance()

        self.assertIn("2026 端午节", guidance, "应包含 2026 年端午节摘要")
        self.assertIn("节日当天 2026-06-19（星期五）", guidance, "端午节当天不得错写")
        self.assertIn("假期 2026-06-19（星期五）至 2026-06-21（星期日）", guidance)
        self.assertIn("不得输出未由节假日工具或本摘要支持", guidance)
        self.assertNotIn("2026-06-01", guidance, "端午节摘要不得包含错误的六月一日")

    def test_agent_prompt_includes_public_holiday_guidance(self) -> None:
        """Qwen Agent 系统提示应注入已收录节假日摘要作为兜底上下文。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("已收录节假日摘要", agent.system_message)
        self.assertIn("2026 端午节", agent.system_message)
        self.assertIn("2026-06-19", agent.system_message)
        self.assertIn("2026-06-21", agent.system_message)

    def test_agent_prompt_requires_numbered_next_action_options(self) -> None:
        """Qwen Agent 提供多个下一步动作时应使用数字编号。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("使用连续数字编号", agent.system_message)
        self.assertIn("直接回复数字", agent.system_message)
        self.assertIn("不得列出当前工具或数据无法完成的动作", agent.system_message)

    def test_agent_prompt_requires_numbered_preference_options(self) -> None:
        """Qwen Agent 询问强度等简单偏好时应让用户用数字选择。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("路线强度", agent.system_message)
        self.assertIn("简单偏好", agent.system_message)
        self.assertIn("1. 轻松 2. 适中 3. 挑战", agent.system_message)
        self.assertIn("把复杂判断留给后台", agent.system_message)
        self.assertIn("不得先展开长篇定义，再重复询问同一个问题", agent.system_message)

    def test_holiday_tool_returns_verified_weekday_and_day_type(self) -> None:
        """节假日工具按日期查询时应返回星期和交通日期类型。"""
        result = json.loads(ResolvePublicHolidayTool(self.service).call({
            "date": "2026-06-15",
        }))

        self.assertEqual("星期一", result["weekday_name"], "日期对应星期必须由工具计算")
        self.assertEqual("weekday", result["day_type"], "工作日类型必须由工具返回")

    def test_holiday_tool_distinguishes_departure_date_from_festival_date(self) -> None:
        """假期内出发日不得被误写成节日当天。"""
        result = json.loads(ResolvePublicHolidayTool(self.service).call({
            "date": "2026-06-20",
        }))

        self.assertTrue(result["is_holiday"], "2026-06-20 应判定为端午假期内日期")
        self.assertEqual("2026-06-20", result["date"], "应保留用户具体出发日期")
        self.assertEqual("星期六", result["weekday_name"], "应返回出发日星期")
        self.assertEqual("2026-06-19", result["festival_date"], "端午节当天应为 2026-06-19")
        self.assertNotEqual(
            result["date"],
            result["festival_date"],
            "出发日处于假期内时也不得等同于节日当天",
        )

    def test_agent_prompt_requires_date_tool_for_weekday_classification(self) -> None:
        """Qwen Agent 不得自行计算星期或交通日期类型。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("必须使用具体出发日期调用节假日查询工具", agent.system_message)
        self.assertIn("不得自行计算星期", agent.system_message)
        self.assertIn("不得声称景区人流或补给点开放遵循相同规则", agent.system_message)

    def test_agent_prompt_requires_departure_and_festival_date_distinction(self) -> None:
        """Qwen Agent 回答时应区分出发日期和节日当天。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("出发日期", agent.system_message)
        self.assertIn("节日当天", agent.system_message)
        self.assertIn("不得把假期内日期表述为节日当天", agent.system_message)

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

        self.assertIn("后天", agent.system_message)
        self.assertIn("必须先调用相对出发日期查询工具", agent.system_message)
        self.assertIn("不得自行推算具体日期", agent.system_message)
        self.assertIn("不得在调用工具前先输出", agent.system_message)

    def test_agent_prompt_requires_tool_weekday_when_date_weekday_conflicts(self) -> None:
        """日期与星期冲突时，Qwen Agent 应以工具返回结果为准。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("如果用户给出的日期和星期不一致", agent.system_message)
        self.assertIn("以工具返回的日期和星期为准", agent.system_message)

    def test_agent_prompt_requires_weekend_day_confirmation(self) -> None:
        """用户只说周末出行时，Qwen Agent 应先确认具体日期。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("周末出行", agent.system_message)
        self.assertIn("必须先询问清楚具体是哪一天", agent.system_message)
        self.assertIn("不得自行选择周六或周日", agent.system_message)

    def test_agent_prompt_defaults_recommendations_to_single_day_routes(self) -> None:
        """Qwen Agent 默认应只推荐单日往返路线，多日游作为后续 TODO。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("默认面向单日往返出行", agent.system_message)
        self.assertIn("多日游路线暂未完整支持", agent.system_message)
        self.assertIn("TODO", agent.system_message)

    def test_agent_prompt_requires_route_selection_prerequisites(self) -> None:
        """Qwen Agent 选择路线前必须先明确出行方式和出行时间。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("选择路线", agent.system_message, "系统提示应覆盖路线选择场景")
        self.assertIn("先明确出行方式和出行时间", agent.system_message, "应先确认出行方式和时间")
        self.assertIn("自驾、公共交通、报团", agent.system_message, "出行方式选项应面向用户清晰表达")
        self.assertIn("不得继续追问预算、强度、风景、设施", agent.system_message, "前置条件不完整时不得先问其它筛选条件")
        self.assertIn("报团", agent.system_message, "应覆盖报团场景")
        self.assertIn("recommend_commercial_tours", agent.system_message, "报团场景应使用商团推荐工具")

    def test_agent_prompt_requires_recommendation_output_order(self) -> None:
        """Qwen Agent 输出路线推荐时应按固定信息顺序组织。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        expected_order = "推荐路线、推荐理由、天气参考、交通参考、费用参考、设施与风险"
        self.assertIn(expected_order, agent.system_message, "推荐回答应先路线再理由和各类参考")
        self.assertIn("每条路线先给路线名称和核心行程数据", agent.system_message)
        self.assertIn("天气参考先说官方预警", agent.system_message)
        self.assertIn("交通参考说明去程/返程耗时和数据类型", agent.system_message)
        self.assertIn("费用参考说明总费用范围和对应交通方式", agent.system_message)
        self.assertIn("缺少某一类工具结果时，说明暂无该项参考", agent.system_message)

    def test_agent_prompt_requires_weather_source_display(self) -> None:
        """Qwen Agent 展示和风天气结果时应明确天气来源。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("展示天气参考时", agent.system_message)
        self.assertIn("表明来自和风天气，必须明确写出天气来源", agent.system_message)
        self.assertIn("官方预警来源：和风天气官方预警聚合", agent.system_message)
        self.assertIn("天气预报来源：和风天气每日天气预报", agent.system_message)
        self.assertIn("天气来源暂未提供", agent.system_message)
        self.assertIn("不得自行补充来源", agent.system_message)

    def test_interview_guidance_prioritizes_route_selection_prerequisites(self) -> None:
        """访谈引导应优先补齐出行方式和出行时间，再进入其它筛选条件。"""
        guidance = build_interview_guidance([
            {"role": "user", "content": "想找一条成都周边徒步路线"},
        ])

        self.assertIn("先补齐出行方式和出行时间", guidance, "早期访谈应优先确认前置条件")
        self.assertIn("自驾、公共交通、报团", guidance, "应明确给出三类出行方式")
        self.assertIn("不要先追问预算、强度、风景或设施", guidance, "前置条件前不得进入其它筛选")

    def test_commercial_tour_tool_returns_provider_product_route_and_warning(self) -> None:
        """商团工具应返回可展示的商团名称、产品、路线、价格和二次确认提示。"""
        result = json.loads(RecommendCommercialToursTool(self.service).call({
            "departure_date": "2026-06-20",
            "party_size": 2,
            "max_budget_cny": 400,
        }))

        self.assertGreater(result["count"], 0, "当天有收录商团时应返回结果")
        item = result["items"][0]
        self.assertIn("product", item, "商团工具应包含产品信息")
        self.assertIn("provider_name", item["product"], "商团工具应包含可展示的商团名称")
        self.assertTrue(item["product"]["provider_name"], "商团名称不得为空")
        self.assertIn("route", item, "商团工具应包含路线摘要")
        self.assertIn("total_price_max_cny", item, "商团工具应包含按人数估算的总价")
        self.assertIn("risk_notice", item, "商团工具应提醒用户二次确认")
        self.assertIn("商团产品为已收录信息", item["risk_notice"], "二次确认提示应说明信息口径")
        self.assertIn("价格、团期、名额和安全要求", item["risk_notice"], "二次确认提示应覆盖关键确认项")

    def test_agent_prompt_contains_commercial_tour_boundaries(self) -> None:
        """Qwen Agent 不得编造未收录商团信息或承诺余位成团状态。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("recommend_commercial_tours", agent.system_message)
        self.assertIn("不得编造未收录商家", agent.system_message)
        self.assertIn("不承诺余位", agent.system_message)
        self.assertIn("必须展示商团名称", agent.system_message)
        self.assertIn("该商团的小程序", agent.system_message)


if __name__ == "__main__":
    unittest.main()
