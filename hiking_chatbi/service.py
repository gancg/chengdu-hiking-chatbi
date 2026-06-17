from __future__ import annotations

from datetime import datetime
from contextlib import closing
import logging
from pathlib import Path
from typing import Any

from .db import connect, get_route, initialize, list_routes
from .importer import import_file
from .recommend import recommend
from .traffic import TrafficProvider, estimate_traffic
from .weather import (
    AlertProvider,
    NoAlertProvider,
    build_weather_alert_window,
    estimate_route_weather,
)
from .validation import validate_import_item
from .db import import_routes


logger = logging.getLogger(__name__)


class ChatBIService:
    def __init__(
        self,
        db_path: Path,
        provider: TrafficProvider,
        alert_provider: AlertProvider | None = None,
    ) -> None:
        self.db_path = db_path
        self.provider = provider
        self.alert_provider = alert_provider or NoAlertProvider()
        initialize(db_path)
        logger.info("ChatBIService 初始化完成 db_path=%s", db_path)

    def seed(self, sample_path: Path) -> int:
        count = import_file(self.db_path, sample_path)
        logger.info("样例路线初始化完成 count=%s", count)
        return count

    def routes(self) -> list[dict[str, Any]]:
        return list_routes(self.db_path)

    def recommendations(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        if "departure_at" not in query:
            raise ValueError("缺少 departure_at")
        results = recommend(
            self.routes(),
            query,
            self.provider,
            self.alert_provider,
        )
        logger.info(
            "路线推荐完成 departure_at=%s result_count=%s",
            query.get("departure_at"), len(results),
        )
        return results

    def traffic(self, query: dict[str, Any]) -> dict[str, Any]:
        for field in ("route_id", "departure_at"):
            if field not in query:
                raise ValueError(f"缺少 {field}")
        route = get_route(self.db_path, query["route_id"])
        if not route:
            raise ValueError("路线不存在")
        departure = datetime.fromisoformat(query["departure_at"])
        result = estimate_traffic(
            route, query.get("origin", "成都"), departure,
            query.get("direction", "outbound"), self.provider,
            is_holiday=bool(query.get("is_holiday")),
        )
        logger.info(
            "交通估算完成 route_id=%s data_type=%s",
            route["id"], result["data_type"],
        )
        return result

    def weather(self, query: dict[str, Any]) -> dict[str, Any]:
        for field in ("route_id", "departure_at"):
            if field not in query:
                raise ValueError(f"缺少 {field}")
        route = get_route(self.db_path, query["route_id"])
        if not route:
            raise ValueError("路线不存在")
        departure = datetime.fromisoformat(query["departure_at"])
        alert_start, alert_end = build_weather_alert_window(departure)
        result = estimate_route_weather(
            route,
            alert_start,
            alert_end,
            self.alert_provider,
        )
        logger.info(
            "官方天气预警判断完成 route_id=%s filtered=%s",
            route["id"], result["is_filtered"],
        )
        return result

    def import_items(self, items: list[dict[str, Any]]) -> int:
        for item in items:
            validate_import_item(item)
        count = import_routes(self.db_path, items)
        logger.info("路线数据导入完成 count=%s", count)
        return count

    def record_feedback(self, payload: dict[str, Any]) -> int:
        required = {"route_id", "traveled_at", "direction", "actual_minutes", "congestion_level", "source"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"缺少字段: {', '.join(sorted(missing))}")
        if not get_route(self.db_path, payload["route_id"]):
            raise ValueError("路线不存在")
        if payload["direction"] not in {"outbound", "return"}:
            raise ValueError("direction 无效")
        if payload["congestion_level"] not in {"low", "medium", "high", "severe"}:
            raise ValueError("congestion_level 无效")
        with closing(connect(self.db_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """INSERT INTO trip_feedback
                    (route_id,traveled_at,direction,actual_minutes,congestion_level,source,notes,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        payload["route_id"], payload["traveled_at"], payload["direction"],
                        int(payload["actual_minutes"]), payload["congestion_level"],
                        payload["source"], payload.get("notes"),
                        datetime.now().astimezone().isoformat(timespec="seconds"),
                    ),
                )
                feedback_id = int(cursor.lastrowid)
                logger.info(
                    "行程反馈记录完成 feedback_id=%s route_id=%s",
                    feedback_id, payload["route_id"],
                )
                return feedback_id
