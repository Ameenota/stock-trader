# P0 Live-Readiness Implementation Plan

Audience: a coding agent that needs explicit sequencing and should make one small, verifiable change at a time.

Scope: implement backlog items 1–4 in `docs/backlog.md`:

1. Deterministic pre-trade policy engine.
2. Fail closed on broker, quote, and market-data failures.
3. Separate deterministic entry, hold, add, reduce, and exit rules.
4. Add deterministic downside protection.

This plan does not authorize deployment or live trading. Keep `SKIP_LIVE_TRADES=true` throughout implementation and verification. A human will continue reviewing each proposed live run after these controls are complete.

## Desired outcome

The LLM agents may propose and explain a portfolio, but only deterministic Python may authorize an executable plan. Missing approval, invalid portfolio logic, stale data, an upstream failure, or an uncertain order result must stop execution without creating additional market exposure.

At the end of this plan:

- `BrokerExecutor` accepts only a validated execution plan, never a raw LLM allocation list.
- A final advisor rejection or exhausted debate loop can never reach order execution.
- Broker and quote failures cannot be converted into `$100` cash or an empty portfolio.
- Entry rules cannot be used as exit rules.
- Existing holdings have deterministic downside overrides based on an ATR stop and SPY regime state.
- Every P0 path has deterministic unit/integration tests.
- Agent eval results are recorded for explanation/orchestration behavior, but no safety decision depends on an LLM evaluator.

## Non-negotiable constraints

The implementing agent must follow all of these rules:

1. Do not change either Gemini model name or generation configuration.
2. Do not modify `.env`, credentials, account numbers, deployment metadata, cron configuration, or Cloud resources.
3. Do not run with `SKIP_LIVE_TRADES=false`.
4. Do not call `agents-cli deploy`, `gcloud`, or a live order tool.
5. Do not combine all four backlog items into one large edit. Complete the phases below in order.
6. After every phase, run its targeted tests before editing the next phase.
7. Use `pytest` for deterministic contracts. Do not assert on free-form LLM wording in `pytest`.
8. Use ADK eval only for non-deterministic agent behavior such as rule comprehension and explanation quality.
9. Preserve unrelated user changes. Never use `git reset --hard` or overwrite whole files.
10. If the same error occurs three times, stop and report it instead of retrying blindly.

## Fixed policy decisions

These decisions remove ambiguity for the implementing agent. Do not invent different thresholds during implementation.

| Setting | Required value |
|---|---:|
| Maximum active positions | 3 |
| Minimum cash after proposed orders | 5% of equity |
| Normal target position | 30% of equity |
| Existing-position tolerance | ±3 percentage points |
| Maximum target gross exposure | 95% of equity |
| Maximum single order | Lesser of 35% of equity or `MAX_ORDER_NOTIONAL_USD` |
| Default `MAX_ORDER_NOTIONAL_USD` | `$35.00` |
| Same-day sell and buy behavior | If any sell is planned or submitted, defer every buy until a later market date |
| Path A drawdown minimum | 10% |
| Path A EWMA minimum | Greater than 0.10 |
| Path A sentiment-volatility maximum | 0.40 |
| Path B sentiment-volatility maximum | 0.85 |
| Forward P/E ceiling for new stock risk | 80 when known |
| Hard negative-sentiment exit | EWMA below -0.50 |
| Soft exit EWMA ceiling | Below +0.05 |
| Minimum hold for a soft exit | 21 completed days |
| ATR period and multiplier | 14 sessions, 3x ATR |
| SPY regime rule | Latest completed SPY close below 200-session SMA |
| Macro risk-off target | At most 30% TLT, at least 70% cash |

Do not implement the legacy 90% TLT idea. TLT is a concentrated duration position and must remain subject to the 30% single-position target.

## Files expected to change

Prefer this file layout. Do not create alternate modules with overlapping responsibility.

| File | Purpose |
|---|---|
| `agent/app/trading_policy.py` | Pure types, action classification, proposal validation, and policy reason codes |
| `agent/app/risk_controls.py` | Pure ATR/SPY calculations and risk-override types |
| `agent/app/broker_executor.py` | Strict broker parsing, order planning/execution, reconciliation, and failure behavior |
| `agent/app/agent.py` | Final-approval gate, policy invocation, richer agent context, and orchestration only |
| `agent/app/tools/robinhood_service.py` | Strict portfolio-state fetching and account/ticker validation helpers |
| `agent/app/tools/data_ingestion.py` | Completed-bar preparation and SPY/ATR input acquisition only if needed |
| `agent/app/tools/bigquery_service.py` | Execution-run audit and position risk-state persistence |
| `agent/tests/unit/test_trading_policy.py` | Pure policy test matrix |
| `agent/tests/unit/test_risk_controls.py` | Pure ATR and SPY regime tests |
| `agent/tests/unit/test_robinhood_execution.py` | Strict broker and order failure tests |
| `agent/tests/integration/test_live_readiness_pipeline.py` | Approval → policy → executor integration tests with mocked external systems |
| `agent/tests/eval/datasets/p0-policy-dataset.json` | Small agent-behavior regression dataset if the eval harness can exercise the debate agents |
| `docs/backlog.md` | Status and verification evidence after each phase |

