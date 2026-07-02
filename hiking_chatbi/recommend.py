from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from .costs import calculate_cost_estimates
from .traffic import LEVEL_RANK, TrafficProvider, estimate_traffic
from .weather import (
    AlertProvider,
    build_weather_alert_window,
    estimate_route_weather,
)


DIFFICULTY_RANK = {"easy": 0, "moderate": 1, "hard": 2, "expert": 3}
logger = logging.getLogger(__name__)


def _parse_datetime(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须为 ISO 8601 时间") from exc


def recommend(
    routes: list[dict[str, Any]],
    query: dict[str, Any],
    provider: TrafficProvider,
    alert_provider: AlertProvider,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    departure = _parse_datetime(query["departure_at"], "departure_at")
    latest_return = (
        _parse_datetime(query["latest_return_at"], "latest_return_at")
        if query.get("latest_return_at")
        else None
    )
    modes = set(query.get("transport_modes", []))
    scenery = set(query.get("scenery_preferences", []))
    tolerance = query.get("traffic_tolerance")
    tolerance_rank = LEVEL_RANK[tolerance] if tolerance else None
    party_size = query.get("party_size", 1)
    vehicle_count = query.get("vehicle_count", 1)
    results = []
    logger.info(
        "开始路线推荐 route_count=%s departure_at=%s",
        len(routes), departure.isoformat(),
    )

    for route in routes:
        reasons: list[str] = []
        if modes and not modes.intersection(route["transport_modes"]):
            continue
        matched_scenery = sorted(scenery.intersection(route["scenery"]))
        if scenery and not matched_scenery:
            continue
        if route["distance_km"] > query.get("max_distance_km", float("inf")):
            continue
        if route["ascent_m"] > query.get("max_ascent_m", float("inf")):
            continue
        cost_estimates = calculate_cost_estimates(
            route, modes, party_size, vehicle_count
        )
        if not cost_estimates:
            continue
        if not any(
            item["total_max_cny"] <= query.get("max_budget_cny", float("inf"))
            for item in cost_estimates
        ):
            continue
        if route["duration_days"] > query.get("max_duration_days", 1):
            continue
        max_difficulty = query.get("max_difficulty")
        if max_difficulty and DIFFICULTY_RANK[route["difficulty"]] > DIFFICULTY_RANK[max_difficulty]:
            continue

        outbound = estimate_traffic(
            route, query.get("origin", "成都"), departure, "outbound", provider, now,
            bool(query.get("is_holiday")),
        )
        if outbound["max_minutes"] > query.get("max_one_way_minutes", float("inf")):
            continue
        if (
            tolerance_rank is not None
            and LEVEL_RANK[outbound["congestion_level"]] > tolerance_rank
        ):
            continue

        hiking_start = departure + timedelta(minutes=outbound["max_minutes"])
        hiking_end = hiking_start + timedelta(minutes=route["hiking_minutes"])
        alert_start, alert_end = build_weather_alert_window(departure)
        weather = estimate_route_weather(
            route, alert_start, alert_end, alert_provider
        )
        if weather["is_filtered"]:
            logger.debug("路线因官方天气预警过滤 route_id=%s", route["id"])
            continue
        parking_transfer_minutes = (
            route["traverse_transfer_minutes"]
            if route["is_traverse"] and "self_drive" in modes
            else 0
        )
        return_departure = hiking_end + timedelta(
            minutes=60 + parking_transfer_minutes
        )
        return_traffic = estimate_traffic(
            route, route["start_location"], return_departure, "return", provider, now,
            bool(query.get("is_holiday")),
        )
        arrival = return_departure + timedelta(minutes=return_traffic["max_minutes"])
        if latest_return and arrival > latest_return:
            continue

        score = route["confidence"] * 30 + route["traffic_confidence"] * 10
        score += max(0, 25 - outbound["max_minutes"] / 12)
        score += len(matched_scenery) * 8
        score -= LEVEL_RANK[outbound["congestion_level"]] * 5
        score -= weather["score_penalty"]
        if matched_scenery:
            reasons.append(f"匹配风景偏好：{'、'.join(matched_scenery)}")
        reasons.append(
            f"预计单程 {outbound['min_minutes']}–{outbound['max_minutes']} 分钟"
        )
        reasons.append(
            f"徒步约 {route['distance_km']} 公里，爬升 {route['ascent_m']} 米"
        )
        results.append(
            {
                "route": {
                    key: route[key]
                    for key in (
                        "id", "name", "distance_km", "ascent_m", "highest_altitude_m",
                        "hiking_minutes", "difficulty", "duration_days", "is_traverse",
                        "traverse_transfer_minutes", "scenery",
                        "risks", "source_url",
                        "updated_at", "confidence",
                    )
                },
                "cost_estimates": cost_estimates,
                "score": round(score, 2),
                "reasons": reasons,
                "outbound_traffic": outbound,
                "return_traffic": return_traffic,
                "weather": weather,
                "suggested_departure_time": route["best_departure_time"],
                "suggested_return_time": route["suggested_return_time"],
                "estimated_parking_transfer_minutes": parking_transfer_minutes,
                "estimated_arrival_at": arrival.isoformat(timespec="minutes"),
                "estimated_total_minutes": round(
                    (arrival - departure).total_seconds() / 60
                ),
            }
        )
    sorted_results = sorted(results, key=lambda item: item["score"], reverse=True)
    logger.info("路线推荐计算完成 result_count=%s", len(sorted_results))
    return sorted_results
