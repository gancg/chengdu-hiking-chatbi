from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DockerSampleRoutesPackagingTest(unittest.TestCase):
    def test_dockerfile_copies_sample_routes_to_required_container_path(self) -> None:
        """中文测试：镜像必须把样例路线明确复制到约定的容器绝对路径。"""
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn(
            "COPY data/sample_routes.json /app/data/sample_routes.json",
            dockerfile,
            "Dockerfile 未把 data/sample_routes.json 复制到 /app/data/sample_routes.json",
        )

    def test_container_entrypoint_restores_file_hidden_by_empty_volume(self) -> None:
        """中文测试：空数据卷遮挡镜像目录时，入口脚本必须恢复样例路线。"""
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        entrypoint_path = ROOT / "docker-entrypoint.sh"
        self.assertTrue(entrypoint_path.is_file(), "缺少容器入口脚本 docker-entrypoint.sh")
        entrypoint = entrypoint_path.read_text(encoding="utf-8")

        self.assertIn(
            "COPY data/sample_routes.json /app/image-data/sample_routes.json",
            dockerfile,
            "镜像缺少不受 /app/data 数据卷遮挡的初始副本",
        )
        self.assertIn(
            'if [ ! -f "/app/data/sample_routes.json" ]; then',
            entrypoint,
            "入口脚本未检测缺失的样例路线文件",
        )
        self.assertIn(
            'cp "/app/image-data/sample_routes.json" "/app/data/sample_routes.json"',
            entrypoint,
            "入口脚本未从镜像初始副本恢复样例路线文件",
        )
        self.assertIn('exec "$@"', entrypoint, "入口脚本必须继续执行容器启动命令")

    def test_sample_routes_source_is_valid_json(self) -> None:
        """中文测试：被打包的样例路线源文件必须是合法 JSON。"""
        sample_path = ROOT / "data" / "sample_routes.json"
        try:
            routes = json.loads(sample_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            self.fail(f"读取样例路线 JSON 失败：{error}")
        self.assertIsInstance(routes, list, "样例路线 JSON 顶层必须是数组")
        self.assertGreater(len(routes), 0, "样例路线 JSON 不得为空")

    def test_shell_entrypoint_keeps_linux_line_endings(self) -> None:
        """中文测试：Windows 检出仓库时，容器入口脚本也必须保持 LF 换行。"""
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn(
            "*.sh text eol=lf",
            attributes,
            "缺少 Shell 脚本 LF 换行约束，Windows 构建的镜像可能无法执行入口脚本",
        )


if __name__ == "__main__":
    unittest.main()