Do not put network calls in `trading_policy.py` or in the pure calculation functions in `risk_controls.py`.

## Phase 0 — Baseline and work isolation

### Goal

Prove the repository's starting state before changing behavior.

### Steps

1. Read:
   - `AGENTS.md`
   - `docs/backlog.md`
   - this plan
   - `agent/app/agent.py`
   - `agent/app/broker_executor.py`
   - `agent/app/tools/robinhood_service.py`
   - `agent/app/tools/bigquery_service.py`
   - the relevant existing tests
2. Run `git status --short` and record unrelated modified/untracked files. Do not modify them.
3. From `agent/`, run:

   ```bash
   uv sync
   PYTHONPATH=. uv run pytest tests/unit/test_decoupled_loop.py tests/unit/test_robinhood_execution.py tests/unit/test_trading_agent.py
   ```

4. If baseline tests fail, record the failures before making P0 changes. Do not silently adjust the plan to hide them.
5. Update backlog item 1 to `In progress` and update `Last reviewed`.

Current tooling note: `agents-cli info` reported CLI v0.5.1 with locally installed ADK skills at v0.5.0. Do not run `agents-cli update` as part of this work unless the human explicitly expands scope; record the mismatch if it affects a command.

### Exit criteria

- The baseline command and result are recorded in the eventual backlog evidence.
- No production behavior has changed.

## Phase 1 — Create the deterministic policy boundary

This phase implements the core of backlog item 1 without changing broker network behavior yet.

### 1.1 Add internal policy types

Create `agent/app/trading_policy.py`. Use frozen dataclasses or Pydantic models with strict validation. Do not reuse raw dictionaries past the orchestration boundary.

Define these types:

```text
TradeAction enum:
  ENTER, ADD, HOLD, REDUCE, EXIT

PolicyViolation:
  code: stable uppercase string
  message: human-readable explanation
  ticker: optional ticker

HoldingState:
  ticker, shares, price, equity, weight, days_held

AssetPolicyMetrics:
  ticker, observed_at, sentiment_ewma, sentiment_volatility,
  drawdown_pct, forward_pe, is_20d_high, macd_bullish_cross,
  final_signal

RiskOverride:
  ticker, stop_breached, macro_risk_off, reason

PlannedTrade:
  ticker, action, current_weight, target_weight, delta_weight, reason_codes

PolicyDecision:
  allowed, decision_id, normalized_allocations, planned_trades, violations

ValidatedExecutionPlan:
  decision_id, account_number, created_at, expires_at,
  allocations, planned_trades, policy_version
```

Requirements:

- Reject NaN and infinity for every numeric field.
- Normalize tickers to uppercase once.
- Use stable violation codes so tests and logs do not depend on prose.
- Start `policy_version` at `p0-v1`.
- `ValidatedExecutionPlan` must only be constructed by a successful policy function. A leading-underscore constructor helper is sufficient; Python secrecy is not required, but normal callers must receive it from validation.

Suggested violation codes:

```text
ADVISOR_NOT_APPROVED
MISSING_DECISION_ID
DUPLICATE_DECISION_ID
UNAUTHORIZED_ACCOUNT
UNKNOWN_TICKER
DUPLICATE_ALLOCATION
INVALID_WEIGHT
TOO_MANY_POSITIONS
GROSS_EXPOSURE_EXCEEDED
CASH_RESERVE_VIOLATION
STALE_MARKET_METRICS
MISSING_MARKET_METRICS
ENTRY_GATE_FAILED
ADD_GATE_FAILED
EXIT_NOT_AUTHORIZED
HOLDING_PERIOD_VIOLATION
ORDER_NOTIONAL_EXCEEDED
RISK_DATA_UNAVAILABLE
SAME_DAY_SELL_BUY
```

### 1.2 Implement global proposal validation

Add a pure function with an explicit signature similar to:

```python
def validate_pretrade_plan(
    *,
    advisor_approved: bool,
    decision_id: str,
    account_number: str,
    allocations: list[dict],
    holdings: list[HoldingState],
    metrics_by_ticker: dict[str, AssetPolicyMetrics],
    overrides_by_ticker: dict[str, RiskOverride],
    total_equity: float,
    allowed_tickers: set[str],
    already_executed: bool,
    now: datetime,
) -> PolicyDecision:
    ...
```

