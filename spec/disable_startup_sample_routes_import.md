# 禁用启动时自动导入样例路线

## 目标

应用启动时只初始化数据库结构，不再自动将 `sample_routes.json` 导入或同步到数据库，避免启动过程覆盖数据库中已有的路线和关联数据。

## 行为

- `serve`、`qwen-chat`、`qwen-web`、`qwen-h5` 和 `app` 命令启动时不得调用样例路线导入。
- `ChatBIService` 初始化数据库表结构的行为保持不变。
- 显式执行 `python -m hiking_chatbi init` 时，仍按 `CHATBI_SAMPLE_DATA_PATH` 导入样例路线。
- 显式执行 `python -m hiking_chatbi import <path>` 的手工导入能力保持不变。
- Docker 镜像继续携带 `sample_routes.json`，供调度器、`init` 和手工操作使用；文件存在不代表应用启动时会自动导入。

## 验收标准

- 启动命令分发逻辑中，样例路线导入只存在于显式 `init` 分支。
- 启动已有数据库后，路线数据不会因 `sample_routes.json` 内容而被替换。
- 文档不再声明应用启动会自动同步样例路线。
