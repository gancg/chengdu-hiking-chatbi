# 未指定拥堵容忍度时的推荐行为

## 背景

节假日路线推荐会根据 `is_holiday` 和出发时间估算拥堵等级。此前
`recommend_hiking_routes` 未收到 `traffic_tolerance` 时默认使用 `medium`，
导致用户未明确表示不能接受拥堵时，节假日候选路线可能被全部硬过滤。

## 需求

- 当请求未提供 `traffic_tolerance` 时，拥堵等级不得作为硬过滤条件。
- 未提供 `traffic_tolerance` 时，拥堵仍应参与评分扣分，并保留在推荐理由和交通结果中。
- 当请求显式提供 `traffic_tolerance` 时，仍按该等级进行硬过滤。
- `max_one_way_minutes` 仍独立作为去程时长硬过滤条件，不受本规则影响。

## 验收

- 节假日早高峰自驾路线即使估算为 `severe`，只要用户未显式限制拥堵等级，也应可返回。
- 同一条件下显式传入低于实际拥堵等级的 `traffic_tolerance`，仍应过滤该路线。
