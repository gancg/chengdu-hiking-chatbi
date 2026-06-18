from __future__ import annotations

import gzip
import json
import logging
import os
from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)


class AlertProvider(Protocol):
    def alerts(
        self, latitude: float, longitude: float, start_at: datetime, end_at: datetime
    ) -> list[dict[str, Any]] | None: ...

    def daily_weather(
        self, latitude: float, longitude: float, forecast_date: date
    ) -> dict[str, Any] | None: ...


class _TimedCache:
    def __init__(self, ttl: timedelta = timedelta(minutes=30)) -> None:
        self.ttl = ttl
        self.items: dict[tuple[Any, ...], tuple[datetime, Any]] = {}

    def get(self, key: tuple[Any, ...]) -> Any | None:
        cached = self.items.get(key)
        if not cached or datetime.now().astimezone() - cached[0] >= self.ttl:
            return None
        logger.debug("天气预警缓存命中 key=%s", key)
        return deepcopy(cached[1])

    def put(self, key: tuple[Any, ...], value: Any) -> None:
        self.items[key] = (datetime.now().astimezone(), deepcopy(value))


class NoAlertProvider:
    def alerts(
        self, latitude: float, longitude: float, start_at: datetime, end_at: datetime
    ) -> None:
        return None

    def daily_weather(
        self, latitude: float, longitude: float, forecast_date: date
    ) -> None:
        return None


class MockAlertProvider:
    def __init__(
        self,
        alerts: list[dict[str, Any]] | None = None,
        daily_weather: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.items = alerts or []
        self.error = error
        self.call_count = 0
        self.daily_weather_item = daily_weather
        self.daily_weather_call_count = 0

    def alerts(
        self, latitude: float, longitude: float, start_at: datetime, end_at: datetime
    ) -> list[dict[str, Any]]:
        self.call_count += 1
        if self.error:
            raise self.error
        return deepcopy(self.items)

    def daily_weather(
        self, latitude: float, longitude: float, forecast_date: date
    ) -> dict[str, Any] | None:
        self.daily_weather_call_count += 1
        if self.error:
            raise self.error
        return deepcopy(self.daily_weather_item)


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    logger.debug("开始请求外部天气预警服务 url=%s", url)
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=10) as response:
        body = response.read()
        content_encoding = (response.headers.get("Content-Encoding") or "").lower()
        if "gzip" in content_encoding or body.startswith(b"\x1f\x8b"):
            try:
                body = gzip.decompress(body)
            except gzip.BadGzipFile as exc:
                raise ValueError("外部天气预警服务返回了无效的 gzip 响应") from exc
        payload = json.loads(body.decode("utf-8"))
        logger.debug("和风天气返回数据: %s", payload)
        return payload


class QWeatherAlertProvider:
    """Fetch active official weather alerts aggregated by QWeather."""

    def __init__(self, api_key: str, api_host: str) -> None:
        self.api_key = api_key
        self.api_host = api_host.removeprefix("https://").removeprefix("http://").rstrip("/")
        self.cache = _TimedCache()

    def alerts(
        self, latitude: float, longitude: float, start_at: datetime, end_at: datetime
    ) -> list[dict[str, Any]]:
        request_latitude = round(latitude, 2)
        request_longitude = round(longitude, 2)
        key = (request_latitude, request_longitude)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        url = (
            f"https://{self.api_host}/weatheralert/v1/current/"
            f"{request_latitude}/{request_longitude}"
        )
        payload = _get_json(url, {"X-QW-Api-Key": self.api_key})
        result = []
        for item in payload.get("warning", payload.get("alerts", [])):
            color = item.get("color") or {}
            result.append({
                "title": item.get("title", item.get("headline", "天气预警")),
                "severity": _normalize_alert_severity(
                    item.get("severityColor", color.get("code", item.get("severity", "other")))
                ),
                "sender": item.get("senderName", item.get("sender", "未知发布机构")),
                "source": item.get("source", payload.get("source", "和风天气")),
                "start_at": item.get(
                    "startTime", item.get("effectiveTime", item.get("effective"))
                ),
                "end_at": item.get(
                    "endTime", item.get("expireTime", item.get("expires"))
                ),
                "description": item.get("text", item.get("description", "")),
            })
        self.cache.put(key, result)
        logger.info(
            "和风天气预警获取完成 latitude=%s longitude=%s alert_count=%s result=%s",
            latitude, longitude, len(result), result,
        )
        return result

    def daily_weather(
        self, latitude: float, longitude: float, forecast_date: date
    ) -> dict[str, Any] | None:
        forecast_days = _select_daily_weather_days(forecast_date)
        if forecast_days is None:
            return _unavailable_daily_weather(
                "出发日期超出和风天气30日预报范围", forecast_date
            )
        request_latitude = round(latitude, 2)
        request_longitude = round(longitude, 2)
        key = (f"daily_weather_{forecast_days}", request_latitude, request_longitude)
        cached = self.cache.get(key)
        if cached is None:
            query = urlencode({
                "location": f"{request_longitude},{request_latitude}",
                "lang": "zh",
                "unit": "m",
            })
            url = f"https://{self.api_host}/v7/weather/{forecast_days}?{query}"
            payload = _get_json(url, {"X-QW-Api-Key": self.api_key})
            cached = payload.get("daily", [])
            self.cache.put(key, cached)
        for item in cached:
            if item.get("fxDate") == forecast_date.isoformat():
                return _normalize_daily_weather(item, payload_source="和风天气每日天气预报")
        return _unavailable_daily_weather(
            f"出发日期不在和风天气{forecast_days}预报结果中", forecast_date
        )


