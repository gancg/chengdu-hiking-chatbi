from __future__ import annotations

import unittest

from hiking_chatbi.app import run_dual_ui_app


class FakeServer:
    def __init__(self) -> None:
        self.has_shutdown = False
        self.has_closed = False

    def serve_forever(self) -> None:
        return None

    def shutdown(self) -> None:
        self.has_shutdown = True

    def server_close(self) -> None:
        self.has_closed = True


class FakePage:
    def __init__(self) -> None:
        self.has_closed = False

    def close(self) -> None:
        self.has_closed = True


class DualUiLauncherTest(unittest.TestCase):
    def test_app_starts_api_web_and_h5_then_cleans_up(self) -> None:
        """组合命令应启动三个端口，并在 H5 退出后清理页面和 API。"""
        server = FakeServer()
        web_page = FakePage()
        events: list[str] = []

        def create_server(service: object, host: str, port: int) -> FakeServer:
            events.append(f"api:{host}:{port}")
            return server

        def run_web(
            service: object,
            model: str,
            host: str,
            port: int,
            *,
            prevent_thread_lock: bool,
        ) -> FakePage:
            events.append(f"web:{host}:{port}:{prevent_thread_lock}")
            return web_page

        def run_h5(service: object, model: str, host: str, port: int) -> None:
            events.append(f"h5:{host}:{port}")

        run_dual_ui_app(
            service=object(),
            api_host="127.0.0.1",
            api_port=8000,
            web_host="127.0.0.1",
            web_port=7860,
            h5_host="127.0.0.1",
            h5_port=7861,
            model="qwen-max",
            create_api_server=create_server,
            run_web=run_web,
            run_h5=run_h5,
        )

        self.assertEqual(
            [
                "api:127.0.0.1:8000",
                "web:127.0.0.1:7860:True",
                "h5:127.0.0.1:7861",
            ],
            events,
        )
        self.assertTrue(web_page.has_closed, "H5 退出后应关闭 Web 页面")
        self.assertTrue(server.has_shutdown, "H5 退出后应停止 API")
        self.assertTrue(server.has_closed, "H5 退出后应关闭 API 端口")

    def test_app_cleans_up_api_when_web_start_fails(self) -> None:
        """Web 端口启动失败时也必须清理已经启动的 API。"""
        server = FakeServer()

        def create_server(service: object, host: str, port: int) -> FakeServer:
            return server

        def run_web(*args: object, **kwargs: object) -> FakePage:
            raise OSError("Web 端口已占用")

        with self.assertRaisesRegex(OSError, "Web 端口已占用"):
            run_dual_ui_app(
                service=object(),
                api_host="127.0.0.1",
                api_port=8000,
                web_host="127.0.0.1",
                web_port=7860,
                h5_host="127.0.0.1",
                h5_port=7861,
                model="qwen-max",
                create_api_server=create_server,
                run_web=run_web,
                run_h5=lambda *args: None,
            )

        self.assertTrue(server.has_shutdown, "Web 启动失败后应停止 API")
        self.assertTrue(server.has_closed, "Web 启动失败后应关闭 API 端口")


if __name__ == "__main__":
    unittest.main()
