# 官方天气预警服务规范

## 目标与边界

- 可选使用和风天气 Weather Alert API 获取当前生效的官方天气预警聚合结果。
- 预警查询只使用路线起点经纬度，不代表整条路线沿途情况。
- 不为墨脱等特定地区增加单独的天气获取或坐标转换逻辑；第三方数据源可能无法返回部分地区的数据。
- 不提供逐小时天气和系统计算的天气风险，不保存历史预警，不新增数据库表，不接入地质灾害、封路等信息。

## 配置与数据源

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `CHATBI_ALERT_PROVIDER` | `none` | `qweather` 启用和风天气预警，`mock` 用于演示 |
| `QWEATHER_API_KEY` | 无 | 和风天气 API KEY |
| `QWEATHER_API_HOST` | 无 | 和风天气控制台中显示的项目专属 API Host |

启用和风天气时，`QWEATHER_API_KEY` 和 `QWEATHER_API_HOST` 均为必填项。不得使用
`devapi.qweather.com` 等公共 API Host 作为默认值；和风天气自 2026 年起逐步停止公共
API Host 服务，且 API Host 本身属于身份认证的一部分。

Provider 使用 `GET /weatheralert/v1/current/{latitude}/{longitude}`，通过
`X-QW-Api-Key` 请求头认证。请求路径中的经纬度最多保留两位小数。响应按当前接口的
`alerts`、`color.code`、`effectiveTime` 和 `expireTime` 字段解析。
和风天气响应可能使用 gzip 压缩；Provider 必须在 JSON 解码前识别并解压 gzip 正文。

和风天气只提供当前生效预警聚合，不提供逐小时天气。返回结果可能因地区覆盖、
坐标解析或当前无生效预警而为空；空结果不得解释为该地区没有天气风险。
预警结果应保留上游实际提供的发布机构、来源声明、严重级别、发布时间和有效期。

和风天气 Provider 使用 30 分钟内存缓存。服务重启后缓存清空。

## 预警处理规则

- 预警判断时段遵循 [天气预警查询时段规范](weather_alert_query_window.md)。
- 红色、橙色且系统判定与预警判断时段重叠的官方预警过滤所有路线。
- 系统判定与预警判断时段重叠的黄色预警过滤 `hard`、`expert` 路线；其他路线扣 18 分。
- 系统判定与预警判断时段重叠的蓝色及其他预警扣 8 分并提示。

## 接口契约

### `POST /weather/estimate`

请求：

```json
{
  "route_id": "qingcheng-back-mountain",
  "departure_at": "2026-06-13T06:00:00+08:00",
  "origin": "成都",
  "is_holiday": false
}
```

返回包含：

- `hiking_start_at`、`hiking_end_at`：用于判断预警是否重叠的安全覆盖时段；字段名为兼容保留。
- `score_penalty`、`is_filtered`：官方预警产生的扣分和过滤结果。
- `official_alerts`：和风天气返回且系统判定与徒步时段重叠的当前官方预警；可能为空。
- `data_sources`、`fallback_reasons`：数据来源及降级原因。

推荐结果增加同结构的 `weather` 字段。Qwen Agent 的
`estimate_route_weather` 工具参数与 HTTP 接口一致。

## 异常与降级

- 路线不存在或缺少起点经纬度时，抛出明确异常。
- 和风天气未配置或临时异常时继续推荐，并提示官方预警不可用。
- 和风天气成功返回空预警列表时，不视为服务异常，不增加降级原因；空列表不代表路线所在地没有天气风险。
- 和风天气无法覆盖墨脱等特定地区时，按预警数据源不可用处理，不调用地区专用兜底逻辑。

## 验收标准

- 系统判定与安全覆盖时段重叠的分级官方预警按规则过滤或扣分。
- 预警判断时段固定为出发日期当天 `08:30–19:00`。
- 和风天气服务异常不会被静默吞掉，推荐结果包含明确降级原因。
- 相同坐标在 30 分钟内不会重复请求和风天气服务。
- HTTP 接口、推荐结果及 Qwen Agent 工具均能返回官方预警信息。
