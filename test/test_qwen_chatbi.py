from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from qwen_agent.llm.schema import ASSISTANT, Message

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
            "transport_modes": ["self_drive"],
            "max_distance_km": 13,
            "max_ascent_m": 800,
            "max_budget_cny": 200,
            "traffic_tolerance": "high",
        }))

        self.assertGreater(result["count"], 0, "符合条件时应返回自驾路线")

    def test_recommend_tool_uses_default_count_for_unfounded_zero(self) -> None:
        """用户未提供人数时，模型生成的零不得覆盖默认人数。"""
        with patch.object(self.service, "recommendations", return_value=[]) as call:
            RecommendHikingRoutesTool(self.service).call(
                {
                    "departure_at": self.departure,
                    "party_size": 0,
                    "vehicle_count": None,
                },
                messages=[{
                    "role": "user",
                    "content": "本周日出发，有草甸的徒步路线推荐",
                }],
            )

        normalized_query = call.call_args.args[0]
        self.assertNotIn("party_size", normalized_query)
        self.assertNotIn("vehicle_count", normalized_query)

    def test_recommend_tool_rejects_explicit_zero_party_size(self) -> None:
        """用户明确说零人出行时，不得静默改成默认一人。"""
        with self.assertRaisesRegex(ValueError, "party_size 必须为正整数"):
            RecommendHikingRoutesTool(self.service).call(
                {"departure_at": self.departure, "party_size": 0},
                messages=[{"role": "user", "content": "我们0个人去徒步"}],
            )

    def test_recommend_tool_rejects_disabled_public_transit(self) -> None:
        """模型暂时不得通过推荐工具选择公共交通。"""
        with self.assertRaisesRegex(ValueError, "公共交通出行方式暂未开放"):
            RecommendHikingRoutesTool(self.service).call({
                "departure_at": self.departure,
                "transport_modes": ["public_transit"],
            })

    def test_recommend_tool_locks_named_balangshan_route(self) -> None:
        """用户点名巴朗山时，推荐工具不得返回其他相似雪山路线。"""
        result = json.loads(RecommendHikingRoutesTool(self.service).call(
            {
                "departure_at": self.departure,
                "transport_modes": ["group_tour"],
            },
            messages=[{
                "role": "user",
                "content": "周六想报团去爬巴朗山，不知道天气怎么样",
            }],
        ))

        self.assertEqual(1, result["count"], "点名路线后只能返回唯一命中路线")
        self.assertEqual(
            "wenchuan-balangshan-panda-peak",
            result["items"][0]["route"]["id"],
        )

    def test_recommend_tool_normalizes_search_term_route_id(self) -> None:
        """模型把巴朗山放入 route_id 时，应先按报团检索词规范化。"""
        result = json.loads(RecommendHikingRoutesTool(self.service).call({
            "route_id": "巴朗山",
            "departure_at": self.departure,
            "transport_modes": ["group_tour"],
        }))

        self.assertEqual(1, result["count"], "检索词唯一命中后只能推荐该路线")
        self.assertEqual(
            "wenchuan-balangshan-panda-peak",
            result["items"][0]["route"]["id"],
        )

    def test_recommend_tool_resolves_extracted_destination_name(self) -> None:
        """模型提炼出的目的地名称应通过报团检索词转换为路线 ID。"""
        tool = RecommendHikingRoutesTool(self.service)
        result = json.loads(tool.call({
            "destination_name": "巴朗山",
            "departure_at": self.departure,
            "transport_modes": ["group_tour"],
        }))

        self.assertIn(
            "destination_name",
            {parameter["name"] for parameter in tool.parameters},
            "推荐工具应向模型提供独立的目的地名称字段",
        )
        self.assertEqual(1, result["count"])
        self.assertEqual(
            "wenchuan-balangshan-panda-peak",
            result["items"][0]["route"]["id"],
        )

    def test_recommend_tool_does_not_match_route_name(self) -> None:
        """推荐工具点名匹配不得使用路线 name 字段。"""
        routes = [{
            "id": "route-by-name-only",
            "name": "只存在于名称里的目的地",
            "group_tour_search_terms": ["完全不同的检索词"],
        }]
        with (
            patch.object(self.service, "routes", return_value=routes),
            patch.object(self.service, "recommendations", return_value=[]) as call,
        ):
            RecommendHikingRoutesTool(self.service).call(
                {"departure_at": self.departure},
                messages=[{
                    "role": "user",
                    "content": "我想去只存在于名称里的目的地",
                }],
            )

        self.assertNotIn("route_id", call.call_args.args[0], "name 字段不得用于锁定路线")

    def test_service_fuzzy_matches_group_tour_search_terms_json(self) -> None:
        """服务应通过数据库检索词 JSON 字段模糊匹配巴朗山。"""
        routes = self.service.routes_by_group_tour_search_term("巴朗山")

        self.assertEqual(
            ["wenchuan-balangshan-panda-peak"],
            [route["id"] for route in routes],
        )

    def test_service_rejects_unknown_locked_route(self) -> None:
        """指定路线不存在时不得回退为全库推荐。"""
        with self.assertRaisesRegex(ValueError, "指定路线不存在或未审核"):
            self.service.recommendations({
                "route_id": "missing-route",
                "departure_at": self.departure,
            })

    def test_recommend_tool_hides_weather_for_multiple_routes(self) -> None:
        """推荐多条候选路线时，不应返回任意路线的天气供模型统一展示。"""
        result = json.loads(RecommendHikingRoutesTool(self.service).call({
            "departure_at": self.departure,
            "max_distance_km": 10,
            "max_ascent_m": 800,
            "traffic_tolerance": "high",
        }))

        self.assertGreater(result["count"], 1, "测试条件应产生多条候选路线")
        for item in result["items"]:
            self.assertNotIn("weather", item, "多路线候选结果不应暴露天气详情")

    def test_recommend_tool_extracts_snow_mountain_preference_from_user(self) -> None:
        """用户原话提到雪山时，推荐工具应只返回含雪山标签的路线。"""
        result = json.loads(RecommendHikingRoutesTool(self.service).call(
            {"departure_at": self.departure},
            messages=[{
                "role": "user",
                "content": "本周日出发，有雪山的徒步路线推荐",
            }],
        ))

        self.assertGreater(result["count"], 0, "样例数据应包含雪山路线")
        for item in result["items"]:
            self.assertIn(
                "雪山",
                item["route"]["scenery"],
                "提炼出的雪山偏好应作为路线过滤条件",
            )
            self.assertTrue(
                any("匹配风景偏好：雪山" in reason for reason in item["reasons"]),
                "推荐理由应说明命中的风景偏好",
            )

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

    def test_weather_tool_normalizes_named_destination_to_route_id(self) -> None:
        """天气工具收到巴朗山检索词时，应解析为库内路线 ID。"""
        with patch.object(self.service, "weather", return_value={"official_alerts": []}) as call:
            result = json.loads(EstimateRouteWeatherTool(self.service).call({
                "route_id": "巴朗山",
                "departure_at": self.departure,
            }))

        self.assertEqual([], result["official_alerts"])
        call.assert_called_once()
        self.assertEqual(
            "wenchuan-balangshan-panda-peak",
            call.call_args.args[0]["route_id"],
            "自然语言目的地应规范化为准确路线 ID",
        )

    def test_agent_executes_only_first_tool_from_parallel_model_output(self) -> None:
        """模型并行生成工具时，只执行首个并基于其结果继续生成。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")
        parallel_output = [
            Message(
                role=ASSISTANT,
                content="",
                function_call={"name": "resolve_departure_date", "arguments": "{}"},
            ),
            Message(
                role=ASSISTANT,
                content="",
                function_call={"name": "resolve_public_holiday", "arguments": "{}"},
            ),
        ]
        final_output = [Message(role=ASSISTANT, content="已完成")]
        llm_messages: list[list[Message]] = []

        def call_llm(**kwargs: object) -> object:
            llm_messages.append(deepcopy(kwargs["messages"]))
            return iter([parallel_output if len(llm_messages) == 1 else final_output])

        with (
            patch.object(agent, "_call_llm", side_effect=call_llm),
            patch.object(
                agent,
                "_call_tool",
                return_value='{"departure_date":"2026-07-04"}',
            ) as call_tool,
        ):
            list(agent._run_one_tool_at_a_time([], "zh"))

        call_tool.assert_called_once()
        self.assertEqual("resolve_departure_date", call_tool.call_args.args[0])
        self.assertEqual(2, len(llm_messages), "首个工具返回后应再次请求模型")
        second_call_messages = llm_messages[1]
        self.assertTrue(
            any(
                message.role == "function"
                and message.name == "resolve_departure_date"
                and "2026-07-04" in message.content
                for message in second_call_messages
            ),
            "下一次模型生成必须基于首个工具的真实返回值",
        )
        self.assertFalse(
            any(
                message.name == "resolve_public_holiday"
                for message in second_call_messages
            ),
            "同轮生成但未执行的工具调用不得进入后续消息",
        )

    def test_agent_streams_text_before_model_generation_finishes(self) -> None:
        """模型生成普通文本时，应在整轮完成前持续返回累计内容。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")
        partial_output = [Message(role=ASSISTANT, content="正在查询")]
        final_output = [Message(role=ASSISTANT, content="正在查询天气")]

        def stream_output(**kwargs: object) -> object:
            yield partial_output
            yield final_output

        with patch.object(agent, "_call_llm", side_effect=stream_output):
            responses = list(agent._run_one_tool_at_a_time([], "zh"))

        self.assertGreaterEqual(len(responses), 2, "至少应包含增量输出和最终输出")
        self.assertEqual("正在查询", responses[0][0].content)
        self.assertEqual("正在查询天气", responses[1][0].content)

    def test_agent_waits_for_user_after_multiple_route_recommendations(self) -> None:
        """推荐多条候选后，不得在同一用户轮次替用户选路线并查询天气。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")
        recommend_output = [Message(
            role=ASSISTANT,
            content="",
            function_call={"name": "recommend_hiking_routes", "arguments": "{}"},
        )]
        unauthorized_weather_output = [
            Message(role=ASSISTANT, content="请选择木骡子、二古溪或大二普三海"),
            Message(
                role=ASSISTANT,
                content="",
                function_call={
                    "name": "estimate_route_weather",
                    "arguments": '{"route_id":"muluozi"}',
                },
            ),
        ]

        with (
            patch.object(
                agent,
                "_call_llm",
                side_effect=[
                    iter([recommend_output]),
                    iter([unauthorized_weather_output]),
                ],
            ),
            patch.object(
                agent,
                "_call_tool",
                return_value='{"count":3,"items":[{},{},{}]}',
            ) as call_tool,
        ):
            responses = list(agent._run_one_tool_at_a_time([], "zh"))

        call_tool.assert_called_once()
        self.assertEqual("recommend_hiking_routes", call_tool.call_args.args[0])
        self.assertTrue(
            any(
                message.content == "请选择木骡子、二古溪或大二普三海"
                for response in responses
                for message in response
            ),
            "应展示候选路线并等待用户选择",
        )
        self.assertFalse(
            any(
                message.name == "estimate_route_weather"
                for response in responses
                for message in response
            ),
            "未经用户选择的天气调用不应暴露或执行",
        )

    def test_agent_does_not_call_tool_after_asking_user_question(self) -> None:
        """模型已经询问路线偏好时，必须等待用户回答再调用推荐工具。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")
        output = [
            Message(
                role=ASSISTANT,
                content="你对距离、爬升高度或者难度有什么特别的要求吗？",
            ),
            Message(
                role=ASSISTANT,
                content="",
                function_call={
                    "name": "recommend_hiking_routes",
                    "arguments": '{"departure_at":"2026-07-05T06:30:00+08:00"}',
                },
            ),
        ]

        with (
            patch.object(agent, "_call_llm", return_value=iter([output])),
            patch.object(agent, "_call_tool") as call_tool,
        ):
            responses = list(agent._run_one_tool_at_a_time([], "zh"))

        call_tool.assert_not_called()
        self.assertTrue(
            any(
                "有什么特别的要求吗" in message.content
                for response in responses
                for message in response
            ),
            "应保留向用户提出的问题",
        )
        self.assertFalse(
            any(
                message.name == "recommend_hiking_routes"
                for response in responses
                for message in response
            ),
            "等待用户回答时不得展示工具调用",
        )

    def test_agent_remembers_question_across_stream_chunks(self) -> None:
        """提问和工具位于不同流片段时，也必须等待用户回答。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")
        question_output = [Message(
            role=ASSISTANT,
            content="这次徒步强度你更倾向哪一种？",
        )]
        later_tool_output = [Message(
            role=ASSISTANT,
            content="",
            function_call={"name": "recommend_hiking_routes", "arguments": "{}"},
        )]

        with (
            patch.object(
                agent,
                "_call_llm",
                return_value=iter([question_output, later_tool_output]),
            ),
            patch.object(agent, "_call_tool") as call_tool,
        ):
            responses = list(agent._run_one_tool_at_a_time([], "zh"))

        call_tool.assert_not_called()
        self.assertTrue(
            any(
                "强度你更倾向" in message.content
                for response in responses
                for message in response
            ),
            "最终响应应保留先前流片段中的问题",
        )

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

    def test_compound_relative_date_weather_group_tour_is_strictly_sequential(self) -> None:
        """相对日期、天气和报团在同一句中时，应按依赖关系串行调用工具。"""
        routes = self.service.routes()
        guidance = build_interview_guidance(
            [{"role": "user", "content": "周六想报团去爬巴朗山，不知道天气怎么样"}],
            build_route_search_terms(routes),
            routes,
        )

        route_id = "wenchuan-balangshan-panda-peak"
        self.assertNotIn(
            f"route_id={route_id}",
            guidance,
            "推荐工具返回前不得提前提供路线 ID，使模型绕过路线确认",
        )
        self.assertIn("destination_name=巴朗山", guidance)
        expected_order = [
            "resolve_departure_date",
            "resolve_public_holiday",
            "recommend_hiking_routes",
            "estimate_route_weather",
            "find_group_tour_links",
        ]
        positions = [guidance.index(tool_name) for tool_name in expected_order]
        self.assertEqual(sorted(positions), positions, "工具应按依赖关系依次调用")
        self.assertIn("不能并行调用", guidance)
        self.assertIn("每一步必须等待上一步工具结果", guidance)
        self.assertIn("任一步失败都要停止", guidance)
        self.assertIn("不得自行推算日期、星期或日期类型", guidance)
        self.assertIn("不得把自然语言目的地名称当作 route_id", guidance)
        self.assertIn("不得跳过路线推荐", guidance)

    def test_named_destination_guidance_exposes_exact_route_id(self) -> None:
        """点名库内目的地时，应向模型提供准确路线 ID，避免使用自然语言名称调用工具。"""
        routes = self.service.routes()
        guidance = build_interview_guidance(
            [{"role": "user", "content": "想去巴朗山看看天气"}],
            build_route_search_terms(routes),
            routes,
        )

        self.assertIn("route_id=wenchuan-balangshan-panda-peak", guidance)

    def test_generic_request_does_not_trigger_named_destination_guidance(self) -> None:
        """未点名库内目的地时，应保留原有引导式访谈。"""
        route_search_terms = build_route_search_terms(self.service.routes())

        guidance = build_interview_guidance(
            [{"role": "user", "content": "想找一条成都周边徒步路线"}],
            route_search_terms,
        )

        self.assertIn("探索阶段", guidance)

    def test_date_and_scenery_request_recommends_without_follow_up(self) -> None:
        """日期和风景偏好均明确时，应直接推荐而不是追问普通偏好。"""
        routes = self.service.routes()
        guidance = build_interview_guidance(
            [{"role": "user", "content": "本周日出发，有草甸的徒步路线推荐"}],
            build_route_search_terms(routes),
            routes,
        )

        self.assertIn("风景偏好：草甸", guidance)
        self.assertNotIn("日出", guidance, "“本周日出发”不得误识别为日出风景偏好")
        self.assertIn("直接调用 recommend_hiking_routes", guidance)
        self.assertIn("不得再询问体力、距离、爬升或难度", guidance)

    def test_date_and_beginner_request_recommends_without_follow_up(self) -> None:
        """日期和新手要求均明确时，应按保守难度直接推荐。"""
        routes = self.service.routes()
        messages = [{
            "role": "user",
            "content": "本周六从成都出发，推荐适合新手的路线",
        }]
        guidance = build_interview_guidance(
            messages,
            build_route_search_terms(routes),
            routes,
        )

        self.assertIn("新手", guidance)
        self.assertIn("直接调用 recommend_hiking_routes", guidance)
        self.assertIn("max_difficulty=easy", guidance)
        self.assertIn("不得再询问强度", guidance)

        with patch.object(self.service, "recommendations", return_value=[]) as call:
            RecommendHikingRoutesTool(self.service).call(
                {"departure_at": self.departure},
                messages=messages,
            )

        self.assertEqual("easy", call.call_args.args[0]["max_difficulty"])
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

    def test_departure_date_tool_resolves_plain_saturday(self) -> None:
        """用户只说周六时，应解析为参考日期起最近的周六。"""
        result = json.loads(ResolveDepartureDateTool(self.service).call({
            "expression": "周六",
            "reference_date": "2026-07-01",
        }))

        self.assertEqual(1, len(result["candidates"]), "周六应得到唯一日期")
        self.assertEqual("2026-07-04", result["candidates"][0]["date"])
        self.assertEqual("星期六", result["candidates"][0]["weekday_name"])

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

        expected_order = "推荐路线、推荐理由、设施与风险、路线选择"
        self.assertIn(expected_order, agent.system_message, "候选推荐应以路线选择结束")
        self.assertIn("每条路线先给路线名称和核心行程数据", agent.system_message)
        self.assertIn("多条候选路线的起点坐标不同", agent.system_message)
        self.assertIn("不得调用 `estimate_route_weather`", agent.system_message)
        self.assertIn("不得展示“天气参考”", agent.system_message)
        self.assertIn("推荐结果只有一条路线", agent.system_message)
        self.assertIn("天气参考先说官方预警", agent.system_message)
        self.assertIn("候选路线阶段不得展开交通和费用比较", agent.system_message)
        self.assertIn("选定路线并确认交通方式后", agent.system_message)

    def test_self_drive_cost_guidance_hides_group_fee_and_total(self) -> None:
        """用户选择自驾后，不应展示报团费用或预计总费用。"""
        routes = self.service.routes()
        messages = [
            {"role": "user", "content": "我选青城后山环线"},
            {"role": "assistant", "content": "1. 自驾 2. 报团 3. 公共交通"},
            {"role": "user", "content": "1"},
        ]

        guidance = build_interview_guidance(
            messages,
            build_route_search_terms(routes),
            routes,
        )

        self.assertIn("不得展示“路线费用”", guidance, "自驾方案应隐藏路线费用项")
        self.assertIn("自驾交通费：油费自理，无额外交通费用", guidance)
        self.assertIn("不得展示“预计总费用”", guidance)
        self.assertIn("cost_min_cny", guidance)
        self.assertIn("预计报团费用区间", guidance)
        self.assertIn("estimate_route_weather", guidance)
        self.assertIn("route_id=qingcheng-back-mountain", guidance)
        self.assertIn("不得用泛化天气提醒代替工具查询", guidance)

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

    def test_interview_guidance_queries_weather_after_explicit_route_choice(self) -> None:
        """用户明确选择路线后，应先查天气再确认交通方式。"""
        routes = self.service.routes()
        messages = [
            {"role": "user", "content": "周六出发"},
            {
                "role": "function",
                "name": "resolve_departure_date",
                "content": '{"candidates":[{"date":"2026-07-04"}]}',
            },
            {"role": "assistant", "content": "这里有三条候选路线，请先选择一条"},
            {"role": "user", "content": "我选青城后山环线"},
        ]
        guidance = build_interview_guidance(
            messages,
            build_route_search_terms(routes),
            routes,
        )

        self.assertIn("用户已经明确选定路线", guidance)
        self.assertIn("estimate_route_weather", guidance)
        self.assertIn("route_id=qingcheng-back-mountain", guidance)
        self.assertIn("天气返回后", guidance)
        self.assertIn("再询问交通方式", guidance)
        self.assertIn(
            "请选择交通方式：\n1. 自驾\n2. 报团\n\n直接回复 1 或 2 即可。",
            guidance,
        )

    def test_route_weather_does_not_repeat_known_transport_mode(self) -> None:
        """确认路线时已说明自驾，天气返回后不得重复询问交通方式。"""
        routes = self.service.routes()
        guidance = build_interview_guidance(
            [
                {"role": "user", "content": "2026-07-04 出发"},
                {"role": "assistant", "content": "请选择一条路线"},
                {"role": "user", "content": "我选青城后山环线，自驾"},
            ],
            build_route_search_terms(routes),
            routes,
        )

        self.assertIn("estimate_route_weather", guidance)
        self.assertIn("已经明确选择自驾", guidance)
        self.assertIn("不得重复询问交通方式", guidance)
        self.assertNotIn("请选择交通方式：", guidance)

    def test_interview_guidance_rejects_current_public_transit_choice(self) -> None:
        """用户主动选择已下线的公共交通时，应说明不可用并重新提供两种选项。"""
        routes = self.service.routes()
        messages = [
            {"role": "user", "content": "我选青城后山环线"},
            {"role": "assistant", "content": "请选择交通方式"},
            {"role": "user", "content": "公共交通"},
        ]

        guidance = build_interview_guidance(
            messages,
            build_route_search_terms(routes),
            routes,
        )

        self.assertIn("该出行方式暂未开放", guidance)
        self.assertIn("1. 自驾\n2. 报团", guidance)
        self.assertIn("不得查询、推荐或整合公共交通信息", guidance)

    def test_agent_prompt_uses_fixed_transport_choice_template(self) -> None:
        """路线选定后的交通选择应简单唯一，避免嵌套编号和额外问题。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")

        expected = (
            "请选择交通方式：\n"
            "1. 自驾\n"
            "2. 报团\n\n"
            "直接回复 1 或 2 即可。"
        )
        self.assertIn(expected, agent.system_message)
        self.assertIn("公共交通出行方式暂未开放", agent.system_message)
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
