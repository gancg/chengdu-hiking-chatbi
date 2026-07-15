from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def find_seed_calls(nodes: list[ast.stmt]) -> list[ast.Call]:
    """查找语句中的 service.seed 调用。"""
    calls: list[ast.Call] = []
    for node in nodes:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            function = child.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr == "seed"
                and isinstance(function.value, ast.Name)
                and function.value.id == "service"
            ):
                calls.append(child)
    return calls


class DisableStartupSampleRoutesImportTest(unittest.TestCase):
    def test_only_explicit_init_command_imports_sample_routes(self) -> None:
        """中文测试：只有显式 init 命令可以导入样例路线，其他启动命令不得导入。"""
        source = (ROOT / "hiking_chatbi" / "__main__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        all_seed_calls = find_seed_calls(tree.body)
        init_seed_calls: list[ast.Call] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if ast.unparse(node.test) == "args.command == 'init'":
                init_seed_calls.extend(find_seed_calls(node.body))

        self.assertEqual(
            1,
            len(all_seed_calls),
            "启动命令中不应存在自动导入；service.seed 只能由显式 init 调用一次",
        )
        self.assertEqual(
            all_seed_calls,
            init_seed_calls,
            "service.seed 必须只位于显式 init 命令分支",
        )


if __name__ == "__main__":
    unittest.main()
