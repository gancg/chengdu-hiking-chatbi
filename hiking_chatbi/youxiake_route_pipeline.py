from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
if __package__:
    from .config import (
        COLLECTOR_BROWSER_TIMEOUT_SECONDS,
        COLLECTOR_LINK_TIMEOUT_SECONDS,
        COLLECTOR_MAX_PAGES,
        COLLECTOR_MODEL,
        COLLECTOR_REQUEST_TIMEOUT_SECONDS,
        DASHSCOPE_CHAT_COMPLETIONS_URL,
        YOUXIAKE_LIST_URL,
    )
    from .importer import load_import_file
    from .validation import validate_import_item
else:
    sys.path.insert(0, str(ROOT))
    from hiking_chatbi.config import (
        COLLECTOR_BROWSER_TIMEOUT_SECONDS,
        COLLECTOR_LINK_TIMEOUT_SECONDS,
        COLLECTOR_MAX_PAGES,
        COLLECTOR_MODEL,
        COLLECTOR_REQUEST_TIMEOUT_SECONDS,
        DASHSCOPE_CHAT_COMPLETIONS_URL,
        YOUXIAKE_LIST_URL,
    )
    from hiking_chatbi.importer import load_import_file
    from hiking_chatbi.validation import validate_import_item


MODEL_NAME = COLLECTOR_MODEL
LIST_URL = YOUXIAKE_LIST_URL
SELECT_OUTPUT_PATH = ROOT / "data" / "sample_routes_select.json"
RUNTIME_OUTPUT_PATH = ROOT / "data" / "sample_routes.json"
HIKING_WORDS = ("徒步", "轻徒", "登山", "古道", "穿越", "爬山", "溯溪", "攀登", "牧场")
ROUTE_COST_TYPES = {"ticket", "parking", "shuttle", "waste", "other"}
TRANSPORT_COST_TYPES = {"fuel", "toll", "train", "bus", "other"}
BILLING_UNITS = {"person", "vehicle", "group"}
GENERIC_SEGMENTS = {
    "休闲轻徒", "徒步玩水", "雪山海子", "宝藏小城", "野趣轻徒", "穿越",
    "雪山", "轻装", "经典", "重装徒步", "亲子", "特惠", "夜徒牛背山",
}
NAME_OVERRIDES = {
    "徒步玩水·龙窝子小环线": "龙窝子小环线",
    "潮玩旅行家·沉舟秘境寻宝记": "复兴村沉舟秘境",
    "宝藏小城 · 寻古荥经": "荥经古城",
    "花海寻菌": "海子坪",
    "夜徒牛背山": "牛背山夜徒线",
    "亲子·蜀道少年": "蜀道精华线",
    "亲子·奇迹孟屯河谷": "孟屯河谷",
    "去东极·忘记你": "东极岛环线",
    "广西阿勒泰2天": "全州天湖-茶坪-真宝顶",
    "亲子·宁海湾赶海": "宁海湾赶海",
}
SCHEMA_TEMPLATE: dict[str, Any] = {
    "route": {
        "id": "lowercase-english-slug", "name": "路线名称",
        "group_tour_search_terms": ["搜索词"], "start_location": "起点",
        "end_location": "终点", "latitude": 30.0, "longitude": 103.0,
        "distance_km": 10.0, "ascent_m": 500, "highest_altitude_m": 2000,
        "hiking_minutes": 300, "difficulty": "moderate", "duration_days": 1,
        "route_type": "out_and_back", "is_traverse": False,
        "traverse_transfer_minutes": 0, "best_seasons": ["春", "秋"],
        "scenery": ["森林"], "risks": ["雨天湿滑"],
        "transport_modes": ["self_drive", "group_tour"], "parking": "停车说明",
        "supplies": "补给说明", "has_toilet": True, "has_supply_shop": False,
        "signal": "信号说明", "camping": "露营说明", "source_url": "https://...",
        "source_name": "来源名称", "collected_at": "2026-07-01T12:00:00+08:00",
        "updated_at": "2026-07-01T12:00:00+08:00", "confidence": 0.8,
        "reviewed": False,
    },
    "costs": {
        "route_fees": [{
            "name": "费用名称", "cost_type": "ticket", "billing_unit": "person",
            "min_cny": 0, "max_cny": 0, "source_url": "https://...",
            "updated_at": "2026-07-01T12:00:00+08:00",
        }],
        "transport_options": [{
            "transport_mode": "group_tour", "name": "团费", "cost_type": "bus",
            "billing_unit": "person", "min_cny": 0, "max_cny": 0,
            "source_url": "https://...", "updated_at": "2026-07-01T12:00:00+08:00",
        }],
    },
    "traffic": {
        "base_one_way_minutes": 120, "weekday_extra_min": 10,
        "weekday_extra_max": 30, "weekend_extra_min": 20,
        "weekend_extra_max": 60, "holiday_extra_min": 40,
        "holiday_extra_max": 120, "morning_extra_minutes": 20,
        "evening_extra_minutes": 30, "common_bottlenecks": ["拥堵点"],
        "best_departure_time": "06:30前", "suggested_return_time": "16:30前",
        "source_url": "https://...", "updated_at": "2026-07-01T12:00:00+08:00",
        "confidence": 0.8,
    },
}


