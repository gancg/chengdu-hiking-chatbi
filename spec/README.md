# chengdu-hiking-chatbi 当前实现规格

## 1. 文档说明

本文档描述 `chengdu-hiking-chatbi` 当前 demo 版本已经实现的行为，是后续需求、测试和实现变更的基线。

- 当前实现日期：2026-06-11
- 事实来源：当前业务代码、数据库结构、样例数据和现有测试
- 变更原则：修改既有行为前先更新本规格，再补充或更新测试，最后修改实现

## 2. 产品范围

项目是一个成都周边徒步路线数据与推荐服务。当前版本提供：

- 保存并查询经过人工审核的结构化徒步路线
- 按用户约束筛选并排序路线
- 根据基础配置、历史规律、用户反馈或实时适配器估算交通情况
- 导入结构化路线及交通数据
- 记录用户实际出行反馈
- 通过 Qwen Agent 理解自然语言，并调用受控工具查询路线、推荐路线和估算交通

当前版本不提供：

- 通用 SQL 生成或任意数据库访问
- 独立业务 Web 前端或 BI 看板；Qwen Agent WebUI 仅用于初版演示
- 用户、权限和鉴权
- 真实地图或天气服务
- 自动采集、自动审核或数据发布

## 3. 技术与运行方式

### 3.1 技术组成

- Python 标准库
- SQLite
- `http.server.ThreadingHTTPServer`
- `unittest`
- 仓库内置的 `qwen_agent`
- DashScope SDK，用于调用 Qwen 模型
- 当前尚无依赖清单

### 3.2 命令行

```powershell
python -m hiking_chatbi init
python -m hiking_chatbi serve
python -m hiking_chatbi import data/sample_routes.json
python -m hiking_chatbi qwen-chat
python -m hiking_chatbi qwen-web
python -m hiking_chatbi qwen-h5
python -m hiking_chatbi app
```

- `init`：初始化数据库并导入样例数据。
- `serve`：启动 HTTP 服务；当审核通过的路线为空时，自动导入样例数据。
- `import <path>`：验证并导入指定 JSON 文件。
- `qwen-chat`：启动 Qwen Agent 终端连续对话。
- `qwen-web`：启动 Qwen Agent 自带的 WebUI 演示界面。
- `qwen-h5`：启动独立的移动端 H5 对话界面。
- `app`：一键启动后台 HTTP API、WebUI 和移动端 H5；H5 退出时自动关闭其余服务。

### 3.3 环境配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CHATBI_DB_PATH` | `data/chatbi.db` | SQLite 数据库路径 |
| `CHATBI_TRAFFIC_PROVIDER` | `none` | 交通适配器，可选 `none`、`mock` |
| `CHATBI_HOST` | `127.0.0.1` | HTTP 服务监听地址 |
| `CHATBI_PORT` | `8000` | HTTP 服务监听端口 |
| `CHATBI_WEB_HOST` | `127.0.0.1` | Qwen WebUI 监听地址 |
| `CHATBI_WEB_PORT` | `7860` | Qwen WebUI 监听端口 |
| `CHATBI_H5_HOST` | `127.0.0.1` | 移动端 H5 监听地址 |
| `CHATBI_H5_PORT` | `7861` | 移动端 H5 监听端口 |
| `DASHSCOPE_API_KEY` | 无 | Qwen Agent 调用 DashScope 所需密钥 |
| `CHATBI_QWEN_MODEL` | `qwen-plus` | Qwen Agent 使用的模型 |

除 `mock` 外的任意交通适配器名称当前都会使用 `none` 适配器。

本地前端联调推荐直接运行 `python -m hiking_chatbi app`。启动成功后：

- 后台 API：`http://127.0.0.1:8000`
- 前台 WebUI：`http://127.0.0.1:7860`
- 移动端 H5：`http://127.0.0.1:7861`

### 3.4 Qwen Agent ChatBI

Qwen Agent 负责理解用户自然语言、补充必要信息、选择工具并组织回答。业务结果必须来自以下受控工具：

| 工具 | 用途 |
| --- | --- |
| `list_hiking_routes` | 查询当前已审核路线及设施、风险、费用等信息 |
| `recommend_hiking_routes` | 将用户条件转换为结构化推荐请求并调用现有推荐服务 |
| `estimate_route_traffic` | 查询指定路线和出发时间的交通估算 |

