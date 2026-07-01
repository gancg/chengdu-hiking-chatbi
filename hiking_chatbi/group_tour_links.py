from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, urljoin, urlparse
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)

YOUXIAKE_AROUND_URL = "https://www.youxiake.com/search/results/0-0-0-1-0-0/azEtaTE.html"
DAE_URL = "https://www.cddee.cn/"
MIDO_URL = "https://cdmdtb.360jlb.cn/events?mid=52240"
ALLOWED_YOUXIAKE_HOSTS = {"www.youxiake.com", "m.youxiake.com"}
BLOCKED_PAGE_MARKERS = ("验证码", "安全验证", "访问验证", "请先登录")


class GroupTourLinkError(RuntimeError):
    """Raised when online group-tour links cannot be fetched safely."""


class GroupTourLinkProvider(Protocol):
    def find_links(
        self, route_name: str, search_terms: list[str]
    ) -> list[dict[str, str]]:
        """Find reviewed online links related to one route."""


class MultiGroupTourLinkProvider:
    """Merge independent merchant providers without coupling their site rules."""

    def __init__(
        self,
        providers: list[tuple[str, GroupTourLinkProvider]],
        max_links: int = 15,
    ) -> None:
        if max_links <= 0:
            raise ValueError("max_links 必须大于 0")
        self.providers = providers
        self.max_links = max_links

    def find_links(
        self, route_name: str, search_terms: list[str]
    ) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        errors: list[tuple[str, Exception]] = []
        successful_provider_count = 0
        for source_name, provider in self.providers:
            try:
                items = provider.find_links(route_name, search_terms)
                successful_provider_count += 1
            except Exception as exc:
                errors.append((source_name, exc))
                logger.exception("商团链接来源查询失败 source_name=%s", source_name)
                continue
            for item in items:
                url = str(item.get("url", "")).strip()
                url_key = _normalize_result_url(url)
                if not url or url_key in seen_urls:
                    continue
                seen_urls.add(url_key)
                result = dict(item)
                result["source_name"] = source_name
                results.append(result)
                if len(results) >= self.max_links:
                    return results
        if errors and successful_provider_count == 0:
            failed_sources = "、".join(source for source, _ in errors)
            raise GroupTourLinkError(
                f"报团链接暂时无法获取，查询失败来源：{failed_sources}"
            ) from errors[0][1]
        return results


class _DaeActivityParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self.current_url = ""
        self.is_reading_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and re.search(r"(?:^|/)News_read_id_\d+\.shtml$", attributes.get("href") or ""):
            self.current_url = attributes.get("href") or ""
            self.title_parts = []
        elif tag == "div" and self.current_url and "tit" in (attributes.get("class") or "").split():
            self.is_reading_title = True

    def handle_data(self, data: str) -> None:
        if self.is_reading_title:
            self.title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.is_reading_title:
            self.is_reading_title = False
        elif tag == "a" and self.current_url:
            title = " ".join(part.strip() for part in self.title_parts if part.strip())
            if title:
                self.items.append({"title": title, "url": self.current_url})
            self.current_url = ""
            self.title_parts = []


class _MidoActivityParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self.current_url = ""
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        href = attributes.get("href") or ""
        if tag == "a" and urlparse(href).path == "/event":
            self.current_url = href
            self.title_parts = []

    def handle_data(self, data: str) -> None:
        if self.current_url:
            self.title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_url:
            title = " ".join(part.strip() for part in self.title_parts if part.strip())
            if title:
                self.items.append({"title": title, "url": self.current_url})
            self.current_url = ""
            self.title_parts = []


class DaeGroupTourLinkProvider:
    """Search and match public Dae activity links."""

    def __init__(
        self,
        page_url: str = DAE_URL,
        timeout_seconds: int = 20,
        max_links: int = 5,
        html_fetcher: Callable[[str], str] | None = None,
    ) -> None:
        self.page_url = page_url
        self.timeout_seconds = timeout_seconds
        self.max_links = max_links
        self.html_fetcher = html_fetcher or self._fetch_search_html

    def _fetch_search_html(self, keyword: str) -> str:
        search_url = urljoin(
            self.page_url,
            f"/News_lists_quyu_224_sort_1.shtml?title={quote(keyword)}",
        )
        return _fetch_public_html(search_url, "大鹅", self.timeout_seconds)

    def find_links(self, route_name: str, search_terms: list[str]) -> list[dict[str, str]]:
        terms = _ordered_unique_terms(route_name, search_terms)
        keyword = search_terms[0].strip() if search_terms else route_name.strip()
        parser = _DaeActivityParser()
        parser.feed(self.html_fetcher(keyword))
        return _match_public_candidates(
            parser.items,
            terms,
            lambda value: _validate_dae_url(value, self.page_url),
            self.max_links,
        )


