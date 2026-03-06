"""
Automated scheduler module.
Five strategies:
  1. AI Arbitrage Scan (every 30 min) - Simmer AI probability vs Polymarket price
  2. Whale Copy-Trading (every 4 hours) - Follow high-win-rate wallets
  3. Liquidity Reward Farming (daily 2:00 UTC) - Place maker orders for rewards
  4. Fast Market Momentum (every 5 min) - Binance price momentum on crypto fast markets
  5. Resolution Sniper (every 3 min) - Buy near-certain outcomes before settlement
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import config
import simmer_api
import price_feed

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_daily_traded_usdc = 0.0
_daily_reset_date = ""
_scan_count = 0
_trade_count = 0
_last_scan_time = "N/A"
_last_signal = "N/A"
_recent_trades: list[dict] = []
_sniped_markets: set[str] = set()

DIVERGENCE_THRESHOLD = config.DIVERGENCE_THRESHOLD_PCT
MAX_SINGLE_TRADE = config.MAX_SINGLE_TRADE_USDC
MAX_DAILY_TRADE = config.MAX_DAILY_TRADE_USDC
STOP_LOSS_PCT = -50.0
WHALE_WIN_RATE_MIN = config.WHALE_WIN_RATE_THRESHOLD
MOMENTUM_THRESHOLD = config.MOMENTUM_THRESHOLD_PCT
SNIPER_PROB_THRESHOLD = 0.82
SNIPER_HOURS_LEFT = 0.5
SNIPER_AMOUNT = min(5.0, config.MAX_SINGLE_TRADE_USDC)


def _reset_daily_limit():
    global _daily_traded_usdc, _daily_reset_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _daily_reset_date != today:
        _daily_traded_usdc = 0.0
        _daily_reset_date = today
        _sniped_markets.clear()


def _check_daily_limit(amount: float) -> bool:
    _reset_daily_limit()
    return (_daily_traded_usdc + amount) <= MAX_DAILY_TRADE


def _record_trade(amount: float, info: dict):
    global _daily_traded_usdc, _trade_count
    _daily_traded_usdc += amount
    _trade_count += 1
    _recent_trades.append(info)
    if len(_recent_trades) > 30:
        _recent_trades.pop(0)


async def _notify_admin(text: str):
    from telegram_bot import send_notification
    for admin_id in config.TELEGRAM_ADMIN_IDS:
        await send_notification(admin_id, text)


# ---------------------------------------------------------------------------
# Strategy 1: AI Arbitrage Scan (every 30 min)
# ---------------------------------------------------------------------------

async def ai_arbitrage_scan():
    """
    Compare Simmer AI's estimated probability vs Polymarket price.
    If divergence > 10%, buy the underpriced side with real USDC.
    """
    global _scan_count, _last_scan_time
    _scan_count += 1
    _last_scan_time = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    logger.info("AI arbitrage scan #%d", _scan_count)

    try:
        redeemed = simmer_api.auto_redeem_resolved_trades()
        for r in redeemed:
            if r.get("success"):
                await _notify_admin(
                    f"💰 *自动结算成功*\n\n"
                    f"市场: {r.get('market_question', '?')}\n"
                    f"方向: {r.get('side', '?').upper()}\n"
                    f"TX: `{r.get('tx_hash', 'N/A')[:20]}...`"
                )
            else:
                logger.warning("Auto-redeem failed: %s", r.get("error"))
    except Exception as e:
        logger.warning("Auto-redeem check failed: %s", e)

    venue = config.TRADING_VENUE

    try:
        positions = simmer_api.get_positions(venue)
        for pos in positions:
            pnl = getattr(pos, "pnl", 0) if hasattr(pos, "pnl") else pos.get("pnl", 0)
            cost = getattr(pos, "cost", 1) if hasattr(pos, "cost") else pos.get("cost", 1)
            pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
            if pnl_pct <= STOP_LOSS_PCT:
                name = getattr(pos, "question", "Unknown")[:30] if hasattr(pos, "question") else pos.get("question", "Unknown")[:30]
                await _notify_admin(
                    f"🔴 *止损警告*\n\n"
                    f"持仓: {name}\n"
                    f"亏损: {pnl_pct:.1f}% (${pnl:+.2f})\n"
                    f"建议立即手动平仓 /sell"
                )
    except Exception as e:
        logger.warning("Position check failed: %s", e)

    try:
        client = simmer_api.get_client("simmer")
        markets = client.get_markets(status="active", import_source="polymarket", limit=20)
    except Exception as e:
        logger.error("Market fetch failed: %s", e)
        return

    for market in markets:
        simmer_prob = market.current_probability
        ext_price = getattr(market, "external_price_yes", None)
        if ext_price is None or ext_price <= 0:
            continue

        divergence = (simmer_prob - ext_price) * 100
        if abs(divergence) < DIVERGENCE_THRESHOLD:
            continue

        side = "yes" if divergence > 0 else "no"
        edge_pct = abs(divergence)
        amount = min(MAX_SINGLE_TRADE, 5.0 + (edge_pct / 10.0) * 5.0)

        if not _check_daily_limit(amount):
            return

        reasoning = (
            f"AI套利: Simmer {simmer_prob:.0%} vs 市场 {ext_price:.0%}, "
            f"偏差 {edge_pct:.1f}%"
        )

        try:
            result = simmer_api.execute_trade(market.id, side, amount, reasoning, venue=venue)
            if result.get("success"):
                _record_trade(amount, {
                    "time": _last_scan_time, "strategy": "AI套利",
                    "market": market.question[:35], "side": side,
                    "amount": amount, "edge": f"{edge_pct:.1f}%", "success": True,
                })
                venue_label = "USDC" if venue == "polymarket" else "SIM"
                await _notify_admin(
                    f"🎯 *AI套利 [{venue_label}]*\n\n"
                    f"市场: {market.question[:45]}\n"
                    f"Simmer: {simmer_prob:.0%} vs 市场: {ext_price:.0%}\n"
                    f"方向: {side.upper()} | 金额: ${amount:.2f}\n"
                    f"额度: ${_daily_traded_usdc:.2f}/${MAX_DAILY_TRADE:.2f}"
                )
        except Exception as e:
            logger.error("Arb trade error: %s", e)

    logger.info("Arb scan #%d done", _scan_count)


# ---------------------------------------------------------------------------
# Strategy 2: Whale Copy-Trading (every 4 hours)
# ---------------------------------------------------------------------------

async def whale_copy_trading():
    """Check Simmer for high-win-rate whale signals and copy-trade."""
    logger.info("Whale copy-trading check")
    venue = config.TRADING_VENUE

    try:
        briefing = simmer_api.get_briefing()
    except Exception as e:
        logger.error("Briefing fetch failed: %s", e)
        return

    whale_signals = briefing.get("whale_signals", [])
    if not whale_signals:
        logger.info("No whale signals")
        return

    for signal in whale_signals:
        win_rate = signal.get("win_rate", 0)
        if win_rate < WHALE_WIN_RATE_MIN:
            continue

        market_id = signal.get("market_id", "")
        side = signal.get("side", "yes")
        whale_addr = signal.get("address", "?")[:10]
        whale_amount = signal.get("amount", 0)
        market_name = signal.get("market_name", signal.get("question", "Unknown"))[:35]

        amount = min(10.0, MAX_SINGLE_TRADE)
        if win_rate > 85:
            amount = MAX_SINGLE_TRADE

        if not _check_daily_limit(amount):
            return

        reasoning = f"巨鲸跟单: {whale_addr}... 胜率{win_rate:.0f}%"

        try:
            result = simmer_api.execute_trade(market_id, side, amount, reasoning, venue=venue)
            if result.get("success"):
                _record_trade(amount, {
                    "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    "strategy": "巨鲸跟单", "market": market_name,
                    "side": side, "amount": amount,
                    "edge": f"胜率{win_rate:.0f}%", "success": True,
                })
                await _notify_admin(
                    f"🐋 *巨鲸跟单*\n\n"
                    f"巨鲸: `{whale_addr}...` 胜率{win_rate:.1f}%\n"
                    f"金额: ${whale_amount:,.0f} → 跟单${amount:.2f}\n"
                    f"市场: {market_name} | {side.upper()}"
                )
        except Exception as e:
            logger.error("Whale copy error: %s", e)


# ---------------------------------------------------------------------------
# Strategy 3: Liquidity Reward Farming (daily 2:00 UTC)
# ---------------------------------------------------------------------------

async def liquidity_farming():
    """Place passive orders on hot markets to earn platform rewards."""
    logger.info("Liquidity farming")
    venue = config.TRADING_VENUE

    try:
        client = simmer_api.get_client("simmer")
        markets = client.get_markets(status="active", import_source="polymarket", limit=3)
    except Exception as e:
        logger.error("LP market fetch failed: %s", e)
        return

    report_lines = ["📦 *流动性挖矿报告*\n"]
    orders_placed = 0

    for market in markets:
        amount = 2.0
        if not _check_daily_limit(amount):
            break

        try:
            result = simmer_api.execute_trade(
                market.id, "yes", amount,
                f"LP挖矿: {market.question[:30]}", venue=venue,
            )
            if result.get("success"):
                _record_trade(amount, {
                    "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    "strategy": "LP挖矿", "market": market.question[:35],
                    "side": "yes", "amount": amount,
                    "edge": "流动性", "success": True,
                })
                orders_placed += 1
                report_lines.append(f"✅ {market.question[:40]}")
        except Exception as e:
            report_lines.append(f"❌ {str(e)[:40]}")

    report_lines.append(f"\n挂单: {orders_placed} | 额度: ${_daily_traded_usdc:.2f}/${MAX_DAILY_TRADE:.2f}")

    try:
        portfolio = simmer_api.get_portfolio()
        report_lines.append(f"💵 USDC: ${portfolio.get('balance_usdc', 0):,.2f}")
    except Exception:
        pass

    await _notify_admin("\n".join(report_lines))


# ---------------------------------------------------------------------------
# Strategy 4: Fast Market Momentum (every 5 min)
# ---------------------------------------------------------------------------

async def fast_market_momentum():
    """
    Every 5 min: check Binance for crypto price momentum.
    If BTC/ETH/SOL/XRP moved > 0.3% in last 5 min,
    buy the matching direction on Polymarket fast markets.
    """
    global _last_signal
    global _scan_count, _last_scan_time
    _scan_count += 1
    _last_scan_time = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    logger.info("Fast market momentum scan #%d", _scan_count)
    venue = config.TRADING_VENUE

    try:
        client = simmer_api.get_client("simmer")
        fast_markets = client.get_fast_markets()
    except Exception as e:
        logger.error("Fast market fetch failed: %s", e)
        return

    if not fast_markets:
        return

    for market in fast_markets:
        question = market.question
        market_prob = market.current_probability

        signal = price_feed.get_signal_for_market(question)
        if signal is None or signal.direction == "neutral":
            continue

        if abs(signal.change_pct) < MOMENTUM_THRESHOLD:
            continue

        _last_signal = f"{signal.symbol} {signal.direction} {signal.change_pct:+.2f}%"

        if signal.direction == "up" and market_prob < 0.55:
            side = "yes"
        elif signal.direction == "down" and market_prob > 0.45:
            side = "no"
        else:
            continue

        amount = min(5.0, MAX_SINGLE_TRADE)
        if signal.confidence > 0.5:
            amount = min(amount * 1.5, MAX_SINGLE_TRADE)

        if not _check_daily_limit(amount):
            return

        reasoning = (
            f"动量策略: {signal.symbol} {signal.change_pct:+.2f}% 5min, "
            f"市场 {market_prob:.0%}, 买入 {side.upper()}"
        )

        try:
            result = simmer_api.execute_trade(market.id, side, amount, reasoning, venue=venue)
            if result.get("success"):
                _record_trade(amount, {
                    "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    "strategy": "动量", "market": question[:35],
                    "side": side, "amount": amount,
                    "edge": f"{signal.change_pct:+.2f}%", "success": True,
                })
                venue_label = "USDC" if venue == "polymarket" else "SIM"
                await _notify_admin(
                    f"⚡ *动量交易 [{venue_label}]*\n\n"
                    f"信号: {signal.symbol} {signal.direction} {signal.change_pct:+.2f}%\n"
                    f"价格: ${signal.current_price:,.2f}\n"
                    f"市场: {question[:40]}\n"
                    f"方向: {side.upper()} (概率 {market_prob:.0%})\n"
                    f"金额: ${amount:.2f} | 份额: {result.get('shares_bought', 0):.4f}"
                )
            break
        except Exception as e:
            logger.error("Momentum trade error: %s", e)


# ---------------------------------------------------------------------------
# Strategy 5: Resolution Sniper (every 3 min)
# ---------------------------------------------------------------------------

async def resolution_sniper():
    """
    Every 3 min: find markets resolving within 30 min
    where the outcome is nearly certain (prob > 82% or < 18%).
    Buy the winning side cheaply before final settlement.
    """
    global _scan_count, _last_scan_time
    _scan_count += 1
    _last_scan_time = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    logger.info("Resolution sniper scan #%d", _scan_count)
    venue = config.TRADING_VENUE

    try:
        client = simmer_api.get_client("simmer")
        fast_markets = client.get_fast_markets()
    except Exception as e:
        logger.error("Sniper market fetch failed: %s", e)
        return

    if not fast_markets:
        return

    now = datetime.now(timezone.utc)

    for market in fast_markets:
        mid = market.id
        if mid in _sniped_markets:
            continue

        prob = market.current_probability
        resolves_at = getattr(market, "resolves_at", None)

        hours_left = None
        if resolves_at:
            try:
                if isinstance(resolves_at, str):
                    res_dt = datetime.fromisoformat(resolves_at.replace("Z", "+00:00"))
                else:
                    res_dt = resolves_at
                hours_left = (res_dt - now).total_seconds() / 3600
            except Exception:
                pass

        if hours_left is None or hours_left > SNIPER_HOURS_LEFT or hours_left < 0.01:
            continue

        signal = price_feed.get_signal_for_market(market.question)

        if prob >= SNIPER_PROB_THRESHOLD:
            if signal and signal.direction == "down" and abs(signal.change_pct) > 0.2:
                continue
            side = "yes"
            edge = prob
        elif prob <= (1 - SNIPER_PROB_THRESHOLD):
            if signal and signal.direction == "up" and abs(signal.change_pct) > 0.2:
                continue
            side = "no"
            edge = 1 - prob
        else:
            if signal and abs(signal.change_pct) > 0.5:
                if signal.direction == "up" and prob > 0.6:
                    side = "yes"
                    edge = prob
                elif signal.direction == "down" and prob < 0.4:
                    side = "no"
                    edge = 1 - prob
                else:
                    continue
            else:
                continue

        amount = min(SNIPER_AMOUNT, MAX_SINGLE_TRADE)
        if not _check_daily_limit(amount):
            return

        reasoning = (
            f"结算狙击: 概率{prob:.0%}, {hours_left*60:.0f}分钟后结算, "
            f"买入{side.upper()}"
        )

        try:
            result = simmer_api.execute_trade(mid, side, amount, reasoning, venue=venue)
            if result.get("success"):
                _sniped_markets.add(mid)
                _record_trade(amount, {
                    "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    "strategy": "狙击", "market": market.question[:35],
                    "side": side, "amount": amount,
                    "edge": f"概率{edge:.0%}", "success": True,
                })
                mins_left = hours_left * 60
                venue_label = "USDC" if venue == "polymarket" else "SIM"
                await _notify_admin(
                    f"🎯 *结算狙击 [{venue_label}]*\n\n"
                    f"市场: {market.question[:40]}\n"
                    f"概率: {prob:.0%} → 买入 {side.upper()}\n"
                    f"结算: {mins_left:.0f} 分钟后\n"
                    f"金额: ${amount:.2f}"
                )
        except Exception as e:
            logger.error("Sniper trade error: %s", e)


# ---------------------------------------------------------------------------
# Manual scan & status
# ---------------------------------------------------------------------------

async def run_scan_once() -> str:
    try:
        briefing = simmer_api.get_briefing()
        try:
            agent_info = simmer_api.get_agent_info()
        except Exception:
            agent_info = None
        text = simmer_api.format_briefing(briefing, agent_info)

        text += "\n\n*动量信号:*\n"
        for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]:
            signal = price_feed.get_momentum(symbol, lookback_minutes=5)
            if signal:
                emoji = "🟢" if signal.direction == "up" else ("🔴" if signal.direction == "down" else "⚪")
                text += f"{emoji} {symbol}: {signal.change_pct:+.2f}% (${signal.current_price:,.2f})\n"

        client = simmer_api.get_client("simmer")
        markets = client.get_markets(status="active", import_source="polymarket", limit=10)
        arb_count = 0
        text += "\n*套利扫描:*\n"
        for m in markets:
            ext = getattr(m, "external_price_yes", None)
            if ext is None:
                continue
            div = (m.current_probability - ext) * 100
            if abs(div) >= DIVERGENCE_THRESHOLD:
                arb_count += 1
                side = "YES" if div > 0 else "NO"
                text += f"  🎯 {m.question[:35]} → {side} ({abs(div):.1f}%)\n"
        if arb_count == 0:
            text += f"  暂无>={DIVERGENCE_THRESHOLD:.0f}%偏差\n"

        fast = client.get_fast_markets()
        now = datetime.now(timezone.utc)
        sniper_count = 0
        text += "\n*狙击机会:*\n"
        for m in fast:
            p = m.current_probability
            res = getattr(m, "resolves_at", None)
            if res:
                try:
                    res_dt = datetime.fromisoformat(str(res).replace("Z", "+00:00"))
                    hrs = (res_dt - now).total_seconds() / 3600
                    if 0 < hrs < SNIPER_HOURS_LEFT and (p >= SNIPER_PROB_THRESHOLD or p <= 1 - SNIPER_PROB_THRESHOLD):
                        sniper_count += 1
                        text += f"  🔫 {m.question[:35]} ({p:.0%}, {hrs*60:.0f}min)\n"
                except Exception:
                    pass
        if sniper_count == 0:
            text += "  暂无狙击机会\n"

        text += f"\n最近信号: {_last_signal}"
        text += f"\n模式: {'🟠 USDC' if config.TRADING_VENUE == 'polymarket' else '🔵 SIM'}"
        text += f"\n额度: ${_daily_traded_usdc:.2f}/${MAX_DAILY_TRADE:.2f}"

        return text
    except Exception as e:
        return f"❌ 扫描失败: {e}"


def get_status() -> str:
    _reset_daily_limit()
    running = _scheduler is not None and _scheduler.running
    venue_label = "🟠 USDC真实" if config.TRADING_VENUE == "polymarket" else "🔵 SIM虚拟"

    text = (
        "🤖 *机器人状态*\n\n"
        f"调度器: {'🟢 运行中' if running else '🔴 未运行'}\n"
        f"交易模式: {venue_label}\n"
        f"扫描次数: {_scan_count}\n"
        f"交易次数: {_trade_count}\n"
        f"上次扫描: {_last_scan_time}\n"
        f"最近信号: {_last_signal}\n"
        f"今日额度: ${_daily_traded_usdc:.2f} / ${MAX_DAILY_TRADE:.2f}\n"
    )

    try:
        all_positions = simmer_api.get_positions(config.TRADING_VENUE)
        real_positions = [
            p for p in all_positions
            if (getattr(p, "venue", None) if hasattr(p, "venue") else p.get("venue")) != "sim"
        ]
        if real_positions:
            total_pnl = 0.0
            total_cost = 0.0
            for pos in real_positions:
                pnl = float(getattr(pos, "pnl", 0) if hasattr(pos, "pnl") else pos.get("pnl", 0))
                cost = float(
                    getattr(pos, "cost_basis", 0) or getattr(pos, "cost", 0) or 0
                    if hasattr(pos, "cost_basis")
                    else pos.get("cost_basis", 0) or pos.get("cost", 0) or 0
                )
                total_pnl += pnl
                total_cost += cost
            pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
            pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
            text += (
                f"\n*持仓概况:*\n"
                f"  📊 持仓数: {len(real_positions)}\n"
                f"  💰 总成本: ${total_cost:.2f}\n"
                f"  {pnl_emoji} 总P&L: ${total_pnl:+.2f} ({pnl_pct:+.1f}%)\n"
            )
        else:
            text += "\n📊 当前无真实持仓\n"
    except Exception:
        text += "\n📊 持仓查询失败\n"

    text += (
        f"\n*五大策略:*\n"
        f"  1️⃣ AI套利: 每30分钟, 偏差>{DIVERGENCE_THRESHOLD:.0f}%\n"
        f"  2️⃣ 巨鲸跟单: 每4小时, 胜率>{WHALE_WIN_RATE_MIN:.0f}%\n"
        f"  3️⃣ LP挖矿: 每天2:00 UTC\n"
        f"  4️⃣ 动量交易: 每5分钟, 变化>{MOMENTUM_THRESHOLD:.1f}%\n"
        f"  5️⃣ 结算狙击: 每3分钟, 概率>{SNIPER_PROB_THRESHOLD:.0%}\n"
        f"  单笔: ${MAX_SINGLE_TRADE:.0f} | 日限: ${MAX_DAILY_TRADE:.0f} | 止损: {STOP_LOSS_PCT:.0f}%"
    )

    if _recent_trades:
        text += "\n\n*最近交易:*\n"
        for t in _recent_trades[-5:]:
            ok = "✅" if t.get("success") else "❌"
            text += (
                f"{ok} [{t.get('strategy','')}] "
                f"{t.get('market','')[:20]} "
                f"{t.get('side','').upper()} ${t.get('amount',0):.2f} "
                f"({t.get('edge','')})\n"
            )

    return text


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def start_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        ai_arbitrage_scan,
        trigger=IntervalTrigger(minutes=30),
        id="ai_arbitrage",
        name="AI Arbitrage Scan",
        replace_existing=True,
    )

    _scheduler.add_job(
        whale_copy_trading,
        trigger=IntervalTrigger(hours=4),
        id="whale_copy",
        name="Whale Copy-Trading",
        replace_existing=True,
    )

    _scheduler.add_job(
        liquidity_farming,
        trigger=CronTrigger(hour=config.REWARD_CRON_HOUR, minute=0),
        id="lp_farming",
        name="Liquidity Farming",
        replace_existing=True,
    )

    _scheduler.add_job(
        fast_market_momentum,
        trigger=IntervalTrigger(minutes=5),
        id="fast_momentum",
        name="Fast Market Momentum",
        replace_existing=True,
    )

    _scheduler.add_job(
        resolution_sniper,
        trigger=IntervalTrigger(minutes=3),
        id="resolution_sniper",
        name="Resolution Sniper",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "Scheduler started: 5 strategies, venue=%s",
        config.TRADING_VENUE,
    )
