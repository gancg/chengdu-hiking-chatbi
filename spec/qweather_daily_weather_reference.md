# 和风天气温度与天气现象参考

## 背景

现有天气能力只查询和风天气官方预警。路线推荐和天气查询需要在不替代预警安全判断的前提下，
额外返回出发日期的温度和简单天气现象，作为用户参考。

## 官方接口

- 和风天气实时天气接口 `/v7/weather/now` 可返回实时温度和天气现象文字。
- 和风天气每日天气预报接口 `/v7/weather/{days}` 可返回未来 3-30 天的最高/最低温度、白天/夜间天气现象文字。

## 本期实现

- 按出发日期和当前日期的间隔动态选择最小可覆盖接口：`3d`、`7d`、`10d`、`15d` 或 `30d`。
- `location` 使用路线起点经纬度，格式为 `longitude,latitude`。
- 返回与 `departure_at` 日期一致的一天，字段名为 `daily_weather`。
- `daily_weather` 只作为参考，不参与路线过滤或评分。
- 预警判断仍只使用官方预警结果，红橙黄蓝预警规则不变。
- 预报服务未配置、异常或出发日期不在 30 日预报范围内时，不抛出异常，应在 `daily_weather.fallback_reason` 中说明。

## 返回字段

`daily_weather` 包含：

- `is_available`：是否获取到出发日期天气。
- `forecast_date`：预报日期。
- `temp_min_c`、`temp_max_c`：最低/最高温度，摄氏度。
- `text_day`、`text_night`：白天/夜间天气现象。
- `precip_mm`：预报降水量，毫米，可能为空。
- `humidity_percent`：相对湿度百分比，可能为空。
- `wind_dir_day`、`wind_scale_day`：白天风向和风力等级，可能为空。
- `source`：数据来源说明。
- `fallback_reason`：不可用原因。
