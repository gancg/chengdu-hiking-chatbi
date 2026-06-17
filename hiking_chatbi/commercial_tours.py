from __future__ import annotations

from datetime import date, datetime
from typing import Any


DIFFICULTY_RANK = {"easy": 0, "moderate": 1, "hard": 2, "expert": 3}
REQUIRED_PRODUCT_FIELDS = {
    "id",
    "route_id",
    "provider_name",
    "product_name",
    "departure_dates",
    "meeting_point",
    "price_min_cny",
    "price_max_cny",
    "included_services",
    "source_url",
    "updated_at",
    "reviewed",
}


def _require_fields(data: dict[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"{label} 缺少字段: {', '.join(missing)}")


def _validate_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须为非空字符串")
    return value


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须为 ISO 8601 日期")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} 必须为 ISO 8601 日期") from exc


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须为 ISO 8601 时间")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} 必须为 ISO 8601 时间") from exc


def _validate_string_list(value: Any, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(f"{field} 必须为非空字符串数组")
    return value


def _validate_non_negative_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{field} 必须为非负数字")
    return float(value)


def _validate_positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} 必须为正整数")
    return value


def _money(value: float) -> int | float:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded


def validate_commercial_tour_product(item: dict[str, Any]) -> None:
    """Validate one reviewed commercial tour product record."""
    if not isinstance(item, dict):
        raise ValueError("商团产品必须为对象")
    _require_fields(item, REQUIRED_PRODUCT_FIELDS, "commercial_tour")
    for field in (
        "id",
        "route_id",
        "provider_name",
        "product_name",
        "meeting_point",
        "source_url",
    ):
        _validate_string(item[field], field)
    for departure_date in _validate_string_list(
        item["departure_dates"], "departure_dates"
    ):
        _parse_date(departure_date, "departure_dates")
    _validate_string_list(item["included_services"], "included_services")
    price_minimum = _validate_non_negative_number(
        item["price_min_cny"], "price_min_cny"
    )
    price_maximum = _validate_non_negative_number(
        item["price_max_cny"], "price_max_cny"
    )
    if price_maximum < price_minimum:
        raise ValueError("price_max_cny 必须大于或等于 price_min_cny")
    _parse_datetime(item["updated_at"], "updated_at")
    if not isinstance(item["reviewed"], bool):
        raise ValueError("reviewed 必须为布尔值")


def recommend_commercial_tours(
    routes: list[dict[str, Any]],
    products: list[dict[str, Any]],
    query: dict[str, Any],
    current_date: date | None = None,
) -> list[dict[str, Any]]:
    """Recommend reviewed commercial tour products using route constraints."""
    if not isinstance(query, dict):
        raise ValueError("商团推荐查询参数必须为对象")
    today = current_date or datetime.now().astimezone().date()
    party_size = _validate_positive_integer(query.get("party_size", 1), "party_size")
    max_duration_days = _validate_positive_integer(
        query.get("max_duration_days", 1), "max_duration_days"
    )
    departure = (
        _parse_date(query["departure_date"], "departure_date")
        if query.get("departure_date")
        else None
    )
    max_difficulty = query.get("max_difficulty")
    if max_difficulty and max_difficulty not in DIFFICULTY_RANK:
        raise ValueError("max_difficulty 无效")
    scenery_preferences = set(
        _validate_optional_string_list(
            query.get("scenery_preferences", []), "scenery_preferences"
        )
    )
    route_id = query.get("route_id")
    if route_id is not None:
        route_id = _validate_string(route_id, "route_id")
    max_distance_km = _optional_non_negative_limit(query, "max_distance_km")
    max_ascent_m = _optional_non_negative_limit(query, "max_ascent_m")
    max_budget = query.get("max_budget_cny")
    if max_budget is not None:
        max_budget = _validate_non_negative_number(max_budget, "max_budget_cny")

    reviewed_routes = {route["id"]: route for route in routes if route.get("reviewed", True)}
    results: list[dict[str, Any]] = []
    for product in products:
        if not product.get("reviewed"):
            continue
        route = reviewed_routes.get(product["route_id"])
        if not route:
            continue
        if route_id and product["route_id"] != route_id:
            continue
        if route["duration_days"] > max_duration_days:
            continue
        if route["distance_km"] > max_distance_km:
            continue
        if route["ascent_m"] > max_ascent_m:
            continue
        if max_difficulty and DIFFICULTY_RANK[route["difficulty"]] > DIFFICULTY_RANK[max_difficulty]:
            continue

        available_dates = _available_departure_dates(
            product["departure_dates"],
            today,
            departure,
        )
        if not available_dates:
            continue
        total_minimum = float(product["price_min_cny"]) * party_size
        total_maximum = float(product["price_max_cny"]) * party_size
        if max_budget is not None and total_maximum > max_budget:
            continue

        matched_scenery = sorted(scenery_preferences.intersection(route["scenery"]))
        score = route["confidence"] * 30
        score += len(matched_scenery) * 8
        score -= DIFFICULTY_RANK[route["difficulty"]] * 2
        score -= max(0, route["duration_days"] - 1) * 5
        results.append(
            {
                "product": {
                    "id": product["id"],
                    "provider_name": product["provider_name"],
                    "product_name": product["product_name"],
                    "meeting_point": product["meeting_point"],
                    "price_min_cny": _money(float(product["price_min_cny"])),
                    "price_max_cny": _money(float(product["price_max_cny"])),
                    "included_services": product["included_services"],
                    "source_url": product["source_url"],
                    "updated_at": product["updated_at"],
                    "reviewed": bool(product["reviewed"]),
                },
                "route": {
                    key: route[key]
                    for key in (
                        "id",
                        "name",
                        "distance_km",
                        "ascent_m",
                        "highest_altitude_m",
                        "hiking_minutes",
                        "difficulty",
                        "duration_days",
                        "scenery",
                        "risks",
                        "source_url",
                        "updated_at",
                        "confidence",
                    )
                },
                "available_departure_dates": available_dates,
                "party_size": party_size,
                "total_price_min_cny": _money(total_minimum),
                "total_price_max_cny": _money(total_maximum),
                "matched_scenery": matched_scenery,
                "reasons": _build_reasons(route, matched_scenery),
                "score": round(score, 2),
                "risk_notice": "商团产品为已收录信息，报名前仍需二次确认价格、团期、名额和安全要求。",
            }
        )
    return sorted(
        results,
        key=lambda item: (
            -item["score"],
            item["total_price_max_cny"],
            item["available_departure_dates"][0],
            item["product"]["id"],
        ),
    )


def _available_departure_dates(
    departure_dates: list[str],
    today: date,
    departure: date | None,
) -> list[str]:
    parsed = sorted(date.fromisoformat(item) for item in departure_dates)
    if departure:
        return [departure.isoformat()] if departure in parsed else []
    return [item.isoformat() for item in parsed if item >= today]


def _validate_optional_string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} 必须为字符串数组")
    for item in value:
        _validate_string(item, field)
    return value


def _optional_non_negative_limit(query: dict[str, Any], field: str) -> float:
    if field not in query or query[field] is None:
        return float("inf")
    return _validate_non_negative_number(query[field], field)


def _build_reasons(route: dict[str, Any], matched_scenery: list[str]) -> list[str]:
    reasons = [
        f"路线为 {route['duration_days']} 日行程",
        f"徒步约 {route['distance_km']} 公里，爬升 {route['ascent_m']} 米",
    ]
    if matched_scenery:
        reasons.append(f"匹配风景偏好：{'、'.join(matched_scenery)}")
    return reasons
