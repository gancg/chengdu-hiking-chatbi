# Qwen GUI 依赖环境

## 目标

- Qwen Agent WebUI 使用仓库独立的 `.venv`，不依赖全局 Python 环境。
- GUI 依赖通过 `qwen-agent[gui]==0.0.34` 安装，采用该版本声明的兼容组合。
- 保留项目已有的 Playwright 依赖。

## 版本要求

- `qwen-agent[gui]==0.0.34`
- `gradio==5.23.1`
- `gradio-client==1.8.0`
- `modelscope-studio==1.1.7`
- `pydantic==2.9.2`
- `pydantic-core==2.23.4`
- `soundfile==0.13.1`
- `playwright==1.60.0`

其中 GUI 的间接依赖版本以 Qwen Agent 0.0.34 的 `gui` extra 声明为准，
不在 `requirements.txt` 中重复维护。Qwen Agent 源码会直接导入但未在该 extra
中声明的 `soundfile` 作为显式运行依赖维护。

## 验收标准

- `requirements.txt` 明确启用固定版本的 Qwen Agent GUI extra。
- 在 `.venv` 中安装依赖后，GUI 关键包版本与上述要求一致。
- `python -m pip check` 不报告依赖冲突。
