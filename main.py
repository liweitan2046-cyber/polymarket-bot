"""
Polymarket Trading Bot — Main Entry Point.

Starts Telegram bot + automated scheduler.
No OpenClaw or Polymarket CLI dependency required.
"""

import logging
import sys

import config
from telegram_bot import build_app
from scheduler import start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def preflight_checks():
    """Validate required configuration before startup."""
    errors = []

    if not config.TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN 未设置")

    if not config.TELEGRAM_ADMIN_IDS:
        errors.append("TELEGRAM_ADMIN_IDS 未设置")

    if not config.SIMMER_API_KEY:
        errors.append("SIMMER_API_KEY 未设置（自动交易功能不可用）")
        logger.warning("SIMMER_API_KEY not configured — trading features disabled")

    if errors:
        for e in errors:
            logger.error("Config error: %s", e)

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_ADMIN_IDS:
        logger.error("Telegram config is required. Copy .env.example to .env and fill in values.")
        sys.exit(1)


def main():
    logger.info("=" * 50)
    logger.info("Polymarket Trading Bot starting...")
    logger.info("=" * 50)

    preflight_checks()

    logger.info("Admin IDs: %s", config.TELEGRAM_ADMIN_IDS)
    logger.info("Scan interval: %d min", config.SCAN_INTERVAL_MINUTES)
    logger.info("Reward claim: %d:00 UTC", config.REWARD_CRON_HOUR)
    logger.info("Whale copy: every %d hours", config.COPYTRADING_INTERVAL_HOURS)
    logger.info("Max single trade: $%.2f", config.MAX_SINGLE_TRADE_USDC)
    logger.info("Max daily trade: $%.2f", config.MAX_DAILY_TRADE_USDC)
    logger.info("Divergence threshold: %.1f%%", config.DIVERGENCE_THRESHOLD_PCT)

    app = build_app()

    async def post_init(application):
        start_scheduler()
        logger.info("Scheduler started.")

    app.post_init = post_init

    logger.info("Bot is running. Send /start in Telegram to begin.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
