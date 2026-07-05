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


def positive_int_from_env(name: str, default: int) -> int:
    """读取正整数环境变量，并在配置无效时给出明确错误。"""
    value = optional_int_from_env(name, default)
    if value is None or value <= 0:
        raise ValueError(f"{name} 必须是正整数")
    return value


DB_PATH = Path(os.getenv("CHATBI_DB_PATH", ROOT / "data" / "chatbi.db"))
SAMPLE_DATA_PATH = Path(
    os.getenv("CHATBI_SAMPLE_DATA_PATH", ROOT / "data" / "sample_routes.json")
)
HOLIDAY_DATA_PATH = Path(
    os.getenv("CHATBI_HOLIDAY_DATA_PATH", ROOT / "data" / "holidays.json")
)
HOST = os.getenv("CHATBI_HOST", "127.0.0.1")
PORT = int(os.getenv("CHATBI_PORT", "8000"))
WEB_HOST = os.getenv("CHATBI_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("CHATBI_WEB_PORT", "7860"))
H5_HOST = os.getenv("CHATBI_H5_HOST", "127.0.0.1")
H5_PORT = int(os.getenv("CHATBI_H5_PORT", "7861"))
TRAFFIC_PROVIDER = os.getenv("CHATBI_TRAFFIC_PROVIDER", "none")
ALERT_PROVIDER = os.getenv("CHATBI_ALERT_PROVIDER", "qweather")
QWEN_MODEL = os.getenv("CHATBI_QWEN_MODEL", "qwen-max")
QWEN_SEED = optional_int_from_env("CHATBI_QWEN_SEED", 42)
QWEN_MAX_LLM_CALLS = positive_int_from_env("CHATBI_QWEN_MAX_LLM_CALLS", 20)
QWEN_MAX_RETRIES = positive_int_from_env("CHATBI_QWEN_MAX_RETRIES", 2)
QWEN_REQUEST_TIMEOUT_SECONDS = positive_int_from_env(
    "CHATBI_QWEN_REQUEST_TIMEOUT_SECONDS", 20
)
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

QWEATHER_API_HOST = os.getenv(
    "QWEATHER_API_HOST", "n32k5q6wdt.re.qweatherapi.com"
).strip()


def qweather_api_host_from_env() -> str:
    """读取天气 Host，允许测试和长运行进程在调用前更新环境配置。"""
    return os.getenv("QWEATHER_API_HOST", QWEATHER_API_HOST).strip()


WEATHER_REQUEST_TIMEOUT_SECONDS = positive_int_from_env(
    "CHATBI_WEATHER_REQUEST_TIMEOUT_SECONDS", 10
)
WEATHER_CACHE_TTL_MINUTES = positive_int_from_env(
    "CHATBI_WEATHER_CACHE_TTL_MINUTES", 30
)

YOUXIAKE_LIST_URL = os.getenv(
    "CHATBI_YOUXIAKE_LIST_URL",
    "https://www.youxiake.com/search/results/0-0-0-1-0-0/azEtaTE.html",
).strip()
COLLECTOR_MODEL = os.getenv("CHATBI_COLLECTOR_MODEL", "qwen3.7-max").strip()
DASHSCOPE_CHAT_COMPLETIONS_URL = os.getenv(
    "CHATBI_DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
).strip()
COLLECTOR_REQUEST_TIMEOUT_SECONDS = positive_int_from_env(
    "CHATBI_COLLECTOR_REQUEST_TIMEOUT_SECONDS", 240
)
COLLECTOR_BROWSER_TIMEOUT_SECONDS = positive_int_from_env(
    "CHATBI_COLLECTOR_BROWSER_TIMEOUT_SECONDS", 60
)
COLLECTOR_LINK_TIMEOUT_SECONDS = positive_int_from_env(
    "CHATBI_COLLECTOR_LINK_TIMEOUT_SECONDS", 45
)
COLLECTOR_DEFAULT_COUNT = positive_int_from_env("CHATBI_COLLECTOR_DEFAULT_COUNT", 40)
COLLECTOR_MAX_PAGES = positive_int_from_env("CHATBI_COLLECTOR_MAX_PAGES", 30)
COLLECTOR_INPUT_PATH = Path(
    os.getenv(
        "CHATBI_COLLECTOR_INPUT_PATH",
        ROOT / "data" / "youxiake_chengdu_day_route_links_40.json",
    )
)
COLLECTOR_OUTPUT_PATH = Path(
    os.getenv(
        "CHATBI_COLLECTOR_OUTPUT_PATH",
        ROOT / "data" / "youxiake_routes_enriched_40.json",
    )
)
COLLECTOR_LEGACY_OUTPUT_PATH = Path(
    os.getenv(
        "CHATBI_COLLECTOR_LEGACY_OUTPUT_PATH",
        ROOT / "data" / "youxiake_chengdu_day_hikes_40.json",
    )
)
