# 成都徒步 ChatBI

## 使用 Docker 本地打包

前置条件：Windows 安装 Docker Desktop，并切换到 Linux containers。

```powershell
docker build --platform linux/amd64 -t chengdu-hiking-chatbi:local .
Copy-Item .env.example .env
# 在 .env 中填写 DASHSCOPE_API_KEY、QWEATHER_API_KEY 等运行配置
docker compose up --build -d
```

启动后访问：

- WebUI：<http://127.0.0.1:7860>
- API 健康检查：<http://127.0.0.1:8000/health>

查看日志或停止服务：

```powershell
docker compose logs -f chatbi
docker compose down
```

Compose 使用 `chatbi-runtime` 命名卷保存 `/app/runtime/chatbi.db`。执行
`docker compose down` 或重建容器不会删除该卷；只有显式执行
`docker compose down --volumes` 才会删除数据。

不使用 Compose 时可直接运行：

```powershell
docker run --rm --name hiking-chatbi `
  --env-file .env `
  -e CHATBI_HOST=0.0.0.0 `
  -e CHATBI_WEB_HOST=0.0.0.0 `
  -e CHATBI_DB_PATH=/app/runtime/chatbi.db `
  -p 8000:8000 -p 7860:7860 `
  -v chatbi-runtime:/app/runtime `
  chengdu-hiking-chatbi:local
```

`.env`、本地数据库和密钥均被排除在镜像之外。不要把真实密钥写入 Dockerfile，
也不要提交 `.env`。

## GitHub 自动构建

推送代码到 `main` 后，GitHub Actions 会先运行 `/test` 测试，再构建
`linux/amd64` 镜像并发布到：

```text
ghcr.io/gancg/chengdu-hiking-chatbi
```

每次发布包含 `latest`、`main` 和 `sha-<短提交号>` 标签，也可在 GitHub Actions
页面手工触发工作流。工作流使用仓库内置 `GITHUB_TOKEN`，无需另建 Registry 密钥。

GHCR 包默认可能是私有的。需要公开拉取时，在 GitHub 包页面的 Package settings 中
将可见性改为 Public；保持私有时，Linux 服务器需使用具有 `read:packages` 权限的
GitHub Personal Access Token 登录：

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
docker pull ghcr.io/gancg/chengdu-hiking-chatbi:latest
docker volume create chatbi-runtime
docker run -d --name hiking-chatbi --restart unless-stopped \
  --env-file /opt/hiking-chatbi/.env \
  -p 8000:8000 -p 7860:7860 \
  -v chatbi-runtime:/app/runtime \
  ghcr.io/gancg/chengdu-hiking-chatbi:latest
```

生产环境建议固定使用 `sha-<短提交号>` 标签，确认新版本正常后再更新容器，避免
`latest` 变化导致不可预期升级。

