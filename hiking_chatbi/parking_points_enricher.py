from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import http.client
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import (
    COLLECTOR_MODEL,
    COLLECTOR_REQUEST_TIMEOUT_SECONDS,
    DASHSCOPE_CHAT_COMPLETIONS_URL,
    DB_PATH,
)
from .db import connect, initialize


logger = logging.getLogger(__name__)


def build_parking_prompt(routes: list[dict[str, Any]]) -> str:
    """Build a strict web-research prompt for parking candidates."""
    return f"""你是 qwen3.7-max 路线停车点资料核验助手。请联网搜索下面每条路线的停车点。

要求：
1. 每条输入路线必须在 routes 中返回一次；找不到可核验的具体停车点或精确坐标时，parking_points 返回空数组。
2. 不得把路线起点坐标当作停车点坐标，也不得仅根据停车概况或地点名称猜测坐标。
3. 停车点必须有具体名称、GCJ-02 经纬度、可直接访问的证据来源 URL；优先景区、政府、地图地点或路线来源页面。
4. note 说明收费、停车限制、换乘或步行到入口的信息；未知时为 null。
5. 每条路线最多返回 2 个停车点，最多一个 is_recommended=true；只有证据最充分且适合自驾到达的点才设为首选。
6. 只返回 JSON，不要 Markdown。结构必须为：
{{"routes":[{{"route_id":"...","parking_points":[{{"name":"...","latitude":30.0,"longitude":103.0,"note":null,"is_recommended":true,"source_url":"https://..."}}]}}]}}

路线数据：
{json.dumps(routes, ensure_ascii=False, separators=(',', ':'))}
"""


