# Stock Trader - Project TODOs

## Category 1: Strategic & Algorithmic Gate Changes (Entry/Exit Rules)
These tasks adjust the pre-screener filters, entry gates, volatility gates, and liquidation gates to align the strategy and prevent logical conflicts.

- [x] **Address Relative Ranking Liquidation Risk (Liquidation Gate)**
  - **Risk Score**: 2/5 (Low)
  - **Problem**: The deterministic Python screening flags the bottom-3 assets on the active watchlist as `LIQUIDATE` based purely on relative rank. On quiet news days (where scores default to `0.0`) or during sector-wide bull markets (where even the lowest score is positive), this triggers a false liquidation signal. For positions held longer than 21 days (where the minimum holding period guardrail is inactive), the LLM analyst might unnecessarily liquidate perfectly healthy assets.
  - **Proposed Solution**: Add an absolute sentiment floor check. Only allow a bottom-3 asset to be flagged as `LIQUIDATE` if its 5-day EWMA sentiment is below a certain absolute threshold (e.g., $< +0.05$).
  - **Verification & Testing Plan**:
    * **Scenario A (Spurious Liquidation Blocked)**: Mock a watchlist where the lowest-ranked stock has an EWMA sentiment of `+0.06` (bullish). Verify that the Python code overrides its signal to `HOLD` or `STRONG BUY` instead of leaving it as `LIQUIDATE`.
    * **Scenario B (Valid Liquidation Allowed)**: Mock a watchlist where the lowest-ranked stock has an EWMA sentiment of `-0.02` (bearish). Verify that the code correctly leaves its signal as `LIQUIDATE`.
    * **Verification Method**: Add a unit test in `tests/unit/test_data_ingestion.py` that passes mock histories and watchlist states to verify that the signal override is triggered correctly.

- [x] **Address No-News Ticker Systematic Downgrades (Sentiment Gate)**
  - **Risk Score**: 2/5 (Low)
  - **Problem**: The Sentiment Agent defaults to a raw score of `0.0` if there is no news coverage for a ticker in the last 24 hours. This systematically drags down the 5-day EWMA sentiment and relative rank for otherwise strongly trending, healthy stocks, potentially triggering unwarranted liquidations.
  - **Proposed Solution**: Implement a damped carry-forward of the trend in Python during the ingestion pipeline (`data_ingestion.py`) when there is no news coverage. If no news is found for a ticker, bypass LLM scoring for that asset and set:
    $$\text{raw\_score} = \text{ewma\_sentiment} \times 0.7$$
  - **Verification & Testing Plan**:
    * **Scenario A (Decay Applied)**: Mock a ticker with an empty news list and a historical 5-day EWMA sentiment of `+0.40`. Verify that the pipeline does not make an LLM API call for this ticker and sets its `raw_score` to `+0.28` (damped carry-forward).
    * **Scenario B (Zero Base Fallback)**: Mock a ticker with an empty news list and no historical sentiment data. Verify that its score defaults to `0.0`.
    * **Verification Method**: Add a unit test in `tests/unit/test_data_ingestion.py` that mocks the news fetcher to return empty results for a ticker, mocks the BigQuery history call to return a known score, and checks that the output dict matches the expected decayed score.

