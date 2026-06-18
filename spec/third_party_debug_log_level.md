# 第三方 Debug 日志级别规范

## 目标

- `CHATBI_LOG_LEVEL=DEBUG` 用于排查本项目业务逻辑和 SQL，不应默认放大第三方网络库的底层连接日志。
- Hugging Face、httpx、httpcore 等第三方库连接失败时，不应在默认 debug 模式下持续刷屏。
- 如确需排查第三方库，可通过单独环境变量显式打开。

## 行为

- 应用日志初始化后，默认将常见第三方库 logger 设置为 `WARNING`。
- 第三方库日志级别可通过 `CHATBI_THIRD_PARTY_LOG_LEVEL` 覆盖。
- 本项目 `hiking_chatbi` 下的 debug 日志不受第三方库日志级别影响。

## 验收标准

- `CHATBI_LOG_LEVEL=DEBUG` 时，根 logger 仍为 `DEBUG`。
- `CHATBI_LOG_LEVEL=DEBUG` 且未设置 `CHATBI_THIRD_PARTY_LOG_LEVEL` 时，`httpcore`、`httpx` 和 `huggingface_hub` logger 为 `WARNING`。
- 设置 `CHATBI_THIRD_PARTY_LOG_LEVEL=DEBUG` 时，可恢复第三方库 debug 日志。
