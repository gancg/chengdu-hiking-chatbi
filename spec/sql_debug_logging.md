# SQL Debug 日志规范

## 目标

- 后台执行 SQLite SQL 语句时，在 debug 日志级别输出实际执行的 SQL，便于定位查询和写入问题。
- SQL 日志使用 Python 标准库 `logging`，不使用 `print`。
- 非 debug 日志级别默认不输出 SQL，避免正常运行时日志过多。

## 行为

- 数据库连接创建时，如果 `hiking_chatbi.db` logger 已启用 `DEBUG` 级别，则注册 SQLite trace callback。
- trace callback 记录 SQLite 实际执行的语句，包括事务语句、PRAGMA、SELECT、INSERT、UPDATE、DELETE 和建表语句。
- 日志消息格式为 `SQL: <statement>`。

## 验收标准

- `CHATBI_LOG_LEVEL=DEBUG` 或等效 debug 配置下，执行数据库语句会产生 `hiking_chatbi.db` 的 debug SQL 日志。
- 默认 `INFO` 级别下不输出 SQL trace 日志。
- SQL 日志测试不依赖真实外部服务。
