"""
Configuration management.
Loads settings from .env file and provides typed access.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_IDS = [
    int(uid) for uid in _get("TELEGRAM_ADMIN_IDS").split(",") if uid.strip().isdigit()
]

SIMMER_API_KEY = _get("SIMMER_API_KEY")
SIMMER_BASE_URL = _get("SIMMER_BASE_URL", "https://api.simmer.markets/api/sdk")

WALLET_PRIVATE_KEY = _get("WALLET_PRIVATE_KEY")

POLYMARKET_GAMMA_URL = _get(
    "POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com"
)
POLYMARKET_CLOB_URL = _get(
    "POLYMARKET_CLOB_URL", "https://clob.polymarket.com"
)

SCAN_INTERVAL_MINUTES = int(_get("SCAN_INTERVAL_MINUTES", "30"))
REWARD_CRON_HOUR = int(_get("REWARD_CRON_HOUR", "2"))
COPYTRADING_INTERVAL_HOURS = int(_get("COPYTRADING_INTERVAL_HOURS", "4"))

MAX_SINGLE_TRADE_USDC = float(_get("MAX_SINGLE_TRADE_USDC", "10"))
MAX_DAILY_TRADE_USDC = float(_get("MAX_DAILY_TRADE_USDC", "500"))
DIVERGENCE_THRESHOLD_PCT = float(_get("DIVERGENCE_THRESHOLD_PCT", "10"))
WHALE_WIN_RATE_THRESHOLD = float(_get("WHALE_WIN_RATE_THRESHOLD", "75"))

MOMENTUM_THRESHOLD_PCT = float(_get("MOMENTUM_THRESHOLD_PCT", "0.3"))
FAST_MARKET_INTERVAL_MINUTES = int(_get("FAST_MARKET_INTERVAL_MINUTES", "5"))
TRADING_VENUE = _get("TRADING_VENUE", "simmer")