def build_page_url(page_number: int, page_url: str = LIST_URL) -> str:
    """根据游侠客筛选路径中的第 4 个数字生成分页 URL。"""
    if page_number <= 0:
        raise ValueError("page_number 必须为正整数")
    result, replaced = re.subn(
        r"(/search/results/\d+-\d+-\d+-)\d+(-\d+-\d+/)",
        rf"\g<1>{page_number}\g<2>",
        page_url,
        count=1,
    )
    if replaced != 1:
        raise ValueError(f"无法识别游侠客筛选页分页结构: {page_url}")
    return result


def validate_page_url(page_url: str) -> str:
    """校验并返回可用于采集的游侠客 HTTPS 筛选页。"""
    normalized = page_url.strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.youxiake.com", "m.youxiake.com"}
        or not parsed.path.startswith("/search/results/")
    ):
        raise ValueError("page-url 必须是 HTTPS 游侠客筛选页地址")
    build_page_url(1, normalized)
    return normalized


def normalize_route_link(url: str) -> tuple[str, str] | None:
    """规范化游侠客详情链接并返回活动 ID。"""
    from urllib.parse import parse_qs, urljoin, urlparse

    absolute = urljoin("https://www.youxiake.com", url.strip())
    parsed = urlparse(absolute)
    if parsed.hostname not in {"www.youxiake.com", "m.youxiake.com"}:
        return None
    route_id = parse_qs(parsed.query).get("id", [""])[0]
    if not route_id.isdigit():
        return None
    return f"https://m.youxiake.com/lines.html?id={route_id}", route_id


def select_unique_routes(
    candidates: Iterable[dict[str, str]], count: int = 40
) -> list[dict[str, str]]:
    """按活动 ID 去重并保留页面中的首次出现顺序。"""
    routes: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        name = str(candidate.get("name", "")).strip()
        normalized = normalize_route_link(str(candidate.get("url", "")))
        if not name or normalized is None:
            continue
        url, route_id = normalized
        if route_id in seen_ids:
            continue
        seen_ids.add(route_id)
        routes.append({"name": name, "url": url})
        if len(routes) == count:
            break
    return routes


class RouteLinkFetcher:
    """使用 Playwright 逐页读取游侠客活动名称和详情链接。"""

    def __init__(
        self,
        page_url: str = LIST_URL,
        timeout_seconds: int = COLLECTOR_LINK_TIMEOUT_SECONDS,
    ) -> None:
        from playwright.sync_api import sync_playwright

        self.page_url = page_url
        self.timeout_ms = timeout_seconds * 1000
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._page = self._browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
        )

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._browser.close()
        with contextlib.suppress(Exception):
            self._playwright.stop()

    def fetch(self, count: int) -> list[dict[str, str]]:
        """按页面顺序抓取候选，详情筛选阶段再确定前 N 条合格路线。"""
        all_candidates: list[dict[str, str]] = []
        previous_ids: set[str] = set()
        for page_number in range(1, COLLECTOR_MAX_PAGES + 1):
            page_url = build_page_url(page_number, self.page_url)
            self._open_page(page_url)
            self._reject_blocked_page(page_url)
            page_candidates = self._read_candidates()
            page_ids = {
                normalized[1]
                for item in page_candidates
                if (normalized := normalize_route_link(item.get("url", ""))) is not None
            }
            if not page_ids or (page_number > 1 and page_ids == previous_ids):
                break
            previous_ids = page_ids
            all_candidates.extend(page_candidates)
        routes = select_unique_routes(all_candidates, count=len(all_candidates))
        if len(routes) < count:
            raise RuntimeError(f"游侠客公开页面候选不足 {count} 条，实际抓取 {len(routes)} 条")
        return routes

    def _open_page(self, url: str) -> None:
        try:
            self._page.goto(url, wait_until="commit", timeout=self.timeout_ms)
            self._page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
        except Exception as exc:
            raise RuntimeError(f"无法打开游侠客路线页面 {url}: {exc}") from exc

    def _reject_blocked_page(self, url: str) -> None:
        body = self._page.locator("body").inner_text(timeout=self.timeout_ms)
        marker = next(
            (item for item in ("验证码", "安全验证", "访问过于频繁") if item in body),
            None,
        )
        if marker:
            raise RuntimeError(f"游侠客页面出现{marker}，已停止抓取: {url}")

    def _read_candidates(self) -> list[dict[str, str]]:
        return self._page.locator('a[href*="/lines.html?id="]').evaluate_all(
            """els => els.filter(a => a.offsetParent !== null).map(a => ({
                name: (a.innerText || a.textContent || '').trim(),
                url: a.href || a.getAttribute('href') || ''
            })).filter(item => item.name && item.url)"""
        )


