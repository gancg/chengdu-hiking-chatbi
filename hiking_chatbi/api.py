from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .service import ChatBIService


logger = logging.getLogger(__name__)


def make_handler(service: ChatBIService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            logger.info(
                "HTTP 请求完成 method=%s path=%s status=%s",
                self.command, urlparse(self.path).path, int(status),
            )

        def _body(self) -> Any:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 2_000_000:
                raise ValueError("请求体过大")
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
            elif path == "/routes":
                self._json(HTTPStatus.OK, {"items": service.routes()})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path == "/recommendations":
                    self._json(HTTPStatus.OK, {"items": service.recommendations(body)})
                elif path == "/traffic/estimate":
                    self._json(HTTPStatus.OK, service.traffic(body))
                elif path == "/weather/estimate":
                    self._json(HTTPStatus.OK, service.weather(body))
                elif path == "/routes/import":
                    items = body if isinstance(body, list) else body.get("items", [])
                    self._json(HTTPStatus.CREATED, {"imported": service.import_items(items)})
                elif path == "/feedback/trips":
                    self._json(HTTPStatus.CREATED, {"id": service.record_feedback(body)})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                logger.warning(
                    "HTTP 请求参数无效 method=%s path=%s error=%s",
                    self.command, path, exc,
                )
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:
                logger.exception(
                    "HTTP 请求处理失败 method=%s path=%s",
                    self.command, path,
                )
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "服务内部错误"})

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("HTTP server: " + format, *args)

    return Handler


def create_server(service: ChatBIService, host: str, port: int) -> ThreadingHTTPServer:
    """Create the HTTP API server without starting its blocking loop."""
    return ThreadingHTTPServer((host, port), make_handler(service))


def serve(service: ChatBIService, host: str, port: int) -> None:
    server = create_server(service, host, port)
    logger.info("ChatBI HTTP API 已启动 host=%s port=%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中断信号，准备关闭 ChatBI HTTP API")
    finally:
        server.server_close()
        logger.info("ChatBI HTTP API 已关闭")