def alert_provider_from_name(name: str) -> AlertProvider:
    if name == "qweather":
        api_key = os.getenv("QWEATHER_API_KEY", "").strip()
        api_host = os.getenv("QWEATHER_API_HOST", "n32k5q6wdt.re.qweatherapi.com").strip()
        if not api_key:
            logger.warning("缺少 QWEATHER_API_KEY，官方天气预警 Provider 未启用")
            return NoAlertProvider()
        if not api_host:
            logger.warning("缺少 QWEATHER_API_HOST，官方天气预警 Provider 未启用")
            return NoAlertProvider()
        return QWeatherAlertProvider(api_key, api_host)
    if name == "mock":
        return MockAlertProvider()
    logger.warning("官方天气预警 Provider 未启用 name=%s", name)
    return NoAlertProvider()


def _parse_at(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=fallback.tzinfo)


def _normalize_alert_severity(value: Any) -> str:
    text = str(value).lower()
    for severity, labels in {
        "red": ("red", "红"),
        "orange": ("orange", "橙"),
        "yellow": ("yellow", "黄"),
        "blue": ("blue", "蓝"),
    }.items():
        if any(label in text for label in labels):
            return severity
    return "other"


def _select_daily_weather_days(
    forecast_date: date,
    current_date: date | None = None,
) -> str | None:
    today = current_date or datetime.now().astimezone().date()
    days_ahead = (forecast_date - today).days + 1
    if days_ahead <= 0 or days_ahead > 30:
        return None
    for supported_days in (3, 7, 10, 15, 30):
        if days_ahead <= supported_days:
            return f"{supported_days}d"
    return None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_daily_weather(
    item: dict[str, Any],
    payload_source: str = "和风天气每日天气预报",
) -> dict[str, Any]:
    return {
        "is_available": True,
        "forecast_date": item.get("fxDate"),
        "temp_min_c": _optional_int(item.get("tempMin")),
        "temp_max_c": _optional_int(item.get("tempMax")),
        "text_day": item.get("textDay"),
        "text_night": item.get("textNight"),
        "precip_mm": _optional_float(item.get("precip")),
        "humidity_percent": _optional_int(item.get("humidity")),
        "wind_dir_day": item.get("windDirDay"),
        "wind_scale_day": item.get("windScaleDay"),
        "source": payload_source,
        "fallback_reason": None,
    }


def _unavailable_daily_weather(reason: str, forecast_date: date) -> dict[str, Any]:
    return {
        "is_available": False,
        "forecast_date": forecast_date.isoformat(),
        "temp_min_c": None,
        "temp_max_c": None,
        "text_day": None,
        "text_night": None,
        "precip_mm": None,
        "humidity_percent": None,
        "wind_dir_day": None,
        "wind_scale_day": None,
        "source": None,
        "fallback_reason": reason,
    }


