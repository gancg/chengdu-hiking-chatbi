# 单条徒步路线字段及中文解释

## 1. 用途

本文档依据 `data/sample_routes.json` 整理，用于指导 OpenManus 从公开网页采集一条徒步路线，并输出与项目样例一致的 JSON 数据。

单条路线记录包含三个一级对象：

| 字段 | 类型 | 中文解释 |
| --- | --- | --- |
| `route` | object | 路线本身的基础信息、徒步参数、设施、风险和来源信息。 |
| `costs` | object | 路线现场费用与不同交通方式的费用。 |
| `traffic` | object | 默认从成都出发时的单程交通耗时、拥堵增量和出行建议。 |

## 2. `route` 路线基础信息

| 字段 | 类型 | 单位/格式 | 中文解释及采集口径 |
| --- | --- | --- | --- |
| `id` | string | 小写英文 slug | 路线唯一标识。建议由地点和路线名组成，使用小写英文字母、数字及连字符，例如 `qingcheng-back-mountain`。 |
| `name` | string | — | 路线中文名称，应能区分具体走法，如“赵公山西线”，不只写景区名。 |
| `group_tour_search_terms` | string[] | — | 搜索跟团产品时使用的关键词和常见别名，例如 `["巴朗山", "巴郎山", "熊猫王国之巅"]`。 |
| `start_location` | string | — | 徒步起点的可识别位置，尽量写到区县、乡镇、村、停车场或地标。 |
| `end_location` | string | — | 徒步终点位置。往返线或环线可与起点相同，穿越线应填写实际终点。 |
| `latitude` | number | 十进制度 | 路线起点或主要目的地纬度，北纬为正数。 |
| `longitude` | number | 十进制度 | 路线起点或主要目的地经度，东经为正数。 |
| `distance_km` | number | 千米 | 徒步全程距离，不含成都往返车程。 |
| `ascent_m` | integer | 米 | 徒步累计爬升，不是起终点海拔差。 |
| `highest_altitude_m` | integer | 米 | 路线最高点海拔。 |
| `hiking_minutes` | integer | 分钟 | 通常情况下完成徒步部分所需时间，不含成都往返车程。小时需换算为分钟。 |
| `difficulty` | string | 枚举 | 难度：`easy`（简单）、`moderate`（中等）、`hard`（困难）、`expert`（专家级）。 |
| `duration_days` | integer | 天 | 完成整条路线通常需要的自然日数。 |
| `route_type` | string | 枚举 | 路线类型：`loop`（环线）、`out_and_back`（原路往返）、`point_to_point`（异地起终点/穿越线）。 |
| `is_traverse` | boolean | `true`/`false` | 是否为起终点不同、通常需要接驳的穿越路线。 |
| `traverse_transfer_minutes` | integer | 分钟 | 穿越路线起终点之间预计接驳耗时；非穿越路线填 `0`。 |
| `best_seasons` | string[] | 季节数组 | 适合徒步的季节，值使用 `春`、`夏`、`秋`、`冬`。 |
| `scenery` | string[] | — | 主要景观标签，例如森林、雪山、草甸、湖泊、瀑布。 |
| `risks` | string[] | — | 路线风险及限制，每项描述一种风险，例如高原反应、落石、临时交通管制。 |
| `transport_modes` | string[] | 枚举数组 | 可行交通方式：`self_drive`（自驾）、`public_transit`（公共交通）、`carpool`（拼车）、`group_tour`（跟团）。 |
| `parking` | string | — | 停车位置、容量、参考价格或限制；无可靠信息时明确写“未查到可靠信息”。 |
| `supplies` | string | — | 沿途和起终点的饮水、餐食、商店等补给情况。 |
| `has_toilet` | boolean | `true`/`false` | 路线起点、终点或途中是否有可用厕所。 |
| `has_supply_shop` | boolean | `true`/`false` | 路线起点、终点或途中是否有商店、农家乐等稳定补给点。 |
| `signal` | string | — | 手机信号覆盖情况，应指出弱信号或无信号路段。 |
| `camping` | string | — | 是否适合或允许露营，以及景区、保护区或属地管理限制。 |
| `source_url` | string | URL | 支撑路线主体信息的主要原始网页地址，不填写搜索结果页。 |
| `source_name` | string | — | 信息来源网站或机构名称；多来源核验时可写明交叉核对来源。 |
| `collected_at` | string | ISO 8601 | 本次采集时间，例如 `2026-07-01T14:00:00+08:00`。 |
| `updated_at` | string | ISO 8601 | 信息最后核验或更新时间；网页有发布日期时优先参考网页日期，否则使用采集核验时间。 |
| `confidence` | number | `0`～`1` | 路线信息可信度。多来源一致且来源权威时较高，单一游记或信息冲突时较低。 |
| `reviewed` | boolean | `true`/`false` | 是否已经人工审核。仅由 OpenManus 自动采集、尚未人工复核时填 `false`。 |

