from __future__ import annotations

import logging
import os


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
THIRD_PARTY_LOGGERS = (
    "httpcore",
    "httpx",
    "huggingface_hub",
    "urllib3",
)


def configure_logging(force: bool = False) -> None:
    """Configure application logging from environment variables."""
    level_name = os.getenv("CHATBI_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT, force=force)
    third_party_level_name = os.getenv("CHATBI_THIRD_PARTY_LOG_LEVEL", "WARNING").upper()
    third_party_level = getattr(logging, third_party_level_name, logging.WARNING)
    for logger_name in THIRD_PARTY_LOGGERS:
        logging.getLogger(logger_name).setLevel(third_party_level)