Agent 不得直接生成或执行 SQL，不得修改路线、费用或反馈数据。工具返回完整 JSON，Agent 应保留关键推荐依据、费用范围、预计总耗时、交通数据类型和风险提示。

Agent 使用引导式需求访谈收集推荐条件：

1. 第 1–2 个用户轮次处于探索阶段，每次只询问一个容易回答且最有价值的问题，并简短回应用户已经表达的偏好。
2. 第 3 个用户轮次进入收敛阶段，确认仍会显著影响推荐结果的条件，不机械罗列缺失字段。
3. 第 4 个及后续用户轮次进入推荐阶段，信息基本可用时直接给出初步推荐，并明确说明采用的默认值或假设。
4. 用户明确要求立即推荐时，可跳过访谈阶段。
5. 用户已经提供足够条件时，应提前推荐，不得为了凑轮次继续追问。

前期访谈先确认具体出发时间，再了解体力或经验、距离、爬升、难度、风景和设施等路线筛选条件；前期不得主动询问或要求用户选择交通方式。形成符合用户预期的候选路线后，必须先让用户明确选择其中一条路线，不得在推荐候选路线的同一轮追加交通方式问题。用户选定路线后，下一轮再确认自驾、报团或公共交通，并补充交通、费用或最终方案比较。`recommend_hiking_routes` 至少需要 `departure_at`，形成候选路线时可以不传 `transport_modes`；仍缺少明确日期时，可先使用 `list_hiking_routes` 给出不含交通时效承诺的候选路线，并自然邀请用户补充日期，不得虚构日期。

## 4. 数据模型

### 4.1 路线 `routes`

| 字段 | 类型/范围 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 是 | 路线唯一标识 |
| `name` | string | 是 | 路线名称 |
| `group_tour_search_terms` | string[] | 否 | 人工审核的报团平台检索别名，最多 5 个；缺省时仅使用路线名称 |
| `start_location` | string | 是 | 起点 |
| `end_location` | string | 是 | 终点 |
| `latitude`、`longitude` | number/null | 否 | 起点坐标 |
| `distance_km` | number，`> 0` | 是 | 徒步距离 |
| `ascent_m` | integer，`>= 0` | 是 | 累计爬升 |
| `highest_altitude_m` | integer，`>= 0` | 是 | 最高海拔 |
| `hiking_minutes` | integer，`> 0` | 是 | 徒步预计时长 |
| `difficulty` | enum | 是 | `easy`、`moderate`、`hard`、`expert` |
| `duration_days` | integer，`> 0` | 是 | 行程天数 |
| `route_type` | string | 是 | 路线类型，当前样例包含 `loop`、`out_and_back` |
| `is_traverse` | boolean | 是 | 是否为起终点不同的穿越线 |
| `traverse_transfer_minutes` | integer，`>= 0` | 是 | 穿越线结束后打车或包车返回停车点的预估时长；非穿越线必须为 `0` |
| `best_seasons` | string[] | 是 | 推荐季节 |
| `scenery` | string[] | 是 | 风景标签 |
| `risks` | string[] | 是 | 风险提示 |
| `transport_modes` | enum[] | 是 | 可用交通方式，至少一项 |
| `has_toilet` | boolean | 是 | 路线沿途或起终点是否有可用卫生间 |
| `has_supply_shop` | boolean | 是 | 路线沿途或起终点是否有小卖部等补给购买点 |
| `parking`、`supplies`、`signal`、`camping` | string/null | 否 | 配套信息 |
| `source_url`、`source_name` | string | 是 | 路线数据来源 |
| `collected_at`、`updated_at` | ISO 8601 string | 是 | 采集和更新时间 |
| `confidence` | number，`0..1` | 是 | 路线数据置信度 |
| `reviewed` | boolean | 是 | 是否人工审核 |

交通方式枚举：

- `self_drive`
- `public_transit`
- `carpool`
- `group_tour`

对外路线列表和推荐仅使用 `reviewed = true` 的路线。

### 4.2 路线费用 `route_cost_items`

路线费用不再作为汇总字段保存在 `routes`，而是按收费项目保存。路线费用包括景区门票、中转车、垃圾处理等与到达方式无关的现场费用。

