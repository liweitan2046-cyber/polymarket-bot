"""
Interactive setup wizard.
Guides user through wallet and API configuration.
"""

import os
import shutil
import sys
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parent / ".env"
EXAMPLE_PATH = Path(__file__).resolve().parent / ".env.example"


def prompt(label: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value if value else default


def main():
    print("=" * 50)
    print("  Polymarket Trading Bot — 配置向导")
    print("=" * 50)
    print()

    if ENV_PATH.exists():
        overwrite = input(".env 文件已存在，是否覆盖? (y/N): ").strip().lower()
        if overwrite != "y":
            print("已跳过配置。你可以手动编辑 .env 文件。")
            return

    settings = {}

    print("\n--- Telegram 配置 ---")
    settings["TELEGRAM_BOT_TOKEN"] = prompt(
        "Telegram Bot Token (从 @BotFather 获取)"
    )
    settings["TELEGRAM_ADMIN_IDS"] = prompt(
        "你的 Telegram User ID (从 @userinfobot 获取)"
    )

    print("\n--- Simmer API 配置 ---")
    print("如果还没有 Simmer API Key，可以先留空，后续手动填入 .env")
    settings["SIMMER_API_KEY"] = prompt("Simmer API Key", default="")

    print("\n--- 交易参数 ---")
    settings["SCAN_INTERVAL_MINUTES"] = prompt("市场扫描间隔（分钟）", "30")
    settings["REWARD_CRON_HOUR"] = prompt("每日领奖时间（UTC 小时，0-23）", "2")
    settings["COPYTRADING_INTERVAL_HOURS"] = prompt("巨鲸跟单间隔（小时）", "4")
    settings["MAX_SINGLE_TRADE_USDC"] = prompt("单笔交易上限（USDC）", "10")
    settings["MAX_DAILY_TRADE_USDC"] = prompt("每日交易上限（USDC）", "500")
    settings["DIVERGENCE_THRESHOLD_PCT"] = prompt("套利偏差阈值（%）", "10")
    settings["WHALE_WIN_RATE_THRESHOLD"] = prompt("跟单巨鲸最低胜率（%）", "75")

    lines = []
    lines.append("# === Telegram ===")
    lines.append(f"TELEGRAM_BOT_TOKEN={settings['TELEGRAM_BOT_TOKEN']}")
    lines.append(f"TELEGRAM_ADMIN_IDS={settings['TELEGRAM_ADMIN_IDS']}")
    lines.append("")
    lines.append("# === Simmer API ===")
    lines.append(f"SIMMER_API_KEY={settings['SIMMER_API_KEY']}")
    lines.append("")
    lines.append("# === 交易参数 ===")
    lines.append(f"SCAN_INTERVAL_MINUTES={settings['SCAN_INTERVAL_MINUTES']}")
    lines.append(f"REWARD_CRON_HOUR={settings['REWARD_CRON_HOUR']}")
    lines.append(f"COPYTRADING_INTERVAL_HOURS={settings['COPYTRADING_INTERVAL_HOURS']}")
    lines.append(f"MAX_SINGLE_TRADE_USDC={settings['MAX_SINGLE_TRADE_USDC']}")
    lines.append(f"MAX_DAILY_TRADE_USDC={settings['MAX_DAILY_TRADE_USDC']}")
    lines.append(f"DIVERGENCE_THRESHOLD_PCT={settings['DIVERGENCE_THRESHOLD_PCT']}")
    lines.append(f"WHALE_WIN_RATE_THRESHOLD={settings['WHALE_WIN_RATE_THRESHOLD']}")
    lines.append("")

    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n✅ 配置已保存到 {ENV_PATH}")
    print("\n启动机器人:")
    print(f"  cd {ENV_PATH.parent}")
    print("  python main.py")


if __name__ == "__main__":
    main()
