# Qwen 运行一致性规范

## 目标

- VS Code debugger 与命令行 `python -m hiking_chatbi app` 使用同一套默认运行参数。
- 启动时输出关键运行配置，便于定位工作目录、数据库、模型或 provider 不一致的问题。
- Qwen 调用默认使用稳定 seed，减少同一问题在不同启动方式下因随机采样产生的回答差异。

## 配置

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `CHATBI_QWEN_SEED` | `42` | Qwen 生成 seed；设置为空字符串可恢复随机 seed |

## 行为

- `build_qwen_agent` 默认将 `CHATBI_QWEN_SEED` 写入 `generate_cfg.seed`。
- 启动命令记录有效的数据库路径、模型、provider、host、port 和 Python 可执行文件。
- 若 `CHATBI_QWEN_SEED` 为空字符串，则不传 seed，沿用 Qwen Agent 原有随机 seed 行为。

## 验收标准

- 默认构建 Qwen Agent 时，LLM 配置包含 `seed=42`。
- 设置 `CHATBI_QWEN_SEED=123` 时，LLM 配置包含 `seed=123`。
- 设置 `CHATBI_QWEN_SEED=""` 时，LLM 配置不包含 `seed`。
