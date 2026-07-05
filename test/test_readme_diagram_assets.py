from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class ReadmeDiagramAssetsTest(unittest.TestCase):
    def test_readme引用的架构图资源完整(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        asset_paths = [
            "docs/assets/system-architecture.svg",
            "docs/assets/recommendation-flow.svg",
        ]

        for relative_path in asset_paths:
            with self.subTest(relative_path=relative_path):
                self.assertIn(
                    relative_path,
                    readme,
                    f"README 未引用图片资源：{relative_path}",
                )
                content = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("<svg", content, f"图片不是有效 SVG：{relative_path}")
                self.assertIn("<title>", content, f"SVG 缺少标题：{relative_path}")
                self.assertIn("<desc>", content, f"SVG 缺少说明：{relative_path}")


if __name__ == "__main__":
    unittest.main()
