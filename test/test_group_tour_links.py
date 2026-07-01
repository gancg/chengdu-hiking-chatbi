from __future__ import annotations

import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hiking_chatbi.config import SAMPLE_DATA_PATH
from hiking_chatbi.db import initialize
from hiking_chatbi.group_tour_links import (
    DaeGroupTourLinkProvider,
    GroupTourLinkError,
    MidoGroupTourLinkProvider,
    MultiGroupTourLinkProvider,
    PlaywrightYouxiakeBrowserFetcher,
    YouxiakeGroupTourLinkProvider,
)
from hiking_chatbi.importer import load_import_file
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider
from hiking_chatbi.validation import validate_import_item


class StubGroupTourProvider:
    def __init__(self, results: list[dict[str, str]]) -> None:
        self.results = results
        self.calls: list[tuple[str, list[str]]] = []

    def find_links(
        self, route_name: str, search_terms: list[str]
    ) -> list[dict[str, str]]:
        self.calls.append((route_name, search_terms))
        return self.results


class MultiGroupTourLinkProviderTest(unittest.TestCase):
    def test_merges_sources_and_marks_merchant_name(self) -> None:
        """多个商团结果应按配置顺序合并，并明确标注商团名称。"""
        provider = MultiGroupTourLinkProvider([
            ("游侠客", StubGroupTourProvider([
                {"title": "青城后山一日游", "url": "https://youxiake.example/1"}
            ])),
            ("大鹅", StubGroupTourProvider([
                {"title": "青城后山徒步", "url": "https://dae.example/2"}
            ])),
            ("蜜多", StubGroupTourProvider([])),
        ])

        results = provider.find_links("青城后山", ["青城山后山"])

        self.assertEqual(["游侠客", "大鹅"], [item["source_name"] for item in results])

    def test_keeps_successful_results_when_one_source_fails(self) -> None:
        """单个商团查询异常时，应保留其他商团成功返回的链接。"""
        class FailingProvider:
            def find_links(self, route_name: str, search_terms: list[str]) -> list[dict[str, str]]:
                raise GroupTourLinkError("大鹅查询失败")

        provider = MultiGroupTourLinkProvider([
            ("大鹅", FailingProvider()),
            ("蜜多", StubGroupTourProvider([
                {"title": "赵公山徒步", "url": "https://mido.example/1"}
            ])),
        ])

        results = provider.find_links("赵公山", [])

        self.assertEqual("蜜多", results[0]["source_name"])

    def test_raises_chinese_error_when_all_sources_fail(self) -> None:
        """全部已启用商团均失败时，应输出包含来源名称的中文异常。"""
        class FailingProvider:
            def find_links(self, route_name: str, search_terms: list[str]) -> list[dict[str, str]]:
                raise RuntimeError("network failed")

        provider = MultiGroupTourLinkProvider([
            ("大鹅", FailingProvider()),
            ("蜜多", FailingProvider()),
        ])

        with self.assertRaisesRegex(GroupTourLinkError, "大鹅、蜜多"):
            provider.find_links("赵公山", [])


class DaeGroupTourLinkProviderTest(unittest.TestCase):
    def test_searches_keyword_and_returns_valid_detail_link(self) -> None:
        """大鹅应使用审核关键词搜索，并只返回匹配的合法详情链接。"""
        searched_keywords: list[str] = []
        html = '''
        <a href="/News_read_id_6646.shtml"><div class="tit">【巴朗山】花海徒步</div></a>
        <a href="https://evil.example/News_read_id_1.shtml"><div class="tit">巴朗山</div></a>
        '''
        provider = DaeGroupTourLinkProvider(
            html_fetcher=lambda keyword: searched_keywords.append(keyword) or html
        )

        results = provider.find_links("巴朗山徒步线", ["巴朗山"])

        self.assertEqual(["巴朗山"], searched_keywords)
        self.assertEqual("https://www.cddee.cn/News_read_id_6646.shtml", results[0]["url"])