Apply checks in this order and collect all violations before returning:

1. Advisor approval is exactly `True`.
2. Decision ID is present and has not already executed.
3. Account number ends in `48661`.
4. Equity is finite and greater than zero.
5. Every allocation has exactly one allowed ticker and a finite weight between 0 and 1.
6. No duplicate tickers.
7. At most three positive target positions.
8. Total target exposure is at most 0.95.
9. Each new position targets 0.30. Existing protected positions may retain their current out-of-band weight.
10. Required market metrics and risk state exist and are fresh.
11. Classify every held or targeted ticker into an action; Phase 3 will provide the full action rules.
12. If the classified actions contain any `REDUCE` or `EXIT`, reject a plan that also contains `ENTER` or `ADD` with `SAME_DAY_SELL_BUY`. The system must produce a sell-only plan; buys require a newly generated and validated decision on a later market date.
13. Calculate estimated order notional and reject an order above the configured cap.

Do not partially approve a proposal. Any violation means `allowed=False`, no `ValidatedExecutionPlan`, and zero broker calls.

### 1.3 Enforce final advisor approval in orchestration

In `financial_analysis_pipeline()` in `agent/app/agent.py`:

1. Retrieve both `analyst_proposal` and `advisor_critique` after the loop.
2. Convert dictionary/Pydantic forms through one small helper each; avoid duplicated parsing branches.
3. If the critique is missing or `approved` is not exactly `True`:
   - Print a critical policy rejection.
   - Record a rejected execution run.
   - Send the normal failure/notification path if available.
   - Do not instantiate or call `BrokerExecutor`.
   - Return the ranked portfolio without changing target weights to an executable state.
4. Query whether `decision_id` already executed.
5. Call `validate_pretrade_plan()`.
6. Only call the executor with the resulting `ValidatedExecutionPlan`.

The decision ID should be deterministic for the same execution window. Use a value based on:

```text
market date + configured execution window + account suffix + policy version
```

Do not include a random UUID in the decision ID. Retries must produce the same ID.

### 1.4 Make the executor reject raw allocations

Change the executor signature to:

```python
async def execute_rebalance(
    self,
    plan: ValidatedExecutionPlan,
) -> ExecutionResult:
```

At the start of the method, verify the runtime object type and account match. A plain list or dictionary must raise `TypeError` before broker tools are requested.

Keep order math separate from order submission:

```text
build_orders(plan, broker_state, quotes) -> OrderBatch
submit_orders(order_batch, tools) -> ExecutionResult
```

Both functions should have typed results. `build_orders` must be pure.

### 1.5 Add execution-run audit storage

Extend `setup_bigquery()` with an `execution_runs` table containing at least:

```text
decision_id STRING REQUIRED
created_at TIMESTAMP REQUIRED
updated_at TIMESTAMP REQUIRED
dry_run BOOLEAN REQUIRED
policy_version STRING REQUIRED
policy_allowed BOOLEAN REQUIRED
status STRING REQUIRED
violations STRING NULLABLE
proposal STRING NULLABLE
execution_result STRING NULLABLE
```

Add helpers:

```text
execution_run_exists(decision_id, dry_run, dataset_id) -> bool
insert_execution_run(...)
update_execution_run(...)
```

Allowed statuses:

```text
POLICY_REJECTED
VALIDATED
EXECUTING
COMPLETED
ABORTED
RECONCILIATION_FAILED
```

BigQuery does not provide a simple unique constraint here. The existence check is still required for cron retries, and backlog item 5 can later add stronger distributed idempotency.

### Phase 1 tests

Create `agent/tests/unit/test_trading_policy.py` and cover:

1. Approved valid three-position proposal passes.
2. Missing critique fails with `ADVISOR_NOT_APPROVED`.
3. Rejected critique fails with `ADVISOR_NOT_APPROVED`.
4. Duplicate decision fails.
5. Unauthorized account fails.
6. Unknown ticker fails.
7. Duplicate allocation fails.
8. Negative, greater-than-one, NaN, and infinite weights fail.
9. Four positive targets fail.
10. Gross exposure above 95% fails.
11. A proposal implying both a sell and a buy fails with `SAME_DAY_SELL_BUY` before broker access.
12. A sell-only proposal may pass when all other rules pass.
13. Raw allocations passed directly to `BrokerExecutor` fail before `get_tools()`.
14. `financial_analysis_pipeline()` never calls the executor when the final critique is rejected or absent.

Run:

```bash
cd agent
PYTHONPATH=. uv run pytest tests/unit/test_trading_policy.py tests/unit/test_decoupled_loop.py tests/unit/test_bigquery_service.py
```

### Phase 1 exit criteria

