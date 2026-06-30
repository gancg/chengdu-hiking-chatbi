from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import parse_qs, urljoin, urlparse


logger = logging.getLogger(__name__)

YOUXIAKE_AROUND_URL = "https://www.youxiake.com/around?site=19"
ALLOWED_YOUXIAKE_HOSTS = {"www.youxiake.com", "m.youxiake.com"}
BLOCKED_PAGE_MARKERS = ("验证码", "安全验证", "访问验证", "请先登录")


class GroupTourLinkError(RuntimeError):
    """Raised when online group-tour links cannot be fetched safely."""


class GroupTourLinkProvider(Protocol):
    def find_links(
        self, route_name: str, search_terms: list[str]
    ) -> list[dict[str, str]]:
        """Find reviewed online links related to one route."""


class PlaywrightYouxiakeBrowserFetcher:
    """Read public one-day activity cards from Youxiake in one browser session."""

    def __init__(
        self,
        page_url: str = YOUXIAKE_AROUND_URL,
        timeout_seconds: int = 20,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.page_url = page_url
        self.timeout_ms = timeout_seconds * 1000
        self.playwright_factory = playwright_factory

    def fetch_candidates(self) -> list[dict[str, str]]:
        try:
            factory = self.playwright_factory or self._load_playwright_factory()
            with factory() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(
                        self.page_url,
                        wait_until="commit",
                        timeout=self.timeout_ms,
                    )
                    self._reject_blocked_page(page)
                    self._select_filter(page, "成都出发")
                    self._select_filter(page, "一日")
                    self._load_visible_cards(page)
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

    def _reject_blocked_page(self, page: Any) -> None:
        body_text = page.locator("body").inner_text(timeout=self.timeout_ms)
        marker = next(
            (item for item in BLOCKED_PAGE_MARKERS if item in body_text), None
        )
        if marker:
            raise GroupTourLinkError(
                f"游侠客报团链接暂时无法获取：页面出现{marker}"
            )

    def _select_filter(self, page: Any, label: str) -> None:
        locator = page.get_by_text(label, exact=True)
        if locator.count() == 0:
            raise GroupTourLinkError(
                f"游侠客报团链接暂时无法获取：页面缺少“{label}”筛选项"
            )
        locator.first.click(timeout=self.timeout_ms)
        page.wait_for_timeout(500)

    @staticmethod
    def _load_visible_cards(page: Any) -> None:
        stable_rounds = 0
        previous_count = -1
        for _ in range(8):
            count = page.locator("div.linesSearchTitle a").count()
            stable_rounds = stable_rounds + 1 if count == previous_count else 0
            if stable_rounds >= 2:
                break
            previous_count = count
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(500)

    def _read_candidates(self, page: Any) -> list[dict[str, str]]:
        links = page.locator("div.linesSearchTitle a")
        if links.count() == 0:
            raise GroupTourLinkError(
                "游侠客报团链接暂时无法获取：无法识别活动列表结构"
            )
        candidates: list[dict[str, str]] = []
        for index in range(links.count()):
            link = links.nth(index)
            title = link.inner_text(timeout=self.timeout_ms).strip()
            url = (link.get_attribute("href") or "").strip()
            if title and url:
                candidates.append({"title": title, "url": url})
        return candidates


class YouxiakeGroupTourLinkProvider:
    """Match reviewed route terms against live Youxiake activity cards."""

    def __init__(
        self,
        candidate_fetcher: Callable[[], list[dict[str, str]]] | None = None,
        max_links: int = 5,
        page_url: str = YOUXIAKE_AROUND_URL,
        timeout_seconds: int = 20,
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
        candidates = self.candidate_fetcher()
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
