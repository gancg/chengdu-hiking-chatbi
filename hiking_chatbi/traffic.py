from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import logging
from typing import Protocol


LEVEL_RANK = {"low": 0, "medium": 1, "high": 2, "severe": 3}
logger = logging.getLogger(__name__)


@dataclass
class RealtimeTraffic:
    min_minutes: int
    max_minutes: int
    congestion_level: str
    bottlenecks: list[str]
    updated_at: str


class TrafficProvider(Protocol):
    def estimate(
        self, origin: str, destination: str, departure_at: datetime, direction: str
    ) -> RealtimeTraffic | None: ...


class NoTrafficProvider:
    def estimate(
        self, origin: str, destination: str, departure_at: datetime, direction: str
    ) -> None:
        return None


class MockTrafficProvider:
    """Deterministic local adapter for demos and contract tests."""

    def estimate(
        self, origin: str, destination: str, departure_at: datetime, direction: str
    ) -> RealtimeTraffic:
        peak = departure_at.hour in range(7, 10) or departure_at.hour in range(17, 20)
        duration = 155 if peak else 125
        return RealtimeTraffic(
            min_minutes=duration,
            max_minutes=duration + 20,
            congestion_level="high" if peak else "medium",
            bottlenecks=["地图服务返回的模拟拥堵路段"],
            updated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )


def provider_from_name(name: str) -> TrafficProvider:
    return MockTrafficProvider() if name == "mock" else NoTrafficProvider()


def _level(extra_max: int, base: int) -> str:
    ratio = extra_max / max(base, 1)
    if ratio >= 0.75:
        return "severe"
    if ratio >= 0.4:
        return "high"
    if ratio >= 0.15:
        return "medium"
    return "low"


def historical_estimate(
    route: dict, departure_at: datetime, direction: str, is_holiday: bool = False
) -> dict:
    if is_holiday:
        kind = "holiday"
    elif departure_at.weekday() >= 5:
        kind = "weekend"
    else:
        kind = "weekday"
    extra_min = route[f"{kind}_extra_min"]
    extra_max = route[f"{kind}_extra_max"]
    if 7 <= departure_at.hour < 10:
        extra_min += route["morning_extra_minutes"] // 2
        extra_max += route["morning_extra_minutes"]
    if direction == "return" and 16 <= departure_at.hour < 21:
        extra_min += route["evening_extra_minutes"] // 2
        extra_max += route["evening_extra_minutes"]
    base = route["base_one_way_minutes"]
    feedback_count = route.get("feedback_count") or 0
    if feedback_count >= 3 and route.get("feedback_avg_minutes"):
        observed_extra = max(0, round(route["feedback_avg_minutes"] - base))
        extra_min = round(extra_min * 0.7 + observed_extra * 0.3)
        extra_max = round(extra_max * 0.7 + observed_extra * 0.3)
    return {
        "min_minutes": base + extra_min,
        "max_minutes": base + extra_max,
        "congestion_level": _level(extra_max, base),
        "bottlenecks": route["common_bottlenecks"],
        "data_type": "historical_feedback" if feedback_count >= 3 else ("historical" if extra_max else "base"),
        "updated_at": route["traffic_updated_at"],
        "confidence": route["traffic_confidence"],
        "fallback_reason": None,
        "feedback_samples": feedback_count,
    }


def estimate_traffic(
    route: dict,
    origin: str,
    departure_at: datetime,
    direction: str,
    provider: TrafficProvider,
    now: datetime | None = None,
    is_holiday: bool = False,
) -> dict:
    historical = historical_estimate(route, departure_at, direction, is_holiday)
    current = now or datetime.now().astimezone()
    if departure_at.tzinfo is None:
        departure_at = departure_at.astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    delta = departure_at - current
    if timedelta(hours=-2) <= delta <= timedelta(hours=24):
        try:
            live = provider.estimate(
                origin, route["start_location"], departure_at, direction
            )
            if live:
                result = asdict(live)
                result.update(data_type="realtime", confidence=0.95, fallback_reason=None)
                return result
            historical["fallback_reason"] = "实时交通服务未返回数据，已使用历史估算"
            logger.debug(
                "实时交通服务未返回数据 route_id=%s direction=%s",
                route["id"], direction,
            )
        except Exception:
            logger.warning(
                "实时交通服务异常，已使用历史估算 route_id=%s direction=%s",
                route["id"], direction, exc_info=True,
            )
            historical["fallback_reason"] = "实时交通服务不可用，已使用历史估算"
    logger.info(
        "交通估算完成 route_id=%s direction=%s data_type=%s",
        route["id"], direction, historical["data_type"],
    )
    return historical
