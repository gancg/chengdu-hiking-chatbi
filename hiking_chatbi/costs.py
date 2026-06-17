from __future__ import annotations

from typing import Any, Iterable


def _validate_positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} 必须为正整数")
    return value


def _sum_costs(
    items: Iterable[dict[str, Any]],
    party_size: int,
    vehicle_count: int,
) -> tuple[float, float]:
    minimum = 0.0
    maximum = 0.0
    for item in items:
        multiplier = 1
        if item["billing_unit"] == "person":
            multiplier = party_size
        elif item["billing_unit"] == "vehicle":
            multiplier = vehicle_count
        minimum += float(item["min_cny"]) * multiplier
        maximum += float(item["max_cny"]) * multiplier
    return minimum, maximum


def _money(value: float) -> int | float:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded


def calculate_cost_estimates(
    route: dict[str, Any],
    transport_modes: set[str],
    party_size: int,
    vehicle_count: int,
) -> list[dict[str, Any]]:
    """Calculate full-trip cost ranges for each eligible transport mode."""
    party_size = _validate_positive_integer(party_size, "party_size")
    vehicle_count = _validate_positive_integer(vehicle_count, "vehicle_count")
    supported_modes = set(route["transport_modes"])
    candidate_modes = transport_modes & supported_modes if transport_modes else supported_modes
    route_minimum, route_maximum = _sum_costs(
        route.get("route_fees", []), party_size, vehicle_count
    )
    estimates = []
    for mode in sorted(candidate_modes):
        transport_items = [
            item for item in route.get("transport_options", [])
            if item["transport_mode"] == mode
        ]
        transport_minimum, transport_maximum = _sum_costs(
            transport_items, party_size, vehicle_count
        )
        estimates.append({
            "transport_mode": mode,
            "route_fee_min_cny": _money(route_minimum),
            "route_fee_max_cny": _money(route_maximum),
            "transport_min_cny": _money(transport_minimum),
            "transport_max_cny": _money(transport_maximum),
            "total_min_cny": _money(route_minimum + transport_minimum),
            "total_max_cny": _money(route_maximum + transport_maximum),
        })
    return estimates
