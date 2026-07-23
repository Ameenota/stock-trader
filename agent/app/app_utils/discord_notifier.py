# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def send_discord_webhook(
    summary: str,
    approved_allocations: List[Dict[str, Any]],
    decisions: List[Dict[str, Any]],
    is_dry_run: bool = True,
    execution_result: Dict[str, Any] = None
) -> bool:
    """Sends a formatted summary of daily trading decisions, target allocations, and executed trades to Discord via a Webhook.
    
    Args:
        summary: Concise summary string of the day's action.
        approved_allocations: List of target allocations with 'ticker' and 'weight_pct'.
        decisions: List of asset decisions containing 'ticker', 'signal', and 'thesis'.
        is_dry_run: Whether the pipeline was run in dry-run mode (SKIP_LIVE_TRADES=true).
        execution_result: Dict containing 'sells', 'buys', and 'buy_power_skip' info.
        
    Returns:
        bool: True if sent successfully, False otherwise.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("Discord integration bypassed: DISCORD_WEBHOOK_URL is not set in environment.")
        print("⚠️ [DISCORD] Bypassed notification. DISCORD_WEBHOOK_URL environment variable is missing.")
        return False

    # Define color (Green for Live, Blue for Dry Run/Simulation, Red for Error/No Action)
    color = 0x3498DB if is_dry_run else 0x2ECC71  # Blue (3447003) vs Green (3066993)

    # Format Allocations
    alloc_lines = []
    total_allocated = 0.0
    for alloc in approved_allocations:
        if isinstance(alloc, dict):
            ticker = alloc.get("ticker", "UNKNOWN")
            weight = alloc.get("weight_pct", 0.0)
        else:
            ticker = getattr(alloc, "ticker", "UNKNOWN")
            weight = getattr(alloc, "weight_pct", 0.0)
            
        # Convert fraction to percentage if needed
        weight_val = weight * 100 if weight <= 1.0 else weight
        total_allocated += weight_val
        alloc_lines.append(f"• **{ticker}**: `{weight_val:.1f}%` weight")
    
    # Calculate implicit cash
    cash_pct = max(0.0, 100.0 - total_allocated)
    if cash_pct > 0:
        alloc_lines.append(f"• **CASH (USD)**: `{cash_pct:.1f}%` weight (Implicit cash buffer)")
        
    allocations_str = "\n".join(alloc_lines) if alloc_lines else "No allocations proposed."

    # Format Decisions / Watchlist Actions
    decision_lines = []
    for d in decisions:
        if isinstance(d, dict):
            ticker = d.get("ticker", "UNKNOWN")
            signal = d.get("signal", "HOLD")
            thesis = d.get("thesis", "No thesis provided.")
        else:
            ticker = getattr(d, "ticker", "UNKNOWN")
            signal = getattr(d, "signal", "HOLD")
            thesis = getattr(d, "thesis", "No thesis provided.")
        
        # Emoji representation for signal
        emoji = "⚪"
        if signal == "STRONG BUY":
            emoji = "🟢"
        elif signal == "LIQUIDATE":
            emoji = "🔴"
            
        decision_lines.append(f"{emoji} **{ticker}** (`{signal}`)\n*{thesis}*")
        
    decisions_str = "\n\n".join(decision_lines) if decision_lines else "No watchlist decisions today."

    # Construct the Discord Embed Payload fields dynamically
    fields = [
        {
            "name": "📊 Target Allocations",
            "value": allocations_str,
            "inline": True
        },
        {
            "name": "⚙️ Execution Context",
            "value": f"• **Mode**: `{'Dry Run (Simulation)' if is_dry_run else 'Live Account (48661)'}`\n• **Timestamp**: `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}`",
            "inline": True
        }
    ]

    # Add executed trades details if present
    if execution_result:
        trade_lines = []
        sells = execution_result.get("sells", [])
        buys = execution_result.get("buys", [])
        buy_power_skip = execution_result.get("buy_power_skip", False)

        for sell in sells:
            action = "🔴 LIQUIDATE" if sell.get("liquidate") else "🟠 REDUCE"
            trade_lines.append(f"• {action} **{sell['ticker']}**: {sell['shares']:.4f} shares (~${sell['amount_usd']:.2f})")

        for buy in buys:
            trade_lines.append(f"• 🟢 BUY **{buy['ticker']}**: {buy['shares']:.4f} shares (~${buy['amount_usd']:.2f})")

        if buy_power_skip:
            trade_lines.append("• ⚠️ *Buys skipped due to Buying Power Guard (waiting for cash settlement).*")
        
        trades_str = "\n".join(trade_lines) if trade_lines else "• No trades executed (portfolio within tolerance)."
        fields.append({
            "name": "💸 Executed Orders" + (" (Simulated)" if is_dry_run else ""),
            "value": trades_str[:1024],
            "inline": False
        })

    fields.append({
        "name": "🔍 Watchlist Actions & Theses",
        "value": decisions_str[:1024],
        "inline": False
    })

    payload = {
        "username": "AI Stock Trader Bot",
        "avatar_url": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=256&h=256&q=80",
        "embeds": [
            {
                "title": "📈 Daily Portfolio Optimization & Rebalance" + (" (DRY RUN)" if is_dry_run else " (LIVE EXECUTION)"),
                "description": summary,
                "color": color,
                "fields": fields,
                "footer": {
                    "text": "Multi-Agent Trading System • powered by Gemini Flash 1.5"
                }
            }
        ]
    }

    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; StockTraderBot/1.0)"
            },
            method="POST"
        )
        with urllib.request.urlopen(req) as response:
            if response.status in (200, 204):
                print("✅ [DISCORD] Successfully posted daily execution update.")
                return True
            else:
                logger.error(f"Failed to send Discord webhook: status code {response.status}")
                return False
    except urllib.error.URLError as e:
        logger.error(f"Network error sending Discord webhook: {e}")
        print(f"⚠️ [DISCORD] Network error sending notification: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending Discord webhook: {e}")
        print(f"⚠️ [DISCORD] Unexpected error sending notification: {e}")
        return False


def send_accounts_summary_webhook(
    accounts: List[Dict[str, Any]],
    *,
    run_kind: str,
    is_dry_run: bool,
) -> bool:
    """Send one registry-wide performance report after an account batch."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("Discord integration bypassed: DISCORD_WEBHOOK_URL is not set.")
        print("⚠️ [DISCORD] Bypassed consolidated account summary; webhook is missing.")
        return False

    fields = []
    combined_equity = 0.0
    combined_baseline = 0.0
    reported = 0
    processed_ids = []
    reporting_only_ids = []
    for account in accounts:
        account_id = str(account["account_id"])
        run_status = str(account.get("run_status", "NOT SELECTED"))
        attempted = run_status in {"PROCESSED", "FAILED"}
        batch_result = {
            "PROCESSED": "SUCCEEDED",
            "FAILED": "FAILED",
            "NOT RUN": "NOT RUN",
            "NOT SELECTED": "NOT SELECTED",
        }.get(run_status, run_status)
        if run_status in {"PROCESSED", "FAILED"}:
            processed_ids.append(account_id)
        else:
            reporting_only_ids.append(account_id)
        baseline = float(account["initial_cash"])
        equity = account.get("total_equity")
        cash = account.get("total_cash")
        if equity is None:
            performance = "No portfolio snapshot yet"
        else:
            equity = float(equity)
            cash = float(cash or 0.0)
            pnl = equity - baseline
            pnl_pct = pnl / baseline * 100
            pnl_money = f"{'+' if pnl >= 0 else '-'}${abs(pnl):,.2f}"
            combined_equity += equity
            combined_baseline += baseline
            reported += 1
            performance = (
                f"• **Equity**: `${equity:,.2f}`\n"
                f"• **Cash**: `${cash:,.2f}`\n"
                f"• **P&L vs ${baseline:,.2f}**: `{pnl_money}` (`{pnl_pct:+.2f}%`)"
            )
        holdings = account.get("holdings") or []
        symbols = ", ".join(
            str(item.get("symbol") or item.get("ticker") or "?")
            for item in holdings
        ) or "Cash only"
        recommendation = account.get("recommendation") or []
        target_lines = []
        target_total = 0.0
        for target in recommendation:
            weight = float(target.get("weight_pct") or 0.0)
            weight_pct = weight * 100 if abs(weight) <= 1 else weight
            target_total += weight_pct
            target_lines.append(
                f"{str(target.get('ticker') or '?').upper()} {weight_pct:.1f}%"
            )
        if target_total < 100:
            target_lines.append(f"CASH {max(0.0, 100 - target_total):.1f}%")
        targets_text = ", ".join(target_lines) or "No equity allocation"
        trade_lines = []
        for trade in account.get("trades") or []:
            action = str(trade.get("action") or "TRADE").upper()
            ticker = str(trade.get("ticker") or "?").upper()
            quantity = trade.get("filled_quantity")
            if quantity is None:
                quantity = trade.get("requested_quantity")
            amount = trade.get("amount_usd")
            detail = f"{action} {ticker}"
            if quantity is not None:
                detail += f" {float(quantity):.4f} sh"
            if amount is not None:
                detail += f" (~${float(amount):,.2f})"
            trade_lines.append(detail)
        trades_text = "; ".join(trade_lines) or "NO TRADE"
        decision_id = account.get("decision_id")
        decision_status = account.get("decision_status") or "UNKNOWN"
        activity = (
            f"• **Latest saved decision**: `{decision_id}` (`{decision_status}`)\n"
            f"• **Recommended target**: `{targets_text}`\n"
            f"• **Orders saved for that decision**: `{trades_text}`\n"
            if decision_id
            else "• **Latest saved decision**: `NONE`\n"
        )
        batch_error = account.get("run_error")
        batch_text = (
            f"• **Attempted this batch**: `{'YES' if attempted else 'NO'}`\n"
            f"• **Batch result**: `{batch_result}`\n"
        )
        if batch_error:
            batch_text += f"• **Batch error**: `{str(batch_error)[:300]}`\n"
        performance = (
            f"• **Account ID**: `{account_id}`\n"
            f"• **Ledger type**: `{account['account_type']}`\n"
            f"• **Account status**: `{account['status']}`\n"
            f"{batch_text}"
            f"{activity}"
            f"{performance}\n"
            f"• **Holdings**: `{symbols}`"
            f"\n• **Policy**: `{account['policy_name']}`"
        )
        fields.append({
            "name": (
                f"{'🟢' if account['account_type'] == 'REAL' else '🧪'} "
                f"{account['account_type']} · {account['display_name']}"
            ),
            "value": performance[:1024],
            "inline": False,
        })

    if reported:
        combined_pnl = combined_equity - combined_baseline
        combined_pct = combined_pnl / combined_baseline * 100
        combined_money = (
            f"{'+' if combined_pnl >= 0 else '-'}${abs(combined_pnl):,.2f}"
        )
        overall = (
            f"• **Accounts reported**: `{reported}/{len(accounts)}`\n"
            f"• **Combined equity**: `${combined_equity:,.2f}`\n"
            f"• **Combined starting capital**: `${combined_baseline:,.2f}`\n"
            f"• **Overall P&L**: `{combined_money}` (`{combined_pct:+.2f}%`)"
        )
    else:
        overall = "No account snapshots are available."
    fields.insert(0, {"name": "🎯 Overall Performance", "value": overall, "inline": False})

    processed_text = ", ".join(f"`{item}`" for item in processed_ids) or "none"
    reporting_text = (
        ", ".join(f"`{item}`" for item in reporting_only_ids) or "none"
    )
    payload = {
        "username": "AI Stock Trader Bot",
        "embeds": [{
            "title": "📊 All-Account Portfolio Summary" + (" (DRY RUN)" if is_dry_run else ""),
            "description": (
                f"`{run_kind.upper()}` batch complete. "
                f"Live orders were {'disabled' if is_dry_run else 'enabled'}.\n"
                f"**Accounts attempted this batch:** {processed_text}\n"
                f"**Reporting only:** {reporting_text}"
            ),
            "color": 0x3498DB if is_dry_run else 0x2ECC71,
            "fields": fields,
            "footer": {
                "text": f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} • account-scoped ledgers"
            },
        }],
    }
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "StockTraderBot/2.0"},
            method="POST",
        )
        with urllib.request.urlopen(req) as response:
            if response.status in (200, 204):
                print("✅ [DISCORD] Posted consolidated all-account summary.")
                return True
            logger.error("Discord summary failed with status %s", response.status)
            return False
    except Exception as exc:
        logger.error("Failed to send consolidated Discord summary: %s", exc)
        print(f"⚠️ [DISCORD] Failed consolidated account summary: {exc}")
        return False