class MidoGroupTourLinkProviderTest(unittest.TestCase):
    def test_reads_public_list_and_filters_by_reviewed_terms(self) -> None:
        """蜜多应从公开列表读取活动，并按审核后的路线词过滤。"""
        html = '''
        <a href="/event?id=876570&amp;mid=52240">7月4日 巴朗山花海徒步</a>
        <a href="/event?id=2&amp;mid=99999">巴朗山错误商户</a>
        <a href="/event?id=3&amp;mid=52240">喇叭河徒步</a>
        '''
        provider = MidoGroupTourLinkProvider(html_fetcher=lambda _keyword: html)

        results = provider.find_links("巴朗山徒步线", ["巴朗山"])

        self.assertEqual(1, len(results))
        self.assertEqual(
            "https://cdmdtb.360jlb.cn/event?id=876570&mid=52240",
            results[0]["url"],
        )


class GroupTourSearchTermsTest(unittest.TestCase):
    def test_validates_and_imports_group_tour_search_terms(self) -> None:
        """报团检索词校验通过后，应随路线写入并读取。"""
        item = copy.deepcopy(load_import_file(SAMPLE_DATA_PATH)[0])
        item["route"]["group_tour_search_terms"] = ["青城后山", "青城山后山"]
        validate_import_item(item)

        with tempfile.TemporaryDirectory() as temp:
            provider = StubGroupTourProvider([])
            service = ChatBIService(
                Path(temp) / "test.db", NoTrafficProvider(), group_tour_provider=provider
            )
            service.import_items([item])

            route = service.routes()[0]
            self.assertEqual(
                ["青城后山", "青城山后山"],
                route["group_tour_search_terms"],
                "数据库应完整保留人工审核的报团检索词",
            )

    def test_allows_legacy_route_without_search_terms(self) -> None:
        """历史路线缺少报团检索词时，应按空数组兼容。"""
        item = copy.deepcopy(load_import_file(SAMPLE_DATA_PATH)[0])
        item["route"].pop("group_tour_search_terms", None)

        validate_import_item(item)

    def test_rejects_invalid_search_terms(self) -> None:
        """报团检索词过多、过短或重复时，应输出明确异常。"""
        base = copy.deepcopy(load_import_file(SAMPLE_DATA_PATH)[0])
        invalid_values = [
            (["甲乙", "丙丁", "戊己", "庚辛", "壬癸", "子丑"], "最多 5 个"),
            (["山"], "至少 2 个字符"),
            (["青城后山", " 青城后山 "], "不得重复"),
        ]
        for value, message in invalid_values:
            with self.subTest(value=value):
                item = copy.deepcopy(base)
                item["route"]["group_tour_search_terms"] = value
                with self.assertRaisesRegex(ValueError, message):
                    validate_import_item(item)

    def test_initialize_adds_search_terms_to_existing_database(self) -> None:
        """旧数据库初始化时，应无损增加报团检索词字段。"""
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "legacy.db"
            connection = sqlite3.connect(db_path)
            connection.execute("CREATE TABLE routes (id TEXT PRIMARY KEY)")
            connection.commit()
            connection.close()

            initialize(db_path)

            connection = sqlite3.connect(db_path)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(routes)")}
            connection.close()
            self.assertIn(
                "group_tour_search_terms_json", columns, "旧数据库应自动补充新字段"
            )