| 字段 | 类型/范围 | 说明 |
| --- | --- | --- |
| `route_id` | string | 关联路线 |
| `name` | string | 收费项目名称 |
| `cost_type` | enum | `ticket`、`shuttle`、`waste`、`parking`、`other` |
| `billing_unit` | enum | `person`、`vehicle`、`group` |
| `min_cny`、`max_cny` | number，`>= 0` | 完整行程费用范围 |
| `source_url`、`updated_at` | string | 数据来源与更新时间 |

`person` 表示按人数收费，`vehicle` 表示按车辆收费，`group` 表示整组行程只收取一次。

### 4.3 交通费用 `transport_cost_items`

交通费用按路线、交通方式和费用项目保存：

| 字段 | 类型/范围 | 说明 |
| --- | --- | --- |
| `route_id` | string | 关联路线 |
| `transport_mode` | enum | 必须是路线支持的交通方式 |
| `name` | string | 费用项目名称 |
| `cost_type` | enum | `fuel`、`toll`、`train`、`bus`、`other` |
| `billing_unit` | enum | `person`、`vehicle`、`group` |
| `min_cny`、`max_cny` | number，`>= 0` | 完整往返行程费用范围 |
| `source_url`、`updated_at` | string | 数据来源与更新时间 |

`person` 表示按人数收费，`vehicle` 表示按车辆数收费，`group` 表示整组行程只收取一次。

费用计算：

```text
路线费用 = 按人路线费用 * party_size
         + 按车路线费用 * vehicle_count
         + 按组路线费用
交通费用 = 按人交通费用 * party_size
         + 按车交通费用 * vehicle_count
         + 按组交通费用
行程总费用 = 路线费用 + 对应交通方式的交通费用
```

默认 `party_size = 1`、`vehicle_count = 1`。一条路线支持多种交通方式时，分别计算每种方式的总费用范围。

现有数据库中的 `routes.cost_min_cny` 和 `routes.cost_max_cny` 作为兼容字段暂时保留，但不再作为费用事实来源。删除兼容字段需要单独确认并执行数据库迁移。

### 4.4 交通画像 `traffic_profiles`

每条路线有且仅有一条交通画像：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `base_one_way_minutes` | integer | 基础单程时间 |
| `weekday_extra_min/max` | integer | 工作日额外时间范围 |
| `weekend_extra_min/max` | integer | 周末额外时间范围 |
| `holiday_extra_min/max` | integer | 节假日额外时间范围 |
| `morning_extra_minutes` | integer | 早高峰最大额外时间 |
| `evening_extra_minutes` | integer | 返程晚高峰最大额外时间 |
| `common_bottlenecks` | string[] | 常见拥堵点 |
| `best_departure_time` | string/null | 建议出发时间 |
| `suggested_return_time` | string/null | 建议返程时间 |
| `source_url`、`updated_at` | string | 数据来源与更新时间 |
| `confidence` | number，`0..1` | 交通数据置信度 |

### 4.5 行程反馈 `trip_feedback`

| 字段 | 类型/范围 | 说明 |
| --- | --- | --- |
| `route_id` | string | 必须关联已存在路线 |
| `traveled_at` | string | 实际出行时间 |
| `direction` | enum | `outbound` 或 `return` |
| `actual_minutes` | integer，`> 0` | 实际交通时间 |
| `congestion_level` | enum | `low`、`medium`、`high`、`severe` |
| `source` | string | 反馈来源 |
| `notes` | string/null | 备注 |
| `created_at` | ISO 8601 string | 服务记录时间 |

## 5. 数据导入

导入文件根节点必须是数组，每项必须包含 `route`、`costs` 和 `traffic`。`costs` 必须包含 `route_fees` 和 `transport_options` 数组。

导入流程：

1. 检查必填字段。
2. 验证难度、交通方式、置信度、费用项目和时间格式。
3. 以路线 `id` 为键写入或更新路线。
4. 替换该路线已有的路线费用与交通费用明细。
5. 同步写入或更新该路线的交通画像。

当前验证不覆盖所有数据库约束。例如导入层未主动验证距离、爬升、时长和交通额外时间是否为合理数值，最终可能由 SQLite 抛出错误。

样例数据包含 16 条已审核路线，覆盖不同难度、交通方式、设施条件、费用类型和穿越线场景。原始基线路线包括：

- 青城后山环线
- 赵公山西线
- 毕棚沟磐羊湖轻徒步

## 6. HTTP API

服务使用 JSON 请求与响应。请求体超过 `2,000,000` 字节时返回 `400`。

已捕获的 `ValueError`、`KeyError`、`TypeError` 和 JSON 解码错误返回：