class MidoGroupTourLinkProvider:
    """Read and match public Mido activity links."""

    def __init__(
        self,
        page_url: str = MIDO_URL,
        timeout_seconds: int = 20,
        max_links: int = 5,
        html_fetcher: Callable[[str], str] | None = None,
    ) -> None:
        self.page_url = page_url
        self.timeout_seconds = timeout_seconds
        self.max_links = max_links
        self.html_fetcher = html_fetcher or self._fetch_list_html

    def _fetch_list_html(self, _keyword: str) -> str:
        return _fetch_browser_html(self.page_url, "蜜多", self.timeout_seconds)

    def find_links(self, route_name: str, search_terms: list[str]) -> list[dict[str, str]]:
        terms = _ordered_unique_terms(route_name, search_terms)
        keyword = search_terms[0].strip() if search_terms else route_name.strip()
        parser = _MidoActivityParser()
        parser.feed(self.html_fetcher(keyword))
        return _match_public_candidates(
            parser.items,
            terms,
            lambda value: _validate_mido_url(value, self.page_url),
            self.max_links,
        )


class PlaywrightYouxiakeBrowserFetcher:
    """Search and read public one-day activities in one browser session."""

    def __init__(
        self,
        page_url: str = YOUXIAKE_AROUND_URL,
        timeout_seconds: int = 30,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.page_url = page_url
        self.timeout_ms = timeout_seconds * 1000
        self.playwright_factory = playwright_factory

    def fetch_candidates(self, keyword: str) -> list[dict[str, str]]:
        try:
            factory = self.playwright_factory or self._load_playwright_factory()
            with factory() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    self._open_search_page(page)
                    self._reject_blocked_page(page)
                    self._search(page, keyword)
                    self._reject_blocked_page(page)
                    return self._read_candidates(page)
                finally:
                    try:
                        browser.close()
                    except Exception:
                        logger.exception("关闭游侠客抓取浏览器失败")
        except GroupTourLinkError:
            raise
        except Exception as exc:
            logger.exception("游侠客报团链接抓取失败 url=%s", self.page_url)
            raise GroupTourLinkError(
                "游侠客报团链接暂时无法获取，请稍后重试"
            ) from exc

    @staticmethod
    def _load_playwright_factory() -> Callable[[], Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise GroupTourLinkError(
                "游侠客报团链接暂时无法获取：Playwright 未安装"
            ) from exc
        return sync_playwright

    def _open_search_page(self, page: Any) -> None:
        for attempt in range(2):
            try:
                page.goto(
                    self.page_url,
                    wait_until="commit",
                    timeout=self.timeout_ms,
                )
                return
            except Exception:
                if attempt == 1:
                    raise
                logger.warning("游侠客搜索页首次加载失败，准备重试 url=%s", self.page_url)

    def _reject_blocked_page(self, page: Any) -> None:
        body_text = page.locator("body").inner_text(timeout=self.timeout_ms)
        marker = next(
            (item for item in BLOCKED_PAGE_MARKERS if item in body_text), None
        )
        if marker:
            raise GroupTourLinkError(
                f"游侠客报团链接暂时无法获取：页面出现{marker}"
            )

    def _search(self, page: Any, keyword: str) -> None:
        search_input = page.locator('input[name="keyword"]')
        search_input.wait_for(state="visible", timeout=self.timeout_ms)
        initial_url = page.url
        search_input.fill(keyword)
        page.locator("button.yxk_header_search_submit").click(
            timeout=self.timeout_ms
        )
        page.wait_for_url(
            lambda url: str(url) != initial_url,
            wait_until="commit",
            timeout=self.timeout_ms,
        )

    def _read_candidates(self, page: Any) -> list[dict[str, str]]:
        links = page.locator('a[href*="/lines.html?id="]')
        candidates: list[dict[str, str]] = []
        for index in range(links.count()):
            link = links.nth(index)
            if not link.is_visible():
                continue
            title = link.inner_text(timeout=self.timeout_ms).strip()
            url = (link.get_attribute("href") or "").strip()
            if title and url:
                candidates.append({"title": title, "url": url})
        return candidates


class YouxiakeGroupTourLinkProvider:
    """Match reviewed route terms against live Youxiake activity cards."""

    def __init__(
        self,
        candidate_fetcher: Callable[[str], list[dict[str, str]]] | None = None,
        max_links: int = 5,
        page_url: str = YOUXIAKE_AROUND_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self.page_url = page_url
        self.max_links = max_links
        browser_fetcher = PlaywrightYouxiakeBrowserFetcher(
            page_url=page_url,
            timeout_seconds=timeout_seconds,
        )
        self.candidate_fetcher = candidate_fetcher or browser_fetcher.fetch_candidates

    def find_links(
        self, route_name: str, search_terms: list[str]
    ) -> list[dict[str, str]]:
        terms = _ordered_unique_terms(route_name, search_terms)
        search_keyword = search_terms[0].strip() if search_terms else route_name.strip()
        candidates = self.candidate_fetcher(search_keyword)
        fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
        results: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for candidate in candidates:
            title = str(candidate.get("title", "")).strip()
            matched_term = _find_matched_term(title, terms)
            validated = _validate_youxiake_url(
                str(candidate.get("url", "")), self.page_url
            )
            if not title or not matched_term or validated is None:
                continue
            url, url_key = validated
            if url_key in seen_urls:
                continue
            seen_urls.add(url_key)
            results.append(
                {
                    "title": title,
                    "url": url,
                    "matched_term": matched_term,
                    "fetched_at": fetched_at,
                }
            )
            if len(results) >= self.max_links:
                break
        logger.info(
            "游侠客报团链接匹配完成 route_name=%s term_count=%s candidate_count=%s result_count=%s",
            route_name,
            len(terms),
            len(candidates),
            len(results),
        )
        return results


def _ordered_unique_terms(route_name: str, search_terms: list[str]) -> list[str]:
    result: list[str] = []
    normalized_seen: set[str] = set()
    for value in [route_name, *search_terms]:
        term = value.strip()
        normalized = _normalize_text(term)
        if normalized and normalized not in normalized_seen:
            normalized_seen.add(normalized)
            result.append(term)
    return result


def _find_matched_term(title: str, terms: list[str]) -> str | None:
    normalized_title = _normalize_text(title)
    for term in terms:
        if _normalize_text(term) in normalized_title:
            return term
    return None


def _normalize_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _normalize_result_url(value: str) -> str:
    parsed = urlparse(value.strip())
    return parsed._replace(fragment="").geturl()


def _fetch_public_html(url: str, source_name: str, timeout_seconds: int) -> str:
    request = Request(url, headers={"User-Agent": "chengdu-hiking-chatbi/1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise GroupTourLinkError(
            f"{source_name}报团链接暂时无法获取，请稍后重试"
        ) from exc


def _fetch_browser_html(url: str, source_name: str, timeout_seconds: int) -> str:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_seconds * 1000,
                )
                return str(page.content())
            finally:
                browser.close()
    except Exception as exc:
        raise GroupTourLinkError(
            f"{source_name}报团链接暂时无法获取，请稍后重试"
        ) from exc


def _match_public_candidates(
    candidates: list[dict[str, str]],
    terms: list[str],
    validate_url: Callable[[str], tuple[str, str] | None],
    max_links: int,
) -> list[dict[str, str]]:
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        title = candidate.get("title", "").strip()
        matched_term = _find_matched_term(title, terms)
        validated = validate_url(candidate.get("url", ""))
        if not title or not matched_term or validated is None:
            continue
        url, url_key = validated
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        results.append({
            "title": title,
            "url": url,
            "matched_term": matched_term,
            "fetched_at": fetched_at,
        })
        if len(results) >= max_links:
            break
    return results


def _validate_dae_url(raw_url: str, base_url: str) -> tuple[str, str] | None:
    absolute = urljoin(base_url, raw_url.strip())
    parsed = urlparse(absolute)
    matched = re.fullmatch(r"/News_read_id_(\d+)\.shtml", parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "www.cddee.cn" or matched is None:
        return None
    activity_id = matched.group(1)
    return f"https://www.cddee.cn/News_read_id_{activity_id}.shtml", f"dae:{activity_id}"


def _validate_mido_url(raw_url: str, base_url: str) -> tuple[str, str] | None:
    absolute = urljoin(base_url, raw_url.strip())
    parsed = urlparse(absolute)
    base = urlparse(base_url)
    query = parse_qs(parsed.query)
    ids = query.get("id", [])
    mids = query.get("mid", [])
    expected_mids = parse_qs(base.query).get("mid", [])
    if (
        parsed.scheme != "https"
        or parsed.hostname != base.hostname
        or parsed.path != "/event"
        or len(ids) != 1
        or not ids[0].isdigit()
        or len(mids) != 1
        or mids != expected_mids
    ):
        return None
    return (
        f"https://{parsed.hostname}/event?id={ids[0]}&mid={mids[0]}",
        f"mido:{mids[0]}:{ids[0]}",
    )


def _validate_youxiake_url(
    raw_url: str, base_url: str
) -> tuple[str, str] | None:
    absolute = urljoin(base_url, raw_url.strip())
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_YOUXIAKE_HOSTS:
        return None
    query = parse_qs(parsed.query)
    ids = query.get("id", [])
    if parsed.path != "/lines.html" or len(ids) != 1 or not ids[0].isdigit():
        return None
    canonical_url = f"https://{parsed.hostname}/lines.html?id={ids[0]}"
    return canonical_url, f"lines:{ids[0]}"