def write_links(
    path: Path,
    routes: list[dict[str, str]],
    target_count: int,
    source_page_url: str,
) -> None:
    """保存第一阶段的链接检查点。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "source_page_url": source_page_url,
                "target_count": target_count,
                "routes": routes,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def extract_route_name(product_name: str) -> str:
    """从游侠客产品标题中提取可用于路线数据的短名称。"""
    cleaned = re.sub(r"\s*跟团游\s*$", "", product_name.strip())
    cleaned = re.sub(r"^\d+元(?:特惠|户外)?[·・]?", "", cleaned)
    normalized_cleaned = re.sub(r"\s+", " ", cleaned)
    override = next(
        (value for key, value in NAME_OVERRIDES.items() if key in normalized_cleaned),
        None,
    )
    if override is not None:
        return override
    segments = [part.strip() for part in re.split(r"[|｜│]", cleaned) if part.strip()]
    first = segments[0] if segments else cleaned
    dot_parts = [part.strip() for part in re.split(r"[·・]", first) if part.strip()]
    if len(dot_parts) > 1:
        candidate = dot_parts[-1]
    else:
        candidate = first
    if candidate in GENERIC_SEGMENTS and len(segments) > 1:
        candidate = segments[1]
    candidate = re.sub(r"<[^>]+>", "", candidate)
    candidate = re.sub(r"(?:1日|2日|2天|半自由行)$", "", candidate).strip(" -—")
    if not candidate:
        raise ValueError(f"无法从产品标题提取路线名称: {product_name}")
    return candidate


def default_links_path(count: int) -> Path:
    """返回指定数量的候选链接检查点路径。"""
    return ROOT / "data" / f"youxiake_route_links_{count}.json"


def default_checkpoint_path(count: int) -> Path:
    """返回指定数量的核验进度检查点路径。"""
    return ROOT / "data" / f"youxiake_routes_checkpoint_{count}.json"


def load_candidate_checkpoint(
    path: Path,
    expected_count: int,
    source_page_url: str,
) -> list[dict[str, str]]:
    """读取候选检查点并拒绝复用不同采集条件的数据。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or payload.get("target_count") != expected_count:
        raise ValueError("候选检查点的目标数量与本次 count 不一致，请使用 --refresh-links")
    if payload.get("source_page_url") != source_page_url:
        raise ValueError("候选检查点的来源页面不一致，请使用 --refresh-links")
    if not isinstance(routes, list) or len(routes) < expected_count:
        actual = len(routes) if isinstance(routes, list) else 0
        raise ValueError(f"候选检查点至少需要 {expected_count} 条 routes，实际为 {actual}")
    selected = select_unique_routes(
        [{"name": str(item["name"]), "url": str(item["url"])} for item in routes],
        count=len(routes),
    )
    if len(selected) < expected_count:
        raise ValueError(
            f"候选检查点规范化后不足 {expected_count} 条，实际为 {len(selected)}"
        )
    return selected


