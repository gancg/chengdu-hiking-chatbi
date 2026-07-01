from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from hiking_chatbi.config import SAMPLE_DATA_PATH, optional_int_from_env
import hiking_chatbi.qwen_chatbi as qwen_chatbi
from hiking_chatbi.qwen_chatbi import (
    EstimateRouteTrafficTool,
    EstimateRouteWeatherTool,
    FindGroupTourLinksTool,
    ListHikingRoutesTool,
    RecommendHikingRoutesTool,
    ResolveDepartureDateTool,
    ResolvePublicHolidayTool,
    build_departure_date_guidance,
    build_conversation_state,
    build_interview_guidance,
    build_route_search_terms,
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
        self.service.seed(SAMPLE_DATA_PATH)
        self.departure = (datetime.now().astimezone() + timedelta(days=1)).replace(
            hour=6, minute=0, second=0, microsecond=0
        ).isoformat()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_list_tool_returns_reviewed_routes(self) -> None:
        """路线查询工具应返回已审核路线的结构化信息。"""
        result = json.loads(ListHikingRoutesTool(self.service).call({}))

        self.assertEqual(16, result["count"], "应返回十六条样例路线")
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
                "find_group_tour_links",
                "resolve_departure_date",
                "resolve_public_holiday",
            },
            set(agent.function_map),
            "Agent 只能注册受控的徒步查询工具",
        )

    def test_group_tour_link_tool_uses_selected_route(self) -> None:
        """报团链接工具应只按已选路线查询在线活动链接。"""
        expected = [{
            "title": "青城后山一日活动",
            "url": "https://m.youxiake.com/lines.html?id=100",
        }]
        with patch.object(self.service, "group_tour_links", return_value=expected) as call:
            result = json.loads(FindGroupTourLinksTool(self.service).call({
                "route_id": "qingcheng-back-mountain",
            }))

        self.assertEqual(expected, result["items"], "工具只能返回服务查询到的链接")
        call.assert_called_once_with("qingcheng-back-mountain")

    def test_group_tour_link_tool_does_not_repeat_conversation_confirmation(self) -> None:
        """工具调用已经开始后，不得再次校验对话中的报团确认状态。"""
        messages = [
            {"role": "user", "content": "想去巴朗山"},
            {"role": "assistant", "content": "交通方式：1. 自驾 2. 报团 3. 公共交通"},
            {"role": "user", "content": "2"},
        ]

        expected = [{"title": "活动", "url": "https://www.youxiake.com/lines.html?id=1"}]
        with patch.object(self.service, "group_tour_links", return_value=expected) as call:
            result = json.loads(FindGroupTourLinksTool(self.service).call(
                {"route_id": "qingcheng-back-mountain"},
                messages=messages,
            ))

        self.assertEqual(expected, result["items"])
        call.assert_called_once_with("qingcheng-back-mountain")

    def test_group_tour_link_tool_ignores_transport_state_after_call_starts(self) -> None:
        """即使消息状态解析为自驾，已发起的只读链接查询也不应二次确认。"""
        messages = [
            {"role": "user", "content": "我选青城后山环线"},
            {"role": "assistant", "content": "交通方式：1. 自驾 2. 报团 3. 公共交通"},
            {"role": "user", "content": "1"},
        ]

        expected = [{"title": "活动", "url": "https://www.youxiake.com/lines.html?id=1"}]
        with patch.object(self.service, "group_tour_links", return_value=expected) as call:
            result = json.loads(FindGroupTourLinksTool(self.service).call(
                {"route_id": "qingcheng-back-mountain"},
                messages=messages,
            ))

        self.assertEqual(expected, result["items"])
        call.assert_called_once_with("qingcheng-back-mountain")

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

    def test_named_destination_only_requests_departure_date(self) -> None:
        """点名库内目的地后，只应确认出发日期，不再收集普通路线偏好。"""
        route_search_terms = build_route_search_terms(self.service.routes())

        guidance = build_interview_guidance(
            [{"role": "user", "content": "我想去巴朗山徒步"}],
            route_search_terms,
        )

        self.assertIn("命中已审核路线", guidance, "巴朗山应命中样例路线库")
        self.assertIn("只确认具体出发日期", guidance, "目的地明确后只应补问日期")
        self.assertIn("不得询问体力、经验、人数、距离、爬升、难度、风景、设施", guidance)

    def test_named_destination_recommends_immediately_after_date(self) -> None:
        """点名库内目的地且日期已确定后，应立即推荐而不是继续追问。"""
        route_search_terms = build_route_search_terms(self.service.routes())

        guidance = build_interview_guidance(
            [
                {"role": "user", "content": "想去巴朗山"},
                {"role": "assistant", "content": "具体哪天出发？"},
                {"role": "user", "content": "2026-07-04 出发"},
            ],
            route_search_terms,
        )

        self.assertIn("日期确定后立即推荐", guidance)
        self.assertIn("不得继续追问", guidance)
        self.assertIn("巴朗山", guidance)

    def test_generic_request_does_not_trigger_named_destination_guidance(self) -> None:
        """未点名库内目的地时，应保留原有引导式访谈。"""
        route_search_terms = build_route_search_terms(self.service.routes())

        guidance = build_interview_guidance(
            [{"role": "user", "content": "想找一条成都周边徒步路线"}],
            route_search_terms,
        )

        self.assertIn("探索阶段", guidance)
        self.assertNotIn("命中已审核路线", guidance)

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

    def test_agent_prompt_filters_routes_before_confirming_transport_mode(self) -> None:
        """Qwen Agent 前期应先确认出发时间并筛选路线，最后再确认交通方式。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("选择路线", agent.system_message, "系统提示应覆盖路线选择场景")
        self.assertIn("先确认具体出发时间", agent.system_message, "前期应先确认出发时间")
        self.assertIn("筛选出符合用户预期的候选路线", agent.system_message, "应先筛选候选路线")
        self.assertIn("前期对话不得询问或要求用户选择交通方式", agent.system_message)
        self.assertIn("先让用户明确选择其中一条路线", agent.system_message, "推荐后应先选定路线")
        self.assertIn("不得在同一轮追加交通方式问题", agent.system_message)
        self.assertIn("用户明确选定某条路线后", agent.system_message, "选定路线后才应确认交通方式")

    def test_agent_prompt_requires_recommendation_output_order(self) -> None:
        """Qwen Agent 推荐候选时应先让用户选路线，再补交通和费用。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        expected_order = "推荐路线、推荐理由、天气参考、设施与风险、路线选择"
        self.assertIn(expected_order, agent.system_message, "候选推荐应以路线选择结束")
        self.assertIn("每条路线先给路线名称和核心行程数据", agent.system_message)
        self.assertIn("天气参考先说官方预警", agent.system_message)
        self.assertIn("候选路线阶段不得展开交通和费用比较", agent.system_message)
        self.assertIn("选定路线并确认交通方式后", agent.system_message)

    def test_agent_prompt_requires_weather_source_display(self) -> None:
        """Qwen Agent 展示和风天气结果时应明确天气来源。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        self.assertIn("展示天气参考时", agent.system_message)
        self.assertIn("表明来自和风天气，必须明确写出天气来源", agent.system_message)
        self.assertIn("官方预警来源：和风天气官方预警聚合", agent.system_message)
        self.assertIn("天气预报来源：和风天气每日天气预报", agent.system_message)
        self.assertIn("天气来源暂未提供", agent.system_message)
        self.assertIn("不得自行补充来源", agent.system_message)

    def test_interview_guidance_does_not_ask_transport_mode_early(self) -> None:
        """早期访谈只确认出发时间和路线偏好，不得要求选择交通方式。"""
        guidance = build_interview_guidance([
            {"role": "user", "content": "想找一条成都周边徒步路线"},
        ])

        self.assertIn("先确认具体出发时间", guidance, "早期访谈应优先确认出发时间")
        self.assertIn("路线偏好", guidance, "确认时间后应继续筛选路线")
        self.assertIn("不要询问交通方式", guidance, "前期不得要求选择交通方式")
        self.assertNotIn("自驾、公共交通、报团", guidance, "前期不得展示交通方式选项")

    def test_interview_guidance_requests_route_choice_before_transport(self) -> None:
        """给出候选路线但用户尚未选择时，只能让用户先选定路线。"""
        guidance = build_interview_guidance([
            {"role": "user", "content": "周六出发"},
            {"role": "assistant", "content": "想走什么强度？"},
            {"role": "user", "content": "轻松一些"},
            {"role": "assistant", "content": "更喜欢森林还是雪山？"},
            {"role": "user", "content": "森林"},
            {"role": "assistant", "content": "这里有几条候选路线"},
            {"role": "user", "content": "可以继续比较"},
        ])

        self.assertIn("先让用户明确选择一条路线", guidance)
        self.assertIn("这一轮不得询问交通方式", guidance)
        self.assertNotIn("1. 自驾", guidance, "路线未选定时不得展示交通方式选项")

    def test_interview_guidance_confirms_transport_after_explicit_route_choice(self) -> None:
        """用户明确选择路线后，下一步才确认自驾、报团或公共交通。"""
        guidance = build_interview_guidance([
            {"role": "user", "content": "周六出发"},
            {"role": "assistant", "content": "这里有三条候选路线，请先选择一条"},
            {"role": "user", "content": "我选青城后山环线"},
        ])

        self.assertIn("用户已经明确选定路线", guidance)
        self.assertIn("下一步只确认交通方式", guidance)
        self.assertIn(
            "请选择交通方式：\n1. 自驾\n2. 报团\n3. 公共交通\n\n直接回复 1、2 或 3 即可。",
            guidance,
        )
        self.assertIn("不得给问题本身编号", guidance)
        self.assertIn("不得追加路线对比或任何第二个问题", guidance)
        self.assertIn("不得增加“其他”选项", guidance)
        self.assertIn("不得使用图标、装饰标题或括号说明", guidance)

    def test_agent_prompt_uses_fixed_transport_choice_template(self) -> None:
        """路线选定后的交通选择应简单唯一，避免嵌套编号和额外问题。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        expected = (
            "请选择交通方式：\n"
            "1. 自驾\n"
            "2. 报团\n"
            "3. 公共交通\n\n"
            "直接回复 1、2 或 3 即可。"
        )
        self.assertIn(expected, agent.system_message)
        self.assertIn("不得给交通方式问题本身编号", agent.system_message)
        self.assertIn("不得追加路线对比或任何第二个问题", agent.system_message)
        self.assertIn("不得增加“其他”选项", agent.system_message)

    def test_interview_guidance_uses_online_tool_after_group_tour_choice(self) -> None:
        """路线选定后用户选择报团时，应进入在线链接查询而不是重复提问。"""
        guidance = build_interview_guidance([
            {"role": "user", "content": "我选青城后山环线"},
            {"role": "assistant", "content": "1. 自驾 2. 报团 3. 公共交通"},
            {"role": "user", "content": "报团"},
        ])

        self.assertIn("find_group_tour_links", guidance)
        self.assertIn("只展示商团名称、活动标题和链接", guidance)
        self.assertIn("不得再次向用户确认", guidance)
        self.assertNotIn("下一步只确认交通方式", guidance)

    def test_group_tour_typo_triggers_direct_link_query(self) -> None:
        """路线已选后输入常见误写“抱团”，也应直接查询而不重复确认。"""
        routes = self.service.routes()
        messages = [
            {"role": "user", "content": "我选青城后山环线"},
            {"role": "assistant", "content": "交通方式：1. 自驾 2. 报团 3. 公共交通"},
            {"role": "user", "content": "抱团"},
        ]

        state = build_conversation_state(messages, routes)
        guidance = build_interview_guidance(
            messages,
            build_route_search_terms(routes),
            routes,
        )

        self.assertEqual("qingcheng-back-mountain", state.selected_route_id)
        self.assertEqual("group_tour", state.transport_mode)
        self.assertIn("请立即调用 find_group_tour_links", guidance)
        self.assertIn("不得再次向用户确认", guidance)

    def test_later_query_does_not_retrigger_group_tour_without_current_choice(self) -> None:
        """只有当前轮明确选择报团时才触发链接查询。"""
        routes = self.service.routes()
        messages = [
            {"role": "user", "content": "我选巴朗山熊猫王国之巅线"},
            {"role": "assistant", "content": "交通方式：1. 自驾 2. 报团 3. 公共交通"},
            {"role": "user", "content": "报团"},
            {"role": "assistant", "content": "需先正式确认报团选项"},
            {"role": "user", "content": "直接查，别确认了"},
        ]

        state = build_conversation_state(messages, routes)
        guidance = build_interview_guidance(
            messages,
            build_route_search_terms(routes),
            routes,
        )

        self.assertEqual("group_tour", state.transport_mode)
        self.assertFalse(state.has_current_transport_choice)
        self.assertIn("当前轮没有重新选择报团", guidance)
        self.assertNotIn("请立即调用 find_group_tour_links", guidance)

    def test_tool_accepts_persisted_group_tour_choice_for_direct_query(self) -> None:
        """工具应接受已持久化的报团选择，不要求当前轮重复选择。"""
        messages = [
            {"role": "user", "content": "我选青城后山环线"},
            {"role": "assistant", "content": "交通方式？"},
            {"role": "user", "content": "报团"},
            {"role": "assistant", "content": "是否确认查询？"},
            {"role": "user", "content": "直接查"},
        ]
        expected = [{"title": "活动", "url": "https://www.youxiake.com/lines.html?id=1"}]

        with patch.object(self.service, "group_tour_links", return_value=expected) as call:
            result = json.loads(FindGroupTourLinksTool(self.service).call(
                {"route_id": "qingcheng-back-mountain"},
                messages=messages,
            ))

        self.assertEqual(expected, result["items"])
        call.assert_called_once_with("qingcheng-back-mountain")

    def test_named_route_and_group_tour_resolve_exact_route_id(self) -> None:
        """点名路线后选择报团，应使用路线目录中的确定 ID。"""
        messages = [
            {"role": "user", "content": "想去巴朗山"},
            {"role": "assistant", "content": "推荐巴朗山熊猫王国之巅线。交通方式？"},
            {"role": "user", "content": "报团"},
        ]

        state = build_conversation_state(messages, self.service.routes())
        guidance = build_interview_guidance(
            messages,
            build_route_search_terms(self.service.routes()),
            self.service.routes(),
        )

        self.assertEqual("wenchuan-balangshan-panda-peak", state.selected_route_id)
        self.assertEqual("group_tour", state.transport_mode)
        self.assertIn("route_id=wenchuan-balangshan-panda-peak", guidance)
        self.assertIn("find_group_tour_links", guidance)

    def test_numbered_route_and_transport_choices_build_state(self) -> None:
        """数字回复应根据上一轮选项映射路线和交通方式。"""
        messages = [
            {
                "role": "assistant",
                "content": "请选择路线：\n1. 巴朗山熊猫王国之巅线\n2. 青城后山环线",
            },
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": "1. 自驾 2. 报团 3. 公共交通"},
            {"role": "user", "content": "2"},
        ]

        state = build_conversation_state(messages, self.service.routes())

        self.assertEqual("wenchuan-balangshan-panda-peak", state.selected_route_id)
        self.assertEqual("group_tour", state.transport_mode)
        self.assertTrue(state.has_current_transport_choice)

    def test_unumbered_transport_list_and_confirmed_route_preserve_state(self) -> None:
        """交通列表漏写编号时，数字 2 仍应映射报团并保留助手确认的路线。"""
        routes = self.service.routes()
        messages = [
            {"role": "assistant", "content": "已确认选择巴朗山熊猫王国之巅线！"},
            {
                "role": "assistant",
                "content": (
                    "接下来，请告诉我你的交通方式偏好：\n"
                    "自驾\n报团（可查询游侠客链接）\n公共交通\n"
                    "请直接回复数字 1、2 或 3。"
                ),
            },
            {"role": "user", "content": "2"},
        ]

        state = build_conversation_state(messages, routes)
        guidance = build_interview_guidance(
            messages,
            build_route_search_terms(routes),
            routes,
        )

        self.assertEqual("wenchuan-balangshan-panda-peak", state.selected_route_id)
        self.assertEqual("group_tour", state.transport_mode)
        self.assertIn("route_id=wenchuan-balangshan-panda-peak", guidance)
        self.assertIn("请立即调用 find_group_tour_links", guidance)

    def test_chinese_parenthesis_number_maps_group_tour(self) -> None:
        """交通选项使用中文括号编号时，数字回复也应正常映射。"""
        messages = [
            {"role": "user", "content": "我选青城后山环线"},
            {"role": "assistant", "content": "1）自驾 2）报团 3）公共交通"},
            {"role": "user", "content": "2"},
        ]

        state = build_conversation_state(messages, self.service.routes())

        self.assertEqual("group_tour", state.transport_mode)

    def test_group_tour_without_selected_route_does_not_trigger_tool(self) -> None:
        """只选择报团但没有路线时，不得要求模型猜测 route_id。"""
        messages = [{"role": "user", "content": "我选报团"}]

        guidance = build_interview_guidance(
            messages,
            build_route_search_terms(self.service.routes()),
            self.service.routes(),
        )

        self.assertIn("尚未确定具体路线", guidance)
        self.assertIn("不得调用 find_group_tour_links", guidance)

    def test_new_route_selection_replaces_stale_route_before_group_tour(self) -> None:
        """更换路线后报团，应使用最新路线而不是历史路线。"""
        messages = [
            {"role": "user", "content": "我选青城后山环线"},
            {"role": "assistant", "content": "已选青城后山环线"},
            {"role": "user", "content": "改成巴朗山"},
            {"role": "assistant", "content": "已改为巴朗山熊猫王国之巅线"},
            {"role": "user", "content": "报团"},
        ]

        state = build_conversation_state(messages, self.service.routes())

        self.assertEqual("wenchuan-balangshan-panda-peak", state.selected_route_id)
        self.assertEqual("group_tour", state.transport_mode)

if __name__ == "__main__":
    unittest.main()
