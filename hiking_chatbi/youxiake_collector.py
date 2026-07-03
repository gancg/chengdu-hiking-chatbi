from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlparse, parse_qs

from .config import (
    COLLECTOR_BROWSER_TIMEOUT_SECONDS,
    COLLECTOR_LEGACY_OUTPUT_PATH,
    COLLECTOR_MAX_PAGES,
    COLLECTOR_MODEL,
    COLLECTOR_REQUEST_TIMEOUT_SECONDS,
    DASHSCOPE_CHAT_COMPLETIONS_URL,
    YOUXIAKE_LIST_URL,
)

LIST_URL = YOUXIAKE_LIST_URL
OUTPUT_PATH = COLLECTOR_LEGACY_OUTPUT_PATH
MODEL_NAME = COLLECTOR_MODEL
HIKING_WORDS = ("徒步", "轻徒", "登山", "古道", "穿越", "爬山", "溯溪", "攀登", "牧场")
DIFFICULTIES = {"easy", "moderate", "hard", "expert"}
ROUTE_TYPES = {"loop", "out_and_back", "point_to_point"}
TRANSPORT_MODES = {"self_drive", "public_transit", "carpool", "group_tour"}
SEASONS = {"春", "夏", "秋", "冬"}
ROUTE_FIELDS = {
    "id", "name", "group_tour_search_terms", "start_location", "end_location",
    "latitude", "longitude", "distance_km", "ascent_m", "highest_altitude_m",
    "hiking_minutes", "difficulty", "duration_days", "route_type", "is_traverse",
    "traverse_transfer_minutes", "best_seasons", "scenery", "risks",
    "transport_modes", "parking", "supplies", "has_toilet", "has_supply_shop",
    "signal", "camping", "source_url", "source_name", "collected_at", "updated_at",
    "confidence", "reviewed",
}


