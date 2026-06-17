from __future__ import annotations

import logging
import os


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(force: bool = False) -> None:
    """Configure application logging from environment variables."""
    level_name = os.getenv("CHATBI_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT, force=force)
