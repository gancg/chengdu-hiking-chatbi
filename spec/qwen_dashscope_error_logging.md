# Qwen DashScope 错误日志增强

## 目标

- 当 DashScope 模型调用失败时，日志应包含足够排查的信息。
- 错误日志不得记录 API Key、完整用户输入或完整模型上下文。
- 流式响应失败时，应能看出失败发生在第几个 chunk，以及失败前是否已经收到响应。

## 日志字段

每次 Qwen Agent 对话调用应生成本地 `call_id`，并在开始、完成和失败日志中记录：

- `call_id`
- `model`
- `message_count`
- `user_turns`
- `last_user_chars`
- `output_batches`
- `elapsed_ms`

对话调用失败时还应记录 `exception_type`、`exception_code` 和 `exception_message`，并保留完整堆栈。

DashScope 错误响应至少记录：

- `model`
- `stream`
- `delta_stream`
- `status_code`
- `code`
- `message`
- `request_id`
- `chunk_index`
- `received_chunks`

DashScope SDK 直接抛出异常时，至少记录：

- `model`
- `stream`
- `delta_stream`
- `message_count`
- `chunk_index`
- `received_chunks`
- `exception_type`
- `exception_message`

非流式响应没有 chunk 时，`chunk_index` 和 `received_chunks` 记录为 `n/a`。

## 异常处理

- DashScope SDK 调用本身抛出异常时，使用 `logger.exception` 保留堆栈，并显式记录异常类型和异常文本。
- DashScope 返回非 OK 状态时，先记录结构化错误日志，再抛出 `ModelServiceError`。
- 流式迭代过程中发生非 `ModelServiceError` 异常时，使用 `logger.exception` 记录 chunk 位置后继续抛出原异常。
- Agent 流式消费过程中发生异常时，使用 `logger.exception` 记录对话级调用信息后继续抛出原异常。

## 验收标准

- 测试无需访问真实 DashScope 服务。
- 非 OK 流式 chunk 会输出包含错误码、request_id 和 chunk 位置的日志。
- SDK 直接抛出的流式迭代异常会输出异常类型、异常文本和 chunk 位置。
- Agent 对话调用会输出可通过同一 `call_id` 关联的开始、完成或失败日志。
- 错误日志不输出完整 messages 内容。
