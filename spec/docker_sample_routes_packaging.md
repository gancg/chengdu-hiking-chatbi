# Docker 样例路线文件打包

## 目标

构建 Docker 镜像时，将仓库中的 `data/sample_routes.json` 明确打包到
`/app/data/sample_routes.json`，保证容器首次启动可以读取样例路线。

## 行为

- `Dockerfile` 必须显式复制 `data/sample_routes.json` 到
  `/app/data/sample_routes.json`。
- 镜像同时保留一份不受 `/app/data` 数据卷遮挡的只读初始副本。
- 容器入口在 `/app/data/sample_routes.json` 缺失时，从初始副本恢复该文件。
- 已存在的 `/app/data/sample_routes.json` 不得被启动过程覆盖，以保留调度器更新后的路线数据。
- 恢复失败时入口脚本立即报错退出，不得在缺少路线文件的状态下继续启动应用。
- Shell 入口脚本在 Windows 检出仓库时也必须保持 LF 换行，避免 Linux 容器无法执行。

## 验收标准

- 打包配置测试验证源文件、容器目标路径和入口恢复逻辑。
- 未挂载数据卷时，镜像内文件位于 `/app/data/sample_routes.json`。
- 挂载既有空数据卷时，容器启动前会补齐 `/app/data/sample_routes.json`。