- All targeted tests pass.
- A rejected/exhausted debate loop provably makes zero broker calls.
- `BrokerExecutor` cannot accept a raw LLM proposal.
- Backlog item 1 remains `In progress` until Phases 2 and 3 complete the policy inputs.

## Phase 2 — Fail-closed broker and order handling

This phase implements backlog item 2.

### 2.1 Replace broker fallback values with explicit failures

In `agent/app/tools/robinhood_service.py`:

1. Add specific exceptions:

   ```text
   BrokerConnectionError
   BrokerPayloadError
   BrokerToolUnavailableError
   QuoteValidationError
   OrderRejectedError
   OrderStateUnknownError
   ```

2. Replace `total_cash = 100.0`, `buying_power = 100.0`, and empty-position fallbacks.
3. Require these tools before a run can be executable:
   - `get_portfolio`
   - `get_equity_positions`
   - `get_equity_quotes` when any position or target exists
   - `place_equity_order` in live mode
4. Validate every required response path and type. Missing `structuredContent`, `data`, `cash`, `buying_power`, `positions`, or quote fields must raise an exception.
5. Validate cash, buying power, shares, prices, and equity as finite non-negative numbers.
6. Never convert a broker exception to a tradable portfolio.

Return a typed `BrokerPortfolioState`, not a tuple. It should contain:

```text
account_number
observed_at
cash
buying_power
holdings
```

### 2.2 Validate quotes strictly

Create one quote parser used by both the initial pipeline state and executor reconciliation.

Rules:

- Every current or target ticker must have exactly one quote.
- Price must be finite and greater than zero.
- Prefer a regular-session last price according to the MCP response contract. Do not silently choose an arbitrary field.
- If a quote timestamp exists, reject quotes older than 120 seconds for execution.
- If the MCP response does not provide a usable timestamp, stamp the observation when the response is received and document that limitation.
- A missing quote cancels the entire order batch; do not skip only that ticker.

### 2.3 Make order acknowledgment explicit

Create an `OrderReceipt` parser. An order is acknowledged only if the broker response contains an explicit accepted/success state and a non-empty broker order ID.

Rules:

- Do not treat a non-empty dictionary as success.
- Do not log `BUY`, `SELL`, or `LIQUIDATE` as executed before acknowledgment.
- Store `SUBMITTED`/`ACCEPTED` separately from `FILLED` when the API exposes those states.
- If an order response is malformed or ambiguous, set the run to `ABORTED` or `RECONCILIATION_FAILED` and stop.

Extend `trade_history` additively with nullable fields:

```text
decision_id STRING
broker_order_id STRING
order_status STRING
requested_quantity FLOAT
filled_quantity FLOAT
```

Do not delete or reinterpret existing rows.

### 2.4 Never sell and buy on the same market date

The current executor can sell and then buy in the same run. Replace that behavior with this sequence:

1. Submit sells serially.
2. On the first rejected or unknown sell, stop submitting more orders and abort all buys.
3. If the validated plan contains any sell, defer every buy in that plan. Do not submit a buy later in the same run or market date, even if buying power updates immediately.
4. Re-fetch broker state to reconcile the sell acknowledgments/fills for audit purposes only.
5. Retry reconciliation at most three times with `await asyncio.sleep(1)` between attempts. Inject or patch sleep in tests.
6. Record deferred buys as `DEFERRED_NEXT_MARKET_DATE`; do not record them as submitted, accepted, filled, or simulated purchases.
7. On the next market date, run the full pipeline again using fresh holdings, cash, quotes, market metrics, risk state, advisor approval, and policy validation. Do not automatically replay yesterday's deferred buy list.
8. If a validated plan contains buys and no sells, calculate the buy budget from current authoritative buying power and submit buys only if the 5% cash reserve remains intact.
9. On a rejected/unknown buy, stop remaining buys.
10. Fetch a final state and compare positions/cash with acknowledged or filled results.
11. Mark the execution run `COMPLETED` only after successful reconciliation. Otherwise mark `RECONCILIATION_FAILED`.

For dry-run mode, do not call `place_equity_order`. Apply the planned orders to an in-memory copy of the fetched state for this run and return simulated receipts clearly marked `SIMULATED`. Do not label them filled live trades.

### 2.5 Keep account and ticker validation in the direct execution path

`validate_and_intercept_trades()` is attached to the ADK `root_agent`, but `BrokerExecutor` invokes MCP tools directly. Therefore:

- Reuse pure account/ticker validator functions inside `BrokerExecutor` immediately before every order.
- Keep the ADK callback as defense in depth for agent-originated tool calls.
- Add a test proving direct executor calls reject a bad account and an unknown ticker even when no callback runs.

### Phase 2 tests

Expand `test_robinhood_execution.py` to cover:

1. Missing `get_portfolio` tool aborts with zero order calls.
2. Portfolio timeout aborts with zero order calls.
3. Missing cash or buying power aborts.
4. Positions payload missing or malformed aborts.
5. One missing quote aborts the whole batch.
6. Zero, negative, NaN, or infinite quote aborts.
7. Sell rejection prevents every buy.
8. Unknown sell state prevents every buy.
9. A successful sell still defers every buy until a later market date.
10. Deferred buys are not automatically replayed; the next market date requires a fresh proposal and validation.
11. A buy-only plan uses current authoritative buying power.
12. Buying power below the requirement prevents buys.
13. Buy rejection prevents later buys.
14. A response without an order ID is not recorded as accepted.
15. Final reconciliation mismatch produces `RECONCILIATION_FAILED`.
16. Dry-run sells are `SIMULATED`, while same-plan buys are `DEFERRED_NEXT_MARKET_DATE` and are not simulated as purchases.
17. Direct executor order validation rejects a bad account and ticker.

Run:

```bash
cd agent
PYTHONPATH=. uv run pytest tests/unit/test_robinhood_execution.py tests/unit/test_trading_agent.py tests/unit/test_bigquery_service.py
```

### Phase 2 exit criteria

- All broker/data failures result in zero additional exposure.
- There is no `$100` or empty-portfolio fallback on an executable path.
- A failed/unknown sell makes all buys impossible.
- Any planned or submitted sell makes all buys impossible until a fresh run on a later market date.
- Backlog item 2 is marked `Done` with the test command and result recorded.

## Phase 3 — Deterministic action and entry/exit semantics

This phase completes backlog item 3 and the remaining action-specific checks in item 1.

### 3.1 Classify actions from current and target state

In `trading_policy.py`, classify each ticker using current and target weight:

```text
current == 0 and target > 0                  -> ENTER
current > 0 and target > current + 0.03      -> ADD
current > 0 and abs(target-current) <= 0.03  -> HOLD
current > 0 and 0 < target < current - 0.03  -> REDUCE
current > 0 and target == 0                  -> EXIT
```

Use a small numeric epsilon for equality. Do not classify from the LLM's prose signal.

An existing holding that fails today's entry gates remains eligible for `HOLD`. Failing an entry gate must never create `REDUCE` or `EXIT`.

### 3.2 Enforce ENTER and ADD gates

For ordinary stocks, `ENTER` and `ADD` require Path A or Path B plus the valuation ceiling.

Path A requires all of:

```text
drawdown_pct >= 10
sentiment_ewma > 0.10
sentiment_volatility <= 0.40
forward_pe is missing OR forward_pe <= 80
```

Path B requires all of:

```text
is_20d_high is True
macd_bullish_cross is True
sentiment_volatility <= 0.85
forward_pe is missing OR forward_pe <= 80
```

TLT rules:

- TLT is exempt from the stock P/E and drawdown rules.
- A normal defensive TLT entry still cannot exceed 30%.
- During macro risk-off, the deterministic override may target TLT at 30% and cash at 70%.

If no path passes, reject the entire proposal with `ENTRY_GATE_FAILED` or `ADD_GATE_FAILED`.

### 3.3 Enforce REDUCE and EXIT gates

Authorize a reduction or exit only when at least one explicit rule passes:

1. `stop_breached is True`; allowed regardless of holding age.
2. `macro_risk_off is True`; allowed regardless of holding age.
3. `sentiment_ewma < -0.50`; allowed regardless of holding age.
4. Soft exit: `days_held >= 21`, final deterministic/agent signal is `LIQUIDATE`, and `sentiment_ewma < +0.05`.

Otherwise reject with `EXIT_NOT_AUTHORIZED`. If the only issue is a soft exit before day 21, also include `HOLDING_PERIOD_VIOLATION`.

Important behavior:

- Sentiment volatility above 0.40 is never an exit reason.
- Drawdown above 10% is never an exit reason by itself.
- Reaching day 21 does not itself trigger an exit.
- An LLM `LIQUIDATE` signal without the deterministic sentiment/age condition cannot execute.
- A held ticker omitted from the allocation list implies a requested `EXIT` and must pass these rules.
- After classification, any mixture of `REDUCE`/`EXIT` with `ENTER`/`ADD` is rejected with `SAME_DAY_SELL_BUY`; the analyst must return a sell-only target for that market date.

### 3.4 Preserve prompts unless policy evidence shows they need adjustment

Do not change the analyst or advisor prompts during the initial Proposal 3 implementation. The immediate bug is the absence of deterministic action/exit validation between the approved target and `BrokerExecutor`, not the executor's order math.

After deterministic tests and a dry-run replay pass, measure whether the unchanged agents repeatedly produce policy-rejected proposals. Change prompts only if evidence shows that these rejections materially prevent useful operation. If a prompt change becomes necessary, make it a separate, reviewable change that:

- Clearly separates rules for new entries/additions from rules for reductions/exits.
- States that high sentiment volatility blocks `ENTER`/`ADD` but does not justify selling an existing holding.
- States all four authorized exit paths.
- Includes `is_20d_high`, `macd_bullish_cross`, risk overrides, and data timestamps in both analyst and advisor contexts.
- States that deterministic Python is the final authority.

Do not change the model. Do not add tool calling to agents that use `output_schema`; ADK structured output disables tool calling.

### 3.5 Add the July 20 regression fixture

Create a deterministic fixture matching the important state from `/tmp/stock-trader/Monday_13_00.log`:

```text
MU: held 24 days, weight about 29.3%, EWMA about +0.353,
    sentiment volatility about 0.665
MRVL: held 21 days, weight about 28.6%, EWMA about +0.284,
      sentiment volatility about 0.552
SNDK: held 2 days, weight about 26.7%, EWMA about +0.425,
      sentiment volatility about 0.526
```

Required assertions:

- A proposal to retain these positions at current weights is allowed as `HOLD` even though volatility exceeds 0.40.
- A proposal to add to MU/MRVL/SNDK is rejected unless another entry path passes.
- A proposal to exit MU or MRVL solely because volatility exceeds 0.40 is rejected with `EXIT_NOT_AUTHORIZED`.
- SNDK cannot be reduced merely because its volatility exceeds 0.40.

### Phase 3 tests

Add at least these cases to `test_trading_policy.py`:

1. New Path A entry passes.
2. New Path A entry with volatility 0.401 fails.
3. New Path B entry with volatility 0.60 passes.
4. New Path B entry with volatility 0.851 fails.
5. Existing high-volatility holding can hold.
6. Existing high-volatility holding cannot be exited for volatility alone.
7. Hard EWMA exit below -0.50 passes before day 21.
8. Soft exit passes at day 21 with `LIQUIDATE` and EWMA below +0.05.
9. Soft exit fails at day 20.
10. Soft exit fails when EWMA is +0.05 or higher.
11. Stop override passes regardless of age.
12. Macro override passes regardless of age.
13. Held ticker omitted from targets is treated as an exit request.
14. Full July 20 regression fixture passes the assertions above.

Run:

```bash
cd agent
PYTHONPATH=. uv run pytest tests/unit/test_trading_policy.py tests/unit/test_decoupled_loop.py tests/unit/test_category_1_gates.py
```

### Phase 3 exit criteria

- Entry gates cannot cause exits.
- The July 20 regression is permanently covered.
- The deterministic policy enforces the action rules regardless of prompt behavior.
- Any prompt change is supported by recorded policy-rejection evidence and reviewed separately.
- Backlog items 1 and 3 are marked `Done` with verification evidence.

## Phase 4 — ATR stop and SPY macro circuit breaker

This phase implements backlog item 4.

### 4.1 Add completed-daily-bar normalization

Add a helper that accepts a price DataFrame and `now` and returns only completed daily bars.

Rules:

- Require timezone-aware `now` in tests.
- Interpret market time in `America/New_York` using the standard library `zoneinfo`.
- If the last bar is dated today and current New York time is before 16:15, drop that bar.
- Require finite `High`, `Low`, and `Close` values.
- Sort ascending and reject duplicate dates.
- Do not forward-fill OHLC data.

This helper must be pure. Fetching from yfinance belongs in a separate adapter.

### 4.2 Implement pure ATR math

In `risk_controls.py`, implement true range exactly as:

```text
max(
  high_t - low_t,
  abs(high_t - close_(t-1)),
  abs(low_t - close_(t-1))
)
```

Use a 14-session Wilder ATR. Document the initialization and make tests use the same definition. Do not hide NaNs by filling them with zero.

Fetch at least 60 calendar days before the entry date and enough history after entry to evaluate every completed session. If 14 valid pre/evaluation sessions are unavailable, return `RISK_DATA_UNAVAILABLE`; do not invent a stop.

### 4.3 Implement the monotonic trailing stop without look-ahead

For each completed session `t` after initialization:

1. Determine whether `close_t < stop_(t-1)`. A breach uses the stop known before session `t` completed.
2. Calculate candidate stop `high_t - 3 * ATR_t`.
3. Set `stop_t = max(stop_(t-1), candidate_stop)`.

This ordering prevents the current session's high from raising the stop and retrospectively stopping the same session using information unavailable at the start of the bar.

Return a structured result:

```text
ticker
as_of_session
atr
previous_stop
current_stop
highest_high
breached
reason
```

### 4.4 Persist position risk state

Add an additive BigQuery table `position_risk_state`:

```text
account_suffix STRING REQUIRED
ticker STRING REQUIRED
entry_timestamp TIMESTAMP REQUIRED
last_session DATE REQUIRED
highest_high FLOAT REQUIRED
stop_price FLOAT REQUIRED
atr FLOAT REQUIRED
breached BOOLEAN REQUIRED
updated_at TIMESTAMP REQUIRED
source STRING REQUIRED
```

Use a BigQuery `MERGE` keyed by account suffix and ticker. The persisted stop may only increase. Reject an attempted lower stop.

Existing-position bootstrap:

- Reconstruct the currently open trade segment from live trade history: find the most recent confirmed full `LIQUIDATE`, then use the earliest confirmed live `BUY` after that event. If no full liquidation exists, use the earliest confirmed live `BUY` available for the open position.
- Do not use dry-run trades for live state.
- If no reliable entry timestamp exists, mark risk state unavailable, block `ADD` for that ticker, and alert the human reviewer.
- Do not guess an entry date from the last simulated trade.

Human-provided Robinhood transaction evidence from 2026-07-20:

| Ticker | Transaction | Date | Quantity | Execution price | Total | Backfill use |
|---|---|---|---:|---:|---:|---|
| SNDK | Market buy | 2026-07-01 | 0.01376 shares | $2,062.00 | $28.37 | Use 2026-07-01 as the current position entry date after confirming the quantity still matches the live holding. |
| MRVL | Market buy | 2026-06-29 | 0.105127 shares | $269.50 | $28.33 | Use 2026-06-29 as the current position entry date after confirming the quantity still matches the live holding. |
| TSM | Market sell | 2026-06-29 | 0.0658 shares | $452.58 | $29.78 | Treat as evidence that the prior TSM position was closed; do not initialize an active TSM trailing stop unless Robinhood currently reports a position. |

The current MU entry date is not established by this screenshot. Resolve MU from authoritative Robinhood/BQ live trade history or obtain a separate human-provided transaction record. If neither is available, initialize MU using the reviewed `BOOTSTRAPPED_CURRENT_DATE` procedure rather than guessing an earlier entry date.

For SNDK and MRVL, fetch price history beginning at least 60 calendar days before the dates above, replay the ATR stop from the entry date through the latest completed session, and store the source as `HUMAN_CONFIRMED_ROBINHOOD_HISTORY`. If broker state shows a different current quantity or a later full liquidation/re-entry, stop and reconcile the discrepancy before persisting risk state.

### 4.5 Implement the SPY 200-session regime check

Use completed daily SPY closes only.

```text
sma_200 = mean(last 200 completed closes)
macro_risk_off = latest_completed_close < sma_200
```

Require at least 200 valid completed closes. Return a structured result with observation time, last session, close, SMA, state, and reason.

Failure behavior:

- If SPY history is unavailable or insufficient, reject new `ENTER`/`ADD` actions with `RISK_DATA_UNAVAILABLE`.
- Do not force liquidation from missing SPY data.
- Do not silently continue as risk-on.
- Alert the human reviewer.

### 4.6 Integrate risk overrides before the debate loop

In `financial_analysis_pipeline()`:

1. Fetch broker state successfully.
2. Calculate risk state for every holding.
3. Calculate SPY regime state.
4. Add structured risk data to session state for both agents.
5. If an ATR breach exists, deterministic policy requires exit regardless of the LLM proposal. Prefer constructing the risk-required target directly rather than hoping the LLM follows a string instruction.
6. If macro risk-off is true, bypass the debate loop. When equities must be sold, construct a sell-only target first; a fresh validated decision on a later market date may then construct this defensive target:

   ```text
   TLT: 30% target
   Cash: implicit 70%
   Existing equities: exit requests authorized by macro override
   ```

   This sequencing resolves the otherwise contradictory requirements to exit equities, buy TLT, and never sell and buy on the same market date.
7. Pass the deterministic target through the same pre-trade policy and broker execution path. A risk override does not bypass account, quote, order-size, cash, or broker-state checks.

### Phase 4 tests

Create `test_risk_controls.py` with:

1. True-range calculation for an ordinary bar.
2. True range across a gap up.
3. True range across a gap down.
4. Wilder ATR initialization and next-step update.
5. Insufficient ATR history returns unavailable.
6. Stop rises when highs rise.
7. Stop never decreases when prices fall.
8. Close below the prior stop breaches.
9. Same-session newly raised stop does not create look-ahead breach.
10. Current incomplete daily bar is excluded.
11. Duplicate/non-finite bars fail.
12. SPY above SMA is risk-on.
13. SPY below SMA is risk-off.
14. Exactly 199 SPY closes is unavailable.
15. Missing SPY data blocks entries/additions but does not force exits.
16. Persisted stop cannot be lowered.
17. Missing live entry history blocks additions and alerts.

Add integration tests for:

1. ATR breach exits a position held fewer than 21 days.
2. Macro risk-off bypasses the debate loop.
3. Macro target is 30% TLT and 70% cash.
4. Macro override still fails closed when TLT quote is unavailable.
5. No risk override plus high entry volatility leaves an existing position held.

Run:

```bash
cd agent
PYTHONPATH=. uv run pytest tests/unit/test_risk_controls.py tests/unit/test_trading_policy.py tests/integration/test_live_readiness_pipeline.py
```

### Phase 4 exit criteria

- ATR and SPY calculations use completed bars and deterministic fixtures.
- Risk overrides feed the policy engine directly.
- Missing risk data cannot increase exposure.
- Backlog item 4 is marked `Done` with verification evidence.

## Phase 5 — Full verification and human handoff

Do not begin this phase until every targeted phase test passes.

### 5.1 Run deterministic verification

From `agent/`:

```bash
uv sync
PYTHONPATH=. uv run pytest
agents-cli lint
```

If lint reports pre-existing unrelated issues, record them separately. Do not rewrite unrelated files to make the command green.

### 5.2 Run ADK behavior evaluation

The current basic eval dataset is generic. Replace or supplement it with a small trading-specific dataset only if the eval harness actually exercises the analyst/advisor behavior. Do not claim the generic greeting/weather cases validate this work.

Minimum behavior scenarios:

1. Existing high-volatility, positive-EWMA holding should be explained as `HOLD`, not liquidated for volatility alone.
2. New Path A candidate above the volatility ceiling should be rejected.
3. ATR stop breach should be described as a mandatory exit.
4. Macro risk-off should not recommend adding equity exposure.

Use rubric-based metrics for rule comprehension and explanation quality. Do not hardcode exact prose or tool sequences.

Run the configured evaluation:

```bash
agents-cli eval generate --dataset tests/eval/datasets/p0-policy-dataset.json
agents-cli eval grade
```

If the current app structure cannot seed the debate-loop state through `agents-cli eval`, record that limitation and rely on deterministic integration tests for the release gate. Do not refactor the whole application merely to make an eval command convenient.

### 5.3 Run one end-to-end dry-run replay

Use a mocked or isolated dataset, never live execution. The replay must show:

- Advisor approval status.
- Policy decision and reason codes.
- Deterministic action per ticker.
- ATR and SPY risk state.
- Planned orders.
- Simulated receipts.
- Final simulated cash and holdings.
- No live broker order calls.

Replay the July 20 fixture and verify MU/MRVL are not liquidated solely for high sentiment volatility.

### 5.4 Update documentation

In the same change:

1. Update each implemented backlog item to `Done` only if its acceptance criteria pass.
2. Record exact test/eval commands and results below each item.
3. Update `Last reviewed`.
4. Update `README.md` and `docs/portfolio_decision_logic.md` if behavior changed from their descriptions.
5. Correct `AGENTS.md` safety-guardrail claims if the final implementation differs.

### 5.5 Human launch checklist

Completion of this plan does not itself enable live trading. Present this checklist to the human reviewer:

```text
[ ] All four P0 backlog items are Done with evidence.
[ ] Full pytest suite passes.
[ ] July 20 regression passes.
[ ] Failure-injection tests prove zero orders on every upstream error.
[ ] Rejected/exhausted debate produces zero orders.
[ ] One end-to-end dry run was reviewed.
[ ] Proposed allocations and reason codes were manually reviewed.
[ ] Account suffix and maximum order notional were manually confirmed.
[ ] Kill switch behavior was manually confirmed.
[ ] Deployment/live-trading approval was explicitly given in a separate action.
```

## Required implementation order

The implementing agent must follow this sequence:

```text
Phase 0 baseline
  -> Phase 1 types and approval/policy boundary
  -> Phase 1 tests
  -> Phase 2 strict broker handling
  -> Phase 2 tests
  -> Phase 3 action semantics
  -> July 20 regression tests
  -> Phase 4 ATR/SPY controls
  -> Phase 4 tests
  -> Full suite and lint
  -> ADK behavior eval where applicable
  -> Dry-run replay
  -> Documentation and human handoff
```

Do not work ahead when a phase is failing. The goal is a chain of small proofs, not a large patch that is difficult to audit.

## Final completion report format

The implementing agent's final response must include:

1. Files changed, grouped by backlog item.
2. Behavior before and after.
3. Every verification command and its pass/fail count.
4. Any eval scores and the result artifact path.
5. Dry-run replay result and confirmation that no live order tool ran.
6. Remaining risks or blocked acceptance criteria.
7. Explicit statement that live trading and deployment were not enabled.

Do not say “ready for live trading” if any P0 acceptance criterion, test, reconciliation check, or human checklist item remains incomplete.