def normalize_text(value: str) -> str:
    """规范化用于筛选和去重的文本。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).lower()


def is_hiking_product(text: str) -> bool:
    """判断产品文本是否明确描述徒步活动。"""
    normalized = normalize_text(text)
    return any(word in normalized for word in HIKING_WORDS)


def normalize_detail_url(url: str) -> str:
    """将桌面或移动详情链接统一为稳定的移动详情 URL。"""
    parsed = urlparse(urljoin("https://www.youxiake.com", url))
    line_id = parse_qs(parsed.query).get("id", [""])[0]
    if not line_id.isdigit():
        raise ValueError(f"游侠客详情链接缺少数字 id: {url}")
    return f"https://m.youxiake.com/lines.html?id={line_id}"


def deduplicate_candidates(candidates: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """按详情 URL 和规范化名称保留首次出现的候选。"""
    result: list[dict[str, str]] = []
    urls: set[str] = set()
    names: set[str] = set()
    for item in candidates:
        url = normalize_detail_url(item["url"])
        name_key = normalize_text(item["name"])
        if url in urls or name_key in names or not is_hiking_product(item["name"]):
            continue
        urls.add(url)
        names.add(name_key)
        result.append({"name": item["name"].strip(), "url": url})
    return result


def merge_site_and_model(site: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """用模型结果补空，绝不覆盖网页已提取的事实。"""
    merged = dict(model)
    for key, value in site.items():
        if value is not None and value != [] and value != "":
            merged[key] = value
    return merged


def calculate_confidence(route: dict[str, Any], site_fields: set[str]) -> float:
    """根据网页证据覆盖和数据一致性计算保守置信度。"""
    evidence_fields = ROUTE_FIELDS - {"id", "source_name", "collected_at", "updated_at", "confidence", "reviewed"}
    direct_ratio = len(site_fields & evidence_fields) / len(evidence_fields)
    critical = {"name", "start_location", "distance_km", "ascent_m", "hiking_minutes", "difficulty", "route_type"}
    critical_ratio = len(site_fields & critical) / len(critical)
    score = 0.76 + 0.12 * direct_ratio + 0.08 * critical_ratio
    if route.get("duration_days") == 1 and "group_tour" in route.get("transport_modes", []):
        score += 0.03
    if route.get("is_traverse") == (route.get("route_type") == "point_to_point"):
        score += 0.02
    return round(min(score, 0.96), 2)


def _parse_iso_time(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是 ISO 8601 字符串")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{field} 必须包含时区")


def validate_route(route: dict[str, Any]) -> None:
    """验证单条路线基础信息。"""
    missing = sorted(ROUTE_FIELDS - route.keys())
    if missing:
        raise ValueError(f"路线缺少字段: {', '.join(missing)}")
    if route["difficulty"] not in DIFFICULTIES:
        raise ValueError(f"difficulty 无效: {route['difficulty']}")
    if route["route_type"] not in ROUTE_TYPES:
        raise ValueError(f"route_type 无效: {route['route_type']}")
    if not isinstance(route["duration_days"], int) or route["duration_days"] != 1:
        raise ValueError("duration_days 必须为 1")
    if not isinstance(route["is_traverse"], bool):
        raise ValueError("is_traverse 必须为布尔值")
    transfer = route["traverse_transfer_minutes"]
    if isinstance(transfer, bool) or not isinstance(transfer, int) or transfer < 0:
        raise ValueError("traverse_transfer_minutes 必须为非负整数")
    if route["is_traverse"] != (route["route_type"] == "point_to_point"):
        raise ValueError("is_traverse 与 route_type 不一致")
    if route["is_traverse"] and transfer <= 0:
        raise ValueError("穿越路线必须提供接驳时间")
    if not route["is_traverse"] and transfer != 0:
        raise ValueError("非穿越路线接驳时间必须为 0")
    modes = route["transport_modes"]
    if not isinstance(modes, list) or "group_tour" not in modes or not set(modes) <= TRANSPORT_MODES:
        raise ValueError("transport_modes 必须包含 group_tour 且只能使用规范枚举")
    if not isinstance(route["best_seasons"], list) or not set(route["best_seasons"]) <= SEASONS:
        raise ValueError("best_seasons 无效")
    for field in ("latitude", "longitude", "distance_km"):
        if isinstance(route[field], bool) or not isinstance(route[field], (int, float)):
            raise ValueError(f"{field} 必须为数字")
    for field in ("ascent_m", "highest_altitude_m", "hiking_minutes"):
        if isinstance(route[field], bool) or not isinstance(route[field], int):
            raise ValueError(f"{field} 必须为整数")
    for field in ("has_toilet", "has_supply_shop", "reviewed"):
        if not isinstance(route[field], bool):
            raise ValueError(f"{field} 必须为布尔值")
    if route["reviewed"]:
        raise ValueError("自动采集路线 reviewed 必须为 false")
    if not isinstance(route["confidence"], (int, float)) or route["confidence"] <= 0.8:
        raise ValueError("confidence 必须严格大于 0.8")
    _parse_iso_time(route["collected_at"], "collected_at")
    _parse_iso_time(route["updated_at"], "updated_at")


def validate_output(payload: dict[str, Any], expected_count: int = 40) -> None:
    """验证最终包装对象、数量与唯一性。"""
    if set(payload) != {"routes"} or not isinstance(payload["routes"], list):
        raise ValueError("JSON 根对象必须只包含 routes 数组")
    routes = payload["routes"]
    if len(routes) != expected_count:
        raise ValueError(f"路线数量必须为 {expected_count}，实际为 {len(routes)}")
    ids: set[str] = set()
    urls: set[str] = set()
    for index, route in enumerate(routes, 1):
        try:
            validate_route(route)
        except Exception as exc:
            raise ValueError(f"第 {index} 条路线校验失败: {exc}") from exc
        if route["id"] in ids:
            raise ValueError(f"路线 id 重复: {route['id']}")
        if route["source_url"] in urls:
            raise ValueError(f"详情 URL 重复: {route['source_url']}")
        ids.add(route["id"])
        urls.add(route["source_url"])


def call_qwen(detail_text: str, extracted: dict[str, Any], api_key: str) -> dict[str, Any]:
    """调用 qwen3.7-max 补全路线字段。"""
    prompt = (
        "根据游侠客成都一日徒步详情补全 route 字段。只返回 JSON 对象，不要 markdown。"
        "不得修改 extracted 中已有非空事实；合理估算缺失值。枚举必须遵守字段指南。"
        f"\nextracted={json.dumps(extracted, ensure_ascii=False)}\n详情正文：\n{detail_text[:30000]}"
    )
    body = json.dumps({
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        DASHSCOPE_CHAT_COMPLETIONS_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=COLLECTOR_REQUEST_TIMEOUT_SECONDS
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
        return json.loads(result["choices"][0]["message"]["content"])
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Qwen 路线补全失败: {exc}") from exc


def extract_site_fields(name: str, url: str, text: str) -> tuple[dict[str, Any], set[str]]:
    """从详情正文提取能够直接确定的路线事实。"""
    data: dict[str, Any] = {"name": name, "source_url": url, "source_name": "游侠客"}
    fields = {"name", "source_url"}
    patterns: list[tuple[str, str, Callable[[str], Any]]] = [
        ("distance_km", r"(?:徒步(?:距离)?|往返|全程)[^\d]{0,12}(\d+(?:\.\d+)?)\s*(?:km|公里)", float),
        ("ascent_m", r"(?:累计)?爬升[^\d]{0,8}\+?(\d+)\s*(?:m|米)", int),
        ("highest_altitude_m", r"(?:最高海拔|终点)[^\d]{0,8}(\d{3,4})\s*(?:m|米)", int),
        ("hiking_minutes", r"徒步[^\d]{0,10}(\d+(?:\.\d+)?)\s*(?:小时|h)", lambda value: round(float(value) * 60)),
    ]
    lower = text.lower()
    for field, pattern, converter in patterns:
        match = re.search(pattern, lower, re.I)
        if match:
            data[field] = converter(match.group(1))
            fields.add(field)
    data["duration_days"] = 1
    data["transport_modes"] = ["group_tour"]
    fields.update({"duration_days", "transport_modes"})
    return data, fields


def collect_routes(
    list_fetcher: Callable[[int], list[dict[str, str]]],
    detail_fetcher: Callable[[str], str],
    completer: Callable[[str, dict[str, Any]], dict[str, Any]],
    count: int = 40,
    max_pages: int = COLLECTOR_MAX_PAGES,
) -> dict[str, list[dict[str, Any]]]:
    """发现候选、读取详情并生成通过门槛的路线集合。"""
    candidates: list[dict[str, str]] = []
    for page_number in range(1, max_pages + 1):
        page_items = list_fetcher(page_number)
        if not page_items:
            break
        candidates = deduplicate_candidates([*candidates, *page_items])
    routes: list[dict[str, Any]] = []
    for candidate in candidates:
        text = detail_fetcher(candidate["url"])
        if "验证码" in text or "安全验证" in text:
            raise RuntimeError(f"游侠客页面出现验证码，已停止采集: {candidate['url']}")
        if not is_hiking_product(candidate["name"] + text):
            continue
        site, site_fields = extract_site_fields(candidate["name"], candidate["url"], text)
        model = completer(text, site)
        route = merge_site_and_model(site, model)
        now = datetime.now().astimezone().replace(microsecond=0).isoformat()
        route.update({"source_url": candidate["url"], "source_name": "游侠客", "collected_at": now,
                      "updated_at": now, "reviewed": False})
        route["confidence"] = calculate_confidence(route, site_fields)
        try:
            validate_route(route)
        except ValueError as exc:
            logging.error("路线校验失败: %s", exc)
            continue
        routes.append(route)
        if len(routes) == count:
            break
    if len(routes) != count:
        raise RuntimeError(f"符合条件且置信度大于 0.8 的路线不足 {count} 条，实际 {len(routes)} 条")
    payload = {"routes": routes}
    validate_output(payload, count)
    return payload


class PlaywrightFetcher:
    """复用一个 Playwright 浏览器抓取游侠客列表和详情。"""

    def __init__(self) -> None:
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._page = self._browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36")

    def close(self) -> None:
        """尽力释放浏览器资源，不让驱动断线异常遮住采集错误。"""
        with contextlib.suppress(Exception):
            self._browser.close()
        with contextlib.suppress(Exception):
            self._playwright.stop()

    def fetch_list(self, page_number: int) -> list[dict[str, str]]:
        url = re.sub(r"/azEtaTE\.html$", f"/azEtaTE_{page_number}.html", LIST_URL) if page_number > 1 else LIST_URL
        try:
            self._page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=COLLECTOR_BROWSER_TIMEOUT_SECONDS * 1000,
            )
        except Exception as exc:
            raise RuntimeError(f"无法打开游侠客列表页 {url}: {exc}") from exc
        self._page.wait_for_timeout(1500)
        body = self._page.locator("body").inner_text()
        if "验证码" in body or "安全验证" in body:
            raise RuntimeError(f"游侠客列表页出现验证码: {url}")
        return self._page.locator("div.linesSearchTitle a, a[href*='lines.html?id=']").evaluate_all(
            "els => els.map(a => ({name:(a.innerText||a.textContent||'').trim(), url:a.href})).filter(x=>x.name)"
        )

    def fetch_detail(self, url: str) -> str:
        try:
            self._page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=COLLECTOR_BROWSER_TIMEOUT_SECONDS * 1000,
            )
        except Exception as exc:
            raise RuntimeError(f"无法打开游侠客详情页 {url}: {exc}") from exc
        self._page.wait_for_timeout(1200)
        return self._page.locator("body").inner_text()


def main() -> int:
    parser = argparse.ArgumentParser(description="采集游侠客成都一日徒步路线")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法调用 qwen3.7-max")
    fetcher = PlaywrightFetcher()
    try:
        payload = collect_routes(
            fetcher.fetch_list,
            fetcher.fetch_detail,
            lambda text, site: call_qwen(text, site, api_key),
            count=args.count,
        )
    finally:
        fetcher.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {len(payload['routes'])} 条路线: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
