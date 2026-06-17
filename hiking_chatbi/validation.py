from __future__ import annotations

from datetime import datetime
from typing import Any


REQUIRED_ROUTE_FIELDS = {
    "id", "name", "start_location", "end_location", "distance_km", "ascent_m",
    "highest_altitude_m", "hiking_minutes", "difficulty", "duration_days",
    "route_type", "is_traverse", "traverse_transfer_minutes",
    "best_seasons", "scenery", "risks", "transport_modes",
    "has_toilet", "has_supply_shop",
    "source_url", "source_name", "collected_at",
    "updated_at", "confidence", "reviewed",
}
REQUIRED_TRAFFIC_FIELDS = {
    "base_one_way_minutes", "weekday_extra_min", "weekday_extra_max",
    "weekend_extra_min", "weekend_extra_max", "holiday_extra_min",
    "holiday_extra_max", "morning_extra_minutes", "evening_extra_minutes",
    "common_bottlenecks", "source_url", "updated_at", "confidence",
}
TRANSPORT_MODES = {"self_drive", "public_transit", "carpool", "group_tour"}
DIFFICULTIES = {"easy", "moderate", "hard", "expert"}
ROUTE_COST_TYPES = {"ticket", "shuttle", "waste", "parking", "other"}
TRANSPORT_COST_TYPES = {"fuel", "toll", "train", "bus", "other"}


def _require_fields(data: dict[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"{label} 缺少字段: {', '.join(missing)}")


def _parse_time(value: str, label: str) -> None:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须为 ISO 8601 时间") from exc


def validate_import_item(item: dict[str, Any]) -> None:
    if not isinstance(item, dict) or not {"route", "costs", "traffic"} <= item.keys():
        raise ValueError("每条数据必须包含 route、costs 和 traffic")
    route, costs, traffic = item["route"], item["costs"], item["traffic"]
    _require_fields(route, REQUIRED_ROUTE_FIELDS, "route")
    _require_fields(traffic, REQUIRED_TRAFFIC_FIELDS, "traffic")
    if route["difficulty"] not in DIFFICULTIES:
        raise ValueError("difficulty 无效")
    modes = set(route["transport_modes"])
    if not modes or not modes <= TRANSPORT_MODES:
        raise ValueError("transport_modes 无效")
    for field in ("has_toilet", "has_supply_shop"):
        if not isinstance(route[field], bool):
            raise ValueError(f"{field} 必须为布尔值")
    if not isinstance(route["is_traverse"], bool):
        raise ValueError("is_traverse 必须为布尔值")
    transfer_minutes = route["traverse_transfer_minutes"]
    if (
        isinstance(transfer_minutes, bool)
        or not isinstance(transfer_minutes, int)
        or transfer_minutes < 0
    ):
        raise ValueError("traverse_transfer_minutes 必须为非负整数")
    if route["is_traverse"] and transfer_minutes <= 0:
        raise ValueError("穿越线必须配置返回停车点接驳时长")
    if not route["is_traverse"] and transfer_minutes != 0:
        raise ValueError("非穿越线的返回停车点接驳时长必须为 0")
    if not 0 <= float(route["confidence"]) <= 1:
        raise ValueError("route confidence 必须在 0 到 1 之间")
    if not 0 <= float(traffic["confidence"]) <= 1:
        raise ValueError("traffic confidence 必须在 0 到 1 之间")
    _validate_costs(costs, modes)
    for field in ("collected_at", "updated_at"):
        _parse_time(route[field], f"route.{field}")
    _parse_time(traffic["updated_at"], "traffic.updated_at")


def _validate_costs(costs: dict[str, Any], route_modes: set[str]) -> None:
    if not isinstance(costs, dict) or not {"route_fees", "transport_options"} <= costs.keys():
        raise ValueError("costs 必须包含 route_fees 和 transport_options")
    for item in costs["route_fees"]:
        _validate_cost_item(
            item, ROUTE_COST_TYPES, {"person", "vehicle", "group"}, "route_fees"
        )
    for item in costs["transport_options"]:
        _validate_cost_item(
            item, TRANSPORT_COST_TYPES, {"person", "vehicle", "group"},
            "transport_options", is_transport=True,
        )
        if item["transport_mode"] not in route_modes:
            raise ValueError(f"路线不支持交通方式: {item['transport_mode']}")


def _validate_cost_item(
    item: dict[str, Any],
    cost_types: set[str],
    billing_units: set[str],
    label: str,
    is_transport: bool = False,
) -> None:
    required = {
        "name", "cost_type", "billing_unit", "min_cny", "max_cny",
        "source_url", "updated_at",
    }
    if is_transport:
        required.add("transport_mode")
    _require_fields(item, required, label)
    if item["cost_type"] not in cost_types:
        raise ValueError(f"{label}.cost_type 无效")
    if item["billing_unit"] not in billing_units:
        raise ValueError(f"{label}.billing_unit 无效")
    if float(item["min_cny"]) < 0 or float(item["max_cny"]) < float(item["min_cny"]):
        raise ValueError(f"{label} 费用范围无效")
    _parse_time(item["updated_at"], f"{label}.updated_at")
