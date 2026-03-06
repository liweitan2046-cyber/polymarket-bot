# Polymarket Trading Bot

基于 Telegram 的 Polymarket 预测市场自动交易机器人。通过 Simmer API 获取 AI 概率与市场数据，支持多种自动化交易策略。

## 功能概览

- **Telegram 控制**：通过指令查看持仓、盈亏、搜索市场、触发扫描
- **五大自动策略**：AI 套利、巨鲸跟单、流动性挖矿、动量交易、结算狙击
- **风控机制**：单笔/日限、止损提醒、自动赎回
- **双模式**：SIM 模拟盘 / USDC 真实交易

## 前置要求

- Python 3.10+
- [Polymarket](https://polymarket.com) 账户
- [Simmer](https://simmer.markets) API 密钥
- Telegram Bot Token（通过 [@BotFather](https://t.me/BotFather) 创建）

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/liweitan2046-cyber/polymarket-bot.git
cd polymarket-bot
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制示例配置并填写：

```bash
cp .env.example .env
```

编辑 `.env` 文件，至少配置：

| 变量 | 说明 | 必填 |
|------|------|------|
| `TELEGRAM_BOT_TOKEN` | Telegram 机器人 Token | ✅ |
| `TELEGRAM_ADMIN_IDS` | 管理员 User ID，逗号分隔 | ✅ |
| `SIMMER_API_KEY` | Simmer API 密钥 | ✅ |
| `WALLET_PRIVATE_KEY` | 钱包私钥（仅真实交易需填） | 可选 |

### 4. 运行

```bash
python main.py
```

在 Telegram 中向机器人发送 `/start` 查看指令列表。

## Telegram 指令

| 指令 | 说明 |
|------|------|
| `/start` | 查看帮助与指令列表 |
| `/briefing` | Simmer 简报（持仓、盈亏、套利机会） |
| `/wallet` | 钱包余额与链上状态 |
| `/search <关键词>` | 搜索市场 |
| `/hot` | 热门市场 |
| `/positions` | 当前持仓 |
| `/scan` | 手动触发市场扫描 |
| `/status` | 机器人运行状态 |

## 五大交易策略

| 策略 | 频率 | 逻辑 |
|------|------|------|
| **AI 套利** | 每 30 分钟 | Simmer AI 概率 vs Polymarket 价格，偏差 >10% 时买入低估方向 |
| **巨鲸跟单** | 每 4 小时 | 跟随 Simmer 高胜率（>75%）巨鲸的交易信号 |
| **流动性挖矿** | 每天 2:00 UTC | 在热门市场挂 maker 单赚取平台奖励 |
| **动量交易** | 每 5 分钟 | 结合 Binance 加密货币 5 分钟涨跌，在快速市场做方向交易 |
| **结算狙击** | 每 3 分钟 | 在 30 分钟内即将结算、概率 >82% 或 <18% 的市场买入高概率方向 |

## 风控参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_SINGLE_TRADE_USDC` | 10 | 单笔最大交易金额（USDC） |
| `MAX_DAILY_TRADE_USDC` | 500 | 每日最大交易总额（USDC） |
| `DIVERGENCE_THRESHOLD_PCT` | 10 | AI 套利触发的最小偏差（%） |
| `WHALE_WIN_RATE_THRESHOLD` | 75 | 巨鲸跟单最低胜率（%） |
| 止损 | -50% | 持仓亏损超 50% 时发送提醒 |

## 交易模式

| 模式 | 配置 | 说明 |
|------|------|------|
| **SIM** | `TRADING_VENUE=simmer` | 模拟盘，虚拟资金，零风险 |
| **USDC** | `TRADING_VENUE=polymarket` + `WALLET_PRIVATE_KEY` | 真实 USDC 交易 |

建议先用 SIM 模式测试，再切换真实交易。

## 费用说明

本项目完全开源免费，不收取任何使用费。你只需自行准备：

- Polymarket 与 Simmer 账户
- Telegram Bot Token
- （真实交易时）Polygon 链上 USDC 与 POL（Gas）

## 项目结构

```
polymarket-bot/
├── main.py           # 入口
├── config.py         # 配置加载
├── telegram_bot.py   # Telegram 指令
├── scheduler.py      # 定时策略调度
├── simmer_api.py     # Simmer API 客户端
├── polymarket_api.py # Polymarket Gamma API
├── price_feed.py     # Binance 价格与动量
├── requirements.txt
├── .env.example
└── README.md
```

## 许可证

MIT License
