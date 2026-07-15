# Docker 初始数据库打包

## 目标

构建 Docker 镜像时，将仓库中的 `data/chatbi.db` 打包到 `/app/data/chatbi.db`，使新容器可以直接使用构建时的路线数据库。

## 行为

- `.dockerignore` 必须只为 `data/chatbi.db` 提供数据库忽略规则例外，其他本地数据库继续排除。
- `.gitignore` 必须只为 `data/chatbi.db` 提供数据库忽略规则例外，使 CI checkout 和 Docker 构建上下文能取得同一份初始数据库；其他本地数据库继续排除。
- `Dockerfile` 必须显式复制 `data/chatbi.db` 到 `/app/data/chatbi.db`。
- 镜像同时保留一份不受 `/app/data` 数据卷遮挡的初始数据库副本。
- 容器入口仅在 `/app/data/chatbi.db` 不存在时恢复初始数据库。
- 已存在的持久化数据库不得被镜像中的初始数据库覆盖。
- 初始数据库必须是可读取的 SQLite 数据库，并包含 `routes` 表。
- 数据库打包测试必须先确认文件真实存在，再以只读方式检查，禁止因 SQLite 自动创建空文件而掩盖缺失问题。

## 验收标准

- Docker 构建上下文包含 `data/chatbi.db`，但继续排除其他 `*.db`。
- Git 提交内容包含 `data/chatbi.db`，使 CI 可以验证并打包该文件。
- 未挂载数据卷时，镜像内数据库位于 `/app/data/chatbi.db`。
- 挂载既有空数据卷时，入口脚本会恢复数据库；非空数据卷中的数据库保持不变。
