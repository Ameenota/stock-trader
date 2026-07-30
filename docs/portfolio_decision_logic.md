# Portfolio Decision-Making Logic: Buy & Sell Strategy

This document outlines the systematic decision-making process used by the automated stock trader to select, evaluate, size, and trade assets. The pipeline blends momentum screening, news sentiment analysis, technical indicators, and a multi-agent risk-control debate to determine daily portfolio allocations.

---

## Process Overview

The trading system follows a six-phase daily pipeline:
```
1. Watchlist Screening ➔ 2. Market Data Ingestion ➔ 3. Sentiment Analysis ➔ 4. Baseline Ranking ➔ 5. Multi-Agent Debate ➔ 6. Rebalancing & Execution
```

---

## Phase 1: Watchlist Screening (Pre-Filtering & Momentum)
Rather than executing resource-intensive sentiment analysis on the entire versioned multi-sector universe, the system dynamically filters it down to a refined **11-stock active watchlist**. More held positions expand the list only when required for safe exit monitoring:

1. **Owned Position Promotion**: Any stock currently held in the portfolio is automatically force-included in the active watchlist.
2. **Recently Sold Live Asset Filter (Cool-down)**: To reduce reactiveness and avoid rapid buy-sell-buy chop, any asset that has been sold or liquidated as a live trade (`dry_run = FALSE` in BigQuery's `trade_history` table) within the last **21 days** is automatically excluded from the active watchlist candidates and fallback padding. (Simulated/dry-run trades are ignored).
3. **Trend Filter (50-Day SMA Gate)**: Candidate (non-owned) stocks must be trading **above their 50-day Simple Moving Average (SMA)**, **UNLESS** they are deeply oversold with a 14-day RSI $< 25$. If they meet this oversold exception, they bypass the SMA gate and are promoted to the active watchlist (allowing high-quality value entry on deep pullbacks).
4. **Momentum Scoring**: The remaining candidates that passed either the SMA trend filter or the RSI oversold bypass are scored and ranked based on a momentum ratio:
   $$\text{Momentum} = \frac{\text{Current Price}}{\text{50-day SMA}}$$
5. **Sector Balance**: At most two non-held candidates from one sector may consume the normal active watchlist.
6. **Watchlist Composition**:
   - The watchlist is populated first by owned assets.
   - The remaining slots (up to 11 total) are filled by candidate assets with the highest momentum scores (including oversold promotions).
   - If the list contains fewer than 11 assets, it is padded using the static core asset watchlist (excluding any recently sold assets under the cool-down filter).

---

## Phase 2: Market Data Ingestion & Indicator Formulation
For each of the 11 assets on the active watchlist, the system gathers several technical, sentiment, and fundamental metrics:

* **News Stream**: Ingests at most the three newest headlines and summaries per ticker from the last 24 hours, with a hard 33-article cap for the entire Gemini run.
* **Technical Trend Indicators**:
  * **20-day SMA**: Calculates the short-term moving average.
  * **Price/MA Ratio**: Evaluates short-term extension ($Current Price / 20\text{-day SMA}$).
  * **MACD (12, 26, 9)**: Computes the MACD value and MACD signal line.
* **Oversold Gates**:
  * **RSI (14-period)**: Evaluates whether the asset is in overbought or oversold territory.
  * **Sustained RSI Drop**: A boolean flag indicating whether the asset's RSI has remained below 30 (highly oversold) for **3 or more consecutive trading days**.
* **Breakout Triggers (Path B)**:
  * **20-day High Breakthrough (`is_20d_high`)**: A boolean flag indicating if the current price is greater than or equal to the maximum closing/high price over the last 20 trading days.
  * **MACD Bullish Cross (`macd_bullish_cross`)**: A boolean flag indicating if the MACD line crossed above the signal line today (i.e., today $MACD > Signal$ and yesterday $MACD \le Signal$).
* **Valuation & Analyst Consensus**:
  * **52-Week Drawdown**: The percentage drop from the asset’s 52-week high:
    $$\text{Drawdown \%} = \frac{\text{52-week High} - \text{Current Price}}{\text{52-week High}} \times 100$$
  * **Analyst Recommendation**: The consensus recommendation key and the consensus target mean price.
  * **Forward P/E**: Fetched from Yahoo Finance during ingestion to provide a fundamental valuation baseline.
* **Historical Sentiment Aggregations**:
  * Queries the past 4 days of sentiment history and combines it with the current day's score to calculate:
    * **5-day EWMA Sentiment**: An Exponentially Weighted Moving Average of sentiment scores to capture the medium-term narrative trend.
    * **5-day Sentiment Volatility**: The standard deviation of the sentiment scores over the last 5 days.

---

## Phase 3: Sentiment Score Generation
The 24-hour news stories for each watchlist ticker are analyzed by a specialized **Sentiment Agent**.
* **Conviction Scoring**: The agent assigns a raw sentiment score ranging from **-1.0 (extremely negative)** to **+1.0 (extremely positive)**, along with a qualitative thesis.
* **No-News Decay Bypass (Weekdays)**: If a ticker on the active watchlist has no news articles in the last 24 hours on a weekday:
  * The system **bypasses calling the Gemini Sentiment Agent** for this ticker (saving API tokens).
  * In Python, it automatically carries forward the trend with a **30% decay** based on the historical 5-day EWMA sentiment:
    $$\text{raw\_score} = \text{ewma\_sentiment} \times 0.7$$
    (If no historical sentiment exists, the score defaults to `0.0`).
* **Weekend Pause State**: On Saturday and Sunday, when market activity and news volume are low, the system bypasses news ingestion, Gemini API calls, and the 30% decay rule entirely. Instead, it carries forward Friday's final EWMA score unchanged as today's raw score to prevent weekend signal decay and jitter.

---

## Phase 4: Baseline Ranking & Initial Signals
The 11 watchlist assets are sorted in ascending order of their **daily raw sentiment scores** (either returned by the Sentiment Agent or decayed via the no-news bypass) and assigned a relative rank from 1 (lowest sentiment) to 11 (highest sentiment):

* **Relative Rank 1 to 3 (Bottom 3)**:
  * Automatically receive a baseline signal of **`LIQUIDATE`**, **UNLESS** their historical 5-day EWMA sentiment is positive/neutral ($\ge +0.05$).
  * If the bottom-3 asset's EWMA sentiment is $\ge +0.05$, its baseline signal is overridden to **`HOLD`** to prevent spurious liquidations on low-news days or sector-wide bull markets.
* **Relative Rank 4 to 11 (Top 8)**:
  * Receive a **`STRONG BUY`** signal if their daily raw sentiment score is **greater than 0.2**.
  * Receive a **`HOLD`** signal if their daily raw sentiment score is **0.2 or less**.

---

## Phase 5: Multi-Agent Portfolio Debate (The Analyst & Risk Critic Loop)
Before executing any trades, the baseline signals, technical metrics, and portfolio state are submitted to a multi-agent critique and rebalancing loop. The **Portfolio Analyst** proposes allocations, and the **Senior Risk Advisor** acts as a risk controller to approve or reject them.

### 1. Portfolio Analyst (Allocation Proposal)
The analyst determines a target portfolio layout according to these guidelines:
* **Concentrated Portfolio**: Targets up to **3 active holdings** with a baseline weight of **30% of total equity each** (90% total allocation).
* **Implicit Cash Buffer**: The remaining **10%** of total equity is left unallocated to act as a cash buffer.
* **Defensive Asset (TLT)**: If the market environment warrants a defensive position rather than active equity, the analyst allocates to **TLT** (iShares 20+ Year Treasury Bond ETF).
* **Dual-Path Proposing**: The analyst proposes buy allocations under one of two entry paths:
  * **Path A (Value/Dip Entry)**: Proposed for quality assets experiencing a drawdown of 10% or more from their 52-week high while maintaining a positive 5-day EWMA sentiment score (> 0.1).
  * **Path B (Momentum Breakout)**: Proposed for high-momentum assets hitting a `is_20d_high` with a `macd_bullish_cross`.
* **Minimum Holding Period**: Cannot propose to sell, reduce, or liquidate an existing holding if it has been held for **less than 21 days**, unless its 5-day EWMA sentiment score falls below **-0.5** (extremely negative).

### 2. Senior Risk Advisor (Risk Critic & Gatekeeper)
The advisor reviews the draft proposal against path-dependent risk gates and issues a structured critique:
* **Cash Buffer Guardrail**: Targets a 10% cash buffer. An adjustment is only forced if the actual cash balance drifts outside a **5% to 15%** tolerance band.
* **Rebalancing Friction Guardrail**: A target allocation is 30%. The advisor will reject adjustments to an existing position if its current weight is within a **+/- 3% tolerance band** of the target.
* **Minimum Holding Period Enforcement**: Rejects any proposal to exit or reduce positions held for less than 21 days, unless the EWMA sentiment score is below **-0.5**.
* **Valuation Ceiling Gate**: Rejects any new allocation to a stock (excluding defensive Treasury ETFs like TLT) if its Forward P/E is known and exceeds **80**, protecting the portfolio against extreme valuation bubbles.
* **Path-Dependent Entry Gating**:
  * **For Path A (Value/Dip Entry)**:
    * **Value Entry Gate**: The asset must be experiencing a **drawdown of 10% or more from its 52-week high**, and its 5-day EWMA sentiment must be bullish (**> 0.1**).
    * **Volatility Gate**: Reject the allocation if 5-day sentiment volatility is exceptionally high (standard deviation **> 0.4**) to avoid catching falling knives.
  * **For Path B (Momentum Breakout Entry)**:
    * **Value Entry Gate**: **Bypassed** (drawdown can be $< 10\%$, allowing entry near all-time highs).
    * **Volatility Gate**: **Bypassed or raised to > 0.85** (high narrative volatility is accepted as a feature of breakout news spikes).
    * **Breakout Check**: Verify that `is_20d_high = True` and `macd_bullish_cross = True`.

### 3. Mediation & Loop Resolution
If the Advisor rejects the proposal, it provides mathematical feedback, and the Analyst generates a revised proposal. This cycle repeats for up to **5 iterations**. Reaching the limit is not approval: a missing or rejected final critique cancels execution.

### 4. Deterministic Policy and Downside-Risk Authority

The agents explain and propose; deterministic Python authorizes. The policy engine independently classifies `ENTER`, `ADD`, `HOLD`, `REDUCE`, and `EXIT`, checks the account/ticker allowlists, weights, exposure, cash reserve, data freshness, entry/exit gates, order cap, and stable decision ID. High sentiment volatility is an entry/add gate only and cannot liquidate an existing holding.

Existing positions use a monotonic 14-session Wilder ATR trailing stop at 3x ATR. Completed SPY daily bars drive a 200-session SMA regime check. ATR breaches and macro risk-off can override the 21-day hold. Missing risk data blocks new exposure but does not manufacture a liquidation signal.

---

## Phase 6: Order Sizing & Execution Guards
Once allocations are approved, the broker executor determines trade sizes and applies safety filters:

1. **Trade Delta Calculation**: Computes the difference between target weights and current holding weights:
   $$\text{Delta USD} = (\text{Target \%} - \text{Current \%}) \times \text{Total Portfolio Equity}$$
2. **Tolerance Band Check**: The trade is skipped if the required change in weight is within **+/- 3%** of total equity, unless it represents a complete liquidation (target is 0%) or a brand new purchase (current weight is 0%).
3. **Sell/Buy Separation**: A market date containing a reduction or liquidation is sell-only. Buys require a fresh proposal, fresh data, and a new validated decision on a later market date; deferred lists are never replayed automatically.
4. **Buying Power Guard**: To prevent account overdrafts, buy orders are skipped if the total capital required for the purchases exceeds the spendable buying power:
   $$\text{Spendable Buying Power} = \text{Effective Buying Power} - (5\% \times \text{Total Portfolio Equity})$$
   A minimum cash reserve of **5% of total equity** must always be maintained post-execution. If buying power is insufficient, the run is cancelled rather than using fallback balances.
