# Linux Docker 打包与 GitHub 自动构建

## 目标

项目应能在 Windows Docker Desktop 本地构建 `linux/amd64` 镜像，并在代码推送到
GitHub `main` 分支后自动测试、构建和发布同架构镜像到 GitHub Container Registry。

## 容器行为

- 镜像使用 Python 3.11，包含 `requirements.txt` 中的依赖、Chromium 及 Playwright
  运行库，保留游侠客浏览器采集能力。
- Qwen GUI 已有的关键传递依赖必须按兼容测试锁定版本，避免本地与 CI 解析出不同版本。
- 默认执行 `python -m hiking_chatbi app`，同时提供 8000 端口的 HTTP API 和 7860
  端口的 Qwen WebUI。
- API 与 WebUI 在容器中监听 `0.0.0.0`。
- SQLite 数据库默认写入 `/app/data/chatbi.db`；部署时挂载 `/app/data`，使数据
  不随容器删除而丢失。
- 容器通过 `GET http://127.0.0.1:8000/health` 检查健康状态。
- 除明确作为初始数据发布的 `data/chatbi.db` 外，其他本地数据库、`.env`、密钥、Git 元数据、
  虚拟环境、缓存和运行输出不得进入镜像。
- `DASHSCOPE_API_KEY`、`QWEATHER_API_KEY` 等敏感配置只允许在启动容器时注入。

## 本地运行

本地支持直接执行 `docker build --platform linux/amd64`，也支持使用 Compose 构建和
启动。Compose 应读取本地 `.env`，映射 8000、7860 端口并使用命名卷持久化运行数据。

## GitHub Actions

- 工作流在 `main` 分支 push 时触发，也允许手工触发。
- 构建前运行 `/test` 下的完整测试；任何测试失败都应显示异常并停止发布。
- 工作流仅申请 `contents: read` 和 `packages: write` 权限。
- 使用 Buildx 构建 `linux/amd64`，并推送到
  `ghcr.io/gancg/chengdu-hiking-chatbi`。
- 每次发布生成 `latest`、`main` 和 `sha-<短提交号>` 标签。
- 发布过程使用 GitHub 内置 `GITHUB_TOKEN`，不得在仓库中保存 Registry 凭据。

## 验收标准

- 打包配置测试能验证基础镜像、Playwright、端口、健康检查、持久化路径、默认命令、
  忽略规则及 Actions 的触发和发布标签。
- 构建后的容器能通过 `/health`，WebUI 可从宿主机访问。
- 删除并重建容器后，挂载卷内的 SQLite 数据仍然存在。
