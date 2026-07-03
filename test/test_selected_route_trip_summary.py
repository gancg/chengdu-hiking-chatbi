from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qwen_agent.llm.schema import ASSISTANT, Message

from test_data import SAMPLE_DATA_PATH
from hiking_chatbi.qwen_chatbi import (
    build_interview_guidance,
    build_qwen_agent,
    build_route_search_terms,
)
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider


class SelectedRouteTripSummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.service = ChatBIService(Path(self.temp.name) / "test.db", NoTrafficProvider())
        self.service.seed(SAMPLE_DATA_PATH)
        self.routes = self.service.routes()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build_guidance(self, function_messages: list[dict[str, str]]) -> str:
        """构造已确认路线、自驾方式及指定工具结果对应的会话策略。"""
        messages = [
            {"role": "user", "content": "2026-07-04 出发，我选择青城后山环线"},
            {"role": "assistant", "content": "请选择交通方式：\n1. 自驾\n2. 报团"},
            {"role": "user", "content": "自驾"},
            *function_messages,
        ]
        return build_interview_guidance(
            messages,
            build_route_search_terms(self.routes),
            self.routes,
        )

    def test_weather_must_be_queried_before_parking(self) -> None:
        """中文测试：自驾路线尚无天气结果时，必须先查天气再查停车场。"""
        guidance = self.build_guidance([])

        self.assertIn("先调用 estimate_route_weather", guidance)
        self.assertIn("天气返回后", guidance)
        self.assertIn("find_route_parking_points", guidance)
        self.assertLess(
            guidance.index("estimate_route_weather"),
            guidance.index("find_route_parking_points"),
            "工具调用说明必须保持天气在停车场之前",
        )

    def test_parking_is_queried_after_weather(self) -> None:
        """中文测试：已有天气结果后，应查询同一路线的停车场。"""
        guidance = self.build_guidance([{
            "role": "function",
            "name": "estimate_route_weather",
            "content": '{"daily_weather":{"text_day":"晴"},"official_alerts":[]}',
        }])

        self.assertIn("立即调用 find_route_parking_points", guidance)
        self.assertIn("route_id=qingcheng-back-mountain", guidance)
        self.assertIn("停车点返回后直接输出路线总结", guidance)

    def test_final_summary_contains_route_weather_and_parking(self) -> None:
        """中文测试：天气和停车场均已查询后，应输出包含三类信息的最终总结。"""
        guidance = self.build_guidance([
            {
                "role": "function",
                "name": "estimate_route_weather",
                "content": '{"daily_weather":{"text_day":"晴"},"official_alerts":[]}',
            },
            {
                "role": "function",
                "name": "find_route_parking_points",
                "content": '{"count":1,"items":[{"name":"游客中心停车场"}]}',
            },
        ])

        self.assertIn("直接输出最终路线总结", guidance)
        for section in ("路线信息", "天气信息", "推荐停车场"):
            self.assertIn(section, guidance, f"最终总结必须包含{section}")
        self.assertIn("青城后山环线", guidance, "总结策略必须携带已审核路线数据")
        self.assertIn('"distance_km":12.0', guidance, "总结策略必须携带准确路线距离")
        self.assertIn("经纬度", guidance)
        self.assertIn("导航链接", guidance)

    def test_executor_blocks_parking_until_weather_and_continues_after_wait_text(self) -> None:
        """中文测试：模型先查停车场或只说请稍等时，执行器仍应先完成天气再查询停车场。"""
        agent = build_qwen_agent(self.service, model="qwen-plus")
        parking_call = [Message(
            role=ASSISTANT,
            content="",
            function_call={
                "name": "find_route_parking_points",
                "arguments": '{"route_id":"qingcheng-back-mountain"}',
            },
        )]
        wait_text = [Message(
            role=ASSISTANT,
            content="接下来，我将查询天气情况，请稍等。",
        )]
        weather_call = [Message(
            role=ASSISTANT,
            content="",
            function_call={
                "name": "estimate_route_weather",
                "arguments": (
                    '{"route_id":"qingcheng-back-mountain",'
                    '"departure_at":"2026-07-04T06:00:00+08:00"}'
                ),
            },
        )]
        final_parking_call = parking_call
        summary = [Message(role=ASSISTANT, content="路线信息、天气信息、推荐停车场")]
        tool_calls: list[str] = []

        def call_tool(name: str, params: str, **kwargs: object) -> str:
            tool_calls.append(name)
            if name == "estimate_route_weather":
                return '{"daily_weather":{"text_day":"晴"}}'
            return '{"count":0,"items":[]}'

        messages = [
            {"role": "user", "content": "2026-07-04 出发，我选择青城后山环线"},
            {"role": "assistant", "content": "请选择交通方式：\n1. 自驾\n2. 报团"},
            {"role": "user", "content": "自驾"},
        ]
        with (
            patch.object(
                agent,
                "_call_llm",
                side_effect=[
                    iter([parking_call]),
                    iter([wait_text]),
                    iter([weather_call]),
                    iter([final_parking_call]),
                    iter([summary]),
                ],
            ),
            patch.object(agent, "_call_tool", side_effect=call_tool),
        ):
            list(agent._run_one_tool_at_a_time(messages, "zh"))

        self.assertEqual(
            ["estimate_route_weather", "find_route_parking_points"],
            tool_calls,
            "被拦截的停车点调用不得执行，且过渡文本不得中断后续工具链",
        )


if __name__ == "__main__":
    unittest.main()