## 3. `costs` 费用信息

### 3.1 `route_fees` 路线现场费用

`costs.route_fees` 是数组。门票、停车费、中转车、清洁费等每种收费单独生成一项；确认免费时可使用空数组 `[]`。

| 字段 | 类型 | 单位/格式 | 中文解释及采集口径 |
| --- | --- | --- | --- |
| `name` | string | — | 费用中文名称，例如“景区门票”“停车费”“垃圾清理费”。 |
| `cost_type` | string | 枚举 | 费用类型：`ticket`（门票）、`parking`（停车）、`shuttle`（景区/当地中转）、`waste`（清洁或垃圾处理）、`other`（其他）。 |
| `billing_unit` | string | 枚举 | 计费单位：`person`（每人）、`vehicle`（每车）、`group`（每组/每队）。 |
| `min_cny` | number | 元人民币 | 最低或通常费用。固定价格时与 `max_cny` 相同。 |
| `max_cny` | number | 元人民币 | 最高费用。价格区间应保留上下限，不取平均数。 |
| `source_url` | string | URL | 直接支撑该费用的网页地址。 |
| `updated_at` | string | ISO 8601 | 该费用价格的最后核验时间。 |

### 3.2 `transport_options` 交通费用

`costs.transport_options` 是数组。每种交通方式或费用组成单独生成一项。样例中的费用通常按成都往返路线目的地计算。

| 字段 | 类型 | 单位/格式 | 中文解释及采集口径 |
| --- | --- | --- | --- |
| `transport_mode` | string | 枚举 | 交通方式：`self_drive`、`public_transit`、`carpool` 或 `group_tour`。 |
| `name` | string | — | 费用中文名称，例如“成都往返油费及过路费估算”“动车及公交往返费”。 |
| `cost_type` | string | 枚举 | 费用类型：`fuel`（油费）、`toll`（过路费）、`train`（火车/动车）、`bus`（巴士/团队交通）、`other`（拼车或合并估算等其他费用）。 |
| `billing_unit` | string | 枚举 | 计费单位：`person`、`vehicle` 或 `group`。 |
| `min_cny` | number | 元人民币 | 交通费用区间下限。 |
| `max_cny` | number | 元人民币 | 交通费用区间上限。 |
| `source_url` | string | URL | 支撑该交通费用或估算依据的网页地址。 |
| `updated_at` | string | ISO 8601 | 该交通费用的最后核验时间。 |

## 4. `traffic` 交通耗时与拥堵信息

除非另有说明，交通耗时以“成都市区到徒步起点的单程公路交通”为统一口径，不包含徒步时间。

