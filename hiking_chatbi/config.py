from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def optional_int_from_env(name: str, default: int | None = None) -> int | None:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = raw_value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc


DB_PATH = Path(os.getenv("CHATBI_DB_PATH", ROOT / "data" / "chatbi.db"))
SAMPLE_DATA_PATH = ROOT / "data" / "sample_routes.json"
SAMPLE_COMMERCIAL_TOURS_PATH = ROOT / "data" / "sample_commercial_tours.json"
HOST = os.getenv("CHATBI_HOST", "127.0.0.1")
PORT = int(os.getenv("CHATBI_PORT", "8000"))
WEB_HOST = os.getenv("CHATBI_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("CHATBI_WEB_PORT", "7860"))
TRAFFIC_PROVIDER = os.getenv("CHATBI_TRAFFIC_PROVIDER", "none")
ALERT_PROVIDER = os.getenv("CHATBI_ALERT_PROVIDER", "qweather")
QWEN_MODEL = os.getenv("CHATBI_QWEN_MODEL", "qwen-plus")
QWEN_SEED = optional_int_from_env("CHATBI_QWEN_SEED", 42)
