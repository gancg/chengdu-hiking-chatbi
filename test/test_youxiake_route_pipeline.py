from __future__ import annotations

import unittest

from hiking_chatbi.youxiake_route_pipeline import (
    build_page_url,
    default_links_path,
    default_output_path,
    extract_route_name,
    generate_validated_item,
    normalize_route_link,
    normalize_costs,
    prepare_detail_text,
    select_unique_routes,
)


class YouxiakeRouteEnricherTest(unittest.TestCase):
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
        self.assertTrue(default_output_path(25).name.endswith("_25.json"))
        self.assertIsNotNone(normalize_route_link("/lines.html?id=123"))

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

        with self.assertRaisesRegex(RuntimeError, "连续 2 次未通过校验"):
            generate_validated_item(
                "首次提示", "云中岭", "https://m.youxiake.com/lines.html?id=1",
                fake_qwen, max_attempts=2,
            )
        self.assertEqual(2, len(prompts), "校验失败后应重试一次")
        self.assertIn("校验错误", prompts[1], "修复提示应包含精确校验错误")
        self.assertIn("置信度低于 0.8", prompts[1])

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