```json
{
  "error": "明确的错误信息"
}
```

其他未捕获异常当前由 HTTP 服务直接处理。

### 6.1 `GET /health`

返回 `200`：

```json
{"status": "ok"}
```

### 6.2 `GET /routes`

返回 `200`：

```json
{"items": []}
```

只返回已审核路线。每项同时包含路线字段、交通画像字段、交通来源别名字段，以及反馈平均时长和反馈数量。

### 6.3 `POST /recommendations`

按用户约束推荐路线。`departure_at` 为唯一强制请求字段。

请求字段：

| 字段 | 默认值 | 行为 |
| --- | --- | --- |
| `departure_at` | 无 | 必填，ISO 8601 时间 |
| `origin` | `成都` | 出发地 |
| `transport_modes` | `[]` | 至少匹配一种交通方式；空数组不限制 |
| `max_distance_km` | 无穷大 | 最大徒步距离 |
| `max_ascent_m` | 无穷大 | 最大爬升 |
| `max_budget_cny` | 无穷大 | 至少一种候选交通方式的行程最高总费用不得超过该值 |
| `party_size` | `1` | 出行人数，必须为正整数 |
| `vehicle_count` | `1` | 车辆数，必须为正整数 |
| `max_one_way_minutes` | 无穷大 | 去程最大预计时间 |
| `max_duration_days` | `1` | 最大行程天数；默认只推荐单日往返路线 |
| `max_difficulty` | 不限制 | 最大难度 |
| `latest_return_at` | 不限制 | 最晚回到出发地时间 |
| `traffic_tolerance` | 不限制 | 显式提供时作为可接受的最高拥堵等级；未提供时只参与评分扣分，不硬过滤 |
| `scenery_preferences` | `[]` | 偏好风景标签，用于加分，不用于过滤 |
| `is_holiday` | `false` | 是否按节假日估算 |

响应：

```json
{
  "items": [
    {
      "route": {},
      "cost_estimates": [],
      "score": 0,
      "reasons": [],
      "outbound_traffic": {},
      "return_traffic": {},
      "suggested_departure_time": "06:30前",
      "suggested_return_time": "16:30前",
      "estimated_arrival_at": "2026-06-13T17:00+08:00",
      "estimated_total_minutes": 660
    }
  ]
}
```

推荐先执行硬约束过滤，再按分数降序排列。过滤条件包括交通方式、距离、爬升、预算、天数、难度、去程时长、显式提供的拥堵容忍度和最晚返回时间。未提供拥堵容忍度时，拥堵等级只用于评分扣分和结果展示，不作为硬过滤条件。

`cost_estimates` 返回候选交通方式各自的路线费用、交通费用和总费用范围。指定 `transport_modes` 时只计算其与路线支持方式的交集；未指定时计算路线支持的全部交通方式。预算过滤通过条件为至少一种候选交通方式的 `total_max_cny <= max_budget_cny`。

时间计算：

```text
徒步结束时间 = 出发时间 + 去程最大时间 + 徒步时间 + 60 分钟缓冲
停车点接驳时间 = 请求明确选择自驾且路线为穿越线时的 traverse_transfer_minutes，否则为 0
返程出发时间 = 徒步结束时间 + 停车点接驳时间
预计到达时间 = 返程出发时间 + 返程最大时间
```

推荐结果通过 `estimated_parking_transfer_minutes` 明确返回本次计算采用的停车点接驳时长。未指定 `transport_modes` 时，不假设用户自驾，不增加接驳时长。

评分公式：

```text
score =
  路线置信度 * 30
  + 交通置信度 * 10
  + max(0, 25 - 去程最大分钟数 / 12)
  + 匹配风景标签数 * 8
  - 去程拥堵等级序号 * 5
```

拥堵等级序号依次为 `low=0`、`medium=1`、`high=2`、`severe=3`。

### 6.4 `POST /traffic/estimate`

估算指定路线在指定时间的交通情况。

必填字段：

- `route_id`
- `departure_at`

可选字段：

- `origin`，默认 `成都`
- `direction`，默认 `outbound`
- `is_holiday`，默认 `false`

返回字段包括：

- `min_minutes`
- `max_minutes`
- `congestion_level`
- `bottlenecks`
- `data_type`
- `updated_at`
- `confidence`
- `fallback_reason`
- 历史估算还包括 `feedback_samples`

