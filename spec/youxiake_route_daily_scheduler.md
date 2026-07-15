# 游侠客路线每日 Python 调度器

## 目标

提供不依赖操作系统计划任务的常驻 Python 进程，在每天指定的本地时间执行游侠客路线流水线，刷新指定数量的
成都一日徒步路线并增量更新 `data/sample_routes.json`，文件完整校验通过后再自动增量导入 `chatbi.db`。

## 行为

- 入口为 `python -m hiking_chatbi.youxiake_route_scheduler --time HH:MM --count N`。
- `--time` 使用运行机器的本地时区并要求 24 小时制；`--count` 必须为正整数。
- 每次执行当前 Python 解释器下的 `hiking_chatbi.youxiake_route_pipeline`，传入 `--count N --refresh-links`，
  确保每天重新读取网站而不是永久复用候选检查点。
- 流水线成功后完整读取并校验 `CHATBI_SAMPLE_DATA_PATH` 指定的路线文件，全部路线通过后才增量导入
  `CHATBI_DB_PATH` 指定的数据库；校验或导入失败时不得写入部分数据。
- 调度器单线程等待，单次流水线结束后才继续计算下一次运行时间，不允许同一进程内重叠执行。
- 单次返回非零状态或抛出异常时记录明确错误，但调度器继续等待下一天，不因一次失败退出。
- 支持 `--run-now` 在启动后立即执行一次，之后仍按每日时间运行。
- 默认日志写入 `data/youxiake_route_scheduler.log`，也可通过 `--log-file` 指定。
- 进程收到 Ctrl+C 时正常退出；调度器本身不负责后台守护，部署方需保证该 Python 进程持续运行。

## 错误处理

- 时间格式、路线数量或日志路径不可用时，在进入调度循环前抛出含义明确的中文异常。
- 日志不得记录 `DASHSCOPE_API_KEY` 等密钥，只记录计划时间、路线数量、子进程返回码和异常。

## Docker Compose 部署

- Compose 增加独立的 `route-scheduler` 常驻服务，与 `chatbi` 使用同一镜像并随 Compose 一起启动。
- 每日时间和条数分别由 `CHATBI_ROUTE_SCHEDULE_TIME`、`CHATBI_ROUTE_SCHEDULE_COUNT` 提供，示例默认值为
  `18:21` 和 `1`；Compose 将它们转换为调度器的 `--time` 与 `--count` 参数。
- 两个服务共同挂载 `chatbi-data:/app/data`，确保调度器更新的 `sample_routes.json` 对应用容器可见；首次创建
  命名卷时沿用镜像中的初始数据。
- 两个服务共同挂载 `chatbi-runtime:/app/runtime`，调度日志写入
  `/app/runtime/youxiake_route_scheduler.log`，并显式使用同一个 `/app/runtime/chatbi.db`，使文件校验通过后的
  路线能够被主应用立即读取。
- 调度服务禁用镜像中面向 HTTP API 的健康检查，并使用 `restart: unless-stopped` 自动恢复常驻进程。
