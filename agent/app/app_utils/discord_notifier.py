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
