# Docker 时区配置

## 需求

- Docker 镜像默认使用 `Asia/Shanghai` 时区，确保服务端相对日期按成都本地日期解析。
- Compose 部署显式传入 `TZ=Asia/Shanghai`，避免运行环境覆盖镜像默认时区。
- 修改配置后需要重新构建镜像并创建容器才会生效。

## 验收

- `Dockerfile` 的环境变量包含 `TZ=Asia/Shanghai`。
- `compose.yaml` 中 `chatbi` 服务的环境变量包含 `TZ: Asia/Shanghai`。
