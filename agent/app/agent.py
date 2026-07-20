# ruff: noqa
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
from datetime import datetime, timezone

from google.adk.agents import Agent, BaseAgent, LoopAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional, AsyncGenerator
from google.adk.events import Event, EventActions
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.callback_context import CallbackContext

# Terminal colors for beautiful outputs
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_RED = "\033[91m"
CLR_GREEN = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_BLUE = "\033[94m"
CLR_MAGENTA = "\033[95m"
CLR_CYAN = "\033[96m"

# Set to True to use Vertex AI (GCP), or False to use Google AI Studio (GEMINI_API_KEY)
USE_VERTEX_AI = True

if USE_VERTEX_AI:
    import google.auth
    try:
        _, project_id = google.auth.default()
    except Exception:
        project_id = None
    project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT") or "conspiracy-493120"
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
else:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"


from app.tools.robinhood_service import robinhood_toolset, validate_and_intercept_trades
from app.tools.data_ingestion import ingest_market_news
from app.tools.ranking import SentimentAnalysisResponse, process_sentiment_rankings
from app.tools.bigquery_service import insert_trade_record
from app.tools.ticker_universe import get_allowed_tickers
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext


class TargetAllocation(BaseModel):
    ticker: str = Field(description="The stock ticker symbol. Must be from the allowed universe.")
    weight_pct: float = Field(description="The target weight as a fraction of total equity (e.g. 0.30 for 30%).")

