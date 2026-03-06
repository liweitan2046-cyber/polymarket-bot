"""
Polymarket REST API client.
Queries market data via the Gamma API (no CLI dependency).
"""

import logging
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "PolymarketBot/1.0"})


def search_markets(query: str, limit: int = 5, active: bool = True) -> list:
    """Search markets by keyword."""
    params = {"query": query, "limit": limit}
    if active:
        params["active"] = "true"

    resp = _SESSION.get(
        f"{config.POLYMARKET_GAMMA_URL}/markets",
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_market(condition_id: str) -> dict:
    """Get detailed market info by condition ID."""
    resp = _SESSION.get(
        f"{config.POLYMARKET_GAMMA_URL}/markets/{condition_id}",
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_active_markets(limit: int = 10, order: str = "volume24hr") -> list:
    """Get top active markets ordered by volume or liquidity."""
    params = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "order": order,
    }
    resp = _SESSION.get(
        f"{config.POLYMARKET_GAMMA_URL}/markets",
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_market_price(condition_id: str) -> Optional[dict]:
    """
    Get current YES/NO prices for a market.
    Returns {"yes": float, "no": float} or None.
    """
    try:
        market = get_market(condition_id)
        tokens = market.get("tokens", [])
        prices = {}
        for token in tokens:
            outcome = token.get("outcome", "").lower()
            price = token.get("price", 0)
            prices[outcome] = float(price)
        return prices if prices else None
    except Exception as e:
        logger.error("Failed to get price for %s: %s", condition_id, e)
        return None


def format_market(market: dict) -> str:
    """Format a single market into readable text."""
    question = market.get("question", "Unknown")
    volume = market.get("volume", 0)
    liquidity = market.get("liquidity", 0)

    tokens = market.get("tokens", [])
    price_info = ""
    for token in tokens:
        outcome = token.get("outcome", "?")
        price = float(token.get("price", 0))
        price_info += f"  • {outcome}: {price*100:.1f}%\n"

    end_date = market.get("endDate", "N/A")
    cid = market.get("conditionId", "N/A")

    return (
        f"❓ *{question}*\n"
        f"{price_info}"
        f"💵 交易量: ${float(volume):,.0f}\n"
        f"🏦 流动性: ${float(liquidity):,.0f}\n"
        f"📅 截止: {end_date[:10] if end_date != 'N/A' else 'N/A'}\n"
        f"🔑 ID: `{cid[:16]}...`"
    )


def format_market_list(markets: list) -> str:
    """Format multiple markets into a summary."""
    if not markets:
        return "未找到相关市场"

    lines = [f"📊 *找到 {len(markets)} 个市场*\n"]
    for i, m in enumerate(markets[:10], 1):
        question = m.get("question", "Unknown")[:50]
        tokens = m.get("tokens", [])
        yes_price = "N/A"
        for t in tokens:
            if t.get("outcome", "").lower() == "yes":
                yes_price = f"{float(t.get('price', 0))*100:.1f}%"
        volume = float(m.get("volume", 0))
        lines.append(f"{i}. {question}")
        lines.append(f"   YES: {yes_price} | 交易量: ${volume:,.0f}")
        lines.append("")

    return "\n".join(lines)
