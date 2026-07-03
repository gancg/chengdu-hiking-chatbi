from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .api import serve
from .config import (
    DB_PATH,
    DAE_MAX_LINKS,
    DAE_TIMEOUT_SECONDS,
    DAE_URL,
    HOST,
    MIDO_MAX_LINKS,
    MIDO_TIMEOUT_SECONDS,
    MIDO_URL,
    PORT,
    QWEN_MODEL,
    QWEN_SEED,
    SAMPLE_DATA_PATH,
    TRAFFIC_PROVIDER,
    YOUXIAKE_AROUND_URL,
    YOUXIAKE_MAX_LINKS,
    YOUXIAKE_TIMEOUT_SECONDS,
    ALERT_PROVIDER,
    WEB_HOST,
    WEB_PORT,
)
from .importer import import_file
from .logging_config import configure_logging
from .service import ChatBIService
from .group_tour_links import (
    DaeGroupTourLinkProvider,
    MidoGroupTourLinkProvider,
    MultiGroupTourLinkProvider,
    YouxiakeGroupTourLinkProvider,
)
from .traffic import provider_from_name
from .weather import alert_provider_from_name


logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="成都周边徒步 ChatBI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="初始化数据库并导入样例路线")
    sub.add_parser("serve", help="启动 HTTP API")
    importer = sub.add_parser("import", help="导入审核后的结构化路线 JSON")
    importer.add_argument("path")
    sub.add_parser("qwen-chat", help="启动 Qwen Agent 终端对话")
    sub.add_parser("qwen-web", help="启动 Qwen Agent WebUI")
    sub.add_parser("app", help="一键启动 HTTP API 和 Qwen Agent WebUI")
    args = parser.parse_args()

    service = ChatBIService(
        DB_PATH,
        provider_from_name(TRAFFIC_PROVIDER),
        alert_provider_from_name(ALERT_PROVIDER),
        group_tour_provider=MultiGroupTourLinkProvider(
            [("游侠客", YouxiakeGroupTourLinkProvider(
                page_url=YOUXIAKE_AROUND_URL,
                timeout_seconds=YOUXIAKE_TIMEOUT_SECONDS,
                max_links=YOUXIAKE_MAX_LINKS,
            )), *(
                [("大鹅", DaeGroupTourLinkProvider(
                    page_url=DAE_URL,
                    timeout_seconds=DAE_TIMEOUT_SECONDS,
                    max_links=DAE_MAX_LINKS,
                ))] if DAE_URL else []
            ), *(
                [("蜜多", MidoGroupTourLinkProvider(
                    page_url=MIDO_URL,
                    timeout_seconds=MIDO_TIMEOUT_SECONDS,
                    max_links=MIDO_MAX_LINKS,
                ))] if MIDO_URL else []
            )]
        ),
    )
    logger.info(
        "应用命令启动 command=%s db_path=%s traffic_provider=%s alert_provider=%s "
        "qwen_model=%s qwen_seed=%s api=%s:%s web=%s:%s python=%s",
        args.command,
        DB_PATH,
        TRAFFIC_PROVIDER,
        ALERT_PROVIDER,
        QWEN_MODEL,
        QWEN_SEED,
        HOST,
        PORT,
        WEB_HOST,
        WEB_PORT,
        sys.executable,
    )
    if args.command == "init":
        count = service.seed(SAMPLE_DATA_PATH)
        logger.info("样例路线导入完成 count=%s db_path=%s", count, DB_PATH)
    elif args.command == "import":
        count = import_file(DB_PATH, Path(args.path))
        logger.info("路线文件导入完成 count=%s source=%s", count, args.path)
    elif args.command in {"qwen-chat", "qwen-web", "app"}:
        service.seed(SAMPLE_DATA_PATH)
        from .qwen_chatbi import run_qwen_chat, run_qwen_web

        if args.command == "qwen-chat":
            run_qwen_chat(service, QWEN_MODEL)
        elif args.command == "qwen-web":
            run_qwen_web(service, QWEN_MODEL, WEB_HOST, WEB_PORT)
        else:
            from .app import run_app

            run_app(service, HOST, PORT, WEB_HOST, WEB_PORT, QWEN_MODEL)
    else:
        service.seed(SAMPLE_DATA_PATH)
        serve(service, HOST, PORT)


if __name__ == "__main__":
    main()
