from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from hiking_chatbi.api import create_server
from hiking_chatbi.config import SAMPLE_DATA_PATH
from hiking_chatbi.service import ChatBIService
from hiking_chatbi.traffic import NoTrafficProvider
from hiking_chatbi.weather import (
    MockAlertProvider,
    NoAlertProvider,
    QWeatherAlertProvider,
    _get_json,
    _normalize_daily_weather,
    _select_daily_weather_days,
    alert_provider_from_name,
    assess_route_alerts,
    estimate_route_weather,
)


def future_departure(days: int = 1) -> datetime:
    return (datetime.now().astimezone() + timedelta(days=days)).replace(
        hour=6, minute=0, second=0, microsecond=0
    )


def official_alert(start_at: datetime, severity: str = "yellow") -> dict:
    return {
        "title": f"暴雨{severity}预警",
        "severity": severity,
        "sender": "测试气象台",
        "source": "和风天气",
        "start_at": start_at.isoformat(),
        "end_at": (start_at + timedelta(hours=2)).isoformat(),
    }


def daily_weather(forecast_date: datetime) -> dict:
    return {
        "is_available": True,
        "forecast_date": forecast_date.date().isoformat(),
        "temp_min_c": 18,
        "temp_max_c": 26,
        "text_day": "多云",
        "text_night": "小雨",
        "precip_mm": 2.5,
        "humidity_percent": 78,
        "wind_dir_day": "东风",
        "wind_scale_day": "1-2",
        "source": "和风天气每日天气预报",
        "fallback_reason": None,
    }


class AlertPolicyTest(unittest.TestCase):
    def test_official_alert_filters_by_severity_and_difficulty(self) -> None:
        """官方预警应按颜色和路线难度过滤或扣分。"""
        start = future_departure()
        alerts = [official_alert(start)]

        easy = assess_route_alerts(
            {"difficulty": "easy"}, start, start + timedelta(hours=1), alerts
        )
        hard = assess_route_alerts(
            {"difficulty": "hard"}, start, start + timedelta(hours=1), alerts
        )

        self.assertFalse(easy["is_filtered"], "简单路线遇黄色预警只应扣分")
        self.assertEqual(18, easy["score_penalty"], "黄色预警应扣十八分")
        self.assertTrue(hard["is_filtered"], "困难路线遇黄色预警应被过滤")

    def test_red_orange_and_blue_alert_policies(self) -> None:
        """红橙预警应过滤路线，蓝色预警应扣分并保留路线。"""
        start = future_departure()

        def assess(severity: str) -> dict:
            return assess_route_alerts(
                {"difficulty": "easy"},
                start,
                start + timedelta(hours=1),
                [official_alert(start, severity)],
            )

        self.assertTrue(assess("red")["is_filtered"], "红色预警必须过滤路线")
        self.assertTrue(assess("orange")["is_filtered"], "橙色预警必须过滤路线")
        blue = assess("blue")
        self.assertFalse(blue["is_filtered"], "蓝色预警不应过滤路线")
        self.assertEqual(8, blue["score_penalty"], "蓝色预警应扣八分")

    def test_alert_outside_hiking_window_is_ignored(self) -> None:
        """不与徒步时段重叠的官方预警不应影响路线。"""
        start = future_departure()
        alert = official_alert(start - timedelta(hours=4), "red")

        result = assess_route_alerts(
            {"difficulty": "easy"}, start, start + timedelta(hours=1), [alert]
        )

        self.assertFalse(result["is_filtered"], "过期预警不应过滤路线")
        self.assertEqual([], result["official_alerts"], "返回结果只应包含重叠预警")


class WeatherServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.departure = future_departure()
        self.alert_provider = MockAlertProvider([])
        self.service = ChatBIService(
            self.db_path,
            NoTrafficProvider(),
            self.alert_provider,
        )
        self.service.seed(SAMPLE_DATA_PATH)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_weather_estimate_uses_safe_daytime_window(self) -> None:
        """独立预警接口应使用当天八点半至十九点的安全覆盖时段。"""
        result = self.service.weather({
            "route_id": "qingcheng-back-mountain",
            "departure_at": self.departure.isoformat(),
        })

        self.assertEqual(
            self.departure.replace(hour=8, minute=30),
            datetime.fromisoformat(result["hiking_start_at"]),
            "预警判断开始时间应固定为当天八点半",
        )
        self.assertEqual(
            self.departure.replace(hour=19, minute=0),
            datetime.fromisoformat(result["hiking_end_at"]),
            "预警判断结束时间应固定为当天十九点",
        )

    def test_recommendation_contains_only_official_alert_result(self) -> None:
        """推荐结果应包含官方预警和每日天气参考，不应包含逐小时天气字段。"""
        results = self.service.recommendations({
            "departure_at": self.departure.isoformat(),
            "transport_modes": ["public_transit"],
            "max_distance_km": 13,
            "max_ascent_m": 800,
            "max_budget_cny": 120,
            "traffic_tolerance": "high",
        })

        self.assertEqual(1, len(results), "无官方预警时应保留青城后山路线")
        weather = results[0]["weather"]
        self.assertEqual([], weather["official_alerts"], "无预警时应返回空列表")
        self.assertIn("daily_weather", weather, "推荐结果应返回每日天气参考字段")
        for field in ("risk_level", "risk_reasons", "key_metrics", "hourly"):
            self.assertNotIn(field, weather, f"返回结果不应包含 {field}")

    def test_weather_estimate_returns_daily_weather_reference(self) -> None:
        """天气查询应返回出发日期的温度和简单天气现象作为参考。"""
        service = ChatBIService(
            self.db_path,
            NoTrafficProvider(),
            MockAlertProvider([], daily_weather(self.departure)),
        )

        result = service.weather({
            "route_id": "qingcheng-back-mountain",
            "departure_at": self.departure.isoformat(),
        })

        self.assertTrue(result["daily_weather"]["is_available"], "有预报时应标记为可用")
        self.assertEqual(18, result["daily_weather"]["temp_min_c"], "应返回最低温")
        self.assertEqual(26, result["daily_weather"]["temp_max_c"], "应返回最高温")
        self.assertEqual("多云", result["daily_weather"]["text_day"], "应返回白天天气现象")
        self.assertEqual("小雨", result["daily_weather"]["text_night"], "应返回夜间天气现象")

    def test_daily_weather_failure_does_not_block_alert_result(self) -> None:
        """每日天气预报异常不应影响官方预警判断主结果。"""
        service = ChatBIService(
            self.db_path,
            NoTrafficProvider(),
            MockAlertProvider(error=RuntimeError("天气预报超时")),
        )

        result = service.weather({
            "route_id": "qingcheng-back-mountain",
            "departure_at": self.departure.isoformat(),
        })

        self.assertIn("official_alerts", result, "预警判断结果仍应返回")
        self.assertFalse(result["daily_weather"]["is_available"], "预报异常时应标记为不可用")
        self.assertIn("天气预报超时", result["daily_weather"]["fallback_reason"])

    def test_red_alert_filters_route_from_recommendation(self) -> None:
        """与徒步时段重叠的红色官方预警应过滤推荐路线。"""
        alert_start = self.departure + timedelta(hours=2)
        service = ChatBIService(
            self.db_path,
            NoTrafficProvider(),
            MockAlertProvider([official_alert(alert_start, "red")]),
        )

        results = service.recommendations({
            "departure_at": self.departure.isoformat(),
            "transport_modes": ["public_transit"],
            "max_distance_km": 13,
            "max_ascent_m": 800,
            "max_budget_cny": 120,
            "traffic_tolerance": "high",
        })

        self.assertEqual([], results, "红色官方预警应过滤青城后山路线")

    def test_evening_red_alert_filters_route_from_recommendation(self) -> None:
        """预计徒步结束后但十九点前的红色预警仍应过滤推荐路线。"""
        alert_start = self.departure.replace(hour=18)
        service = ChatBIService(
            self.db_path,
            NoTrafficProvider(),
            MockAlertProvider([official_alert(alert_start, "red")]),
        )

        results = service.recommendations({
            "departure_at": self.departure.isoformat(),
            "transport_modes": ["public_transit"],
            "max_distance_km": 13,
            "max_ascent_m": 800,
            "max_budget_cny": 120,
            "traffic_tolerance": "high",
        })

        self.assertEqual([], results, "十九点前生效的红色预警应过滤青城后山路线")

    def test_missing_route_coordinates_raise_clear_error(self) -> None:
        """路线缺少起点经纬度时应抛出明确异常。"""
        start = future_departure()

        with self.assertRaisesRegex(ValueError, "缺少起点经纬度"):
            estimate_route_weather(
                {"id": "missing-location", "difficulty": "easy"},
                start,
                start + timedelta(hours=1),
                self.alert_provider,
            )

    def test_alert_provider_failure_continues_with_explicit_warning(self) -> None:
        """预警服务异常时应继续推荐并返回明确降级原因。"""
        service = ChatBIService(
            self.db_path,
            NoTrafficProvider(),
            MockAlertProvider(error=RuntimeError("预警服务超时")),
        )

        result = service.weather({
            "route_id": "qingcheng-back-mountain",
            "departure_at": self.departure.isoformat(),
        })

        self.assertEqual(1, len(result["fallback_reasons"]), "预警服务异常应明确说明")
        self.assertIn("预警服务超时", result["fallback_reasons"][0])

    def test_empty_alert_result_is_not_degradation(self) -> None:
        """和风天气成功返回空预警列表时不应记录降级原因。"""
        result = self.service.weather({
            "route_id": "qingcheng-back-mountain",
            "departure_at": self.departure.isoformat(),
        })

        self.assertEqual([], result["fallback_reasons"], "空预警列表不是服务异常")
        self.assertEqual(["和风天气官方预警聚合"], result["data_sources"])

    def test_alert_provider_records_single_request(self) -> None:
        """一次预警判断只能请求一次预警数据源。"""
        self.service.weather({
            "route_id": "qingcheng-back-mountain",
            "departure_at": self.departure.isoformat(),
        })

        self.assertEqual(1, self.alert_provider.call_count, "预警 Provider 应只调用一次")

    def test_http_weather_endpoint_returns_official_alert_result(self) -> None:
        """HTTP 天气接口应返回指定路线的官方预警判断结果。"""
        server = create_server(self.service, "127.0.0.1", 0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port)
            body = json.dumps({
                "route_id": "qingcheng-back-mountain",
                "departure_at": self.departure.isoformat(),
            })
            connection.request(
                "POST", "/weather/estimate", body,
                {"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(200, response.status, "天气接口应成功返回")
            self.assertIn("official_alerts", payload, "接口应返回官方预警列表")
            self.assertIn("daily_weather", payload, "接口应返回每日天气参考")
            self.assertNotIn("hourly", payload, "接口不应返回逐小时天气")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class AlertProviderCacheTest(unittest.TestCase):
    def test_get_json_decompresses_gzip_response(self) -> None:
        """外部天气服务返回 gzip 正文时应先解压再解析 JSON。"""
        response = unittest.mock.MagicMock()
        response.headers.get.return_value = "gzip"
        response.read.return_value = gzip.compress(
            json.dumps({"alerts": []}).encode("utf-8")
        )
        response.__enter__.return_value = response

        with patch("hiking_chatbi.weather.urlopen", return_value=response):
            payload = _get_json("https://example.qweatherapi.com/weatheralert")

        self.assertEqual({"alerts": []}, payload, "应正确解析 gzip 压缩的 JSON")

    def test_get_json_detects_gzip_body_without_response_header(self) -> None:
        """代理遗漏压缩响应头时仍应根据 gzip 正文特征完成解压。"""
        response = unittest.mock.MagicMock()
        response.headers.get.return_value = None
        response.read.return_value = gzip.compress(
            json.dumps({"alerts": []}).encode("utf-8")
        )
        response.__enter__.return_value = response

        with patch("hiking_chatbi.weather.urlopen", return_value=response):
            payload = _get_json("https://example.qweatherapi.com/weatheralert")

        self.assertEqual({"alerts": []}, payload, "应识别无响应头的 gzip 正文")

    def test_qweather_uses_current_api_request_and_response_fields(self) -> None:
        """和风天气 Provider 应按当前接口格式请求并解析预警。"""
        start = future_departure()
        provider = QWeatherAlertProvider("test-key", "example.qweatherapi.com")
        payload = {
            "alerts": [{
                "senderName": "都江堰市气象台",
                "headline": "暴雨蓝色预警",
                "color": {"code": "blue"},
                "effectiveTime": start.isoformat(),
                "expireTime": (start + timedelta(hours=2)).isoformat(),
                "description": "预计有强降雨",
            }],
        }

        with patch("hiking_chatbi.weather._get_json", return_value=payload) as get_json:
            alerts = provider.alerts(30.91234, 103.51234, start, start + timedelta(hours=1))

        get_json.assert_called_once_with(
            "https://example.qweatherapi.com/weatheralert/v1/current/30.91/103.51",
            {"X-QW-Api-Key": "test-key"},
        )
        self.assertEqual("blue", alerts[0]["severity"], "应解析当前接口的预警颜色")
        self.assertEqual(start.isoformat(), alerts[0]["start_at"], "应解析预警生效时间")
        self.assertEqual(
            (start + timedelta(hours=2)).isoformat(),
            alerts[0]["end_at"],
            "应解析预警失效时间",
        )

    def test_qweather_requires_project_api_host(self) -> None:
        """未配置项目专属 API Host 时不应请求已停用的公共 Host。"""
        with patch.dict(
            "os.environ",
            {"QWEATHER_API_KEY": "test-key", "QWEATHER_API_HOST": ""},
            clear=False,
        ):
            provider = alert_provider_from_name("qweather")

        self.assertIsInstance(provider, NoAlertProvider, "缺少项目专属 API Host 时应禁用 Provider")

    def test_qweather_reuses_thirty_minute_cache(self) -> None:
        """相同坐标应复用和风天气三十分钟内存缓存。"""
        start = future_departure()
        provider = QWeatherAlertProvider("test-key", "devapi.qweather.com")

        with patch("hiking_chatbi.weather._get_json", return_value={"warning": []}) as get_json:
            provider.alerts(30.9, 103.5, start, start + timedelta(hours=2))
            provider.alerts(30.9, 103.5, start, start + timedelta(hours=3))

        self.assertEqual(1, get_json.call_count, "三十分钟内不得重复请求和风天气")

    def test_normalize_daily_weather_keeps_temperature_and_weather_text(self) -> None:
        """每日天气预报解析应保留温度和天气现象文字。"""
        result = _normalize_daily_weather({
            "fxDate": "2026-06-19",
            "tempMin": "18",
            "tempMax": "26",
            "textDay": "多云",
            "textNight": "小雨",
            "precip": "2.5",
            "humidity": "78",
            "windDirDay": "东风",
            "windScaleDay": "1-2",
        })

        self.assertTrue(result["is_available"], "解析成功时应标记为可用")
        self.assertEqual(18, result["temp_min_c"], "最低温应转为整数")
        self.assertEqual(26, result["temp_max_c"], "最高温应转为整数")
        self.assertEqual("多云", result["text_day"], "应保留白天天气")
        self.assertEqual("小雨", result["text_night"], "应保留夜间天气")
        self.assertEqual(2.5, result["precip_mm"], "降水量应转为数字")

    def test_qweather_fetches_three_day_daily_weather_by_lon_lat(self) -> None:
        """和风天气 Provider 应按经度纬度查询三日天气预报并匹配出发日期。"""
        provider = QWeatherAlertProvider("test-key", "example.qweatherapi.com")
        forecast_date = datetime.now().astimezone().date()
        forecast_date = date.fromordinal(forecast_date.toordinal() + 1)
        payload = {
            "daily": [{
                "fxDate": forecast_date.isoformat(),
                "tempMin": "18",
                "tempMax": "26",
                "textDay": "多云",
                "textNight": "小雨",
                "precip": "2.5",
                "humidity": "78",
                "windDirDay": "东风",
                "windScaleDay": "1-2",
            }]
        }

        with patch("hiking_chatbi.weather._get_json", return_value=payload) as get_json:
            result = provider.daily_weather(30.91234, 103.51234, forecast_date)

        get_json.assert_called_once_with(
            "https://example.qweatherapi.com/v7/weather/3d?location=103.51%2C30.91&lang=zh&unit=m",
            {"X-QW-Api-Key": "test-key"},
        )
        self.assertIsNotNone(result, "三日预报中存在出发日期时应返回天气参考")
        self.assertEqual(18, result["temp_min_c"], "应解析最低温")
        self.assertEqual("多云", result["text_day"], "应解析白天天气现象")

    def test_select_daily_weather_days_uses_smallest_supported_window(self) -> None:
        """每日天气接口应按出发日期动态选择最小可覆盖预报天数。"""
        today = datetime.fromisoformat("2026-06-18T08:00:00+08:00").date()

        self.assertEqual("3d", _select_daily_weather_days(today, today), "当天应使用三日预报")
        self.assertEqual(
            "3d",
            _select_daily_weather_days(date.fromordinal(today.toordinal() + 2), today),
            "后天仍应使用三日预报",
        )
        self.assertEqual(
            "7d",
            _select_daily_weather_days(date.fromordinal(today.toordinal() + 4), today),
            "四天后应切换到七日预报",
        )
        self.assertEqual(
            "30d",
            _select_daily_weather_days(date.fromordinal(today.toordinal() + 29), today),
            "三十日范围内应使用三十日预报",
        )
        self.assertIsNone(
            _select_daily_weather_days(date.fromordinal(today.toordinal() + 30), today),
            "超出三十日预报范围时不应请求和风天气",
        )

    def test_qweather_fetches_seven_day_weather_for_departure_four_days_later(self) -> None:
        """出发日期超过三日窗口时应动态切换到七日天气接口。"""
        provider = QWeatherAlertProvider("test-key", "example.qweatherapi.com")
        forecast_date = datetime.now().astimezone().date()
        forecast_date = date.fromordinal(forecast_date.toordinal() + 4)
        payload = {
            "daily": [{
                "fxDate": forecast_date.isoformat(),
                "tempMin": "18",
                "tempMax": "26",
                "textDay": "多云",
                "textNight": "小雨",
            }]
        }

        with patch("hiking_chatbi.weather._get_json", return_value=payload) as get_json:
            result = provider.daily_weather(30.91234, 103.51234, forecast_date)

        self.assertIn("/v7/weather/7d?", get_json.call_args.args[0], "四天后应请求七日天气")
        self.assertIsNotNone(result, "七日预报覆盖出发日期时应返回天气参考")

    def test_qweather_does_not_request_weather_beyond_thirty_days(self) -> None:
        """出发日期超过三十日预报范围时应直接返回不可用原因。"""
        provider = QWeatherAlertProvider("test-key", "example.qweatherapi.com")
        forecast_date = datetime.now().astimezone().date()
        forecast_date = date.fromordinal(forecast_date.toordinal() + 30)

        with patch("hiking_chatbi.weather._get_json") as get_json:
            result = provider.daily_weather(30.91234, 103.51234, forecast_date)

        get_json.assert_not_called()
        self.assertFalse(result["is_available"], "超出三十日范围时应标记为不可用")
        self.assertIn("30日预报范围", result["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
