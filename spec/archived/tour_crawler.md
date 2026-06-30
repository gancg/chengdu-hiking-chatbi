# 商团路线爬虫与定时入库

## 需求

新增可由外部调度调用的商团路线爬虫，用于从商团列表页抓取产品详情和路线草稿。v1 优先支持游侠客，暴走村、大鹅等来源只预留 provider 扩展点。

爬虫结果默认不直接进入推荐结果。商团产品和路线草稿入库时均为 `reviewed=false`，仍由现有推荐逻辑只读取已审核数据。

## 配置

爬虫通过 JSON 配置来源入口：

```json
{
  "sources": [
    {
      "provider": "youxiake",
      "list_urls": ["https://example.org/list"],
      "request_interval_seconds": 1,
      "keywords": ["成都", "徒步", "登山"]
    }
  ]
}
```

## 抓取与入库

- CLI：
  - `python -m hiking_chatbi crawl-tours --provider youxiake --config path/to/sources.json`
  - `python -m hiking_chatbi crawl-tours --all --config path/to/sources.json`
- provider 负责从列表页发现详情页，并从详情页抽取商团产品和路线草稿。
- 商团产品能完整抽取且能关联路线时，写入 `commercial_tour_products`，默认 `reviewed=false`。
- 路线名称使用模糊匹配关联已有路线；低置信度或无法匹配时进入候选表。
- 路线草稿只有在满足现有路线导入必填字段时才写入 `routes`，默认 `reviewed=false`。
- 缺少路线必填字段时，不使用默认值补齐，保存为候选，保留原始 URL、标题、抽取片段和缺失字段。

## 审计与删除

- `crawl_runs` 记录每次抓取批次、来源、开始/结束时间、状态和错误摘要。
- `crawl_events` 记录新增、更新、跳过、删除等事件。
- `crawl_candidates` 记录不能安全写入业务表的候选数据。
- 定时抓取中发现未审核商团产品已经从来源列表消失，或详情页无未来团期时，直接从业务表删除，并在 `crawl_events` 记录删除原因。

## 边界

- v1 不使用浏览器自动化，不处理必须登录、必须小程序授权或强动态渲染的数据。
- 遇到 403、验证码、登录页或页面结构无法识别时，记录失败，不绕过反爬。
- 外部定时由 Windows 任务计划程序或 cron 调用 CLI，应用内不启动后台循环任务。