class YouxiakeGroupTourLinkProviderTest(unittest.TestCase):
    def test_matches_name_and_alias_then_deduplicates_links(self) -> None:
        """路线名称和别名均可命中，重复活动链接只应返回一次。"""
        searched_keywords: list[str] = []
        candidates = [
            {"title": "青城后山环线·清凉一日", "url": "/lines.html?id=100"},
            {"title": "青城山后山轻徒步", "url": "https://m.youxiake.com/lines.html?id=101"},
            {"title": "青城后山重复活动", "url": "https://www.youxiake.com/lines.html?id=100"},
        ]
        provider = YouxiakeGroupTourLinkProvider(
            candidate_fetcher=lambda keyword: searched_keywords.append(keyword) or candidates,
            max_links=5,
        )

        results = provider.find_links("青城后山环线", ["青城山后山"])

        self.assertEqual(2, len(results), "名称和别名命中的活动应合并去重")
        self.assertEqual(["青城山后山"], searched_keywords, "应优先使用第一条审核关键词搜索")
        self.assertEqual("青城后山环线", results[0]["matched_term"])
        self.assertEqual("青城山后山", results[1]["matched_term"])
        self.assertTrue(results[0]["fetched_at"], "在线结果应包含抓取时间")

    def test_rejects_unmatched_and_external_candidates(self) -> None:
        """未命中审核词或指向外站的活动不得返回。"""
        candidates = [
            {"title": "青城前山观光一日", "url": "/lines.html?id=200"},
            {"title": "青城后山环线一日", "url": "https://evil.example/lines.html?id=201"},
            {"title": "青城后山环线一日", "url": "http://www.youxiake.com/lines.html?id=202"},
        ]
        provider = YouxiakeGroupTourLinkProvider(candidate_fetcher=lambda _keyword: candidates)

        self.assertEqual(
            [],
            provider.find_links("青城后山环线", []),
            "相似名称和非法链接均应被过滤",
        )

    def test_empty_candidates_are_not_an_error(self) -> None:
        """网页正常但没有相关活动时，应返回空列表。"""
        provider = YouxiakeGroupTourLinkProvider(candidate_fetcher=lambda _keyword: [])

        self.assertEqual([], provider.find_links("赵公山西线", ["赵公山"]))


class PlaywrightFetcherCleanupTest(unittest.TestCase):
    def test_browser_closes_after_successful_fetch(self) -> None:
        """活动读取成功后，也应正常关闭浏览器。"""
        class FakeBrowser:
            def __init__(self) -> None:
                self.is_closed = False

            def new_page(self) -> object:
                class FakePage:
                    def goto(self, *_args: object, **_kwargs: object) -> None:
                        return None

                return FakePage()

            def close(self) -> None:
                self.is_closed = True

        class FakeChromium:
            def __init__(self, browser: FakeBrowser) -> None:
                self.browser = browser

            def launch(self, **_kwargs: object) -> FakeBrowser:
                return self.browser

        class FakePlaywright:
            def __init__(self, browser: FakeBrowser) -> None:
                self.chromium = FakeChromium(browser)

        class FakeManager:
            def __init__(self, browser: FakeBrowser) -> None:
                self.playwright = FakePlaywright(browser)

            def __enter__(self) -> FakePlaywright:
                return self.playwright

            def __exit__(self, *_args: object) -> None:
                return None

        browser = FakeBrowser()
        fetcher = PlaywrightYouxiakeBrowserFetcher(
            playwright_factory=lambda: FakeManager(browser)
        )
        expected = [{"title": "青城后山", "url": "/lines.html?id=1"}]
        with (
            patch.object(fetcher, "_reject_blocked_page"),
            patch.object(fetcher, "_search"),
            patch.object(fetcher, "_read_candidates", return_value=expected),
        ):
            results = fetcher.fetch_candidates("青城后山")

        self.assertEqual(expected, results, "成功抓取应返回页面候选活动")
        self.assertTrue(browser.is_closed, "成功抓取后必须关闭浏览器")

    def test_fetcher_submits_keyword_in_search_box(self) -> None:
        """抓取器应在一日游页面输入关键词并提交搜索。"""
        class FakeLocator:
            def __init__(self) -> None:
                self.filled = ""
                self.is_clicked = False

            def wait_for(self, **_kwargs: object) -> None:
                return None

            def fill(self, value: str) -> None:
                self.filled = value

            def click(self, **_kwargs: object) -> None:
                self.is_clicked = True

        class FakePage:
            def __init__(self) -> None:
                self.search_input = FakeLocator()
                self.search_button = FakeLocator()
                self.url = "https://www.youxiake.com/search/results/example.html"
                self.waited_for_url = False

            def locator(self, selector: str) -> FakeLocator:
                if selector == 'input[name="keyword"]':
                    return self.search_input
                return self.search_button

            def wait_for_url(self, predicate: object, **_kwargs: object) -> None:
                self.waited_for_url = bool(  # type: ignore[operator]
                    predicate("https://www.youxiake.com/search/results/changed.html")
                )

        page = FakePage()

        PlaywrightYouxiakeBrowserFetcher()._search(page, "巴朗山")

        self.assertEqual("巴朗山", page.search_input.filled, "应输入审核后的路线关键词")
        self.assertTrue(page.search_button.is_clicked, "应点击搜索按钮")
        self.assertTrue(page.waited_for_url, "应等待搜索结果页面跳转")

    def test_browser_closes_when_page_loading_fails(self) -> None:
        """页面加载异常时，应关闭浏览器并输出中文错误。"""
        class FailingPage:
            def goto(self, *_args: object, **_kwargs: object) -> None:
                raise RuntimeError("network failed")

        class FakeBrowser:
            def __init__(self) -> None:
                self.is_closed = False

            def new_page(self) -> FailingPage:
                return FailingPage()

            def close(self) -> None:
                self.is_closed = True

        class FakeChromium:
            def __init__(self, browser: FakeBrowser) -> None:
                self.browser = browser

            def launch(self, **_kwargs: object) -> FakeBrowser:
                return self.browser

        class FakePlaywright:
            def __init__(self, browser: FakeBrowser) -> None:
                self.chromium = FakeChromium(browser)

        class FakeManager:
            def __init__(self, browser: FakeBrowser) -> None:
                self.playwright = FakePlaywright(browser)

            def __enter__(self) -> FakePlaywright:
                return self.playwright

            def __exit__(self, *_args: object) -> None:
                return None

        browser = FakeBrowser()
        fetcher = PlaywrightYouxiakeBrowserFetcher(
            playwright_factory=lambda: FakeManager(browser)
        )

        with self.assertRaisesRegex(GroupTourLinkError, "游侠客报团链接暂时无法获取"):
            fetcher.fetch_candidates("青城后山")

        self.assertTrue(browser.is_closed, "页面加载失败后也必须关闭浏览器")

    def test_open_search_page_retries_once_after_timeout(self) -> None:
        """搜索页首次加载失败时应重试一次。"""
        class FlakyPage:
            def __init__(self) -> None:
                self.goto_count = 0

            def goto(self, *_args: object, **_kwargs: object) -> None:
                self.goto_count += 1
                if self.goto_count == 1:
                    raise RuntimeError("temporary timeout")

        page = FlakyPage()

        PlaywrightYouxiakeBrowserFetcher()._open_search_page(page)

        self.assertEqual(2, page.goto_count, "首次失败后应且只应重试一次")