| 字段 | 类型 | 单位/格式 | 中文解释及采集口径 |
| --- | --- | --- | --- |
| `base_one_way_minutes` | integer | 分钟 | 正常路况下从成都市区到徒步起点的单程基础耗时。 |
| `weekday_extra_min` | integer | 分钟 | 工作日常见额外拥堵时间下限。 |
| `weekday_extra_max` | integer | 分钟 | 工作日常见额外拥堵时间上限。 |
| `weekend_extra_min` | integer | 分钟 | 周末常见额外拥堵时间下限。 |
| `weekend_extra_max` | integer | 分钟 | 周末常见额外拥堵时间上限。 |
| `holiday_extra_min` | integer | 分钟 | 法定节假日常见额外拥堵时间下限。 |
| `holiday_extra_max` | integer | 分钟 | 法定节假日常见额外拥堵时间上限。 |
| `morning_extra_minutes` | integer | 分钟 | 早高峰或早晨集中出城时建议额外预留的时间。 |
| `evening_extra_minutes` | integer | 分钟 | 晚高峰或傍晚集中返程时建议额外预留的时间。 |
| `common_bottlenecks` | string[] | — | 常见拥堵或通行瓶颈，例如高速出口、城区道路、山区窄路、景区中转排队点。 |
| `best_departure_time` | string | — | 建议从成都出发或开始行程的时间，例如 `06:30前`、`前一日出发`。 |
| `suggested_return_time` | string | — | 建议从目的地返程的时间，例如 `16:30前`。 |
| `source_url` | string | URL | 支撑路程、路况或交通建议的来源网页地址。 |
| `updated_at` | string | ISO 8601 | 交通信息最后核验时间。 |
| `confidence` | number | `0`～`1` | 交通信息可信度。实时地图估算和多来源一致时较高，经验推断时应降低。 |

## 5. OpenManus 采集与输出规则

1. 一次只输出一条路线记录，JSON 顶层为对象，不要额外包裹数组。
2. 优先使用政府、景区、地图平台和交通运营方信息；户外俱乐部产品页、新闻和近期游记可用于补充并交叉核对。
3. 保留每类数据的直接来源 URL，不得使用搜索结果页、虚构链接或 `example.org` 示例链接。
4. 距离、累计爬升、海拔和耗时应确认是同一种具体走法的数据，不得把不同线路的数据拼在一起。
5. 网页出现价格或开放状态时，应检查发布日期和有效期；动态信息尽量使用近期来源。
6. 不能确认的数值不得凭空编造。若 OpenManus 必须严格按本结构输出，应将无法核实的字段设为 `null`，并在提交人工审核前补齐；不要用 `0` 代替未知值。
7. `min_cny`、`max_cny`、各类分钟数及经纬度只填写数字，不附带“元”“分钟”“公里”等文字。
8. 同一来源无法覆盖所有信息时可以使用多个来源；各费用项使用各自的 `source_url`。
9. 自动采集结果的 `reviewed` 固定为 `false`，待人工核验后再改为 `true`。

## 6. 单条路线 JSON 输出骨架

```json
{
  "route": {
    "id": null,
    "name": null,
    "group_tour_search_terms": [],
    "start_location": null,
    "end_location": null,
    "latitude": null,
    "longitude": null,
    "distance_km": null,
    "ascent_m": null,
    "highest_altitude_m": null,
    "hiking_minutes": null,
    "difficulty": null,
    "duration_days": null,
    "route_type": null,
    "is_traverse": null,
    "traverse_transfer_minutes": null,
    "best_seasons": [],
    "scenery": [],
    "risks": [],
    "transport_modes": [],
    "parking": null,
    "supplies": null,
    "has_toilet": null,
    "has_supply_shop": null,
    "signal": null,
    "camping": null,
    "source_url": null,
    "source_name": null,
    "collected_at": null,
    "updated_at": null,
    "confidence": null,
    "reviewed": false
  },
  "costs": {
    "route_fees": [
      {
        "name": null,
        "cost_type": null,
        "billing_unit": null,
        "min_cny": null,
        "max_cny": null,
        "source_url": null,
        "updated_at": null
      }
    ],
    "transport_options": [
      {
        "transport_mode": null,
        "name": null,
        "cost_type": null,
        "billing_unit": null,
        "min_cny": null,
        "max_cny": null,
        "source_url": null,
        "updated_at": null
      }
    ]
  },
  "traffic": {
    "base_one_way_minutes": null,
    "weekday_extra_min": null,
    "weekday_extra_max": null,
    "weekend_extra_min": null,
    "weekend_extra_max": null,
    "holiday_extra_min": null,
    "holiday_extra_max": null,
    "morning_extra_minutes": null,
    "evening_extra_minutes": null,
    "common_bottlenecks": [],
    "best_departure_time": null,
    "suggested_return_time": null,
    "source_url": null,
    "updated_at": null,
    "confidence": null
  }
}
```
