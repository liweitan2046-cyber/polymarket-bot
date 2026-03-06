"""
Telegram Bot module.
Handles user commands and pushes notifications.
"""

import logging
from functools import wraps

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import simmer_api
import polymarket_api

logger = logging.getLogger(__name__)

BOT_APP: Application | None = None


def admin_only(func):
    """Decorator: restrict command to configured admin user IDs."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if config.TELEGRAM_ADMIN_IDS and user_id not in config.TELEGRAM_ADMIN_IDS:
            await update.message.reply_text("⛔ 无权限")
            return
        return await func(update, context)
    return wrapper


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    has_wallet = bool(config.WALLET_PRIVATE_KEY)
    wallet_status = "🟢 已配置" if has_wallet else "🔴 未配置"

    await update.message.reply_text(
        "🤖 *Polymarket Trading Bot*\n\n"
        f"钱包状态: {wallet_status}\n\n"
        "📊 *指令列表:*\n"
        "/briefing — 查看持仓、盈亏、套利机会\n"
        "/wallet — 查看钱包余额和状态\n"
        "/search <关键词> — 搜索市场\n"
        "/hot — 查看热门市场\n"
        "/positions — 查看当前持仓\n"
        "/scan — 立即执行一次市场扫描\n"
        "/status — 机器人运行状态\n",
        parse_mode="Markdown",
    )


@admin_only
async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ 正在获取 Simmer Briefing...")
    try:
        data = simmer_api.get_briefing()
        agent_info = simmer_api.get_agent_info()
        text = simmer_api.format_briefing(data, agent_info)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ 获取失败: {e}")


@admin_only
async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ 正在查询钱包状态...")
    try:
        info = simmer_api.get_wallet_info()
        text = simmer_api.format_wallet_info(info)
        await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"❌ 查询失败: {e}")



@admin_only
async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("用法: /search <关键词>")
        return
    keyword = " ".join(context.args)
    await update.message.reply_text(f"🔍 搜索: {keyword}...")
    try:
        markets = simmer_api.find_markets(keyword)
        if not markets:
            await update.message.reply_text("未找到相关市场")
            return
        lines = [f"🔍 *搜索结果: {keyword}*\n"]
        for m in markets[:8]:
            q = getattr(m, "question", str(m))[:50] if hasattr(m, "question") else str(m).get("question", "?")[:50]
            mid = getattr(m, "id", "") if hasattr(m, "id") else ""
            prob = getattr(m, "current_probability", 0) if hasattr(m, "current_probability") else 0
            lines.append(f"📌 {q}")
            lines.append(f"   概率: {prob:.0%} | ID: `{mid[:16]}`\n")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ 搜索失败: {e}")


@admin_only
async def cmd_hot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔥 正在获取热门市场...")
    try:
        markets = simmer_api.get_markets(limit=5)
        if not markets:
            await update.message.reply_text("暂无活跃市场")
            return
        lines = ["🔥 *热门市场*\n"]
        for m in markets:
            q = getattr(m, "question", "?")[:50]
            mid = getattr(m, "id", "")
            prob = getattr(m, "current_probability", 0)
            lines.append(f"📌 {q}")
            lines.append(f"   概率: {prob:.0%} | ID: `{mid[:16]}`\n")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ 获取失败: {e}")


@admin_only
async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        all_positions = simmer_api.get_positions("polymarket")
    except Exception as e:
        await update.message.reply_text(f"❌ 持仓查询失败: {e}")
        return

    positions = []
    for pos in all_positions:
        venue = getattr(pos, "venue", None) or (pos.get("venue") if isinstance(pos, dict) else None)
        if venue == "sim":
            continue
        positions.append(pos)

    if not positions:
        await update.message.reply_text("📋 当前无真实持仓")
        return

    total_pnl = 0.0
    total_cost = 0.0
    lines: list[str] = []

    for pos in positions:
        if hasattr(pos, "question"):
            name = pos.question[:35]
            shares_yes = float(pos.shares_yes)
            shares_no = float(pos.shares_no)
            pnl = float(pos.pnl)
            cost = float(getattr(pos, "cost_basis", 0) or getattr(pos, "cost", 0) or 0)
            avg = float(getattr(pos, "avg_cost", 0) or 0)
            price = float(getattr(pos, "current_price", 0) or 0)
            mid = pos.market_id
        else:
            name = pos.get("question", pos.get("market_name", "Unknown"))[:35]
            shares_yes = float(pos.get("shares_yes", 0))
            shares_no = float(pos.get("shares_no", 0))
            pnl = float(pos.get("pnl", 0))
            cost = float(pos.get("cost_basis", 0) or pos.get("cost", 0) or 0)
            avg = float(pos.get("avg_cost", 0) or 0)
            price = float(pos.get("current_price", 0) or 0)
            mid = pos.get("market_id", "N/A")

        total_pnl += pnl
        total_cost += cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"{emoji} {name}")
        lines.append(f"   YES: {shares_yes:.2f} | NO: {shares_no:.2f}")
        lines.append(f"   均价: ${avg:.3f} | 现价: ${price:.3f}")
        lines.append(f"   成本: ${cost:.2f} | P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
        lines.append(f"   ID: `{mid[:16]}`")

    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    header = (
        f"📋 *持仓总览* — {len(positions)} 个持仓\n"
        f"💰 总成本: ${total_cost:.2f}\n"
        f"{pnl_emoji} 总 P&L: ${total_pnl:+.2f} ({total_pnl_pct:+.1f}%)\n"
    )
    await update.message.reply_text(
        header + "\n".join(lines), parse_mode="Markdown"
    )



@admin_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from scheduler import get_status
    text = get_status()
    has_wallet = bool(config.WALLET_PRIVATE_KEY)
    text += f"\n钱包私钥: {'🟢 已配置' if has_wallet else '🔴 未配置'}"
    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 手动触发市场扫描...")
    from scheduler import run_scan_once
    result = await run_scan_once()
    await update.message.reply_text(result, parse_mode="Markdown")


async def unknown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ 未知指令，输入 /start 查看帮助")


async def send_notification(chat_id: int, text: str):
    """Push a notification message to a specific chat."""
    if BOT_APP and BOT_APP.bot:
        try:
            await BOT_APP.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="Markdown"
            )
        except Exception as e:
            logger.error("Failed to send notification: %s", e)


def build_app() -> Application:
    """Build and return the Telegram Application with all handlers."""
    global BOT_APP

    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("wallet", cmd_wallet))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("hot", cmd_hot))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_cmd))

    BOT_APP = app
    return app
