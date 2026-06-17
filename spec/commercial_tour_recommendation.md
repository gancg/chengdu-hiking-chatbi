# 商团产品推荐 Function

## 需求

新增只读 Qwen 工具 `recommend_commercial_tours`，用于根据已收录、已审核的商团产品数据，推荐适合报商团的一日徒步路线。

商团产品数据独立于路线数据保存，不嵌入路线导入结构。本功能不新增 HTTP API、不新增 CLI 命令、不抓取真实平台数据，也不写入用户数据。

## 商团产品数据

商团产品字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 商团产品唯一标识 |
| `route_id` | string | 关联已存在路线 |
| `provider_name` | string | 商团服务方名称 |
| `product_name` | string | 产品名称 |
| `departure_dates` | string[] | 可报名出发日期，ISO 8601 日期 |
| `meeting_point` | string | 集合点 |
| `price_min_cny` | number | 单人套餐最低价 |
| `price_max_cny` | number | 单人套餐最高价 |
| `included_services` | string[] | 已收录的包含服务 |
| `source_url` | string | 数据来源 |
| `updated_at` | string | 更新时间，ISO 8601 时间 |
| `reviewed` | boolean | 是否人工审核 |

价格口径为单人套餐价。按预算过滤时，使用 `party_size * price_max_cny` 判断总预算上限。

v1 不包含余位、成团状态、报名截止、退改规则、联系方式，也不承诺产品仍可报名。面向用户回答时必须提醒报名前二次确认。

## 工具参数

`recommend_commercial_tours` 支持：

- `departure_date`：可选，ISO 8601 日期；提供时只匹配当天团期。
- `route_id`：可选，限定某条路线。
- `party_size`：可选，默认 1，必须为正整数。
- `max_budget_cny`：可选，整组总预算上限。
- `max_distance_km`、`max_ascent_m`、`max_duration_days`、`max_difficulty`：可选，路线约束；`max_duration_days` 默认 1。
- `scenery_preferences`：可选，用于路线适配排序。

## 过滤与排序

- 仅返回已审核商团产品和已审核路线。
- 未提供 `departure_date` 时，只返回从当前日期起仍有未来团期的产品。
- 提供 `departure_date` 时严格匹配当天团期；当天无收录团期时返回空结果，不自行推荐邻近日期。
- 默认只推荐 `duration_days <= 1` 的路线；用户明确放宽 `max_duration_days` 时才返回多日产品。
- 排序按路线适配优先：匹配风景数、路线置信度、难度和天数，再按价格、最近团期、产品 ID 稳定排序。

## Qwen 回答边界

Agent 使用商团工具结果回答时：

- 商家、产品、集合点、价格、团期和包含服务必须来自工具结果。
- 不得编造未收录商家、余位、成团状态、报名截止、联系方式或报名链接。
- 必须说明商团产品为已收录信息，报名前仍需二次确认价格、团期、名额和安全要求。
- 需要展示商团的名称，这样方便用户去相应商团咨询详细信息，用户确认某个活动后，可以引导用户去该商团的小程序进行报名。
