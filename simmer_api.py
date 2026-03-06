"""
Simmer API client.
Uses simmer-sdk SimmerClient for both virtual ($SIM) and real (USDC) trading.
Includes on-chain balance queries via Polygon RPC.
"""

import logging
from datetime import datetime, timezone

import requests as http_requests
from simmer_sdk import SimmerClient

import config

POLYGON_RPC = "https://1rpc.io/matic"
USDC_E_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_NATIVE_CONTRACT = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
ERC20_BALANCE_OF_SIG = "0x70a08231"

logger = logging.getLogger(__name__)

_sim_client: SimmerClient | None = None
_real_client: SimmerClient | None = None


def _get_sim_client() -> SimmerClient:
    global _sim_client
    if _sim_client is None:
        _sim_client = SimmerClient(
            api_key=config.SIMMER_API_KEY,
            venue="simmer",
        )
        logger.info("SimmerClient (simmer/SIM) initialized")
    return _sim_client


def _get_real_client() -> SimmerClient | None:
    global _real_client
    if _real_client is not None:
        return _real_client
    pk = config.WALLET_PRIVATE_KEY
    if not pk:
        return None
    _real_client = SimmerClient(
        api_key=config.SIMMER_API_KEY,
        venue="polymarket",
        private_key=pk,
    )
    logger.info("SimmerClient (polymarket/USDC) initialized, wallet: %s", _real_client.wallet_address)
    return _real_client


def get_client(venue: str = "simmer") -> SimmerClient:
    """Get the appropriate client based on venue."""
    if venue == "polymarket":
        client = _get_real_client()
        if client is None:
            raise ValueError("未配置 WALLET_PRIVATE_KEY，无法进行真实交易")
        return client
    return _get_sim_client()