sentiment_agent = Agent(
    name="sentiment_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are a professional stock market sentiment analyst.
Analyze the sentiment of the target assets based strictly on the provided news dictionary.
For each ticker present as a key in the news dictionary, check the news headlines and summaries.
Assign a raw_score (float from -1.0 to 1.0) and write a concise thesis explaining your score.
If the news list for a ticker is empty or has no recent news, you MUST return a raw_score of 0.0 and a thesis explaining that no recent news was found for this ticker.
You MUST output exactly one analysis entry for each and every ticker present in the keys of the provided news dictionary.""",
    output_schema=SentimentAnalysisResponse,
    output_key="sentiment_result",
)

async def analyze_and_rank_portfolio(tool_context: ToolContext) -> dict:
    """Ingests latest 24h market news, runs sentiment analysis via the Gemini sentiment agent,
    and runs deterministic Python logic to sort, rank, and assign trade signals to the portfolio.

    Returns:
        A dictionary containing the ranked portfolio results with relative ranks and trade signals.
    """
    # 1. Dynamically determine the watchlist
    from app.tools.ticker_universe import determine_active_watchlist
    active_tickers = await determine_active_watchlist()

    # 2. Ingest news only for the active watchlist
    news_dict = ingest_market_news(tickers=active_tickers)

    # 2. Run sentiment_agent using a separate sub-session
    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="system", app_name="sentiment")
    runner = Runner(agent=sentiment_agent, session_service=session_service, app_name="sentiment")

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=f"Please analyze these news articles:\n{news_dict}")]
    )

    async for _ in runner.run_async(
        new_message=message,
        user_id="system",
        session_id=session.id,
    ):
        pass

    response_obj = session.state.get("sentiment_result")
    if not response_obj:
        return {"error": "Failed to retrieve structured sentiment analysis from Gemini."}

    # 3. Process with deterministic Python ranking logic
    ranked_results = process_sentiment_rankings(response_obj)

    return {"ranked_portfolio": ranked_results}

import sys

# Prompts for Multi-Agent Critique Loop
ANALYST_INSTRUCTION = """You are a portfolio analyst agent. Your goal is to analyze the market metrics and news sentiment for our watchlist and propose a draft portfolio of stock allocations.

Starting Portfolio State:
- Total Equity: ${total_equity}
- Current Cash: ${current_cash} ({current_cash_pct}% of total equity)
- Current Holdings (with days_held): {current_holdings}

Recent Trade History:
{recent_trades}

Today's Watch List & Weekly Metrics:
{ranked_portfolio}

Deterministic Downside-Risk State (Python-authoritative):
{risk_context}

Advisor Critique from Previous Iteration:
{advisor_critique}

Propose target allocations for stocks as percentages of total equity (e.g. 0.30 for 30%). You can select up to 3 active holdings (targeting 30% each, summing to 90% of total equity, leaving 10% for cash). If you want to allocate to a defensive treasury bond option, choose TLT. Do not include CASH or USD in the allocations list. The cash buffer is managed implicitly by leaving the remaining percentage of total equity unallocated.

Trading Rules to follow:
1. Focus on the Trend: Base your conviction on the '5-day EWMA Sentiment' rather than volatile daily spikes.
2. Technical Entry: You have two valid entry paths for new allocations:
   - **Path A (Value/Dip Entry)**: Propose entries for assets experiencing a drawdown of 10% or more from their 52-week high while maintaining a positive 5-day EWMA sentiment score (> 0.1).
   - **Path B (Momentum Breakout)**: Propose entries where 'is_20d_high' is TRUE and 'macd_bullish_cross' is TRUE to participate in strong momentum breakout runs.
3. Minimum Holding Period: Do NOT propose to sell, reduce weight of, or liquidate any stock in "Current Holdings" if its `days_held` is less than 21 days, UNLESS its EWMA sentiment score is extremely negative (below -0.5).
4. Fundamental Value: Consider the 'Forward P/E' when comparing assets. Favor infrastructure assets that offer a reasonable valuation floor relative to their sentiment momentum, avoiding heavily overextended valuations.
5. Concentrated Portfolio: Never hold more than 3 active stock positions (excluding cash, but including TLT if selected). If we already hold positions that cannot be sold (due to the 21-day holding period rule), you cannot propose new allocations that would cause the total number of active positions to exceed 3. Under this scenario, keeping remaining capital in cash is preferred, even if it exceeds the 10% cash target.

Your proposal must output a list of TargetAllocation objects under the `allocations` key. You must also output the final signals and theses for all watchlist assets under the `decisions` key, and a concise, 1-2 line user-facing summary of the final recommended decisions and rationales under the `summary` key. IMPORTANT: Frame the summary as a recommendation or decision proposal rather than a past-tense historical action (e.g., "Recommended to maintain holdings in MU (28.3%) and MRVL (31.7%) and retain 40% cash, as all other watchlist assets failed technical entry conditions").
"""

SENIOR_ADVISOR_INSTRUCTION = """You are a senior financial advisor and risk critic. Your goal is to review the draft portfolio proposal generated by the portfolio analyst and ensure it strictly follows our technical trading rules, while allowing for concentrated, high-risk sector or asset picks.

Starting Portfolio State:
- Total Equity: ${total_equity}
- Current Cash: ${current_cash} ({current_cash_pct}% of total equity)
- Current Holdings (with days_held): {current_holdings}
- Active Watchlist (with EWMA Sentiment, Drawdown, and Volatility): {watchlist_data}

Deterministic Downside-Risk State (Python-authoritative):
{risk_context}

Analyst's Draft Proposal:
{analyst_proposal}

Our strict rules:
1. Target Cash Buffer & Cash Deployment Hierarchy: A target cash buffer of 10% of total equity is preferred. If current cash is between 5% and 15%, do not force an adjustment. However, cash deployment is subordinate to rules 2 and 3: if we already hold 3 active positions, or cannot buy new positions without violating rule 2 or 3, then keeping the excess capital in cash is required and does NOT violate the cash buffer rule. Do NOT force fractional allocations (e.g. 10% each) to deploy excess cash.
2. Concentration Gate: The portfolio must hold AT MOST 3 active positions (excluding cash, including TLT if selected as the defensive asset). Reject any proposal or allocations list containing more than 3 tickers.
3. Position Sizing: Each active position must target a baseline weight of 30% of total equity. Do not rebalance an existing holding if its current weight is within a +/- 3% tolerance of its target (i.e. between 27% and 33%). Reject any new allocations that deviate from the 30% target weight (do not allocate smaller weights like 10% or 15% to fit more stocks).
4. Path-Dependent Entry Gating:
   - **For Path A (Value/Dip Entry)**: Approve entries if the asset has a drawdown of 10% or more from its 52-week high, and its 5-day EWMA sentiment is bullish (EWMA sentiment > 0.1). REJECT the allocation if 'sentiment_volatility' is > 0.4.
   - **For Path B (Momentum Breakout Entry)**: Approve entries regardless of drawdown (drawdown can be < 10% / near all-time highs) and bypass the 0.4 sentiment volatility gate (accepting volatility up to 0.85), provided that `is_20d_high` is TRUE and `macd_bullish_cross` is TRUE.
   Note: The defensive treasury bond option (TLT) is exempt from the 10% drawdown requirement.
5. Minimum Holding Period: REJECT any proposal to sell, reduce weight of, or liquidate an existing holding if its days_held < 21, UNLESS the ticker's EWMA sentiment score is extremely negative (below -0.5).
6. Valuation Ceiling: REJECT any new allocation to a stock (excluding treasury assets like TLT) where the Forward P/E is known and exceeds 80, to protect the portfolio against severe valuation compression during the 21-day holding period. If Forward P/E is missing or null, do not reject.

Output format:
You must output a structured review matching the AdvisorCritique schema. If you reject the proposal, you must provide explicit, mathematically sound feedback so the analyst can correct the weights in the next iteration.
"""

class AssetDecision(BaseModel):
    ticker: str = Field(description="The stock ticker symbol.")
    signal: str = Field(description="The final action signal. Must be 'STRONG BUY', 'HOLD', or 'LIQUIDATE'.")
    thesis: str = Field(description="A concise thesis (max 2 sentences) justifying the signal based on news rank, sentiment, and technical metrics.")

class AnalystProposal(BaseModel):
    allocations: List[TargetAllocation] = Field(description="The list of target stock allocations.")
    decisions: List[AssetDecision] = Field(description="Signal and thesis decisions for all assets in today's active watchlist.")
    thesis: str = Field(description="Detailed explanation of your choices, incorporating news sentiment and technical overlays.")
    summary: str = Field(description="A concise, 1-2 line user-facing summary of the recommended decisions and rationales. Frame this as a recommendation or decision proposal rather than a past-tense historical execution (e.g., 'Recommended to maintain holdings in MU (28.3%) and MRVL (31.7%) and retain 40% cash...').")

class AdvisorCritique(BaseModel):
    approved: bool = Field(description="True if the analyst's proposal satisfies all strict rules. False if any rule is violated.")
    feedback: str = Field(description="Detailed critique explaining which rules were satisfied and which were violated.")
    suggested_allocations: Optional[List[TargetAllocation]] = Field(default=None, description="A revised target allocation proposal if rejected.")


class EscalationChecker(BaseAgent):
    """Checks the advisor's critique. If approved, escalates to break the loop."""
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        critique = ctx.session.state.get("advisor_critique")
        approved = False
        feedback = "No feedback yet."
        if critique:
            if isinstance(critique, dict):
                approved = critique.get("approved", False)
                feedback = critique.get("feedback", "No feedback yet.")
            else:
                approved = getattr(critique, "approved", False)
                feedback = getattr(critique, "feedback", "No feedback yet.")

        if approved:
            print(f"🚨 {CLR_BOLD}{CLR_RED}########################## ESCALATION_CHECKER ##########################{CLR_RESET}")
            print(f"Critique {CLR_BOLD}{CLR_GREEN}APPROVED{CLR_RESET}. Feedback: {feedback}")
            print("Escalating to break loop...")
            print(f"{CLR_RED}###########################################################################{CLR_RESET}\n")
            yield Event(author=self.name, actions=EventActions(escalate=True))
        else:
            print(f"🚨 {CLR_BOLD}{CLR_RED}########################## ESCALATION_CHECKER ##########################{CLR_RESET}")
            print(f"Critique {CLR_BOLD}{CLR_RED}REJECTED{CLR_RESET}. Continuing loop. Feedback: {feedback}")
            print(f"{CLR_RED}###########################################################################{CLR_RESET}\n")
            yield Event(author=self.name)


portfolio_analyst = Agent(
    name="portfolio_analyst",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=ANALYST_INSTRUCTION,
    output_schema=AnalystProposal,
    output_key="analyst_proposal",
)

senior_risk_advisor = Agent(
    name="senior_risk_advisor",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=SENIOR_ADVISOR_INSTRUCTION,
    output_schema=AdvisorCritique,
    output_key="advisor_critique",
)

escalation_checker = EscalationChecker(name="escalation_checker")

portfolio_stabilizer_loop = LoopAgent(
    name="portfolio_stabilizer_loop",
    sub_agents=[portfolio_analyst, senior_risk_advisor, escalation_checker],
    max_iterations=5,
)


def _calculate_downside_risk(holdings: list[dict], *, account_number: str, dataset_id: str, now: datetime):
    """Fetch risk inputs through adapters and return fail-closed deterministic state."""
    from app.risk_controls import calculate_spy_regime, calculate_trailing_stop
    from app.tools.bigquery_service import get_last_buy_timestamp, upsert_position_risk_state
    from app.tools.data_ingestion import fetch_completed_daily_history
    from app.trading_policy import RiskOverride

    try:
        spy_bars = fetch_completed_daily_history("SPY", now=now, calendar_days=420)
        spy_regime = calculate_spy_regime(spy_bars, observed_at=now)
    except Exception:
        spy_regime = None
    overrides = {}
    stop_results = {}
    reviewed_entries = {
        "SNDK": (datetime(2026, 7, 1, tzinfo=timezone.utc), 0.01376, "HUMAN_CONFIRMED_ROBINHOOD_HISTORY"),
        "MRVL": (datetime(2026, 6, 29, tzinfo=timezone.utc), 0.105127, "HUMAN_CONFIRMED_ROBINHOOD_HISTORY"),
    }
    for holding in holdings:
        ticker = holding["symbol"]
        entry_timestamp = get_last_buy_timestamp(ticker, dry_run=False, dataset_id=dataset_id)
        source = "CONFIRMED_LIVE_TRADE_HISTORY"
        if entry_timestamp is None and ticker in reviewed_entries:
            reviewed_timestamp, reviewed_quantity, reviewed_source = reviewed_entries[ticker]
            if abs(float(holding["shares"]) - reviewed_quantity) <= 1e-6:
                entry_timestamp = reviewed_timestamp
                source = reviewed_source
        if entry_timestamp is None and ticker == "MU":
            entry_timestamp = now
            source = "BOOTSTRAPPED_CURRENT_DATE"
        stop_result = None
        if entry_timestamp is not None:
            if entry_timestamp.tzinfo is None:
                entry_timestamp = entry_timestamp.replace(tzinfo=timezone.utc)
            try:
                history_days = max(60, (now - entry_timestamp).days + 60)
                ticker_bars = fetch_completed_daily_history(ticker, now=now, calendar_days=history_days)
                stop_result = calculate_trailing_stop(ticker, ticker_bars, entry_date=entry_timestamp.date())
            except Exception:
                stop_result = None
            if stop_result and stop_result.available:
                try:
                    upsert_position_risk_state(
                        account_suffix=str(account_number)[-5:],
                        ticker=ticker,
                        entry_timestamp=entry_timestamp,
                        last_session=stop_result.as_of_session,
                        highest_high=stop_result.highest_high,
                        stop_price=stop_result.current_stop,
                        atr=stop_result.atr,
                        breached=stop_result.breached,
                        source=source,
                        dataset_id=dataset_id,
                    )
                except Exception:
                    # Persistence failure must not erase an already-calculated breach.
                    pass
        stop_results[ticker] = stop_result
        overrides[ticker] = RiskOverride(
            ticker=ticker,
            stop_breached=bool(stop_result and stop_result.breached),
            macro_risk_off=bool(spy_regime and spy_regime.available and spy_regime.macro_risk_off),
            reason=";".join(filter(None, [
                stop_result.reason if stop_result else "RISK_DATA_UNAVAILABLE",
                spy_regime.reason if spy_regime else "RISK_DATA_UNAVAILABLE",
            ])),
            stop_data_available=bool(stop_result and stop_result.available),
            macro_data_available=bool(spy_regime and spy_regime.available),
        )
    return overrides, stop_results, spy_regime


def _risk_required_proposal(holdings: list[dict], total_equity: float, overrides: dict, spy_regime):
    """Return a deterministic sell-only risk target, or None when debate may proceed."""
    macro_risk_off = bool(spy_regime and spy_regime.available and spy_regime.macro_risk_off)
    breached = {ticker for ticker, override in overrides.items() if override.stop_breached}
    if not macro_risk_off and not breached:
        return None
    allocations = []
    decisions = []
    for holding in holdings:
        ticker = holding["symbol"]
        current_weight = holding["equity"] / total_equity if total_equity > 0 else 0.0
        must_exit = ticker in breached or (macro_risk_off and ticker != "TLT")
        if not must_exit:
            target = min(current_weight, 0.30) if ticker == "TLT" else current_weight
            if target > 0:
                allocations.append({"ticker": ticker, "weight_pct": target})
        decisions.append({
            "ticker": ticker,
            "signal": "LIQUIDATE" if must_exit else "HOLD",
            "thesis": "Deterministic downside-risk override." if must_exit else "Existing position retained by deterministic policy.",
        })
    # With no equity sells required, risk-off may establish the 30% TLT / 70% cash target.
    if macro_risk_off and not holdings:
        allocations = [{"ticker": "TLT", "weight_pct": 0.30}]
        decisions.append({"ticker": "TLT", "signal": "STRONG BUY", "thesis": "Deterministic macro risk-off allocation."})
    return {
        "allocations": allocations,
        "decisions": decisions,
        "thesis": "Deterministic ATR/SPY risk override; no LLM safety interpretation is used.",
        "summary": "Downside-risk controls produced a deterministic target.",
    }

async def financial_analysis_pipeline(
    ranked_portfolio: list, 
    graveyard_rows: list | None = None, 
    dataset_id: str = "portfolio_analytics"
) -> list:
    """Runs a multi-agent critique debate loop to finalize stock allocations,
    then executes trades using BrokerExecutor and logs snapshot/trades to BigQuery."""
    from app.tools.bigquery_service import get_historical_metrics
    from app.broker_executor import BrokerExecutor
    from app.tools.robinhood_service import fetch_robinhood_portfolio_state

    # 1. Fetch weekly historical signals log
    weekly_metrics = get_historical_metrics(days=7, dataset_id=dataset_id)
    
    # Clear INTEGRATION_TEST to allow the Robinhood MCP toolset to connect
    if "INTEGRATION_TEST" in os.environ:
        del os.environ["INTEGRATION_TEST"]

    # Resolve target account ending in 48661 from environment variables
    account_number = os.environ.get("ROBINHOOD_ACCOUNT_NUMBER")
    if not account_number:
        if os.environ.get("SKIP_LIVE_TRADES", "true").lower() == "true":
            account_number = "MOCK_ACCOUNT_48661"
        else:
            raise RuntimeError("Security Guardrail: ROBINHOOD_ACCOUNT_NUMBER environment variable is not set.")

    if not account_number or not str(account_number).endswith("48661"):
        raise RuntimeError(f"Security Guardrail: Unauthorized Robinhood account '{account_number}'. All operations restricted to accounts ending in 48661.")

    # 2. Fetch current holdings and cash from Robinhood to initialize loop state
    print("\nFetching current portfolio state from Robinhood...")
    broker_state = await fetch_robinhood_portfolio_state(account_number)
    total_cash = broker_state.cash
    buying_power = broker_state.buying_power
    holdings = [
        {
            "symbol": holding.symbol,
            "shares": holding.shares,
            "average_buy_price": holding.average_buy_price,
            "current_price": holding.current_price,
            "equity": holding.equity,
        }
        for holding in broker_state.holdings
    ]

    # Compute starting Total Equity and weights
    holdings_value = sum(h["equity"] for h in holdings)
    total_equity = total_cash + holdings_value
    current_cash_pct = (total_cash / total_equity) * 100 if total_equity > 0 else 0.0

    is_dry_run = os.environ.get("SKIP_LIVE_TRADES", "true").lower() == "true"
    
    # Calculate days_held for each holding from trade history
    from app.tools.bigquery_service import get_last_buy_timestamp, get_recent_trades
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)
    holdings_with_days = []
    for h in holdings:
        last_buy = get_last_buy_timestamp(h["symbol"], dry_run=is_dry_run, dataset_id=dataset_id)
        if last_buy:
            if last_buy.tzinfo is None:
                last_buy = last_buy.replace(tzinfo=timezone.utc)
            days_held = (now - last_buy).days
        else:
            days_held = 999  # Long term or no history
        
        holdings_with_days.append({
            "symbol": h["symbol"],
            "shares": h["shares"],
            "current_price": h["current_price"],
            "equity": h["equity"],
            "weight_pct": f"{(h['equity']/total_equity)*100:.1f}%" if total_equity > 0 else "0.0%",
            "days_held": days_held
        })
    current_holdings_str = str(holdings_with_days)

    risk_overrides, trailing_stops, spy_regime = _calculate_downside_risk(
        holdings,
        account_number=account_number,
        dataset_id=dataset_id,
        now=now,
    )
    risk_context = {
        "spy_regime": spy_regime.__dict__ if spy_regime else {"available": False, "reason": "RISK_DATA_UNAVAILABLE"},
        "trailing_stops": {
            ticker: result.__dict__ if result else {"available": False, "reason": "RISK_DATA_UNAVAILABLE"}
            for ticker, result in trailing_stops.items()
        },
    }
    forced_proposal = _risk_required_proposal(holdings, total_equity, risk_overrides, spy_regime)

    # Fetch recent trades history
    recent_trades = get_recent_trades(limit=10, dry_run=is_dry_run, dataset_id=dataset_id)
    recent_trades_str = str(recent_trades) if recent_trades else "No recent trade history found."

    # Build active watchlist summary containing EWMA, drawdown, volatility, and technicals
    watchlist_summary = str([{
        "ticker": item["ticker"],
        "conviction_score": item["raw_score"],
        "sentiment_ewma_5d": item.get("sentiment_ewma"),
        "sentiment_volatility_5d": item.get("sentiment_volatility"),
        "drawdown_pct": item.get("drawdown_pct"),
        "forward_pe": item.get("forward_pe"),
        "sustained_rsi_drop": item.get("sustained_rsi_drop"),
        "rsi": item.get("rsi"),
        "macd": item.get("macd"),
        "macd_signal": item.get("macd_signal")
    } for item in ranked_portfolio])

    print(f"   Current Cash: {CLR_GREEN}${total_cash:.2f}{CLR_RESET}")
    print(f"   Current Holdings: {CLR_BOLD}{current_holdings_str}{CLR_RESET}")
    print(f"   Recent Trades: {recent_trades_str}")
    print(f"   Total Equity: {CLR_BOLD}{CLR_GREEN}${total_equity:.2f}{CLR_RESET}")

    # 3. Initialize loop session state and run the Multi-Agent Loop
    print(f"\n{CLR_BOLD}{CLR_CYAN}🔄 [PHASE: 4. Entering Multi-Agent Portfolio Debate Loop]{CLR_RESET}")
    print(f"   Initializing debate loop with {CLR_BOLD}{CLR_MAGENTA}PORTFOLIO_ANALYST{CLR_RESET}, {CLR_BOLD}{CLR_YELLOW}SENIOR_RISK_ADVISOR{CLR_RESET}, and {CLR_BOLD}{CLR_RED}ESCALATION_CHECKER{CLR_RESET}...")

    print(f"\n📊 {CLR_BOLD}{CLR_CYAN}" + "#" * 26 + " INPUT_CONTEXT " + "#" * 26 + f"{CLR_RESET}")
    print(f"   - Total Equity: {CLR_BOLD}{CLR_GREEN}${total_equity:.2f}{CLR_RESET}")
    print(f"   - Current Cash: {CLR_GREEN}${total_cash:.2f}{CLR_RESET} ({current_cash_pct:.1f}% of total equity)")
    print(f"   - Current Holdings (with days_held): {current_holdings_str}")
    print(f"   - Recent Trades: {recent_trades_str}")
    print(f"   - Watchlist Metrics: {watchlist_summary}")
    print(f"{CLR_BOLD}{CLR_CYAN}" + "#" * 69 + f"{CLR_RESET}\n")

    session_service = InMemorySessionService()
    initial_state = {
        "total_equity": f"{total_equity:.2f}",
        "current_cash": f"{total_cash:.2f}",
        "current_cash_pct": f"{current_cash_pct:.1f}",
        "current_holdings": current_holdings_str,
        "recent_trades": recent_trades_str,
        "watchlist_data": watchlist_summary,
        "ranked_portfolio": str(ranked_portfolio),
        "weekly_metrics": str(weekly_metrics),
        "risk_context": str(risk_context),
        "advisor_critique": "No previous critique. This is your first proposal."
    }
    if forced_proposal is not None:
        initial_state["analyst_proposal"] = forced_proposal
        initial_state["advisor_critique"] = {
            "approved": True,
            "feedback": "Deterministic downside-risk override; debate bypassed.",
            "suggested_allocations": None,
        }
    session = await session_service.create_session(
        user_id="cron_job",
        app_name="trading",
        state=initial_state
    )

    runner = Runner(agent=portfolio_stabilizer_loop, session_service=session_service, app_name="trading")

    async def no_events():
        if False:
            yield None

    event_stream = no_events() if forced_proposal is not None else runner.run_async(
        new_message=types.Content(role="user", parts=[types.Part.from_text(text="Please start the debate loop to finalize today's target allocations.")]),
        user_id="cron_job",
        session_id=session.id,
    )
    async for event in event_stream:
        if event.content and event.content.parts:
            content_str = "".join([part.text for part in event.content.parts if part.text]).strip()
            if content_str:
                author_name = event.author.upper() if event.author else "SYSTEM"
                if author_name != "ESCALATION_CHECKER":
                    emoji_map = {
                        "PORTFOLIO_ANALYST": "🧐 ",
                        "SENIOR_RISK_ADVISOR": "🛡️ ",
                        "SYSTEM": "⚙️ "
                    }
                    color_map = {
                        "PORTFOLIO_ANALYST": CLR_MAGENTA,
                        "SENIOR_RISK_ADVISOR": CLR_YELLOW,
                        "SYSTEM": CLR_CYAN
                    }
                    emoji = emoji_map.get(author_name, "")
                    color = color_map.get(author_name, CLR_RESET)
                    
                    print(f"{color}########################## {emoji}{author_name} ##########################{CLR_RESET}")
                    print(content_str)
                    print(f"{color}" + "#" * (len(author_name) + len(emoji) + 54) + f"{CLR_RESET}\n")
    print(f"\n{CLR_BOLD}{CLR_CYAN}🔄 [PHASE: 4. Exit (Multi-Agent Loop Finished)]{CLR_RESET}")

    # Retrieve the final proposal and critique. The proposal is non-executable unless
    # the final critique is explicitly approved and deterministic policy also passes.
    session = await session_service.get_session(user_id="cron_job", session_id=session.id, app_name="trading")
    proposal = session.state.get("analyst_proposal")
    critique = session.state.get("advisor_critique")
    if not proposal:
        print(f"\n{CLR_BOLD}{CLR_RED}[CRITICAL ERROR] Failed to obtain approved portfolio target allocations from the loop agent.{CLR_RESET}")
        return ranked_portfolio

    # Extract allocations and decisions supporting both dictionary and Pydantic formats
    approved_allocations = []
    decisions = []

    if isinstance(proposal, dict):
        allocations_raw = proposal.get("allocations", [])
        for a in allocations_raw:
            if isinstance(a, dict):
                approved_allocations.append({
                    "ticker": a.get("ticker"),
                    "weight_pct": a.get("weight_pct")
                })
            else:
                approved_allocations.append({
                    "ticker": getattr(a, "ticker"),
                    "weight_pct": getattr(a, "weight_pct")
                })
        decisions = proposal.get("decisions", [])
    else:
        allocations_raw = getattr(proposal, "allocations", [])
        for a in allocations_raw:
            approved_allocations.append({
                "ticker": a.ticker,
                "weight_pct": a.weight_pct
            })
        decisions = getattr(proposal, "decisions", [])

    critique_approved = critique.get("approved") if isinstance(critique, dict) else getattr(critique, "approved", None)
    if critique_approved is not True:
        print(f"\n{CLR_BOLD}{CLR_RED}[POLICY REJECTED] Final advisor approval is missing or false; broker execution cancelled.{CLR_RESET}")
        from app.tools.bigquery_service import insert_execution_run
        from app.trading_policy import POLICY_VERSION
        from zoneinfo import ZoneInfo

        rejected_decision_id = f"{now.astimezone(ZoneInfo('America/New_York')).date().isoformat()}-close-{str(account_number)[-5:]}-{POLICY_VERSION}"
        try:
            insert_execution_run(
                decision_id=rejected_decision_id,
                dry_run=is_dry_run,
                policy_version=POLICY_VERSION,
                policy_allowed=False,
                status="POLICY_REJECTED",
                violations=[{"code": "ADVISOR_NOT_APPROVED"}],
                proposal=approved_allocations,
                dataset_id=dataset_id,
            )
        except Exception as exc:
            print(f"{CLR_YELLOW}Warning: Failed to audit rejected execution run: {exc}{CLR_RESET}")
        return ranked_portfolio

    print(f"\n{CLR_BOLD}{CLR_GREEN}Advisor-approved target allocations: {approved_allocations}{CLR_RESET}")

    dry_run_report_path = None
    if is_dry_run:
        import json
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dry_run_filename = f"dry_run_results_{timestamp}.json"
        proposal_dict = {}
        if proposal:
            if isinstance(proposal, dict):
                proposal_dict = proposal
            else:
                proposal_dict = {
                    "allocations": [
                        {"ticker": a.ticker, "weight_pct": a.weight_pct} for a in getattr(proposal, "allocations", [])
                    ],
                    "decisions": [
                        {"ticker": d.ticker, "signal": d.signal, "thesis": d.thesis} for d in getattr(proposal, "decisions", [])
                    ],
                    "thesis": getattr(proposal, "thesis", ""),
                    "summary": getattr(proposal, "summary", "")
                }
        
        critique_dict = {}
        if critique:
            if isinstance(critique, dict):
                critique_dict = critique
            else:
                critique_dict = {
                    "approved": getattr(critique, "approved", False),
                    "feedback": getattr(critique, "feedback", ""),
                    "suggested_allocations": [
                        {"ticker": a.ticker, "weight_pct": a.weight_pct} for a in getattr(critique, "suggested_allocations", []) or []
                    ]
                }
                
        dry_run_data = {
            "timestamp": datetime.now().isoformat(),
            "target_allocations": approved_allocations,
            "analyst_proposal": proposal_dict,
            "advisor_critique": critique_dict
        }
        
        try:
            logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
            os.makedirs(logs_dir, exist_ok=True)
            filepath = os.path.join(logs_dir, dry_run_filename)
            dry_run_report_path = filepath
            with open(filepath, "w") as f:
                json.dump(dry_run_data, f, indent=2)
            print(f"   {CLR_GREEN}[DRY_RUN] Successfully dumped dry run results to {filepath}{CLR_RESET}")
        except Exception as e:
            print(f"   {CLR_YELLOW}Warning: Failed to dump dry run results: {e}{CLR_RESET}")

    # Map decisions for policy metrics, then perform deterministic authorization before
    # changing executable target weights or constructing a broker executor.
    decision_map = {}
    for d in decisions:
        if isinstance(d, dict):
            ticker = d.get("ticker", "").strip().upper()
            signal = d.get("signal", "").strip().upper()
            thesis = d.get("thesis", "")
        else:
            ticker = getattr(d, "ticker", "").strip().upper()
            signal = getattr(d, "signal", "").strip().upper()
            thesis = getattr(d, "thesis", "")
        if ticker:
            decision_map[ticker] = {"signal": signal, "thesis": thesis}

    from app.trading_policy import AssetPolicyMetrics, HoldingState, POLICY_VERSION, RiskOverride, validate_pretrade_plan
    from app.tools.bigquery_service import execution_run_exists, insert_execution_run, update_execution_run
    from app.tools.ticker_universe import get_allowed_tickers
    from zoneinfo import ZoneInfo

    market_date = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    decision_id = f"{market_date}-close-{str(account_number)[-5:]}-{POLICY_VERSION}"
    try:
        already_executed = execution_run_exists(decision_id, is_dry_run, dataset_id)
    except Exception as exc:
        print(f"{CLR_RED}[POLICY REJECTED] Duplicate-run protection unavailable: {exc}{CLR_RESET}")
        return ranked_portfolio

    holding_policy = [
        HoldingState(
            ticker=holding["symbol"],
            shares=holding["shares"],
            price=holding["current_price"],
            equity=holding["equity"],
            weight=holding["equity"] / total_equity,
            days_held=next(item["days_held"] for item in holdings_with_days if item["symbol"] == holding["symbol"]),
        )
        for holding in holdings
    ]
    metric_rows = {str(item.get("ticker", "")).strip().upper(): item for item in ranked_portfolio}
    policy_tickers = {str(a.get("ticker", "")).strip().upper() for a in approved_allocations} | {h.ticker for h in holding_policy}
    metrics_by_ticker = {}
    for ticker in policy_tickers:
        item = metric_rows.get(ticker)
        if not item:
            continue
        try:
            observed_at = now
            if item.get("timestamp"):
                observed_at = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00"))
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=timezone.utc)
            metrics_by_ticker[ticker] = AssetPolicyMetrics(
                ticker=ticker,
                observed_at=observed_at,
                sentiment_ewma=item.get("sentiment_ewma"),
                sentiment_volatility=item.get("sentiment_volatility"),
                drawdown_pct=item.get("drawdown_pct"),
                forward_pe=item.get("forward_pe"),
                is_20d_high=item.get("is_20d_high") is True,
                macd_bullish_cross=item.get("macd_bullish_cross") is True,
                final_signal=decision_map.get(ticker, {}).get("signal", item.get("signal", "")),
            )
        except (TypeError, ValueError):
            continue
    overrides_by_ticker = {}
    for ticker in policy_tickers:
        overrides_by_ticker[ticker] = risk_overrides.get(ticker) or RiskOverride(
            ticker,
            False,
            bool(spy_regime and spy_regime.available and spy_regime.macro_risk_off),
            spy_regime.reason if spy_regime else "RISK_DATA_UNAVAILABLE",
            stop_data_available=ticker not in {holding.ticker for holding in holding_policy},
            macro_data_available=bool(spy_regime and spy_regime.available),
        )
    policy_decision = validate_pretrade_plan(
        advisor_approved=critique_approved,
        decision_id=decision_id,
        account_number=account_number,
        allocations=approved_allocations,
        holdings=holding_policy,
        metrics_by_ticker=metrics_by_ticker,
        overrides_by_ticker=overrides_by_ticker,
        total_equity=total_equity,
        allowed_tickers=set(get_allowed_tickers()),
        already_executed=already_executed,
        now=now,
    )
    if dry_run_report_path:
        try:
            with open(dry_run_report_path) as report_file:
                dry_run_report = json.load(report_file)
            dry_run_report["policy_result"] = {
                "allowed": policy_decision.allowed,
                "decision_id": policy_decision.decision_id,
                "reason_codes": list(policy_decision.reason_codes),
                "planned_trades": [
                    {
                        "ticker": trade.ticker,
                        "action": trade.action.value,
                        "current_weight": trade.current_weight,
                        "target_weight": trade.target_weight,
                        "reason_codes": list(trade.reason_codes),
                    }
                    for trade in policy_decision.planned_trades
                ],
            }
            with open(dry_run_report_path, "w") as report_file:
                json.dump(dry_run_report, report_file, indent=2)
        except Exception as exc:
            print(f"{CLR_YELLOW}Warning: Failed to append policy result to dry-run report: {exc}{CLR_RESET}")
    insert_execution_run(
        decision_id=decision_id,
        dry_run=is_dry_run,
        policy_version=POLICY_VERSION,
        policy_allowed=policy_decision.allowed,
        status="VALIDATED" if policy_decision.allowed else "POLICY_REJECTED",
        violations=[violation.__dict__ for violation in policy_decision.violations],
        proposal=approved_allocations,
        dataset_id=dataset_id,
    )
    if not policy_decision.allowed or policy_decision.plan is None:
        print(f"{CLR_RED}[POLICY REJECTED] {policy_decision.reason_codes}{CLR_RESET}")
        return ranked_portfolio

    allocation_map = dict(policy_decision.normalized_allocations)

    for item in ranked_portfolio:
        ticker = item["ticker"].strip().upper()
        if ticker in decision_map:
            item["signal"] = decision_map[ticker]["signal"]
            item["thesis"] = decision_map[ticker]["thesis"]
        item["target_weight"] = allocation_map.get(ticker, 0.0)

    # 4. Instantiate BrokerExecutor and run broker execution
    print(f"\n{CLR_BOLD}{CLR_GREEN}💸 [PHASE: 5. Execution & Portfolio Rebalancing]{CLR_RESET}")
    print(f"   Connecting to Robinhood MCP tools for target account ending in 48661...")
    controller = BrokerExecutor(toolset=robinhood_toolset, account_number=account_number, dataset_id=dataset_id)
    update_execution_run(decision_id, is_dry_run, "EXECUTING", dataset_id=dataset_id)
    try:
        execution_result = await controller.execute_rebalance(policy_decision.plan)
    except Exception as exc:
        update_execution_run(
            decision_id,
            is_dry_run,
            "ABORTED",
            execution_result={"error": str(exc)},
            dataset_id=dataset_id,
        )
        try:
            from app.app_utils.discord_notifier import send_discord_webhook
            send_discord_webhook(
                summary=f"🚨 TRADING RUN FAILED CLOSED: {exc}",
                approved_allocations=approved_allocations,
                decisions=decisions,
                is_dry_run=is_dry_run,
            )
        except Exception as notify_exc:
            print(f"{CLR_YELLOW}Warning: Failed to send critical Discord notification: {notify_exc}{CLR_RESET}")
        return ranked_portfolio
    update_execution_run(
        decision_id,
        is_dry_run,
        execution_result.status.value,
        execution_result=execution_result.__dict__,
        dataset_id=dataset_id,
    )
    print(f"{CLR_BOLD}{CLR_GREEN}💸 [PHASE: 5. Exit]{CLR_RESET}")

    # 5. Log post-trade portfolio snapshot to BigQuery
    print(f"\n{CLR_CYAN}Logging portfolio snapshot to BigQuery...{CLR_RESET}")
    try:
        from app.tools.robinhood_service import log_portfolio_snapshot
        summary_str = None
        if proposal:
            if isinstance(proposal, dict):
                summary_str = proposal.get("summary")
            else:
                summary_str = getattr(proposal, "summary", None)
        await log_portfolio_snapshot(summary=summary_str, dataset_id=dataset_id)
        print(f"   {CLR_GREEN}Portfolio snapshot logged successfully.{CLR_RESET}")
    except Exception as e:
        print(f"   {CLR_YELLOW}Warning: Failed to log portfolio snapshot: {e}{CLR_RESET}")

    # 6. Log final unified results to BigQuery
    print(f"\n{CLR_CYAN}Logging final signals and unified theses to BigQuery...{CLR_RESET}")
    try:
        from app.tools.bigquery_service import insert_sentiment
        rows_to_log = list(graveyard_rows) if graveyard_rows is not None else []
        all_rows_to_log = list(ranked_portfolio) + rows_to_log
        
        # Override the timestamp to ensure the recommendations match the current snapshot time
        from datetime import datetime, timezone
        current_time_str = datetime.now(timezone.utc).isoformat()
        for item in all_rows_to_log:
            item["timestamp"] = current_time_str
            
        insert_sentiment(all_rows_to_log, dataset_id=dataset_id)
        print(f"   {CLR_GREEN}Unified market metrics and execution logs written to BigQuery successfully.{CLR_RESET}")
    except Exception as e:
        print(f"   {CLR_YELLOW}Warning: Failed to write unified metrics to BigQuery: {e}{CLR_RESET}")

    # 7. Notify Discord
    try:
        from app.app_utils.discord_notifier import send_discord_webhook
        summary_str = None
        if proposal:
            if isinstance(proposal, dict):
                summary_str = proposal.get("summary")
            else:
                summary_str = getattr(proposal, "summary", None)
        if execution_result.status.value != "COMPLETED":
            summary_str = (
                f"🚨 TRADING RUN FAILED CLOSED: {execution_result.status.value}. "
                f"{execution_result.reason or 'See execution audit for details.'}"
            )
        send_discord_webhook(
            summary=summary_str or "Daily portfolio optimization complete.",
            approved_allocations=approved_allocations,
            decisions=decisions,
            is_dry_run=is_dry_run
        )
    except Exception as e:
        print(f"   {CLR_YELLOW}Warning: Failed to send Discord notification: {e}{CLR_RESET}")

    return ranked_portfolio


# Define tools list, conditionally adding robinhood_toolset if not in a test environment
agent_tools = [analyze_and_rank_portfolio]
if not os.environ.get("INTEGRATION_TEST") and "pytest" not in sys.modules:
    agent_tools.append(robinhood_toolset)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="You are a helpful AI assistant designed to provide accurate and useful information.",
    tools=agent_tools,
    before_tool_callback=validate_and_intercept_trades,
)

app = App(
    root_agent=root_agent,
    name="app",
)