class GroupTourLinkServiceTest(unittest.TestCase):
    def test_service_uses_reviewed_route_name_and_aliases(self) -> None:
        """服务应使用已审核路线名称及别名查询在线链接。"""
        with tempfile.TemporaryDirectory() as temp:
            provider = StubGroupTourProvider(
                [{"title": "活动", "url": "https://m.youxiake.com/lines.html?id=1"}]
            )
            service = ChatBIService(
                Path(temp) / "test.db", NoTrafficProvider(), group_tour_provider=provider
            )
            service.seed(SAMPLE_DATA_PATH)

            results = service.group_tour_links("qingcheng-back-mountain")

            self.assertEqual(1, len(results), "在线 Provider 结果应原样返回")
            self.assertEqual(
                ("青城后山环线", ["青城后山", "青城山后山"]),
                provider.calls[0],
                "服务应传递路线名称和人工审核别名",
            )

    def test_service_rejects_unknown_route(self) -> None:
        """不存在或未审核路线不得用于在线报团查询。"""
        with tempfile.TemporaryDirectory() as temp:
            service = ChatBIService(
                Path(temp) / "test.db",
                NoTrafficProvider(),
                group_tour_provider=StubGroupTourProvider([]),
            )
            service.seed(SAMPLE_DATA_PATH)

            with self.assertRaisesRegex(ValueError, "路线不存在或未审核"):
                service.group_tour_links("missing-route")


if __name__ == "__main__":
    unittest.main()
