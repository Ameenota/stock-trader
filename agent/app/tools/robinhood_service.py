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

import os
import sys
from typing import Tuple, List, Dict, Any
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from app.tools.ticker_universe import get_allowed_tickers

async def validate_and_intercept_trades(tool, args, tool_context) -> dict | None:
    """Interceptor callback (Double Guardrail + Dry Run) for trading execution."""
    print(f"   [DEBUG INTERCEPT] Tool '{tool.name}' called with args: {args}")
    
    # 1. Enforce Robinhood Account Restriction
    account_keys = [k for k in args.keys() if "account" in k.lower()]
    for key in account_keys:
        val = args.get(key)
        if val:
            val_str = str(val).strip()
            if not val_str.endswith("48661"):
                raise ValueError(
                    f"Security Exception: Operation rejected. Tool '{tool.name}' attempted to access "
                    f"unauthorized account '{val_str}'. All actions are restricted to account ending in 48661."
                )

    # 2. Enforce Predefined 40-Asset Universe
    ticker_keys = [k for k in args.keys() if "symbol" in k.lower() or "ticker" in k.lower()]
    ALLOWED_TICKERS = set(get_allowed_tickers())
    for key in ticker_keys:
        val = args.get(key)
        if val:
            if isinstance(val, (list, tuple)):
                tickers_to_check = val
            elif isinstance(val, str):
                if "," in val:
                    tickers_to_check = [t.strip() for t in val.split(",")]
                else:
                    tickers_to_check = [val]
            else:
                tickers_to_check = [str(val)]
                
            for ticker in tickers_to_check:
                ticker_str = str(ticker).strip().upper()
                if ticker_str and ticker_str not in ALLOWED_TICKERS:
                    raise ValueError(
                        f"Security Exception: Operation rejected. Ticker '{ticker_str}' is outside the authorized asset universe."
                    )

    # 3. Dry-Run Interceptor: block order modifications and return simulated success
    if os.environ.get("SKIP_LIVE_TRADES", "true").lower() == "true":
        tool_name = tool.name.lower()
        if "insert_trade_record" not in tool_name:
            if any(action in tool_name for action in ["order", "buy", "sell", "trade", "execute", "cancel"]):
                print(f"[DRY_RUN] Intercepted trade order tool '{tool.name}' with args: {args}")
                return {
                    "status": "success",
                    "message": f"[DRY_RUN] Simulated execution successfully for {tool.name}",
                    "order_id": "dry-run-mock-order-id-12345",
                    "simulated": True
                }

    return None


# Initialize the MCP toolset with mcp-remote for authenticated trading tools
robinhood_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="npx",
            args=["-y", "mcp-remote", "https://agent.robinhood.com/mcp/trading"]
        ),
        timeout=300.0  # 5-minute timeout to allow interactive OAuth sign-in
    )
)


async def fetch_robinhood_portfolio_state(account_number: str) -> Tuple[float, float, List[Dict[str, Any]]]:
    """Queries Robinhood MCP tools for current cash, buying power and holdings.
    
    Returns:
        A tuple (total_cash, buying_power, holdings) where holdings is a list of dicts.
    """
    total_cash = 100.0
    buying_power = 100.0
    holdings = []

    try:
        tools = await robinhood_toolset.get_tools()
        tools_dict = {t.name: t for t in tools}

        if "get_portfolio" in tools_dict:
            try:
                port_res = await tools_dict["get_portfolio"].run_async(args={"account_number": account_number}, tool_context=None)
                data = port_res.get("structuredContent", {}).get("data", {})
                total_cash = float(data.get("cash", 100.0))
                buying_power = float(data.get("buying_power", {}).get("buying_power", total_cash))
            except Exception as e:
                print(f"   [ERROR] get_portfolio failed: {e}")

        if "get_equity_positions" in tools_dict:
            try:
                pos_res = await tools_dict["get_equity_positions"].run_async(args={"account_number": account_number}, tool_context=None)
                positions = pos_res.get("structuredContent", {}).get("data", {}).get("positions", [])
                
                active_symbols = []
                symbol_shares = {}
                symbol_cost = {}
                
                for pos in positions:
                    qty = float(pos.get("quantity", 0))
                    if qty > 0:
                        sym = pos["symbol"]
                        active_symbols.append(sym)
                        symbol_shares[sym] = qty
                        symbol_cost[sym] = float(pos.get("average_buy_price", 0))

                if active_symbols and "get_equity_quotes" in tools_dict:
                    quotes_res = await tools_dict["get_equity_quotes"].run_async(args={"symbols": active_symbols}, tool_context=None)
                    results = quotes_res.get("structuredContent", {}).get("data", {}).get("results", [])
                    for res in results:
                        quote = res.get("quote", {})
                        sym = quote.get("symbol")
                        if sym in symbol_shares:
                            price = float(quote.get("last_non_reg_trade_price") or quote.get("last_trade_price") or 0.0)
                            qty = symbol_shares[sym]
                            holdings.append({
                                "symbol": sym,
                                "shares": qty,
                                "average_buy_price": symbol_cost[sym],
                                "current_price": price,
                                "equity": qty * price
                            })
            except Exception as e:
                print(f"   [ERROR] get_equity_positions failed: {e}")
    except Exception as e:
        print(f"   Warning: Failed to fetch live portfolio state from Robinhood: {e}")

    return total_cash, buying_power, holdings


async def log_portfolio_snapshot(dataset_id: str = "portfolio_analytics") -> None:
    """Queries Robinhood portfolio cash and positions, and logs a snapshot to BigQuery."""
    import json
    from app.tools.bigquery_service import insert_portfolio_snapshot

    # Resolve target account ending in 48661
    account_number = os.environ.get("ROBINHOOD_ACCOUNT_NUMBER")
    if not account_number:
        if os.environ.get("SKIP_LIVE_TRADES", "true").lower() == "true":
            account_number = "MOCK_ACCOUNT_48661"
        else:
            raise RuntimeError("Security Guardrail: ROBINHOOD_ACCOUNT_NUMBER environment variable is not set.")

    if not account_number or not str(account_number).endswith("48661"):
        raise RuntimeError(f"Security Guardrail: Unauthorized Robinhood account '{account_number}'. All operations restricted to accounts ending in 48661.")

    total_cash, buying_power, holdings = await fetch_robinhood_portfolio_state(account_number)
    holdings_value = sum(h["equity"] for h in holdings)
    total_equity = total_cash + holdings_value
    unrealized_gain_loss = total_equity - 100.0
    unrealized_gain_loss_percent = (unrealized_gain_loss / 100.0) * 100.0

    snapshot = {
        "account_number": f"••••{account_number[-5:]}" if len(account_number) >= 5 else account_number,
        "total_equity": total_equity,
        "total_cash": total_cash,
        "buying_power": buying_power,
        "unrealized_gain_loss": unrealized_gain_loss,
        "unrealized_gain_loss_percent": unrealized_gain_loss_percent,
        "holdings": json.dumps(holdings)
    }

    insert_portfolio_snapshot(snapshot, dataset_id=dataset_id)
