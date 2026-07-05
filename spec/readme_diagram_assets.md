# README 架构图静态资源

## 目标

将 README 中依赖 Mermaid 渲染器的两张图改为仓库内置 SVG，使不支持 Mermaid 的阅读器也能直接展示项目架构和推荐流程。

## 验收标准

- 图片统一放在 `docs/assets/`。
- 提供系统架构图 `system-architecture.svg`。
- 提供推荐流程图 `recommendation-flow.svg`。
- README 通过相对路径引用两张图片，并提供有意义的替代文本。
- SVG 必须包含可访问的 `title` 和 `desc`，且不依赖外部字体或图片资源。