- [x] **Implement a Dual-Path Entry Strategy (Drawdown & Volatility Gates)**
  - **Risk Score**: 3/5 (Moderate Risk, Medium Complexity)
  - **Problem**: The Phase 1 momentum filter selects candidate assets with high momentum (high Current Price / 50-day SMA), which pushes stocks trading near their 52-week highs onto the watchlist. However, Phase 5's entry gate requires a $\ge 10\%$ drawdown from the 52-week high for new entries. This creates a structural conflict ("left hand fighting the right hand") where breakout momentum stocks are filtered in but immediately rejected by the Risk Advisor. Additionally, the Portfolio Analyst's prompt currently restricts it to only proposing oversold dips (`sustained_rsi_drop`), meaning it will never pitch breakouts even if the advisor supports them. Finally, the Risk Advisor's 0.4 sentiment volatility gate would choke out any breakouts triggered by explosive news.
  - **Proposed Solution**:
    1. **Drawdown Gate (Risk Advisor)**: Replace the fixed 10% drawdown gate with a dual-path entry condition:
       * *Path A (Value/Dip Entry)*: Permit entry if drawdown is $\ge 10\%$ from the 52-week high, with positive sentiment (EWMA $> 0.1$).
       * *Path B (Momentum Breakout Entry)*: Permit entry if the asset forms a new 20-day high with a MACD bullish cross, allowing participation in strong momentum runs at all-time highs.
    2. **Analyst Prompt Alignment (Portfolio Analyst)**: Update the Analyst's prompt instructions in `agent.py` to be explicitly aware of both Path A (dips) and Path B (breakouts) when proposing new allocations.
    3. **Volatility Gate (Risk Advisor)**: Update the Risk Advisor's gating logic to be path-dependent:
       * *For Path A*: Keep the sentiment volatility gate active at `0.4` to protect against catching falling knives during erratic news cycles.
       * *For Path B*: Completely bypass the sentiment volatility gate (or raise the acceptable threshold to `> 0.85`), accepting high narrative volatility as a necessary feature of breakout trades.
  - **Verification & Testing Plan**:
    * **Scenario A (Oversold Dip Buy)**: Mock a stock with 15% drawdown, RSI = 24, EWMA = 0.25, and Volatility = 0.15. Verify the Analyst proposes it and the Advisor approves.
    * **Scenario B (Momentum Breakout)**: Mock a stock with 1% drawdown (near highs), a new 20-day high, a MACD bullish cross, and a high sentiment volatility = 0.60. Verify the Analyst proposes it (under Path B) and the Advisor approves (bypassing drawdown and volatility gates).
    * **Scenario C (Non-Compliant Rejection)**: Mock a stock near highs (1% drawdown) but with no 20-day high or MACD cross. Verify the Advisor rejects the proposed buy.
    * **Verification Method**: Run these scenarios via a new unit test using mocked session state data, checking that the generated `AnalystProposal` and `AdvisorCritique` Pydantic models contain the expected approvals/rejections.

- [x] **Enable Quality Mean-Reversion Buys (50-Day SMA Gate)**
  - **Risk Score**: 3/5 (Moderate Risk, Medium Complexity)
  - **Problem**: The Phase 1 pre-screener completely filters out any candidate (non-owned) stock trading below its 50-day SMA. While this avoids catching falling knives, it prevents the system from buying high-quality assets undergoing short-term corrections, even if they are heavily oversold (RSI $< 30$) and have positive news sentiment.
  - **Proposed Solution**: Introduce an exception to the 50-day SMA filter for stocks showing extreme technical exhaustion/oversold indicators (e.g., RSI $< 25$) paired with positive sentiment.
  - **Verification & Testing Plan**:
    * **Scenario A (Oversold Filter Bypass)**: Mock a candidate stock trading below its 50-day SMA, but with an RSI of `22` (oversold) and positive news sentiment. Verify that `determine_active_watchlist` includes it in the watchlist as an "Oversold promotion".
    * **Scenario B (Trend Exclusion)**: Mock a candidate stock trading below its 50-day SMA with an RSI of `40` (not oversold). Verify that it is filtered out of the watchlist.
    * **Verification Method**: Add a unit test in `tests/unit/test_screener.py` that mocks the `yfinance` price/indicator returns and checks the output active watchlist list.


## Category 2: Capital Preservation & Execution Controls
These tasks handle price-based stops and profit locking to manage drawdowns and preserve gains.