def call_qwen_parking_search(prompt: str, api_key: str) -> dict[str, Any]:
    """Call DashScope with web search enabled and return the JSON object."""
    body = json.dumps({
        "model": COLLECTOR_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "enable_search": True,
        "temperature": 0.0,
        "max_tokens": 5000,
        "response_format": {"type": "json_object"},
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        DASHSCOPE_CHAT_COMPLETIONS_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=COLLECTOR_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        result = json.loads(content)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DashScope 停车点查询失败: HTTP {exc.code} {detail}") from exc
    except (
        urllib.error.URLError,
        http.client.RemoteDisconnected,
        KeyError,
        IndexError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError(f"DashScope 停车点查询返回无效结果: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError("Qwen 停车点结果必须为 JSON 对象")
    return result


def normalize_parking_response(
    payload: dict[str, Any],
    expected_route_ids: set[str],
    updated_at: str,
) -> dict[str, list[dict[str, Any]]]:
    """Validate a model batch and force every candidate to remain unreviewed."""
    routes = payload.get("routes")
    if not isinstance(routes, list):
        raise ValueError("Qwen 停车点结果缺少 routes 数组")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for route_result in routes:
        if not isinstance(route_result, dict):
            raise ValueError("Qwen 路线停车结果必须为对象")
        route_id = str(route_result.get("route_id", "")).strip()
        if route_id not in expected_route_ids:
            raise ValueError(f"Qwen 返回未知路线: {route_id}")
        if route_id in normalized:
            raise ValueError(f"Qwen 重复返回路线: {route_id}")
        parking_points = route_result.get("parking_points")
        if not isinstance(parking_points, list):
            raise ValueError(f"路线 {route_id} 的 parking_points 必须为数组")
        if len(parking_points) > 2:
            raise ValueError(f"路线 {route_id} 最多返回 2 个停车点")
        names: set[str] = set()
        recommended_count = 0
        items: list[dict[str, Any]] = []
        for candidate in parking_points:
            if not isinstance(candidate, dict):
                raise ValueError(f"路线 {route_id} 的停车点必须为对象")
            name = str(candidate.get("name", "")).strip()
            if not name:
                raise ValueError(f"路线 {route_id} 的停车点名称不得为空")
            if name in names:
                raise ValueError(f"路线 {route_id} 的停车点名称不得重复")
            names.add(name)
            try:
                latitude = float(candidate["latitude"])
                longitude = float(candidate["longitude"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"路线 {route_id} 的停车点经纬度无效") from exc
            if not -90 <= latitude <= 90:
                raise ValueError(f"路线 {route_id} 的停车点纬度无效")
            if not -180 <= longitude <= 180:
                raise ValueError(f"路线 {route_id} 的停车点经度无效")
            is_recommended = candidate.get("is_recommended")
            if not isinstance(is_recommended, bool):
                raise ValueError(f"路线 {route_id} 的 is_recommended 必须为布尔值")
            recommended_count += int(is_recommended)
            source_url = str(candidate.get("source_url", "")).strip()
            if not source_url.startswith(("https://", "http://")):
                raise ValueError(f"路线 {route_id} 的停车点缺少有效来源 URL")
            note = candidate.get("note")
            if note is not None and not isinstance(note, str):
                raise ValueError(f"路线 {route_id} 的停车说明必须为字符串或 null")
            items.append({
                "name": name,
                "latitude": latitude,
                "longitude": longitude,
                "note": note,
                "is_recommended": is_recommended,
                "is_reviewed": False,
                "source_url": source_url,
                "updated_at": updated_at,
            })
        if recommended_count > 1:
            raise ValueError(f"路线 {route_id} 最多一个首选停车点")
        normalized[route_id] = items
    missing = expected_route_ids - normalized.keys()
    if missing:
        raise ValueError(f"Qwen 未返回路线: {', '.join(sorted(missing))}")
    return normalized


def replace_unreviewed_parking_points(
    connection: sqlite3.Connection,
    parking_points_by_route: dict[str, list[dict[str, Any]]],
) -> None:
    """Replace model candidates while preserving every manually reviewed row."""
    for route_id, parking_points in parking_points_by_route.items():
        connection.execute(
            "DELETE FROM route_parking_points WHERE route_id = ? AND is_reviewed = 0",
            (route_id,),
        )
        for item in parking_points:
            connection.execute(
                """INSERT OR IGNORE INTO route_parking_points
                (route_id,name,latitude,longitude,note,is_recommended,is_reviewed,source_url,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    route_id, item["name"], item["latitude"], item["longitude"],
                    item.get("note"), item["is_recommended"], False,
                    item["source_url"], item["updated_at"],
                ),
            )


def enrich_parking_points(
    db_path: Path,
    api_key: str,
    batch_size: int = 5,
    call_model: Callable[[str, str], dict[str, Any]] = call_qwen_parking_search,
) -> tuple[int, int, int]:
    """Research all routes and atomically replace their unreviewed candidates."""
    if not api_key.strip():
        raise ValueError("缺少 DASHSCOPE_API_KEY")
    if batch_size <= 0:
        raise ValueError("batch_size 必须为正整数")
    initialize(db_path)
    with closing(connect(db_path)) as connection:
        route_rows = connection.execute(
            """SELECT id,name,start_location,end_location,parking,latitude,longitude,source_url
               FROM routes ORDER BY id"""
        ).fetchall()
    routes = [dict(row) for row in route_rows]
    if not routes:
        raise ValueError("routes 表中没有可补全的路线")
    updated_at = datetime.now().astimezone().replace(microsecond=0).isoformat()
    all_results: dict[str, list[dict[str, Any]]] = {}
    for start in range(0, len(routes), batch_size):
        batch = routes[start:start + batch_size]
        route_ids = {str(route["id"]) for route in batch}
        logger.info("开始查询停车点 batch=%s route_ids=%s", start // batch_size + 1, sorted(route_ids))
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                payload = call_model(build_parking_prompt(batch), api_key)
                break
            except RuntimeError as exc:
                last_error = exc
                logger.warning(
                    "停车点查询失败，准备重试 batch=%s attempt=%s error=%s",
                    start // batch_size + 1,
                    attempt,
                    exc,
                )
                if attempt < 3:
                    time.sleep(2)
        else:
            raise RuntimeError(
                f"停车点批次查询连续失败: {last_error}"
            ) from last_error
        all_results.update(normalize_parking_response(payload, route_ids, updated_at))
    with closing(connect(db_path)) as connection:
        with connection:
            replace_unreviewed_parking_points(connection, all_results)
    point_count = sum(len(items) for items in all_results.values())
    empty_count = sum(not items for items in all_results.values())
    return len(routes), point_count, empty_count


def main() -> None:
    parser = argparse.ArgumentParser(description="使用 qwen3.7-max 联网补全路线停车点候选")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    route_count, point_count, empty_count = enrich_parking_points(
        args.db,
        os.getenv("DASHSCOPE_API_KEY", ""),
        args.batch_size,
    )
    logger.info(
        "停车点候选补全完成 route_count=%s point_count=%s empty_route_count=%s",
        route_count,
        point_count,
        empty_count,
    )


if __name__ == "__main__":
    main()