### 6.5 `POST /routes/import`

请求体可直接为导入项数组，也可为：

```json
{"items": []}
```

成功返回 `201`：

```json
{"imported": 3}
```

### 6.6 `POST /feedback/trips`

记录一次实际出行反馈。成功返回 `201`：

```json
{"id": 1}
```

当前服务层验证必填字段、路线存在性、方向和拥堵等级。`actual_minutes` 会转换为整数；其他格式和范围主要由 SQLite 约束。

### 6.7 未知接口

未匹配的 GET 或 POST 路径返回 `404`：

```json
{"error": "接口不存在"}
```

## 7. 交通估算规则

### 7.1 历史估算

1. `is_holiday = true` 时使用节假日额外时间。
2. 否则，星期六和星期日使用周末额外时间，其余使用工作日额外时间。
3. `07:00 <= 出发小时 < 10:00` 时：
   - 最小额外时间增加 `morning_extra_minutes // 2`
   - 最大额外时间增加 `morning_extra_minutes`
4. `direction = return` 且 `16:00 <= 出发小时 < 21:00` 时：
   - 最小额外时间增加 `evening_extra_minutes // 2`
   - 最大额外时间增加 `evening_extra_minutes`

最终交通时间为基础单程时间加额外时间。

拥堵等级由“最大额外时间 / 基础单程时间”决定：

| 比例 | 等级 |
| --- | --- |
| `>= 0.75` | `severe` |
| `>= 0.40` | `high` |
| `>= 0.15` | `medium` |
| `< 0.15` | `low` |

### 7.2 用户反馈修正

同一路线累计至少 3 条反馈且存在平均实际时间时，使用全部反馈的平均实际时间修正历史估算：

```text
观测额外时间 = max(0, round(反馈平均实际时间 - 基础单程时间))
修正额外时间 = round(原额外时间 * 0.7 + 观测额外时间 * 0.3)
```

此时 `data_type = historical_feedback`。

当前反馈聚合不区分方向、日期类型或出行时段。

### 7.3 实时估算与降级

当目标时间处于当前时间前 2 小时至后 24 小时之间时，服务尝试调用实时交通适配器。

- 适配器返回数据：使用实时结果，`data_type = realtime`，`confidence = 0.95`。
- 适配器无数据：降级到历史估算，并给出“实时交通服务未返回数据”原因。
- 适配器抛出异常：降级到历史估算，并给出“实时交通服务不可用”原因。
- 目标时间不在实时窗口：直接使用历史估算。

`none` 适配器总是无数据。`mock` 适配器提供确定性演示结果：

- `07:00–09:59` 或 `17:00–19:59`：`155–175` 分钟，`high`
- 其他时段：`125–145` 分钟，`medium`

## 8. 已验证行为

当前测试统一位于 `/test`，覆盖：

- 工作日、周末和节假日交通时间逐级增加
- 临近出发时使用实时交通适配器
- 实时交通无数据时明确降级到历史估算
- 推荐遵守距离、爬升、预算、交通方式和最晚返回时间约束
- 严重节假日拥堵可过滤全部路线
- 至少 3 条反馈后使用反馈修正历史估算

当前测试命令：

```powershell
python -m unittest discover -s test -v
```

按项目开发规范，全部测试统一放在 `/test`，文件名为 `test_*.py`。

## 9. 当前边界与已知风险

- 当前自然语言 Chat 主要用于路线咨询和推荐，尚无通用 BI 指标分析或可视化能力。
- HTTP 服务无鉴权、限流、CORS、分页和结构化访问日志。
- API 请求参数验证不完整，部分非法枚举或类型可能产生未捕获异常。
- `traffic_tolerance`、`max_difficulty` 等非法枚举会触发 `KeyError` 并返回 `400`。
- `direction` 在交通估算接口中未主动验证，非 `return` 值会按去程规则计算。
- 实时适配器异常会被降级处理，不向调用方暴露底层异常详情。
- 数据导入采用 upsert，不保留历史版本。
- 数据库无迁移机制。
- 用户反馈当前按路线整体平均，无法准确反映方向和时段差异。
- 样例来源 URL 为演示地址，不可作为真实路线依据。
- 徒步与交通估算仅用于 demo，不构成安全或出行保证。
- 多日游路线的住宿、跨日天气、补给和行程拆分尚未完整建模，后续补充（TODO）；默认推荐只覆盖单日往返路线。