def load_links(path: Path, expected_count: int) -> list[dict[str, str]]:
    """兼容调用方读取旧链接文件；新流水线使用带元数据的检查点。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not isinstance(routes, list) or len(routes) < expected_count:
        actual = len(routes) if isinstance(routes, list) else 0
        raise ValueError(f"链接文件至少包含 {expected_count} 条 routes，实际为 {actual}")
    return [{"name": str(item["name"]), "url": str(item["url"])} for item in routes]


def _json_from_model_text(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Qwen 返回的不是有效 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Qwen 必须返回 JSON 对象")
    return value


def is_eligible_product(product_name: str, detail_text: str) -> bool:
    """判断正文是否明确支持成都出发、单日及徒步三个条件。"""
    combined = re.sub(r"\s+", "", f"{product_name}\n{detail_text}")
    has_hiking = any(word in combined for word in HIKING_WORDS)
    has_chengdu_departure = any(
        re.search(pattern, combined) is not None
        for pattern in (
            r"成都(?:集合|出发|往返|统一出发|上车)",
            r"(?:集合地|出发地|出发城市)[：:]?成都",
        )
    )
    has_one_day = any(
        marker in combined
        for marker in ("一日", "1日", "1天", "当天往返", "当日往返", "当天返回", "当日返回")
    )
    has_multiple_days = re.search(r"(?:[2-9]|[二三四五六七八九十])(?:日|天)", combined) is not None
    return has_hiking and has_chengdu_departure and has_one_day and not has_multiple_days


def extract_site_route_fields(
    product_name: str,
    source_url: str,
    detail_text: str,
) -> dict[str, Any]:
    """从详情正文提取可锁定的路线事实。"""
    fields: dict[str, Any] = {
        "name": extract_route_name(product_name),
        "source_url": source_url,
        "source_name": "游侠客",
        "duration_days": 1,
        "transport_modes": ["group_tour"],
    }
    patterns: tuple[tuple[str, str, Callable[[str], Any]], ...] = (
        ("distance_km", r"(?:徒步(?:距离)?|往返|全程)[^\d]{0,12}(\d+(?:\.\d+)?)\s*(?:km|公里)", float),
        ("ascent_m", r"(?:累计)?爬升[^\d]{0,8}\+?(\d+)\s*(?:m|米)", int),
        ("highest_altitude_m", r"(?:最高海拔|最高点)[^\d]{0,8}(\d{3,4})\s*(?:m|米)", int),
        ("hiking_minutes", r"徒步[^\d]{0,10}(\d+(?:\.\d+)?)\s*(?:小时|h)", lambda value: round(float(value) * 60)),
    )
    for field, pattern, converter in patterns:
        match = re.search(pattern, detail_text, re.I)
        if match:
            fields[field] = converter(match.group(1))
    return fields


def merge_site_and_model(site: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """用网页非空事实覆盖模型值，其余字段由模型补全。"""
    merged = dict(model)
    for key, value in site.items():
        if value not in (None, "", []):
            merged[key] = value
    return merged


def build_prompt(
    short_name: str,
    product: dict[str, str],
    detail_text: str,
    site_fields: dict[str, Any] | None = None,
) -> str:
    """构造严格的联网补全提示词。"""
    return f"""你是户外路线数据核验员。根据游侠客详情正文和联网搜索，生成一条可导入的路线 JSON。
只返回 JSON，不要 Markdown。顶层必须恰好包含 route、costs、traffic。

产品标题：{product['name']}
确定的路线短名称：{short_name}
游侠客详情 URL：{product['url']}
详情正文：
{detail_text[:45000]}
网页已提取且不得覆盖的事实：
{json.dumps(site_fields or {}, ensure_ascii=False)}

约束：
1. 完全遵循 sample_routes_select.json 的字段、类型和枚举；所有字段必须出现且不得为 null。
2. 本产品已确认是成都出发一日徒步，duration_days 必须为 1。distance_km、ascent_m、海拔和徒步时间必须对应同一种走法。
3. route.id 使用小写英文 slug；route.name 固定为“{short_name}”或增加必要的走法后缀。
4. source_url 优先使用上面的游侠客详情 URL；联网补充必须使用真实可访问的直接来源 URL，禁止 example.org。
5. 交通时间以产品真实出发城市到徒步起点的单程公路交通为口径；无法证实的费用数组可为空，不得编造收费。
6. confidence 必须由证据决定。route.confidence 或 traffic.confidence 低于 0.8 表示证据不足，不得虚增。
7. reviewed=false，时间字段使用带时区的 ISO 8601。
8. route_type 只能是 loop/out_and_back/point_to_point；difficulty 只能是 easy/moderate/hard/expert。
9. transport_modes 只能包含 self_drive/public_transit/carpool/group_tour，且费用交通方式必须在其中。
10. is_traverse 与 point_to_point 一致；非穿越接驳为0，穿越接驳必须大于0。