def _alert_overlaps(alert: dict[str, Any], start_at: datetime, end_at: datetime) -> bool:
    alert_start = _parse_at(alert.get("start_at"), start_at)
    alert_end = _parse_at(alert.get("end_at"), end_at)
    return alert_start <= end_at and alert_end >= start_at


def build_weather_alert_window(departure_at: datetime) -> tuple[datetime, datetime]:
    """Build the conservative official-alert window for a departure date."""
    start_at = departure_at.replace(hour=8, minute=30, second=0, microsecond=0)
    end_at = departure_at.replace(hour=19, minute=0, second=0, microsecond=0)
    return start_at, end_at


def assess_route_alerts(
    route: dict[str, Any],
    hiking_start_at: datetime,
    hiking_end_at: datetime,
    alerts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess official alerts for a route's configured alert window."""
    relevant_alerts = [
        item for item in alerts if _alert_overlaps(item, hiking_start_at, hiking_end_at)
    ]
    is_filtered = False
    score_penalty = 0
    for alert in relevant_alerts:
        severity = _normalize_alert_severity(alert.get("severity"))
        if severity in {"red", "orange"}:
            is_filtered = True
        elif severity == "yellow":
            if route["difficulty"] in {"hard", "expert"}:
                is_filtered = True
            else:
                score_penalty = max(score_penalty, 18)
        else:
            score_penalty = max(score_penalty, 8)
    return {
        "hiking_start_at": hiking_start_at.isoformat(timespec="minutes"),
        "hiking_end_at": hiking_end_at.isoformat(timespec="minutes"),
        "score_penalty": score_penalty,
        "is_filtered": is_filtered,
        "official_alerts": relevant_alerts,
    }


def estimate_route_weather(
    route: dict[str, Any],
    hiking_start_at: datetime,
    hiking_end_at: datetime,
    alert_provider: AlertProvider,
) -> dict[str, Any]:
    """Fetch and assess route-start official alerts with explicit degradation."""
    latitude, longitude = route.get("latitude"), route.get("longitude")
    if latitude is None or longitude is None:
        raise ValueError("路线缺少起点经纬度，无法获取官方天气预警")
    fallback_reasons: list[str] = []
    data_sources: list[str] = []
    forecast_date = hiking_start_at.date()
    try:
        alerts = alert_provider.alerts(
            float(latitude), float(longitude), hiking_start_at, hiking_end_at
        )
        if alerts is None:
            alerts = []
            fallback_reasons.append("官方天气预警服务未配置或未返回数据")
            logger.debug("官方天气预警服务未配置或未返回数据 route_id=%s", route.get("id"))
        else:
            data_sources.append("和风天气官方预警聚合")
    except Exception as exc:
        alerts = []
        fallback_reasons.append(f"官方天气预警不可用：{exc}")
        logger.warning(
            "官方天气预警服务异常 route_id=%s error=%s",
            route.get("id"), exc, exc_info=True,
        )
    daily_weather = _unavailable_daily_weather(
        "每日天气预报服务未配置或未返回数据", forecast_date
    )
    try:
        forecast = alert_provider.daily_weather(
            float(latitude), float(longitude), forecast_date
        )
        if forecast is not None:
            daily_weather = forecast
            source = forecast.get("source")
            if source:
                data_sources.append(source)
        else:
            logger.debug("每日天气预报服务未配置或未返回数据 route_id=%s", route.get("id"))
    except Exception as exc:
        daily_weather = _unavailable_daily_weather(
            f"每日天气预报不可用：{exc}", forecast_date
        )
        logger.warning(
            "每日天气预报服务异常 route_id=%s error=%s",
            route.get("id"), exc, exc_info=True,
        )
    result = assess_route_alerts(route, hiking_start_at, hiking_end_at, alerts)
    result.update(
        data_sources=data_sources,
        fallback_reasons=fallback_reasons,
        location_scope="路线起点附近",
        daily_weather=daily_weather,
    )
    logger.info(
        "路线官方天气预警判断完成 route_id=%s filtered=%s alert_count=%s",
        route.get("id"), result["is_filtered"], len(result["official_alerts"]),
    )
    return result
