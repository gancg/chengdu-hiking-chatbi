from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def read_project_file(relative_path: str) -> str:
    """读取打包配置；文件缺失时给出明确的中文失败信息。"""
    path = ROOT / relative_path
    if not path.is_file():
        raise AssertionError(f"缺少打包配置文件：{relative_path}")
    return path.read_text(encoding="utf-8")


class LinuxDockerPackagingTest(unittest.TestCase):
    def test_requirements_pin_qwen_gui_runtime_versions(self) -> None:
        """镜像和 CI 应锁定现有 Qwen GUI 测试要求的传递依赖版本。"""
        requirements = {
            line.strip().lower()
            for line in read_project_file("requirements.txt").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn("pydantic==2.9.2", requirements, "应锁定兼容的 pydantic 版本")
        self.assertIn(
            "pydantic-core==2.23.4",
            requirements,
            "应锁定兼容的 pydantic-core 版本",
        )

    def test_dockerfile_defines_linux_runtime(self) -> None:
        """Dockerfile 应提供固定 Python、浏览器、端口、健康检查和启动命令。"""
        dockerfile = read_project_file("Dockerfile")

        expected_fragments = {
            "FROM python:3.11-slim-bookworm": "应固定使用 Python 3.11 Linux 基础镜像",
            "playwright install --with-deps chromium": "应安装 Chromium 及其系统依赖",
            "CHATBI_HOST=0.0.0.0": "API 应监听所有容器网卡",
            "CHATBI_WEB_HOST=0.0.0.0": "WebUI 应监听所有容器网卡",
            "CHATBI_H5_HOST=0.0.0.0": "H5 应监听所有容器网卡",
            "CHATBI_DB_PATH=/app/runtime/chatbi.db": "数据库应写入持久化目录",
            "EXPOSE 8000 7860 7861": "应声明 API、WebUI 和 H5 端口",
            "HEALTHCHECK": "应配置容器健康检查",
            'CMD ["python", "-m", "hiking_chatbi", "app"]': "应默认同时启动 API 和 WebUI",
        }
        for fragment, message in expected_fragments.items():
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, dockerfile, message)

    def test_dockerignore_excludes_local_and_sensitive_files(self) -> None:
        """Docker 构建上下文不应包含密钥、数据库、Git 元数据或本地缓存。"""
        dockerignore = {
            line.strip()
            for line in read_project_file(".dockerignore").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        for pattern in (".git", ".env", ".env.*", "*.db", ".venv", "__pycache__", "work"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, dockerignore, f".dockerignore 应排除 {pattern}")
        self.assertIn("!.env.example", dockerignore, "应允许示例环境配置进入构建上下文")

    def test_compose_persists_runtime_and_exposes_services(self) -> None:
        """Compose 应注入本地环境、开放端口并持久化运行数据。"""
        compose = read_project_file("compose.yaml")

        for fragment, message in {
            "platform: linux/amd64": "Compose 应构建 amd64 Linux 镜像",
            "env_file:": "Compose 应读取本地 .env",
            "- .env": "Compose 应明确指定 .env 文件",
            '"8000:8000"': "Compose 应映射 API 端口",
            '"7860:7860"': "Compose 应映射 WebUI 端口",
            '"7861:7861"': "Compose 应映射 H5 端口",
            "chatbi-runtime:/app/runtime": "Compose 应持久化运行目录",
        }.items():
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, compose, message)

    def test_github_actions_builds_and_publishes_main(self) -> None:
        """GitHub Actions 应测试 main 分支并向 GHCR 发布三类镜像标签。"""
        workflow = read_project_file(".github/workflows/docker-publish.yml")

        expected_fragments = {
            "workflow_dispatch:": "工作流应支持手工触发",
            "branches: [main]": "工作流应监听 main 分支",
            "contents: read": "工作流只需读取仓库内容",
            "packages: write": "工作流应具有发布镜像权限",
            "python -m unittest discover -s test -v": "发布前应运行新测试目录",
            "registry: ghcr.io": "应登录 GitHub Container Registry",
            "gancg/chengdu-hiking-chatbi": "应发布到约定的镜像仓库",
            "type=raw,value=latest": "应发布 latest 标签",
            "type=raw,value=main": "应发布 main 标签",
            "type=sha": "应发布提交 SHA 标签",
            "platforms: linux/amd64": "应构建 amd64 Linux 镜像",
        }
        for fragment, message in expected_fragments.items():
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, workflow, message)


if __name__ == "__main__":
    unittest.main()