必须逐字段填写的完整结构如下（字段不得减少，数组无可靠数据时可为空）：
{json.dumps(SCHEMA_TEMPLATE, ensure_ascii=False)}
"""


def prepare_detail_text(text: str, url: str) -> str:
    """允许短正文交给联网模型补充，但拒绝近乎空白的页面。"""
    normalized = text.strip()
    if len(normalized) < 20:
        raise RuntimeError(f"游侠客详情正文近乎为空，无法可靠补全: {url}")
    if len(normalized) < 200:
        return (
            "[详情页动态正文未完整渲染，以下仅为页面可见摘要。请使用产品标题、"
            f"活动URL及活动ID进行联网交叉检索。]\n{normalized}"
        )
    return normalized


def call_qwen(prompt: str, api_key: str) -> dict[str, Any]:
    """以思考模式流式调用开启联网检索的 qwen3.7-max。"""
    body = json.dumps(
        {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "enable_search": True,
            "enable_thinking": True,
            "stream": True,
            "temperature": 0.0,
            "max_tokens": 6000,
        },
        ensure_ascii=False,
    ).encode("utf-8")
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
            content_parts: list[str] = []
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                event_data = line[5:].strip()
                if event_data == "[DONE]":
                    break
                try:
                    event = json.loads(event_data)
                    if not isinstance(event, dict):
                        raise TypeError("事件根节点必须是对象")
                    if "error" in event:
                        raise RuntimeError(f"DashScope 流式响应错误: {event['error']}")
                    if event.get("code") and event.get("message"):
                        raise RuntimeError(
                            f"DashScope 流式响应错误 code={event['code']}: {event['message']}"
                        )
                    choices = event.get("choices")
                    if choices is None and "usage" in event:
                        continue
                    if not isinstance(choices, list):
                        raise TypeError("choices 必须是数组")
                    if not choices:
                        continue
                    for choice in choices:
                        if not isinstance(choice, dict):
                            raise TypeError("choices 每一项必须是对象")
                        delta = choice.get("delta")
                        if delta is None and choice.get("finish_reason") is not None:
                            continue
                        if not isinstance(delta, dict):
                            raise TypeError("choices.delta 必须是对象")
                        content = delta.get("content", "")
                        if isinstance(content, str) and content:
                            content_parts.append(content)
                except (KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(f"DashScope 流式响应格式无效: {exc}") from exc
        content = "".join(content_parts).strip()
        if not content:
            raise RuntimeError("DashScope 流式响应未返回正文")
        return _json_from_model_text(content)
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        detail = f"，响应={error_body[:1000]}" if error_body else ""
        raise RuntimeError(f"DashScope HTTP 请求失败 status={exc.code}{detail}") from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"DashScope 请求超时，超时配置为 {COLLECTOR_REQUEST_TIMEOUT_SECONDS} 秒: {exc}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DashScope 路线补全失败: {exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"DashScope 连接中断: {exc}") from exc


def finalize_item(
    item: dict[str, Any],
    short_name: str,
    source_url: str,
    site_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """锁定权威字段并执行严格校验。"""
    if not {"route", "costs", "traffic"} <= item.keys():
        raise ValueError("模型结果缺少 route、costs 或 traffic")
    if not all(isinstance(item[key], dict) for key in ("route", "costs", "traffic")):
        raise ValueError("route、costs 和 traffic 必须是对象")
    route = merge_site_and_model(site_fields or {}, item["route"])
    item["route"] = route
    route["name"] = short_name
    route["source_url"] = source_url
    route["reviewed"] = True
    now = datetime.now().astimezone().replace(microsecond=0).isoformat()
    route["collected_at"] = now
    route.setdefault("updated_at", now)
    if "group_tour" not in route.get("transport_modes", []):
        route.setdefault("transport_modes", []).append("group_tour")
    normalize_costs(item["costs"], route["transport_modes"])
    if route.get("duration_days") != 1:
        raise ValueError(f"路线 {short_name} 必须是单日路线")
    if route.get("difficulty") not in {"easy", "moderate", "hard", "expert"}:
        raise ValueError(f"路线 {short_name} 的 difficulty 无效")
    route_type = route.get("route_type")
    if route_type not in {"loop", "out_and_back", "point_to_point"}:
        raise ValueError(f"路线 {short_name} 的 route_type 无效")
    if route.get("is_traverse") != (route_type == "point_to_point"):
        raise ValueError(f"路线 {short_name} 的 is_traverse 与 route_type 不一致")
    if float(route.get("confidence", 0)) <= 0.8:
        raise ValueError(f"路线 {short_name} 置信度必须严格大于 0.8")
    if float(item["traffic"].get("confidence", 0)) <= 0.8:
        raise ValueError(f"路线 {short_name} 的交通置信度必须严格大于 0.8")
    validate_import_item(item)
    return item


def has_positive_hiking_distance(item: dict[str, Any]) -> bool:
    """判断核验结果是否包含严格大于零的徒步距离。"""
    try:
        return float(item["route"]["distance_km"]) > 0
    except (KeyError, TypeError, ValueError):
        return False


def keep_positive_hiking_routes(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """将有效徒步路线与应清理的非徒步活动分开。"""
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for item in items:
        target = kept if has_positive_hiking_distance(item) else removed
        target.append(item)
    return kept, removed


def _normalize_billing_unit(item: dict[str, Any]) -> None:
    value = str(item.get("billing_unit", "")).strip().lower()
    aliases = {
        "per_person": "person", "人": "person", "每人": "person",
        "per_vehicle": "vehicle", "车": "vehicle", "每车": "vehicle",
        "per_group": "group", "组": "group", "每组": "group",
    }
    value = aliases.get(value, value)
    if value not in BILLING_UNITS:
        value = "vehicle" if "停车" in str(item.get("name", "")) else "person"
    item["billing_unit"] = value


def normalize_costs(costs: dict[str, Any], route_modes: list[str]) -> None:
    """将模型的语义费用类型确定性映射为项目枚举。"""
    for item in costs.get("route_fees", []):
        name = str(item.get("name", ""))
        value = str(item.get("cost_type", "")).strip().lower()
        if value not in ROUTE_COST_TYPES:
            if "门票" in name or "ticket" in value:
                value = "ticket"
            elif "停车" in name or "parking" in value:
                value = "parking"
            elif any(word in name for word in ("中转", "摆渡", "景交")) or "shuttle" in value:
                value = "shuttle"
            elif any(word in name for word in ("卫生", "清洁", "垃圾")) or any(
                word in value for word in ("waste", "sanitation", "clean")
            ):
                value = "waste"
            else:
                value = "other"
        item["cost_type"] = value
        _normalize_billing_unit(item)

    mode_aliases = {
        "self-drive": "self_drive", "selfdrive": "self_drive", "自驾": "self_drive",
        "public": "public_transit", "公共交通": "public_transit",
        "拼车": "carpool", "tour": "group_tour", "跟团": "group_tour",
    }
    for item in costs.get("transport_options", []):
        name = str(item.get("name", ""))
        value = str(item.get("cost_type", "")).strip().lower()
        if value not in TRANSPORT_COST_TYPES:
            if "油" in name or "fuel" in value:
                value = "fuel"
            elif "过路" in name or "高速" in name or "toll" in value:
                value = "toll"
            elif any(word in name for word in ("火车", "动车", "高铁")) or "train" in value:
                value = "train"
            elif any(word in name for word in ("大巴", "巴士", "团费", "交通")) or "bus" in value:
                value = "bus"
            else:
                value = "other"
        item["cost_type"] = value
        _normalize_billing_unit(item)
        mode = str(item.get("transport_mode", "")).strip().lower()
        mode = mode_aliases.get(mode, mode)
        if mode not in route_modes:
            mode = "group_tour"
        item["transport_mode"] = mode


def generate_validated_item(
    prompt: str,
    short_name: str,
    source_url: str,
    qwen_caller: Callable[[str], dict[str, Any]],
    max_attempts: int = 3,
    site_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成并按精确校验错误让模型修复，直到通过或达到重试上限。"""
    current_prompt = prompt
    last_error: Exception | None = None
    previous_item: dict[str, Any] | None = None
    for attempt in range(1, max_attempts + 1):
        item = qwen_caller(current_prompt)
        previous_item = item
        try:
            return finalize_item(item, short_name, source_url, site_fields)
        except (TypeError, ValueError) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            current_prompt = f"""修复下面的路线 JSON。只返回修复后的完整 JSON 对象，不要解释。
必须保留已有可靠信息，并联网核实缺失字段；禁止删除字段或用 null、虚构 URL、虚增置信度规避校验。
路线名称：{short_name}
游侠客详情：{source_url}
校验错误：{exc}
完整字段骨架：{json.dumps(SCHEMA_TEMPLATE, ensure_ascii=False)}
待修复 JSON：{json.dumps(item, ensure_ascii=False)}
"""
    raise RuntimeError(
        f"路线 {short_name} 连续 {max_attempts} 次未通过校验: {last_error}; "
        f"最后结果={json.dumps(previous_item, ensure_ascii=False)[:1000]}"
    ) from last_error


