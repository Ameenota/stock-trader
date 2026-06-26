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
import uuid
import time
import json
from datetime import datetime, timezone
from app.tools.bigquery_service import insert_trade_record

# Terminal colors for beautiful outputs
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_RED = "\033[91m"
CLR_GREEN = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_BLUE = "\033[94m"
CLR_MAGENTA = "\033[95m"
CLR_CYAN = "\033[96m"

class ExecutionController:
    def __init__(self, toolset, account_number: str, dataset_id: str = "portfolio_analytics"):
        self.toolset = toolset
        self.account_number = account_number
        self.dataset_id = dataset_id

    async def execute_rebalance(self, approved_allocations: list) -> None:
        """Calculates trade deltas based on approved allocations and total equity,
        respects tolerance bands, executes sells first then buys, and logs to BigQuery."""
        print(f"\n{CLR_BOLD}{CLR_GREEN}=== Execution Controller: Starting Portfolio Rebalancing ==={CLR_RESET}")
        
        # Filter out CASH and USD pseudo-allocations
        approved_allocations = [
            a for a in approved_allocations 
            if a.get("ticker", "").upper() not in ("CASH", "USD")
        ]
        
        # 1. Get Robinhood tools from toolset
        tools = await self.toolset.get_tools()
        tools_dict = {t.name: t for t in tools}

        # 2. Fetch current holdings and cash from Robinhood
        print("Fetching live portfolio state from Robinhood...")
        total_cash = 100.0
        buying_power = 100.0
        positions = []

        if "get_portfolio" in tools_dict:
            try:
                port_res = await tools_dict["get_portfolio"].run_async(args={"account_number": self.account_number}, tool_context=None)
                data = port_res.get("structuredContent", {}).get("data", {})
                total_cash = float(data.get("cash", 100.0))
                buying_power = float(data.get("buying_power", {}).get("buying_power", total_cash))
            except Exception as e:
                print(f"   [ERROR] get_portfolio failed: {e}")
                
        if "get_equity_positions" in tools_dict:
            try:
                pos_res = await tools_dict["get_equity_positions"].run_async(args={"account_number": self.account_number}, tool_context=None)
                positions = pos_res.get("structuredContent", {}).get("data", {}).get("positions", [])
            except Exception as e:
                print(f"   [ERROR] get_equity_positions failed: {e}")

        # Extract current shares
        current_shares = {}
        for pos in positions:
            qty = float(pos.get("quantity", 0))
            if qty > 0:
                current_shares[pos["symbol"]] = qty

        # 3. Fetch quote prices for all tickers in target allocations and current holdings
        target_tickers = [alloc.get("ticker") for alloc in approved_allocations if alloc.get("ticker")]
        all_tickers = list(set(target_tickers + list(current_shares.keys())))
        
        current_prices = {}
        if all_tickers and "get_equity_quotes" in tools_dict:
            try:
                quotes_res = await tools_dict["get_equity_quotes"].run_async(args={"symbols": all_tickers}, tool_context=None)
                results = quotes_res.get("structuredContent", {}).get("data", {}).get("results", [])
                for res in results:
                    quote = res.get("quote", {})
                    sym = quote.get("symbol")
                    price = float(quote.get("last_non_reg_trade_price") or quote.get("last_trade_price") or 0.0)
                    if sym and price > 0:
                        current_prices[sym] = price
            except Exception as e:
                print(f"   [ERROR] get_equity_quotes failed: {e}")

        # Compute current holdings with equity value
        current_holdings_list = []
        holdings_value = 0.0
        for sym, qty in current_shares.items():
            price = current_prices.get(sym, 0.0)
            equity = qty * price
            holdings_value += equity
            current_holdings_list.append({
                "symbol": sym,
                "shares": qty,
                "current_price": price,
                "equity": equity
            })

        total_equity = total_cash + holdings_value
        print(f"   Live Cash Balance: {CLR_GREEN}${total_cash:.2f}{CLR_RESET}")
        print(f"   Live Holdings Value: ${holdings_value:.2f}")
        print(f"   Total Portfolio Equity: {CLR_BOLD}{CLR_GREEN}${total_equity:.2f}{CLR_RESET}")

        # Calculate current weight percentages
        current_weights = {}
        for h in current_holdings_list:
            current_weights[h["symbol"]] = h["equity"] / total_equity

        # Map target allocations
        target_weights = {alloc["ticker"]: alloc["weight_pct"] for alloc in approved_allocations}

        # 4. Compute trade deltas
        sells = []
        buys = []

        all_universe_tickers = list(set(list(target_weights.keys()) + list(current_weights.keys())))
        for ticker in all_universe_tickers:
            tgt_pct = target_weights.get(ticker, 0.0)
            cur_pct = current_weights.get(ticker, 0.0)
            cur_qty = current_shares.get(ticker, 0.0)
            price = current_prices.get(ticker, 0.0)

            # If price is 0, we cannot trade
            if price <= 0:
                print(f"   {CLR_YELLOW}[WARNING] Price for {ticker} is 0 or missing. Skipping.{CLR_RESET}")
                continue

            delta_pct = tgt_pct - cur_pct
            
            # Position Sizing Rule: target is 30% (+/- 3% tolerance)
            # If current weight is within +/- 3% of the target, do not adjust,
            # UNLESS complete liquidation (target is 0) or brand new purchase (current is 0)
            if tgt_pct > 0.0 and cur_pct > 0.0 and abs(delta_pct) <= 0.03:
                print(f"   {CLR_BLUE}[TOLERANCE] Ticker {ticker} is at {cur_pct*100:.1f}%, target {tgt_pct*100:.1f}% (within 3% band). Skipping rebalance.{CLR_RESET}")
                continue

            delta_usd = delta_pct * total_equity
            
            if delta_usd < -0.01:
                # If target is 0, liquidate 100% of quantity
                if tgt_pct == 0.0:
                    sells.append({
                        "ticker": ticker,
                        "shares": cur_qty,
                        "amount_usd": cur_qty * price,
                        "liquidate": True,
                        "reasoning": f"Liquidating 100% of {ticker} as it is no longer in target allocations."
                    })
                else:
                    shares_to_sell = abs(delta_usd) / price
                    sells.append({
                        "ticker": ticker,
                        "shares": shares_to_sell,
                        "amount_usd": abs(delta_usd),
                        "liquidate": False,
                        "reasoning": f"Reducing weight in {ticker} from {cur_pct*100:.1f}% to target {tgt_pct*100:.1f}%."
                    })
            elif delta_usd > 0.01:
                shares_to_buy = delta_usd / price
                buys.append({
                    "ticker": ticker,
                    "shares": shares_to_buy,
                    "amount_usd": delta_usd,
                    "reasoning": f"Increasing weight in {ticker} from {cur_pct*100:.1f}% to target {tgt_pct*100:.1f}%."
                })

        # 5. Execute Sells First
        for sell in sells:
            ticker = sell["ticker"]
            shares = sell["shares"]
            amt = sell["amount_usd"]
            reason = sell["reasoning"]
            shares_str = f"{shares:.6f}"
            
            print(f"\n{CLR_BOLD}{CLR_RED}[EXECUTION] Selling {shares_str} shares of {ticker} (${amt:.2f}). Reason: {reason}{CLR_RESET}")
            
            # Enforce double account guardrails & dry-run interceptor
            if os.environ.get("SKIP_LIVE_TRADES", "false").lower() == "true":
                print(f"{CLR_YELLOW}[DRY_RUN] Intercepted place_equity_order and simulated success for {ticker}{CLR_RESET}")
                action = "LIQUIDATE" if sell["liquidate"] else "SELL"
                insert_trade_record(
                    ticker=ticker,
                    action=action,
                    amount_usd=amt,
                    reasoning=reason,
                    dry_run=True,
                    dataset_id=self.dataset_id
                )
            else:
                if "place_equity_order" in tools_dict:
                    try:
                        args = {
                            "account_number": self.account_number,
                            "symbol": ticker,
                            "side": "sell",
                            "type": "market",
                            "quantity": shares_str,
                            "ref_id": str(uuid.uuid4())
                        }
                        res = await tools_dict["place_equity_order"].run_async(args=args, tool_context=None)
                        print(f"   Order result: {res}")
                        
                        # Log trade receipt to BigQuery
                        action = "LIQUIDATE" if sell["liquidate"] else "SELL"
                        insert_trade_record(
                            ticker=ticker,
                            action=action,
                            amount_usd=amt,
                            reasoning=reason,
                            dry_run=False,
                            dataset_id=self.dataset_id
                        )
                    except Exception as e:
                        print(f"   {CLR_RED}[ERROR] Place sell order failed: {e}{CLR_RESET}")

        # Calculate spendable buying power
        is_dry_run = os.environ.get("SKIP_LIVE_TRADES", "false").lower() == "true"
        if is_dry_run:
            total_sell_usd = sum(sell["amount_usd"] for sell in sells)
            effective_buying_power = total_cash + total_sell_usd
        else:
            effective_buying_power = buying_power

        min_cash_reserve = 0.05 * total_equity
        max_spend = max(0.0, effective_buying_power - min_cash_reserve)
        total_buy_usd_needed = sum(buy["amount_usd"] for buy in buys)

        should_execute_buys = True
        if buys and total_buy_usd_needed > max_spend:
            print(f"\n{CLR_BOLD}{CLR_RED}[BUY POWER GUARD] Total buy needed (${total_buy_usd_needed:.2f}) exceeds spendable buying power (${max_spend:.2f}, based on buying power of ${effective_buying_power:.2f} and minimum cash reserve of ${min_cash_reserve:.2f}).{CLR_RESET}")
            print("Skipping all buy orders in this run to prevent buying power overdraft. Buys will execute in a future run once cash settles.")
            should_execute_buys = False

        if should_execute_buys:
            # Pause/Wait for order settlements
            if sells:
                print("\nWaiting 1 second for sell orders to settle before buying...")
                time.sleep(1)

            # 6. Execute Buys Second
            for buy in buys:
                ticker = buy["ticker"]
                shares = buy["shares"]
                amt = buy["amount_usd"]
                reason = buy["reasoning"]
                shares_str = f"{shares:.6f}"
                
                print(f"\n{CLR_BOLD}{CLR_GREEN}[EXECUTION] Buying {shares_str} shares of {ticker} (${buy['amount_usd']:.2f}). Reason: {reason}{CLR_RESET}")
                
                # Enforce double account guardrails & dry-run interceptor
                if os.environ.get("SKIP_LIVE_TRADES", "false").lower() == "true":
                    print(f"{CLR_YELLOW}[DRY_RUN] Intercepted place_equity_order and simulated success for {ticker}{CLR_RESET}")
                    insert_trade_record(
                        ticker=ticker,
                        action="BUY",
                        amount_usd=amt,
                        reasoning=reason,
                        dry_run=True,
                        dataset_id=self.dataset_id
                    )
                else:
                    if "place_equity_order" in tools_dict:
                        try:
                            args = {
                                "account_number": self.account_number,
                                "symbol": ticker,
                                "side": "buy",
                                "type": "market",
                                "quantity": shares_str,
                                "ref_id": str(uuid.uuid4())
                            }
                            res = await tools_dict["place_equity_order"].run_async(args=args, tool_context=None)
                            print(f"   Order result: {res}")
                            
                            # Log trade receipt to BigQuery
                            insert_trade_record(
                                ticker=ticker,
                                action="BUY",
                                amount_usd=amt,
                                reasoning=reason,
                                dry_run=False,
                                dataset_id=self.dataset_id
                            )
                        except Exception as e:
                            print(f"   {CLR_RED}[ERROR] Place buy order failed: {e}{CLR_RESET}")
        else:
            print(f"\n{CLR_YELLOW}Buys skipped in this run.{CLR_RESET}")

        print(f"\n{CLR_GREEN}All trade executions completed.{CLR_RESET}")
        print(f"{CLR_BOLD}{CLR_GREEN}========================================================={CLR_RESET}\n")
