from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hiking_chatbi.youxiake_route_pipeline import (
    build_argument_parser,
    build_page_url,
    build_prompt,
    call_qwen,
    default_links_path,
    default_checkpoint_path,
    extract_route_name,
    finalize_item,
    generate_validated_item,
    get_product_ineligibility_reasons,
    has_positive_hiking_distance,
    keep_positive_hiking_routes,
    is_eligible_product,
    load_candidate_checkpoint,
    merge_route_collections,
    merge_site_and_model,
    normalize_route_link,
    normalize_costs,
    prepare_detail_text,
    publish_route_files,
    select_unique_routes,
    validate_page_url,
)


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "sample_routes.json"


def load_valid_item(index: int = 0) -> dict[str, object]:
    return copy.deepcopy(json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))[index])


class YouxiakeRouteEnricherTest(unittest.TestCase):
    def test_ineligible_product_reports_each_rejection_reason(self) -> None:
        """中文测试：非合格产品必须返回可排查的逐项拒绝原因。"""
        self.assertEqual(
            [],
            get_product_ineligibility_reasons(
                "龙窝子轻徒步一日",
                "成都集合出发，当日往返，全程徒步8公里。",
            ),
        )
        self.assertEqual(
            ["缺少徒步活动特征"],
            get_product_ineligibility_reasons(
                "古镇一日游",
                "成都集合出发，当日往返，参观古镇。",
            ),
        )
        self.assertEqual(
            ["未确认成都出发"],
            get_product_ineligibility_reasons(
                "山野徒步一日",
                "重庆集合，当日往返，徒步8公里。",
            ),
        )
        self.assertEqual(
            ["未确认单日行程", "检测到多日行程"],
            get_product_ineligibility_reasons(
                "雪山徒步三日",
                "成都集合出发，连续徒步三日。",
            ),
        )

    def test_only_positive_hiking_distance_is_eligible_for_collection(self) -> None:
        """中文测试：零、负数或非数字徒步距离必须作为非徒步活动跳过。"""
        item = load_valid_item()
        for distance, expected in (
            (8.5, True),
            (0, False),
            (-1, False),
            ("未知", False),
        ):
            with self.subTest(distance=distance):
                item["route"]["distance_km"] = distance
                self.assertEqual(expected, has_positive_hiking_distance(item))

    def test_existing_non_hiking_routes_are_removed_before_merge(self) -> None:
        """中文测试：正式文件中已有的非徒步活动必须在下次合并前清除。"""
        valid = load_valid_item(0)
        invalid = load_valid_item(1)
        invalid["route"]["distance_km"] = 0

        kept, removed = keep_positive_hiking_routes([valid, invalid])

        self.assertEqual([valid], kept)
        self.assertEqual([invalid], removed)

    def test_count_is_required_by_command_line(self) -> None:
        """中文测试：统一命令必须显式提供路线数量。"""
        with self.assertRaises(SystemExit):
            build_argument_parser().parse_args([])

    def test_page_url_only_accepts_https_youxiake(self) -> None:
        """中文测试：指定页面必须是游侠客 HTTPS 地址。"""
        self.assertEqual(
            "https://www.youxiake.com/search/results/0-0-0-1-0-0/azEtaTE.html",
            validate_page_url("https://www.youxiake.com/search/results/0-0-0-1-0-0/azEtaTE.html"),
        )
        with self.assertRaisesRegex(ValueError, "HTTPS 游侠客"):
            validate_page_url("http://example.com/routes")

    def test_build_page_url_uses_dynamic_page_number(self) -> None:
        """中文测试：链接抓取阶段应正确生成动态分页 URL。"""
        self.assertEqual(
            "https://www.youxiake.com/search/results/0-0-0-3-0-0/azEtaTE.html",
            build_page_url(3),
        )

    def test_link_stage_deduplicates_route_ids(self) -> None:
        """中文测试：链接阶段应按活动 ID 去重并保留首次出现顺序。"""
        candidates = [
            {"name": "路线甲", "url": "/lines.html?id=1"},
            {"name": "重复路线甲", "url": "/lines.html?id=1"},
            {"name": "路线乙", "url": "/lines.html?id=2"},
        ]
        self.assertEqual(
            [
                {"name": "路线甲", "url": "https://m.youxiake.com/lines.html?id=1"},
                {"name": "路线乙", "url": "https://m.youxiake.com/lines.html?id=2"},
            ],
            select_unique_routes(candidates, count=2),
        )

    def test_dynamic_count_uses_matching_checkpoint_names(self) -> None:
        """中文测试：非默认条数应使用包含条数的独立检查点文件。"""
        self.assertTrue(default_links_path(25).name.endswith("_25.json"))
        self.assertTrue(default_checkpoint_path(25).name.endswith("_25.json"))
        self.assertIsNotNone(normalize_route_link("/lines.html?id=123"))

    def test_candidate_checkpoint_rejects_different_page(self) -> None:
        """中文测试：候选检查点不得跨来源页面复用。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "links.json"
            path.write_text(json.dumps({
                "source_page_url": "https://www.youxiake.com/search/results/0-0-0-1-0-0/a.html",
                "target_count": 2,
                "routes": [{"name": "路线甲徒步", "url": "https://m.youxiake.com/lines.html?id=1"}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "来源页面不一致"):
                load_candidate_checkpoint(
                    path,
                    2,
                    "https://www.youxiake.com/search/results/0-0-0-1-0-0/b.html",
                )

    def test_eligibility_requires_chengdu_one_day_and_hiking(self) -> None:
        """中文测试：只有成都出发的一日徒步产品才可进入模型核验。"""
        valid = "成都集合出发，当日往返。全程徒步8公里，累计爬升500米。"
        self.assertTrue(is_eligible_product("龙窝子轻徒步一日", valid))
        self.assertFalse(is_eligible_product("九寨沟三日游", "成都出发，三日行程，观光游览"))
        self.assertFalse(is_eligible_product("古镇一日游", "成都出发，当日往返，古镇纯玩"))
        self.assertFalse(is_eligible_product("山野徒步一日", "重庆集合，当日往返，徒步8公里"))

    def test_site_facts_override_model_values(self) -> None:
        """中文测试：详情页非空事实不得被模型生成值覆盖。"""
        merged = merge_site_and_model(
            {"distance_km": 8.0, "ascent_m": 500, "parking": ""},
            {"distance_km": 12.0, "ascent_m": 800, "parking": "村口停车场"},
        )
        self.assertEqual(8.0, merged["distance_km"])
        self.assertEqual(500, merged["ascent_m"])
        self.assertEqual("村口停车场", merged["parking"])

    def test_prompt_requires_qwen_schema_and_web_facts(self) -> None:
        """中文测试：提示词应包含完整结构和网页事实优先规则。"""
        prompt = build_prompt(
            "龙窝子小环线",
            {"name": "龙窝子轻徒步", "url": "https://m.youxiake.com/lines.html?id=1"},
            "成都出发，当日往返，徒步8公里。",
            {"distance_km": 8.0, "duration_days": 1},
        )
        self.assertIn("route、costs、traffic", prompt)
        self.assertIn("不得覆盖", prompt)
        self.assertIn('"base_one_way_minutes"', prompt)

    def test_qwen_max_uses_thinking_stream_without_response_format(self) -> None:
        """中文测试：Qwen Max 联网核验应使用思考流式接口并自行解析JSON。"""
        chunks = [
            {"choices": [{"delta": {"content": '{"ok":'}}]},
            {"choices": [{"delta": {"content": "true}"}}]},
        ]

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def __iter__(self):
                lines = [
                    f"data: {json.dumps(chunk)}\n".encode("utf-8") for chunk in chunks
                ]
                return iter([*lines, b"data: [DONE]\n"])

        captured_request = None

        def fake_urlopen(request, timeout):
            nonlocal captured_request
            captured_request = request
            self.assertGreater(timeout, 0)
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual({"ok": True}, call_qwen("测试提示", "test-key"))
        body = json.loads(captured_request.data.decode("utf-8"))
        self.assertTrue(body["stream"])
        self.assertTrue(body["enable_thinking"])
        self.assertTrue(body["enable_search"])
        self.assertNotIn("response_format", body)

    def test_qwen_stream_skips_empty_choices_and_usage_events(self) -> None:
        """中文测试：流式统计事件和空choices不得导致数组越界。"""
        chunks = [
            {"choices": [], "usage": {"total_tokens": 10}},
            {"choices": [{"delta": {"reasoning_content": "正在核验"}}]},
            {"choices": [{"delta": {"content": '{"ok":true}'}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"total_tokens": 20}},
        ]

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def __iter__(self):
                lines = [
                    f"data: {json.dumps(chunk)}\n".encode("utf-8") for chunk in chunks
                ]
                return iter([*lines, b"data: [DONE]\n"])

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            self.assertEqual({"ok": True}, call_qwen("测试提示", "test-key"))

    def test_qwen_timeout_has_clear_chinese_error(self) -> None:
        """中文测试：模型连接超时应转换为明确中文异常。"""
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(RuntimeError, "请求超时"):
                call_qwen("测试提示", "test-key")

    def test_normalizes_semantic_cost_types_to_project_enums(self) -> None:
        """中文测试：卫生管理费等语义类型应映射为项目支持的枚举。"""
        costs = {
            "route_fees": [{
                "name": "村上及营地卫生管理费",
                "cost_type": "sanitation_fee",
                "billing_unit": "per_person",
            }],
            "transport_options": [{
                "name": "成都往返旅游大巴",
                "cost_type": "transport",
                "billing_unit": "每人",
                "transport_mode": "tour",
            }],
        }
        normalize_costs(costs, ["group_tour"])
        self.assertEqual("waste", costs["route_fees"][0]["cost_type"])
        self.assertEqual("person", costs["route_fees"][0]["billing_unit"])
        self.assertEqual("bus", costs["transport_options"][0]["cost_type"])
        self.assertEqual("group_tour", costs["transport_options"][0]["transport_mode"])

    def test_validation_error_is_sent_back_for_model_repair(self) -> None:
        """中文测试：模型漏字段时应携带具体校验错误重试。"""
        prompts: list[str] = []

        def fake_qwen(prompt: str) -> dict[str, object]:
            prompts.append(prompt)
            return {"route": {}, "costs": {}, "traffic": {}}

        with self.assertLogs(
            "hiking_chatbi.youxiake_route_pipeline", level="WARNING"
        ) as logs:
            with self.assertRaisesRegex(RuntimeError, "连续 2 次未通过校验"):
                generate_validated_item(
                    "首次提示", "云中岭", "https://m.youxiake.com/lines.html?id=1",
                    fake_qwen, max_attempts=2,
                )
        self.assertEqual(2, len(prompts), "校验失败后应重试一次")
        self.assertIn("校验错误", prompts[1], "修复提示应包含精确校验错误")
        self.assertIn("必须是单日路线", prompts[1])
        diagnostic_logs = "\n".join(logs.output)
        self.assertIn("云中岭", diagnostic_logs)
        self.assertIn("https://m.youxiake.com/lines.html?id=1", diagnostic_logs)
        self.assertIn("attempt=1/2", diagnostic_logs)

    def test_confidence_equal_to_threshold_is_rejected(self) -> None:
        """中文测试：路线或交通置信度等于0.8仍应拒绝。"""
        item = load_valid_item()
        item["route"]["confidence"] = 0.8
        with self.assertRaisesRegex(ValueError, "必须严格大于 0.8"):
            finalize_item(item, item["route"]["name"], item["route"]["source_url"], {})

    def test_merge_updates_by_url_preserves_id_and_old_routes(self) -> None:
        """中文测试：URL命中时原位更新并保留旧ID，未命中旧路线不得删除。"""
        old_items = [load_valid_item(0), load_valid_item(1)]
        incoming = copy.deepcopy(old_items[0])
        incoming["route"]["id"] = "model-generated-new-id"
        incoming["route"]["name"] = "更新后的路线名称"
        incoming["route"]["reviewed"] = False
        merged = merge_route_collections(old_items, [incoming])
        self.assertEqual(old_items[0]["route"]["id"], merged[0]["route"]["id"])
        self.assertEqual("更新后的路线名称", merged[0]["route"]["name"])
        self.assertTrue(merged[0]["route"]["reviewed"])
        self.assertEqual(old_items[1], merged[1])

    def test_merge_updates_by_id_and_appends_new_route(self) -> None:
        """中文测试：ID命中应更新，未命中路线应按顺序追加。"""
        old_items = [load_valid_item(0)]
        by_id = copy.deepcopy(old_items[0])
        by_id["route"]["source_url"] = "https://m.youxiake.com/lines.html?id=900"
        appended = load_valid_item(1)
        merged = merge_route_collections(old_items, [by_id, appended])
        self.assertEqual(by_id["route"]["source_url"], merged[0]["route"]["source_url"])
        self.assertEqual(appended["route"]["id"], merged[1]["route"]["id"])

    def test_merge_rejects_url_and_id_identity_conflict(self) -> None:
        """中文测试：URL和ID分别命中不同旧路线时必须拒绝发布。"""
        old_items = [load_valid_item(0), load_valid_item(1)]
        incoming = copy.deepcopy(old_items[0])
        incoming["route"]["id"] = old_items[1]["route"]["id"]
        with self.assertRaisesRegex(ValueError, "身份冲突"):
            merge_route_collections(old_items, [incoming])

    def test_publish_writes_identical_fully_validated_files(self) -> None:
        """中文测试：候选文件和运行文件必须发布为完全一致的有效JSON。"""
        items = [load_valid_item(0)]
        with tempfile.TemporaryDirectory() as directory:
            select_path = Path(directory) / "sample_routes_select.json"
            runtime_path = Path(directory) / "sample_routes.json"
            publish_route_files(items, select_path, runtime_path)
            self.assertEqual(select_path.read_bytes(), runtime_path.read_bytes())
            self.assertTrue(json.loads(runtime_path.read_text(encoding="utf-8"))[0]["route"]["reviewed"])

    def test_publish_validation_failure_keeps_formal_files_unchanged(self) -> None:
        """中文测试：正式数据校验失败时不得改写已有路线文件。"""
        invalid = load_valid_item(0)
        invalid["route"].pop("name")
        with tempfile.TemporaryDirectory() as directory:
            select_path = Path(directory) / "sample_routes_select.json"
            runtime_path = Path(directory) / "sample_routes.json"
            select_path.write_text("候选旧内容", encoding="utf-8")
            runtime_path.write_text("运行旧内容", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "第 1 条正式路线校验失败"):
                publish_route_files([invalid], select_path, runtime_path)
            self.assertEqual("候选旧内容", select_path.read_text(encoding="utf-8"))
            self.assertEqual("运行旧内容", runtime_path.read_text(encoding="utf-8"))

    def test_short_detail_is_forwarded_with_search_notice(self) -> None:
        """中文测试：较短的动态正文应交给联网模型补充，而不是直接失败。"""
        result = prepare_detail_text(
            "云中岭活动详情，成都出发，徒步五公里，页面其余内容等待动态加载。",
            "https://example.test/1",
        )
        self.assertIn("联网交叉检索", result)
        self.assertIn("云中岭活动详情", result)

    def test_nearly_empty_detail_is_rejected(self) -> None:
        """中文测试：近乎空白的详情页仍须明确拒绝。"""
        with self.assertRaisesRegex(RuntimeError, "正文近乎为空"):
            prepare_detail_text("加载中", "https://example.test/1")

    def test_extracts_name_after_marketing_prefix(self) -> None:
        """中文测试：应移除营销前缀、副标题和跟团游后缀。"""
        self.assertEqual(
            "云中岭",
            extract_route_name("登峰造极·云中岭 | 5-10公里AB线 跟团游"),
        )

    def test_extracts_second_segment_after_generic_activity_type(self) -> None:
        """中文测试：首段只是活动类型时应选择第二段目的地。"""
        self.assertEqual(
            "甲尔猛措",
            extract_route_name("休闲轻徒 | 甲尔猛措 | 河谷山野 跟团游"),
        )

    def test_keeps_compound_destination_name(self) -> None:
        """中文测试：复合目的地名称不应被无依据拆分。"""
        self.assertEqual(
            "四姑娘山+毕棚沟",
            extract_route_name("四姑娘山+毕棚沟半自由行<联合发团> 跟团游"),
        )

    def test_uses_explicit_name_for_marketing_title(self) -> None:
        """中文测试：营销标题应映射为真实目的地或路线名称。"""
        cases = {
            "夜徒牛背山 | 登牛背之巅，迎雪山日出云海 跟团游": "牛背山夜徒线",
            "去东极·忘记你 | 后会无期庙子湖，环东福山 跟团游": "东极岛环线",
            "花海寻菌 | 海子坪星空露营 跟团游": "海子坪",
        }
        for product_name, expected in cases.items():
            with self.subTest(product_name=product_name):
                self.assertEqual(expected, extract_route_name(product_name))


if __name__ == "__main__":
    unittest.main()
