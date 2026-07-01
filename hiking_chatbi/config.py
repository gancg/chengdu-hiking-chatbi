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
HOST = os.getenv("CHATBI_HOST", "127.0.0.1")
PORT = int(os.getenv("CHATBI_PORT", "8000"))
WEB_HOST = os.getenv("CHATBI_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("CHATBI_WEB_PORT", "7860"))
TRAFFIC_PROVIDER = os.getenv("CHATBI_TRAFFIC_PROVIDER", "none")
ALERT_PROVIDER = os.getenv("CHATBI_ALERT_PROVIDER", "qweather")
QWEN_MODEL = os.getenv("CHATBI_QWEN_MODEL", "qwen3.7-max")
QWEN_SEED = optional_int_from_env("CHATBI_QWEN_SEED", 42)
YOUXIAKE_AROUND_URL = os.getenv(
    "CHATBI_YOUXIAKE_AROUND_URL", "https://www.youxiake.com/around?site=19"
)
YOUXIAKE_TIMEOUT_SECONDS = int(os.getenv("CHATBI_YOUXIAKE_TIMEOUT_SECONDS", "20"))
YOUXIAKE_MAX_LINKS = int(os.getenv("CHATBI_YOUXIAKE_MAX_LINKS", "5"))
DAE_URL = os.getenv("CHATBI_DAE_URL", "https://www.cddee.cn/").strip()
DAE_TIMEOUT_SECONDS = int(os.getenv("CHATBI_DAE_TIMEOUT_SECONDS", "20"))
DAE_MAX_LINKS = int(os.getenv("CHATBI_DAE_MAX_LINKS", "5"))
MIDO_URL = os.getenv(
    "CHATBI_MIDO_URL", "https://cdmdtb.360jlb.cn/events?mid=52240"
).strip()
MIDO_TIMEOUT_SECONDS = int(os.getenv("CHATBI_MIDO_TIMEOUT_SECONDS", "20"))
MIDO_MAX_LINKS = int(os.getenv("CHATBI_MIDO_MAX_LINKS", "5"))
