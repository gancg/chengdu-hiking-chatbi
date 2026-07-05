from __future__ import annotations

import logging
from threading import Thread
from typing import Any, Callable, Protocol

from .api import create_server
from .qwen_chatbi import run_qwen_web
from .service import ChatBIService


logger = logging.getLogger(__name__)


class ApiServer(Protocol):
    def serve_forever(self) -> None: ...

    def shutdown(self) -> None: ...

    def server_close(self) -> None: ...


class PageServer(Protocol):
    def close(self) -> None: ...


def run_app(
    service: ChatBIService,
    api_host: str,
    api_port: int,
    web_host: str,
    web_port: int,
    model: str,
    create_api_server: Callable[[Any, str, int], ApiServer] = create_server,
    run_web: Callable[[Any, str, str, int], None] = run_qwen_web,
) -> None:
    """Run the HTTP API in the background and WebUI in the foreground."""
    server = create_api_server(service, api_host, api_port)
    api_thread = Thread(target=server.serve_forever, name="chatbi-api", daemon=True)
    api_thread.start()
    logger.info("ChatBI API 已启动 host=%s port=%s", api_host, api_port)
    logger.info("ChatBI WebUI 正在启动 host=%s port=%s model=%s", web_host, web_port, model)
    try:
        run_web(service, model, web_host, web_port)
    finally:
        logger.info("正在关闭 ChatBI API")
        server.shutdown()
        server.server_close()
        api_thread.join(timeout=5)
        logger.info("ChatBI API 已关闭")


def run_dual_ui_app(
    service: ChatBIService,
    api_host: str,
    api_port: int,
    web_host: str,
    web_port: int,
    h5_host: str,
    h5_port: int,
    model: str,
    create_api_server: Callable[[Any, str, int], ApiServer] = create_server,
    run_web: Callable[..., PageServer] = run_qwen_web,
    run_h5: Callable[[Any, str, str, int], Any] | None = None,
) -> None:
    """Run API and desktop WebUI, keeping the mobile H5 UI in the foreground."""
    if run_h5 is None:
        from .qwen_chatbi import run_qwen_h5

        run_h5 = run_qwen_h5

    server = create_api_server(service, api_host, api_port)
    api_thread = Thread(target=server.serve_forever, name="chatbi-api", daemon=True)
    api_thread.start()
    web_page: PageServer | None = None
    logger.info("ChatBI API 已启动 host=%s port=%s", api_host, api_port)
    try:
        logger.info("ChatBI WebUI 正在启动 host=%s port=%s", web_host, web_port)
        web_page = run_web(
            service,
            model,
            web_host,
            web_port,
            prevent_thread_lock=True,
        )
        logger.info("ChatBI H5 正在启动 host=%s port=%s", h5_host, h5_port)
        run_h5(service, model, h5_host, h5_port)
    finally:
        if web_page is not None:
            logger.info("正在关闭 ChatBI WebUI")
            web_page.close()
        logger.info("正在关闭 ChatBI API")
        server.shutdown()
        server.server_close()
        api_thread.join(timeout=5)
        logger.info("ChatBI API 已关闭")