- [ ] **Implement Volatility-Adjusted Stop-Loss & Cool-Off Controls (Soft/Hard Stops)**
  - **Risk Score**: 2/5 (Low Risk, but Medium Code Complexity)
  - **Problem**: There is no price-based stop-loss in the strategy. High-beta technology stocks (like DELL, SMCI) have high natural weekly price swings (+/-15%), making static stops (like -12% or -20%) highly prone to stopping out on normal noise (whipsawing). Conversely, no stops exposes the concentrated 30% positions to catastrophic drawdowns.
  - **Proposed Solution**: Implement a volatility-adjusted dynamic stop-loss framework combined with a re-entry lockout:
    * **Dynamic Stops (ATR-Based)**: Calculate the soft and hard stop percentages dynamically on each run using the stock's 30-day Average True Range (ATR) relative to its purchase entry price (e.g., Soft Stop = $-2.5 \times \text{ATR}$ from entry; Hard Stop = $-4 \times \text{ATR}$ from entry). Low-volatility assets (like TLT) get tight stops, while high-beta assets get wide stops.
    * **Soft Stop**: Overrides the 21-day minimum holding period constraint in `agent.py` prompts, allowing the portfolio analyst and risk critic to exit if sentiment decays.
    * **Hard Stop**: Bypasses the multi-agent debate loop entirely in `agent.py` orchestration, forcing an immediate market-order liquidation of the position.
    * **7-Day Re-Entry Cool-Off**: If an asset is stopped out (soft or hard), the pre-screener locks the system out from buying back into that ticker for 7 calendar days to prevent whipsawing.

- [ ] **Implement Trailing Take-Profit Controls (Trailing Profit Stop)**
  - **Risk Score**: 3/5 (Moderate Risk, Medium Complexity)
  - **Problem**: The 21-day minimum holding period prevents exiting winning trades early. In highly volatile sectors like AI, a stock can surge 35% in 10 days on a news catalyst, then give it all back over the next week before the 21 days expire, resulting in a round-trip of profits.
  - **Proposed Solution**: Implement a trailing take-profit rule that overrides the 21-day lockup. If a position gains $+15\%$ or more, activate a $5\%$ trailing stop-loss (tracked by checking peak unrealized price in history or BigQuery portfolio snapshots) to lock in profits.


## Category 3: Future Goals (High Risk & High Complexity)

- [ ] **Introduce Sentiment Cross-Validation (Dual-LLM Consensus)**
  - **Risk Score**: 4/5 (High Risk, High Complexity)
  - **Problem**: Relying on a single LLM to score news sentiment is a single point of failure. Minor fluctuations can shift scores across hold/buy boundaries, and parsing/reasoning errors can lead to bad trades.
  - **Proposed Solution**: Integrate a secondary LLM for news sentiment scoring.
    * **Consensus Metric**: Calculate the final daily sentiment score as the **Simple Average** of the two LLM scores.
    * **Divergence Resolution**: If the divergence between the two LLMs exceeds a threshold (e.g., $> 0.35$), flag the asset for divergence. Pass both scores and their qualitative theses to the Multi-Agent Debate Loop (Phase 5), allowing the Analyst and Risk Advisor to evaluate the conflict. If they cannot resolve it or if it is a new position, default the allocation to a safe `HOLD` to prevent executing high-uncertainty trades.

- [ ] **Develop an Agent-Replay Backtesting Framework**
  - **Risk Score**: 2/5 (Low Risk, Medium Complexity)
  - **Problem**: To test modifications to the LLM agent prompts, instructions, or debate loop parameters, we cannot rely on static database analysis. The agents must be run dynamically on historical data to see how their decisions would have changed.
  - **Proposed Solution**: Build a Python backtesting script that performs a historical "agent replay" over a 3-month lookback window:
    1. **Data Replay**: For each simulated day, query BigQuery for that day's recorded news sentiment, prices, and metrics.
    2. **Agent Execution**: Mock the date and portfolio state, and feed the historical context into the actual `portfolio_stabilizer_loop` (Analyst, Risk Advisor).
    3. **Portfolio Simulation**: Capture the agents' output target allocations, simulate the trade executions, track the simulated account cash and holdings value, and log performance metrics (Sharpe ratio, max drawdowns).