class DetailFetcher:
    """在一个浏览器会话中依次读取游侠客详情。"""

    def __init__(
        self,
        timeout_seconds: int = COLLECTOR_BROWSER_TIMEOUT_SECONDS,
    ) -> None:
        from playwright.sync_api import sync_playwright

        self.timeout_ms = timeout_seconds * 1000
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._page = self._browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
        )

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._browser.close()
        with contextlib.suppress(Exception):
            self._playwright.stop()

    def fetch(self, url: str) -> str:
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            with contextlib.suppress(Exception):
                self._page.wait_for_load_state("networkidle", timeout=8000)
            self._page.wait_for_timeout(2500)
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._page.wait_for_timeout(1000)
            text = self._page.locator("body").inner_text(timeout=self.timeout_ms)
        except Exception as exc:
            raise RuntimeError(f"无法读取游侠客详情 {url}: {exc}") from exc
        if any(marker in text for marker in ("验证码", "安全验证")):
            raise RuntimeError(f"游侠客详情页出现验证码，已停止: {url}")
        return prepare_detail_text(text, url)


def normalize_source_url(url: str) -> str:
    """规范化通用来源 URL，以便执行稳定的增量匹配。"""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"来源 URL 无效: {url}")
    normalized_youxiake = normalize_route_link(url)
    if normalized_youxiake is not None:
        return normalized_youxiake[0]
    hostname = parsed.hostname.lower()
    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))


