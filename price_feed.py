"""
Price feed module.
Fetches real-time crypto prices from Binance for momentum signal detection.
"""

import logging
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"

SYMBOL_MAP = {
    "bitcoin": "BTCUSDT",
    "btc": "BTCUSDT",
    "ethereum": "BTCUSDT",
    "eth": "ETHUSDT",
    "solana": "SOLUSDT",
    "sol": "SOLUSDT",
    "xrp": "XRPUSDT",
}

SYMBOL_CORRECTIONS = {
    "ethereum": "ETHUSDT",
    "eth": "ETHUSDT",
}


@dataclass
class MomentumSignal:
    symbol: str
    current_price: float
    prev_price: float
    change_pct: float
    direction: str  # "up", "down", "neutral"
    confidence: float  # 0.0 - 1.0


def _resolve_symbol(text: str) -> str | None:
    """Extract Binance symbol from market question text."""
    text_lower = text.lower()
    for key in SYMBOL_CORRECTIONS:
        if key in text_lower:
            return SYMBOL_CORRECTIONS[key]
    for key, symbol in SYMBOL_MAP.items():
        if key in text_lower:
            return symbol
    return None


def get_binance_price(symbol: str) -> float | None:
    """Get current price from Binance."""
    try:
        resp = requests.get(
            f"https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["price"])
    except Exception as e:
        logger.warning("Binance price fetch failed for %s: %s", symbol, e)
        return None


def get_momentum(symbol: str, lookback_minutes: int = 5) -> MomentumSignal | None:
    """
    Calculate price momentum over the lookback period.
    Uses Binance klines (candlestick) data.
    """
    try:
        resp = requests.get(
            BINANCE_KLINE_URL,
            params={
                "symbol": symbol,
                "interval": "1m",
                "limit": lookback_minutes + 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        klines = resp.json()

        if len(klines) < 2:
            return None

        prev_close = float(klines[0][4])
        current_close = float(klines[-1][4])
        change_pct = ((current_close - prev_close) / prev_close) * 100

        if change_pct > 0.1:
            direction = "up"
        elif change_pct < -0.1:
            direction = "down"
        else:
            direction = "neutral"

        confidence = min(abs(change_pct) / 1.0, 1.0)

        return MomentumSignal(
            symbol=symbol,
            current_price=current_close,
            prev_price=prev_close,
            change_pct=change_pct,
            direction=direction,
            confidence=confidence,
        )
    except Exception as e:
        logger.warning("Momentum calc failed for %s: %s", symbol, e)
        return None


def get_signal_for_market(question: str, lookback_minutes: int = 5) -> MomentumSignal | None:
    """Get momentum signal for a Polymarket question."""
    symbol = _resolve_symbol(question)
    if not symbol:
        return None
    return get_momentum(symbol, lookback_minutes)
