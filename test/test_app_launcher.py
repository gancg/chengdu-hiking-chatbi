from __future__ import annotations

import unittest

from hiking_chatbi.app import run_app


class FakeServer:
    def __init__(self) -> None:
        self.has_served = False
        self.has_shutdown = False
        self.has_closed = False

    def serve_forever(self) -> None:
        self.has_served = True

    def shutdown(self) -> None:
        self.has_shutdown = True

    def server_close(self) -> None:
        self.has_closed = True


class AppLauncherTest(unittest.TestCase):
    def test_app_starts_api_then_web_and_closes_api(self) -> None:
        """统一启动命令应启动后台，并在前台退出后关闭后台。"""
        server = FakeServer()
        events: list[str] = []

        def create_server(service: object, host: str, port: int) -> FakeServer:
            events.append(f"api:{host}:{port}")
            return server

        def run_web(service: object, model: str, host: str, port: int) -> None:
            events.append(f"web:{host}:{port}:{model}")

        run_app(
            service=object(),
            api_host="127.0.0.1",
            api_port=8000,
            web_host="127.0.0.1",
            web_port=7860,
            model="qwen-plus",
            create_api_server=create_server,
            run_web=run_web,
        )

        self.assertEqual(
            ["api:127.0.0.1:8000", "web:127.0.0.1:7860:qwen-plus"],
            events,
            "应先创建后台 API，再启动前台 WebUI",
        )
        self.assertTrue(server.has_served, "后台 API 应进入服务状态")
        self.assertTrue(server.has_shutdown, "前台退出后应停止后台 API")
        self.assertTrue(server.has_closed, "前台退出后应关闭后台端口")


if __name__ == "__main__":
    unittest.main()