def validate_route_collection(items: list[dict[str, Any]]) -> None:
    """全量校验正式路线库的结构和唯一性。"""
    if not isinstance(items, list):
        raise ValueError("正式路线数据根节点必须是数组")
    ids: set[str] = set()
    urls: set[str] = set()
    for index, item in enumerate(items, 1):
        try:
            validate_import_item(item)
            route = item["route"]
            route_id = str(route.get("id", "")).strip()
            if not route_id:
                raise ValueError("route.id 不得为空")
            normalized_url = normalize_source_url(str(route.get("source_url", "")))
            if route_id in ids:
                raise ValueError(f"route.id 重复: {route_id}")
            if normalized_url in urls:
                raise ValueError(f"route.source_url 重复: {normalized_url}")
            ids.add(route_id)
            urls.add(normalized_url)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"第 {index} 条正式路线校验失败: {exc}") from exc


def merge_route_collections(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按来源 URL 优先、路线 ID 次优先更新，并保留未命中的旧路线。"""
    merged = json.loads(json.dumps(existing, ensure_ascii=False))
    url_to_index: dict[str, int] = {}
    id_to_index: dict[str, int] = {}
    for index, item in enumerate(merged):
        route = item["route"]
        route_id = str(route["id"])
        normalized_url = normalize_source_url(str(route["source_url"]))
        if route_id in id_to_index or normalized_url in url_to_index:
            raise ValueError("现有路线库包含重复 ID 或来源 URL，无法安全增量更新")
        id_to_index[route_id] = index
        url_to_index[normalized_url] = index

    seen_incoming_ids: set[str] = set()
    seen_incoming_urls: set[str] = set()
    for item in incoming:
        candidate = json.loads(json.dumps(item, ensure_ascii=False))
        route = candidate["route"]
        route["reviewed"] = True
        route_id = str(route["id"])
        normalized_url = normalize_source_url(str(route["source_url"]))
        if route_id in seen_incoming_ids or normalized_url in seen_incoming_urls:
            raise ValueError(f"本次路线存在重复身份: {route_id}")
        seen_incoming_ids.add(route_id)
        seen_incoming_urls.add(normalized_url)

        url_index = url_to_index.get(normalized_url)
        id_index = id_to_index.get(route_id)
        if url_index is not None and id_index is not None and url_index != id_index:
            raise ValueError(
                f"路线身份冲突：来源 URL 命中第 {url_index + 1} 条，ID 命中第 {id_index + 1} 条"
            )
        target_index = url_index if url_index is not None else id_index
        if target_index is None:
            target_index = len(merged)
            merged.append(candidate)
        else:
            old_route = merged[target_index]["route"]
            old_id = str(old_route["id"])
            old_url = normalize_source_url(str(old_route["source_url"]))
            if url_index is not None:
                route["id"] = old_id
            merged[target_index] = candidate
            id_to_index.pop(old_id, None)
            url_to_index.pop(old_url, None)
        id_to_index[str(route["id"])] = target_index
        url_to_index[normalized_url] = target_index

    validate_route_collection(merged)
    return merged


def _serialized_routes(items: list[dict[str, Any]]) -> str:
    validate_route_collection(items)
    return json.dumps(items, ensure_ascii=False, indent=2) + "\n"


def publish_route_files(
    items: list[dict[str, Any]],
    select_path: Path = SELECT_OUTPUT_PATH,
    runtime_path: Path = RUNTIME_OUTPUT_PATH,
) -> None:
    """校验后分别原子发布完全一致的候选文件和运行文件。"""
    content = _serialized_routes(items)
    temporary_paths: list[tuple[Path, Path]] = []
    for path in (select_path, runtime_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary_paths.append((temporary, path))
    for temporary, path in temporary_paths:
        temporary.replace(path)


def write_progress_checkpoint(
    path: Path,
    source_page_url: str,
    target_count: int,
    processed_count: int,
    items: list[dict[str, Any]],
) -> None:
    """原子保存核验进度，但不触碰正式路线文件。"""
    payload = {
        "source_page_url": source_page_url,
        "target_count": target_count,
        "processed_candidate_count": processed_count,
        "items": items,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_progress_checkpoint(
    path: Path,
    source_page_url: str,
    target_count: int,
) -> tuple[int, list[dict[str, Any]]]:
    """读取并校验核验进度检查点。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("核验检查点根节点必须是对象")
    if payload.get("source_page_url") != source_page_url:
        raise ValueError("核验检查点的来源页面不一致，请使用 --restart")
    if payload.get("target_count") != target_count:
        raise ValueError("核验检查点的目标数量不一致，请使用 --restart")
    processed_count = payload.get("processed_candidate_count")
    items = payload.get("items")
    if not isinstance(processed_count, int) or processed_count < 0 or not isinstance(items, list):
        raise ValueError("核验检查点格式无效")
    for item in items:
        validate_import_item(item)
    if len(items) > target_count:
        raise ValueError("核验检查点路线数量超过本次目标")
    return processed_count, items


def build_argument_parser() -> argparse.ArgumentParser:
    """构建统一流水线命令行参数。"""
    parser = argparse.ArgumentParser(description="抓取并核验游侠客路线，生成完整 JSON")
    parser.add_argument(
        "--count",
        type=int,
        required=True,
        help="需要采集的成都一日徒步路线数量（必填）",
    )
    parser.add_argument("--page-url", default=LIST_URL, help="游侠客筛选页 URL")
    parser.add_argument("--links-file", type=Path, help="第一阶段链接检查点路径")
    parser.add_argument("--checkpoint-file", type=Path, help="逐条核验进度检查点路径")
    parser.add_argument("--select-output", type=Path, default=SELECT_OUTPUT_PATH, help="合并后候选路线文件")
    parser.add_argument("--runtime-output", type=Path, default=RUNTIME_OUTPUT_PATH, help="应用运行路线文件")
    parser.add_argument("--refresh-links", action="store_true", help="忽略链接检查点并重新抓取")
    parser.add_argument("--restart", action="store_true", help="保留链接并从头重新核验")
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    if args.count <= 0:
        raise ValueError("count 必须为正整数")
    page_url = validate_page_url(args.page_url)
    links_path = args.links_file or default_links_path(args.count)
    checkpoint_path = args.checkpoint_file or default_checkpoint_path(args.count)

    if args.refresh_links or not links_path.exists():
        link_fetcher = RouteLinkFetcher(page_url=page_url)
        try:
            products = link_fetcher.fetch(args.count)
        finally:
            link_fetcher.close()
        write_links(links_path, products, args.count, page_url)
        print(f"第一阶段完成，已保存 {len(products)} 条候选名称和链接: {links_path}")
    else:
        products = load_candidate_checkpoint(links_path, args.count, page_url)
        print(f"检测到 {len(products)} 条候选检查点，将跳过列表抓取: {links_path}")

    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY")
    completed: list[dict[str, Any]] = []
    processed_count = 0
    if checkpoint_path.exists() and not args.restart and not args.refresh_links:
        processed_count, completed = load_progress_checkpoint(
            checkpoint_path, page_url, args.count
        )
        if processed_count > len(products):
            raise ValueError("核验检查点处理位置超过候选数量，请使用 --restart")
        print(
            f"检测到 {len(completed)} 条已校验路线，将从第 {processed_count + 1} 个候选继续"
        )

    if len(completed) < args.count:
        fetcher = DetailFetcher()
        try:
            for candidate_index in range(processed_count, len(products)):
                product = products[candidate_index]
                detail_text = fetcher.fetch(product["url"])
                next_processed_count = candidate_index + 1

                short_name = extract_route_name(product["name"])
                site_fields = extract_site_route_fields(
                    product["name"], product["url"], detail_text
                )
                print(f"[{len(completed) + 1}/{args.count}] 正在核验 {short_name}")
                item = generate_validated_item(
                    build_prompt(short_name, product, detail_text, site_fields),
                    short_name,
                    product["url"],
                    lambda prompt: call_qwen(prompt, api_key),
                    site_fields=site_fields,
                )
                if not has_positive_hiking_distance(item):
                    processed_count = next_processed_count
                    print(
                        f"跳过非徒步活动: {short_name} "
                        f"distance_km={item.get('route', {}).get('distance_km')!r}"
                    )
                    write_progress_checkpoint(
                        checkpoint_path,
                        page_url,
                        args.count,
                        processed_count,
                        completed,
                    )
                    continue
                item_id = str(item["route"]["id"])
                item_url = normalize_source_url(str(item["route"]["source_url"]))
                is_duplicate = any(
                    str(existing["route"]["id"]) == item_id
                    or normalize_source_url(str(existing["route"]["source_url"])) == item_url
                    for existing in completed
                )
                processed_count = next_processed_count
                if is_duplicate:
                    print(f"跳过重复路线: {short_name}")
                else:
                    completed.append(item)
                write_progress_checkpoint(
                    checkpoint_path, page_url, args.count, processed_count, completed
                )
                if len(completed) == args.count:
                    break
        finally:
            fetcher.close()

    if len(completed) != args.count:
        raise RuntimeError(
            f"符合成都出发一日徒步条件的路线不足 {args.count} 条，实际完成 {len(completed)} 条"
        )
    existing, removed_existing = keep_positive_hiking_routes(
        load_import_file(args.runtime_output)
    )
    for item in removed_existing:
        route = item.get("route", {})
        print(
            f"移除正式文件中的非徒步活动: {route.get('name', route.get('id'))} "
            f"distance_km={route.get('distance_km')!r}"
        )
    merged = merge_route_collections(existing, completed)
    publish_route_files(merged, args.select_output, args.runtime_output)
    print(
        f"流水线完成：本次核验 {args.count} 条，合并后共 {len(merged)} 条；"
        f"已同步 {args.select_output} 和 {args.runtime_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