def get_agent_info() -> dict:
    """Fetch agent profile via raw API (not in SDK)."""
    import requests
    resp = requests.get(
        f"{config.SIMMER_BASE_URL}/agents/me",
        headers={
            "Authorization": f"Bearer {config.SIMMER_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def get_briefing() -> dict:
    """Fetch current briefing via raw API."""
    resp = http_requests.get(
        f"{config.SIMMER_BASE_URL}/briefing",
        headers={
            "Authorization": f"Bearer {config.SIMMER_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def get_trades() -> list[dict]:
    """Fetch trade history via raw API."""
    resp = http_requests.get(
        f"{config.SIMMER_BASE_URL}/trades",
        headers={
            "Authorization": f"Bearer {config.SIMMER_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("trades", [])


def get_market_detail(market_id: str) -> dict | None:
    """Fetch single market detail including resolution outcome."""
    try:
        resp = http_requests.get(
            f"{config.SIMMER_BASE_URL}/markets/{market_id}",
            headers={
                "Authorization": f"Bearer {config.SIMMER_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("market")
    except Exception as e:
        logger.warning("Failed to fetch market %s: %s", market_id[:16], e)
    return None


def compute_trade_pnl(trade: dict) -> dict:
    """Compute P&L for a single trade by checking market resolution."""
    cost = float(trade.get("cost", 0))
    shares = float(trade.get("shares", 0))
    side = trade.get("side", "yes")
    market_id = trade.get("market_id", "")

    result = {"cost": cost, "shares": shares, "status": "unknown", "pnl": 0.0, "payout": 0.0}

    market = get_market_detail(market_id)
    if market is None:
        return result

    outcome = market.get("outcome")

    if outcome is not None:
        won = (side == "yes" and outcome is True) or (side == "no" and outcome is False)
        if won:
            result["payout"] = shares
            result["pnl"] = shares - cost
            result["status"] = "win"
        else:
            result["payout"] = 0.0
            result["pnl"] = -cost
            result["status"] = "loss"
    else:
        current_price = float(market.get("current_price", 0.5))
        if side == "no":
            current_price = 1.0 - current_price
        result["payout"] = shares * current_price
        result["pnl"] = result["payout"] - cost
        result["status"] = "active"

    return result


def get_portfolio() -> dict:
    """Fetch portfolio summary."""
    client = _get_sim_client()
    return client.get_portfolio()


def _query_erc20_balance(address: str, contract: str) -> float:
    """Query ERC20 token balance from Polygon chain (6 decimals for USDC)."""
    call_data = ERC20_BALANCE_OF_SIG + address[2:].lower().zfill(64)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": contract, "data": call_data}, "latest"],
    }
    resp = http_requests.post(POLYGON_RPC, json=payload, timeout=15)
    result = resp.json().get("result", "0x0")
    return int(result, 16) / 1e6


def _query_native_balance(address: str) -> float:
    """Query native POL balance from Polygon chain."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBalance",
        "params": [address, "latest"],
    }
    resp = http_requests.post(POLYGON_RPC, json=payload, timeout=15)
    result = resp.json().get("result", "0x0")
    return int(result, 16) / 1e18


def get_onchain_balances(address: str) -> dict:
    """Query all on-chain balances for a Polygon address."""
    balances = {}
    try:
        balances["usdc_e"] = _query_erc20_balance(address, USDC_E_CONTRACT)
    except Exception as e:
        logger.warning("Failed to query USDC.e balance: %s", e)
        balances["usdc_e"] = None

    try:
        balances["usdc_native"] = _query_erc20_balance(address, USDC_NATIVE_CONTRACT)
    except Exception as e:
        logger.warning("Failed to query native USDC balance: %s", e)
        balances["usdc_native"] = None

    try:
        balances["pol"] = _query_native_balance(address)
    except Exception as e:
        logger.warning("Failed to query POL balance: %s", e)
        balances["pol"] = None

    return balances


def get_wallet_info() -> dict:
    """Get real wallet status and on-chain balance info."""
    real = _get_real_client()
    if real is None:
        return {"configured": False, "address": None, "error": "WALLET_PRIVATE_KEY 未配置"}

    address = real.wallet_address
    info = {
        "configured": True,
        "address": address,
        "has_wallet": real.has_external_wallet,
    }

    onchain = get_onchain_balances(address)
    info["usdc_e"] = onchain.get("usdc_e")
    info["usdc_native"] = onchain.get("usdc_native")
    info["pol"] = onchain.get("pol")

    try:
        portfolio = real.get_portfolio()
        info["simmer_balance_usdc"] = portfolio.get("balance_usdc", 0)
        info["total_exposure"] = portfolio.get("total_exposure", 0)
        info["positions_count"] = portfolio.get("positions_count", 0)
    except Exception as e:
        info["portfolio_error"] = str(e)

    try:
        approvals = real.check_approvals()
        info["approvals_ready"] = approvals.get("all_set", False)
        info["approvals_detail"] = approvals
    except Exception as e:
        info["approvals_error"] = str(e)

    return info


def link_wallet() -> dict:
    """Link external wallet to Simmer account."""
    real = _get_real_client()
    if real is None:
        return {"success": False, "error": "WALLET_PRIVATE_KEY 未配置"}
    return real.link_wallet()


def ensure_approvals() -> dict:
    """Check and return missing Polymarket approvals."""
    real = _get_real_client()
    if real is None:
        return {"ready": False, "error": "WALLET_PRIVATE_KEY 未配置"}
    return real.ensure_approvals()


def redeem_winning_trade(market_id: str, side: str) -> dict:
    """Redeem a winning position: get unsigned tx from Simmer, sign locally, send to chain."""
    from eth_account import Account

    real = _get_real_client()
    if real is None:
        return {"success": False, "error": "WALLET_PRIVATE_KEY not configured"}

    resp = http_requests.post(
        f"{config.SIMMER_BASE_URL}/redeem",
        headers={
            "Authorization": f"Bearer {config.SIMMER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"market_id": market_id, "side": side},
        timeout=60,
    )

    if resp.status_code != 200:
        return {"success": False, "error": resp.text[:200]}

    data = resp.json()
    if not data.get("success") or not data.get("unsigned_tx"):
        return {"success": False, "error": data.get("error") or data.get("detail", "No unsigned_tx")}

    utx = data["unsigned_tx"]
    acct = Account.from_key(config.WALLET_PRIVATE_KEY)

    nonce_resp = http_requests.post(POLYGON_RPC, json={
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_getTransactionCount",
        "params": [acct.address, "pending"],
    }, timeout=15)
    current_nonce = int(nonce_resp.json()["result"], 16)

    tx = {
        "from": acct.address,
        "to": utx["to"],
        "data": utx["data"],
        "chainId": utx.get("chainId", 137),
        "gas": utx.get("gas", 200000),
        "maxFeePerGas": utx.get("maxFeePerGas", 50000000000),
        "maxPriorityFeePerGas": utx.get("maxPriorityFeePerGas", 30000000000),
        "nonce": current_nonce,
        "type": 2,
        "value": 0,
    }

    signed = acct.sign_transaction(tx)
    raw_hex = "0x" + signed.raw_transaction.hex()

    send_resp = http_requests.post(POLYGON_RPC, json={
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_sendRawTransaction",
        "params": [raw_hex],
    }, timeout=30)
    send_result = send_resp.json()

    if "result" in send_result:
        tx_hash = send_result["result"]
        logger.info("Redeem TX sent: %s for market %s %s", tx_hash, market_id[:16], side)
        return {"success": True, "tx_hash": tx_hash}

    error_msg = send_result.get("error", {}).get("message", str(send_result))
    logger.error("Redeem TX failed: %s", error_msg)
    return {"success": False, "error": error_msg}


def auto_redeem_resolved_trades() -> list[dict]:
    """Check all trades for resolved winning positions and redeem them."""
    results = []
    try:
        trades = get_trades()
    except Exception as e:
        logger.warning("Failed to fetch trades for auto-redeem: %s", e)
        return results

    for t in trades:
        if t.get("venue") != "polymarket":
            continue

        market_id = t.get("market_id", "")
        side = t.get("side", "")
        market = get_market_detail(market_id)
        if market is None:
            continue

        outcome = market.get("outcome")
        if outcome is None:
            continue

        won = (side == "yes" and outcome is True) or (side == "no" and outcome is False)
        if not won:
            continue

        redeem_result = redeem_winning_trade(market_id, side)
        redeem_result["market_question"] = t.get("market_question", "")[:40]
        redeem_result["side"] = side
        results.append(redeem_result)

    return results


def execute_trade(
    market_id: str,
    side: str,
    amount_usdc: float,
    reasoning: str,
    venue: str = "simmer",
) -> dict:
    """
    Place a trade via SimmerClient.

    Args:
        venue: "simmer" for virtual, "polymarket" for real USDC
    """
    if amount_usdc > config.MAX_SINGLE_TRADE_USDC:
        raise ValueError(
            f"交易金额 {amount_usdc} 超过单笔限额 {config.MAX_SINGLE_TRADE_USDC} USDC"
        )

    client = get_client(venue)
    result = client.trade(
        market_id=market_id,
        side=side,
        amount=amount_usdc,
        reasoning=reasoning,
        source="tg-bot:manual",
    )

    result_dict = {
        "success": result.success,
        "trade_id": result.trade_id,
        "market_id": result.market_id,
        "side": result.side,
        "shares_bought": result.shares_bought,
        "cost": result.cost,
        "new_price": result.new_price,
        "balance": result.balance,
        "error": result.error,
        "venue": venue,
    }

    if result.success:
        logger.info(
            "Trade OK: %s %s $%.2f on %s [%s]",
            side, market_id[:16], amount_usdc, venue, result.trade_id,
        )
    else:
        logger.warning("Trade FAILED: %s", result.error)

    return result_dict


def get_positions(venue: str = "simmer") -> list:
    """Get current open positions."""
    client = get_client(venue)
    return client.get_positions()


def get_markets(status: str = "active", source: str = "polymarket", limit: int = 10) -> list:
    """Get available markets."""
    client = _get_sim_client()
    return client.get_markets(status=status, import_source=source, limit=limit)


def find_markets(query: str) -> list:
    """Search markets by keyword."""
    client = _get_sim_client()
    return client.find_markets(query)


def format_briefing(briefing: dict, agent_info: dict | None = None) -> str:
    """Format briefing data into a readable Telegram message."""
    lines = ["📊 *Simmer Briefing*", ""]

    real = _get_real_client()
    if real and real.wallet_address:
        addr = real.wallet_address
        lines.append(f"🔗 钱包: `{addr[:6]}...{addr[-4:]}`")
        try:
            onchain = get_onchain_balances(addr)
            usdc_e = onchain.get("usdc_e")
            pol = onchain.get("pol")
            if usdc_e is not None:
                lines.append(f"💵 USDC.e: ${usdc_e:,.2f}")
            if pol is not None:
                lines.append(f"⛽ POL: {pol:,.2f}")
        except Exception:
            lines.append("💵 链上余额: 查询失败")
        lines.append("")

    try:
        trades = get_trades()
        real_trades = [t for t in trades if t.get("venue") == "polymarket"]
        if real_trades:
            total_cost = 0.0
            total_pnl = 0.0
            wins = 0
            losses = 0
            trade_lines: list[str] = []

            for t in real_trades[:10]:
                pnl_info = compute_trade_pnl(t)
                cost = pnl_info["cost"]
                pnl = pnl_info["pnl"]
                status = pnl_info["status"]
                total_cost += cost
                total_pnl += pnl

                q = t.get("market_question", "Unknown")[:28]
                side = t.get("side", "?").upper()

                if status == "win":
                    wins += 1
                    icon = "✅"
                    pnl_text = f"+${pnl:.2f}"
                elif status == "loss":
                    losses += 1
                    icon = "❌"
                    pnl_text = f"-${abs(pnl):.2f}"
                elif status == "active":
                    icon = "⏳"
                    pnl_text = f"${pnl:+.2f} (未结算)"
                else:
                    icon = "❓"
                    pnl_text = "未知"

                trade_lines.append(f"  {icon} {q}")
                trade_lines.append(f"     {side} ${cost:.2f} → {pnl_text}")

            pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
            lines.append(f"📊 *交易记录: {len(real_trades)} 笔* (赢 {wins} / 亏 {losses})")
            lines.append(f"💸 总投入: ${total_cost:,.2f}")
            lines.append(f"{pnl_emoji} 总盈亏: ${total_pnl:+.2f}")
            lines.extend(trade_lines)
            lines.append("")
    except Exception as e:
        logger.warning("Trade history fetch failed: %s", e)

    perf = briefing.get("performance", {})
    rank = perf.get("rank")
    if rank:
        lines.append(f"🏆 排名: #{rank} / {perf.get('total_agents', '?')}")

    venues = briefing.get("venues", {})
    has_venue_data = False
    for venue_name, venue_data in venues.items():
        if venue_data:
            has_venue_data = True
            balance = venue_data.get("balance", "N/A")
            positions = venue_data.get("positions", [])
            lines.append(f"🏦 {venue_name}: ${balance}")
            if positions:
                for pos in positions[:5]:
                    name = pos.get("question", pos.get("market_name", "Unknown"))[:30]
                    pnl = pos.get("pnl", 0)
                    emoji = "🟢" if pnl >= 0 else "🔴"
                    lines.append(f"  {emoji} {name}: ${pnl:+.2f}")
    if not has_venue_data:
        lines.append("🏦 交易所: 尚未进行过交易（首次交易后显示）")
    lines.append("")

    alerts = briefing.get("risk_alerts", [])
    if alerts:
        lines.append(f"⚠️ 风险提醒: {len(alerts)} 条")
        for alert in alerts[:3]:
            msg = alert.get("message", str(alert)) if isinstance(alert, dict) else str(alert)
            lines.append(f"  🔸 {msg[:50]}")
    else:
        lines.append("✅ 无风险提醒")

    lines.append("")
    opps = briefing.get("opportunities", {})
    new_markets = opps.get("new_markets", [])
    high_score = [m for m in new_markets if m.get("opportunity_score", 0) > 0]
    if high_score:
        lines.append(f"🎯 机会市场: {len(high_score)} 个")
        for m in high_score[:5]:
            q = m.get("question", "Unknown")[:40]
            score = m.get("opportunity_score", 0)
            ttl = m.get("time_to_resolution", "?")
            lines.append(f"  💡 {q}")
            lines.append(f"     评分: {score} | 结算: {ttl}")
    else:
        lines.append(f"🎯 新市场: {len(new_markets)} 个（暂无高分机会）")

    skills = opps.get("recommended_skills", [])
    if skills:
        lines.append("")
        lines.append(f"🛠 推荐策略: {len(skills)} 个")
        for s in skills[:3]:
            lines.append(f"  • {s.get('name', '?')}")

    lines.append("")
    lines.append(f"🕐 更新: {briefing.get('checked_at', 'N/A')[:19]}")

    return "\n".join(lines)


def format_wallet_info(info: dict) -> str:
    """Format wallet info into Telegram message."""
    lines = ["🔐 *钱包状态*", ""]

    if not info.get("configured"):
        lines.append("❌ 未配置钱包私钥")
        lines.append("")
        lines.append("请在 `.env` 文件中设置:")
        lines.append("`WALLET_PRIVATE_KEY=0x...`")
        lines.append("")
        lines.append("⚠️ 私钥仅在本地签名使用，不会上传到任何服务器")
        return "\n".join(lines)

    addr = info.get("address", "N/A")
    lines.append(f"📍 地址: `{addr}`")
    lines.append(f"🔗 Polygonscan: [查看](https://polygonscan.com/address/{addr})")
    lines.append("")

    lines.append("*链上余额 (Polygon):*")
    usdc_e = info.get("usdc_e")
    if usdc_e is not None:
        lines.append(f"  💵 USDC.e: ${usdc_e:,.6f}")
    else:
        lines.append("  💵 USDC.e: 查询失败")

    usdc_native = info.get("usdc_native")
    if usdc_native is not None and usdc_native > 0:
        lines.append(f"  💵 USDC: ${usdc_native:,.6f}")

    pol = info.get("pol")
    if pol is not None:
        lines.append(f"  ⛽ POL: {pol:,.4f}")
    else:
        lines.append("  ⛽ POL: 查询失败")
    lines.append("")

    simmer_usdc = info.get("simmer_balance_usdc")
    if simmer_usdc is not None:
        lines.append(f"*Simmer 托管余额:*")
        lines.append(f"  💰 USDC: ${simmer_usdc:,.2f}")
    if "total_exposure" in info:
        lines.append(f"  📊 总敞口: ${info['total_exposure']:,.2f}")
    if "positions_count" in info:
        lines.append(f"  📋 持仓数: {info['positions_count']}")
    lines.append("")

    if info.get("approvals_ready"):
        lines.append("✅ Polymarket 授权: 已完成")
    elif "approvals_error" in info:
        lines.append(f"⚠️ 授权检查失败: {info['approvals_error'][:50]}")
    else:
        lines.append("⚠️ Polymarket 授权: 未完成")
        lines.append("使用 /approve 完成授权")

    return "\n".join(lines)
