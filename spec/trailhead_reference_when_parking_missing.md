# 停车点缺失时返回徒步起点参考

## 目标

当已选路线在 `route_parking_points` 中没有已审核停车点时，向自驾用户提供路线表中的徒步起点，帮助用户继续导航，同时避免把徒步起点误认为停车场。

## 返回规则

- 先按既有逻辑查询 `route_parking_points`；存在数据时只返回真实停车点，不返回起点兜底。
- 查询结果为空时，停车点工具保持 `count=0`、`items=[]`，并增加 `trailhead_reference`。
- `trailhead_reference` 使用已审核路线的 `start_location`、`latitude`、`longitude` 生成导航链接。
- 兜底对象必须标记 `is_parking_point=false`、`reference_only=true`。
- 必须返回醒目提示：该位置仅为徒步起点参考，不代表可以停车，请以现场停车标识和交通管制为准。
- 起点坐标缺失时仍可返回起点名称，但不得编造坐标或导航链接。

## 展示规则

最终路线总结先明确“暂无已审核停车场信息”，再展示徒步起点参考及提示；不得使用“推荐停车场”称呼该起点。

