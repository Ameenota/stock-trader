# Stock Trader Backlog

This is the canonical engineering and strategy backlog for the stock trader. Items are ordered by expected impact on capital safety and risk-adjusted performance, not by implementation ease.

Last reviewed: 2026-07-21

Detailed implementation sequence for P0 items 1–4: `docs/p0_live_readiness_implementation_plan.md`.

Detailed account-scoped experimentation, migration, failure, and test plan: `docs/account_scoped_experimentation_implementation_plan.md`.

## Status and priority

- Status: `Proposed`, `Ready`, `In progress`, `Blocked`, or `Done`.
- Priority: `P0` blocks live trading, `P1` is the next highest-impact strategy work, and `P2` is an optimization.
- Keep `SKIP_LIVE_TRADES=true` while any P0 item remains incomplete.
- An item is not `Done` until its acceptance criteria are verified and the evidence is recorded here.

## Prioritized backlog

### 1. Deterministic pre-trade policy engine

- Priority: P0
- Status: Done
- Impact: Critical
- Problem: Portfolio constraints are primarily enforced by LLM prompts. The pipeline retrieves the last analyst proposal and can pass it to `BrokerExecutor` without proving that the final advisor critique was approved. The executor also lacks a complete independent validation of allocation semantics.
- Work:
  - Require `advisor_critique.approved is True` before any execution path.
  - Validate the ticker allowlist, maximum position count, target weights, total exposure, minimum cash, holding-period restrictions, entry/exit rules, price freshness, maximum order notional, and duplicate-run protection in deterministic Python.
  - Reject any plan that combines `REDUCE`/`EXIT` with `ENTER`/`ADD`; a market date containing sells must use a sell-only plan, and buys require a fresh later-date decision.
  - Treat malformed, missing, contradictory, or stale inputs as a cancelled run.
  - Wire the MCP interceptor explicitly or enforce equivalent account and ticker checks directly in the executor; add a test proving the protection is active.
- Acceptance criteria:
  - A rejected or missing critique produces zero orders.
  - Invalid tickers, weights, exposure, stale prices, and duplicate decision IDs produce zero orders.
  - A proposal implying both sells and buys is rejected before broker tools are requested.
  - Tests cover every rejection reason and one valid portfolio.
  - The dry-run report records the policy result and reason codes.
- Verification evidence (2026-07-20): `PYTHONPATH=. uv run pytest` passed 101 tests; the final P0-focused matrix passed 81 tests. `test_trading_policy.py` covers stable policy reason codes, the valid portfolio, raw-plan rejection, duplicate decisions, stale/missing inputs, exposure, order caps, and sell/buy separation. Dry-run JSON and `execution_runs` records include the policy result and reason codes.

### 2. Fail closed on broker, quote, and market-data failures

- Priority: P0
- Status: Done
- Impact: Critical
- Problem: Broker helpers currently fall back to `$100` cash and an empty portfolio when calls fail. This can turn an authentication, parsing, or network failure into a false fully funded account.
- Work:
  - Remove tradable fallback values from live and dry-run execution inputs.
  - Require successful cash, buying-power, holdings, and quote responses before computing orders.
  - Reject zero, missing, stale, crossed, or implausible prices.
  - Abort remaining orders after any sell rejection or uncertain order result.
  - If a run plans or submits any sell, defer all buys until a fresh, fully validated run on a later market date; never automatically replay a stale deferred buy.
  - Add a run-level kill switch and a prominent Discord failure notification.
- Acceptance criteria:
  - Every upstream failure scenario produces zero new orders.
  - Partial execution is reconciled from broker state, and no sell-and-buy combination can execute on the same market date.
  - Tests cover timeouts, malformed payloads, missing quotes, rejected orders, and unknown order state.
- Verification evidence (2026-07-20): strict broker tests cover missing tools, timeouts, malformed balances/positions, missing/zero/negative/non-finite/stale/crossed quotes, authoritative buying power, rejected/unknown acknowledgments, central account/ticker validation, sell-only deferral, and three-attempt filled-order reconciliation. The run-level `TRADING_KILL_SWITCH` and critical Discord failure summary are wired. Full suite: 101 passed.

### 3. Separate deterministic entry, hold, add, reduce, and exit rules

- Priority: P0
- Status: Done
- Impact: Critical
- Evidence: On 2026-07-20, the 07:00 and 10:00 dry runs held MU/MRVL/SNDK. The 13:00 run proposed liquidating MU and MRVL despite positive EWMA sentiment because the advisor applied the Path A entry-volatility ceiling to existing positions.
- Problem: Entry eligibility is being reused as an exit rule. A position failing today's entry gate does not imply that liquidation has positive expected value.
- Work:
  - Model `ENTER`, `ADD`, `HOLD`, `REDUCE`, and `EXIT` as distinct deterministic actions.
  - Apply drawdown and sentiment-volatility gates only to `ENTER`/`ADD` unless an independently specified exit rule is met.
  - Define exits using explicit evidence such as a trailing-stop breach, macro override, sustained negative signal, invalidated thesis, or hard portfolio-risk limit.
  - Make the LLM produce explanations and candidate preferences, not final rule interpretations.
  - Preserve the existing prompts initially; update them only if deterministic rejection logs show repeated unusable proposals, and review that prompt change separately.
- Acceptance criteria:
  - High sentiment volatility alone cannot liquidate an existing holding.
  - Identical portfolio state and completed-bar inputs yield identical allowed actions.
  - Regression fixtures reproduce and prevent the July 20 MU/MRVL reversal.
- Verification evidence (2026-07-20): deterministic policy tests distinguish all five actions and cover Path A/Path B boundaries, hard/soft exits, holding age, ATR/macro overrides, and the MU/MRVL/SNDK July 20 fixture. High volatility alone holds rather than liquidates. Full suite: 101 passed.

### 4. Add deterministic downside protection

- Priority: P0
- Status: Done
- Impact: Critical
- Problem: A concentrated position can be locked for 21 days without a price-based stop or systemic market override.
- Work:
  - Implement the planned monotonic 3x ATR trailing stop with enough pre-entry history to initialize ATR.
  - Implement an SPY 200-day SMA macro circuit breaker using completed daily bars.
  - Permit risk overrides to exit during the minimum holding period.
  - Define behavior for unavailable stop or benchmark data; default to no new risk and alert rather than silently proceeding.
- Acceptance criteria:
  - ATR stops never move downward and trigger the expected liquidation override.
  - The macro circuit breaker produces the documented defensive allocation or cash posture without consulting the debate loop.
  - Unit tests cover insufficient history, data failure, gaps, and stop breaches.
- Verification evidence (2026-07-20): `test_risk_controls.py` covers true-range gaps, Wilder initialization, insufficient history, monotonic stops, prior-stop breach ordering, incomplete/duplicate/non-finite bars, and 199/200-session SPY boundaries. Integration tests cover pre-21-day ATR exit, risk-off debate bypass, sell-only first-stage macro posture, later-date 30% TLT posture, and missing-SPY no-new-risk behavior. Reviewed SNDK/MRVL transaction evidence and MU current-date bootstrap are encoded with quantity checks. Full suite: 101 passed.
- ADK eval note: the current `agents-cli` app exposes the generic root assistant and cannot seed the internal portfolio debate-loop state, so no generic greeting/weather eval is claimed as P0 evidence. The existing network-backed ADK integration tests passed 3/3; deterministic policy/integration tests remain the safety release gate.

### 5. Add account-scoped execution safety and database-configured policies

- Priority: P0
- Status: Done
- Impact: Critical
- Evidence: Current dry runs read the real Robinhood portfolio, append simulated trades, discard their simulated portfolio effects, and recommend the same exits again on later market dates. Existing account identity is resolved from environment variables and a hard-coded `48661` suffix rather than an account registry. The dashboard selects the newest portfolio snapshot globally.
- Problem: Persistent paper experiments and future multiple real accounts cannot safely share the current tables until every stateful read/write is account-scoped and broker authorization is derived independently from a validated account type. Using `SKIP_LIVE_TRADES` alone as the execution boundary risks configuration ambiguity, while putting paper snapshots into the existing tables before UI filters are added could replace the real dashboard view.
- Work:
  - Add one BigQuery `accounts` registry with friendly names, `REAL`/`PAPER` type, status, dashboard default, broker metadata references, initial cash, and strictly validated policy JSON/hash.
  - Add `account_id` and deterministic run/record identifiers to the existing trade, snapshot, execution, risk-state, and account-decision records; backfill legacy data explicitly.
  - Make paper accounts brokerless and unconditionally simulation-only. A paper account plus `SKIP_LIVE_TRADES=false` must fail before ingestion, ADK session creation, or Robinhood tool initialization.
  - Resolve account type to a portfolio/execution adapter once; never branch strategy behavior on a specific account ID.
  - Store supported experiment parameters in BigQuery JSON, validate them with a strict Python schema, and snapshot the canonical configuration/hash into every execution run.
  - Keep the existing UI pinned to exactly one active default real account before enabling paper writers.
  - Preserve the current `48661` live allowlist until a separately approved multi-real-account change is implemented.
- Acceptance criteria:
  - Paper accounts have no broker reference, cannot initialize broker tools, and cannot reach `BrokerExecutor` even with a contradictory environment setting.
  - Every stateful account read/write is scoped by `account_id`; cross-account fixtures return no data.
  - Existing real holdings, performance, and trades remain the default UI result when newer paper rows exist.
  - Supported policy JSON can move from a paper account to an authorized real account without account-specific code changes, while historical execution rows retain the exact tested configuration/hash.
  - Migration, fail-closed error handling, concurrency, and safety tests in `docs/account_scoped_experimentation_implementation_plan.md` pass.
- Dependencies: Must precede enabling persistent paper cron or adding another real account. Keep `SKIP_LIVE_TRADES=true` until this item is Done and live enablement is separately approved.
- Verification evidence (2026-07-21): additive BigQuery migration completed in `conspiracy-493120.portfolio_analytics`; three validated account rows were seeded with `live_execution_allowed=false`, paper broker fields null, and exactly one real dashboard default. Legacy backfill checks returned zero unscoped trades, snapshots, runs, risk rows, or metric rows. Both paper policies completed with one deterministic fill, then received auditable capital contributions that preserved those fills and set each ledger to exactly `$10,000.00` (`$9,970.00` cash plus `$30.00` META). A same-day `--all-accounts --run-kind execution` retry skipped finalized work and posted one Discord message containing all three accounts, combined P&L, explicit account identity, latest audited targets, and the orders tied to each decision. The full suite passed 121/121 tests. Evidence logs: `/tmp/stock-trader/manual_all_accounts_final_20260721.log`, `/tmp/stock-trader/manual_all_accounts_idempotency_20260721.log`, and `/tmp/stock-trader/manual_all_accounts_discord_actions_20260721.log`.
- Operational state (updated 2026-07-21): the user explicitly authorized activating both paper experiments before a frontend deployment and accepted that newer paper rows may affect the deployed legacy dashboard. Both paper accounts are `ACTIVE`, brokerless, and permanently ineligible for live execution. The installed `--all-accounts` cron therefore processes the real dry-run account and both persistent paper ledgers.
- Current cron contract: `SKIP_LIVE_TRADES=true` is mandatory. The two `PAPER` accounts execute and persist simulated fills/cash/holdings; `real-48661` may calculate and audit simulated orders in `REAL_DRY_RUN`, but cannot submit a Robinhood order or mutate the real portfolio. Same-day retries remain idempotent, so the recapitalized paper cash first becomes eligible for allocation on the next market-date execution.
- ADK eval note (2026-07-21): `agents-cli eval run` was attempted, but its inference adapter cannot generate a JSON tool schema for the pre-existing `analyze_and_rank_portfolio(tool_context: ToolContext)` callback, so 0/2 generic greeting/weather cases reached inference. The network-backed ADK integration tests passed; deterministic tests and real dry/paper pipeline evidence are the release gate for this account-scoping item. Fixing the generic eval adapter remains operational tooling work and is not evidence against the deterministic execution contracts.

### 6. Make cron runs idempotent and use stable decision times

- Priority: P1
- Status: Done
- Impact: High
- Evidence: The nominally daily pipeline ran at 07:00, 10:00, and 13:00 PDT on 2026-07-20 and changed its recommendation materially during the day.
- Problem: Reprocessing overlapping news and partial daily candles increases turnover and allows retries or multiple scheduled runs to produce conflicting orders.
- Work:
  - Choose and document a primary rebalance time based on completed bars.
  - If multiple scans remain, distinguish advisory scans from the single execution window.
  - Assign every decision a stable market-date/run ID and reject duplicate execution.
  - Add a minimum time or material-signal-change requirement before reconsidering a target portfolio.
- Acceptance criteria:
  - At most one executable decision exists per configured market session.
  - Retrying the same run cannot create additional orders.
  - Intraday advisory runs cannot mutate trading state.
- Verification evidence (2026-07-21): the installed cron uses the documented 13:20 Pacific execution window and `--all-accounts --run-kind execution`. Execution identity is `(account_id, New York market date, close window, run kind)` and deliberately excludes policy version/hash. BigQuery `MERGE` claims are atomic; only aborted/reconciliation-failed claims may be recovered. A completed same-day all-account retry skipped all three accounts before LLM, paper state, or broker access and created no additional trades/snapshots. Advisory mode uses a separate identity and cannot execute orders, commit paper state, write snapshots, or persist risk-state transitions. Covered by CLI, account, executor, and idempotency verification; full suite 118 passed.

### 7. Build a coherent walk-forward simulator and promotion gate

- Priority: P1
- Status: Proposed
- Impact: High
- Problem: Dry runs read the live portfolio, simulate orders, and then discard the simulated portfolio effects. They therefore cannot measure a consistent strategy path. Existing agent evals do not establish investment performance.
- Work:
  - Use the account-scoped shared-ledger design in `docs/account_scoped_experimentation_implementation_plan.md`; do not create parallel paper-only tables.
  - Maintain a separate simulated cash, lots, holdings, orders, fills, and costs ledger.
  - Replay point-in-time data without look-ahead bias or survivorship leakage.
  - Include spread, slippage, fractional-order constraints, and rejected/partial fills.
  - Report total return, maximum drawdown, Sharpe/Sortino, turnover, hit rate, exposure, and performance versus SPY and an appropriate technology benchmark.
  - Define minimum out-of-sample thresholds required before a strategy change can reach live mode.
  - Use ADK evals for agent behavior and deterministic tests for code contracts; do not use `pytest` assertions on free-form LLM prose.
- Acceptance criteria:
  - Repeated simulation runs from the same inputs are reproducible.
  - Baseline, candidate, and benchmark results are generated from identical dates and cost assumptions.
  - Promotion thresholds and evaluation evidence are recorded on the associated backlog item.

### 8. Replace equal-weight concentration with portfolio risk sizing

- Priority: P1
- Status: Proposed
- Impact: High
- Problem: Three 30% positions can still represent one concentrated factor bet; MU, MRVL, and SNDK are closely related semiconductor/memory exposures.
- Work:
  - Add sector and correlated-exposure caps.
  - Size positions using volatility or ATR and a portfolio loss budget rather than a universal 30% target.
  - Define maximum single-name, sector, and gross-risk limits.
  - Specify when cash or TLT is preferred over adding a correlated third stock.
- Acceptance criteria:
  - A portfolio of three highly correlated names is reduced or rejected deterministically.
  - Position sizes respect configured loss and exposure limits across low- and high-volatility fixtures.
  - New limits improve out-of-sample drawdown without relying solely on lower market exposure.

### 9. Correct technical-signal definitions and data timing

- Priority: P1
- Status: Proposed
- Impact: High
- Problem: The 20-day breakout calculation includes the current day's high, so a current close must effectively equal or exceed a high that includes itself. Partial daily bars may also be mixed with indicators intended for completed sessions.
- Work:
  - Compare the current completed close against the prior 20 completed sessions' high.
  - Define MACD cross timing with prior and current completed bars.
  - Normalize split-adjusted price handling and market calendars.
  - Include `is_20d_high` and `macd_bullish_cross` explicitly in every advisor validation context.
- Acceptance criteria:
  - Boundary tests prove breakouts trigger only on a true cross above the prior window.
  - Signals do not change merely because the same incomplete daily candle is fetched at a different intraday time.

### 10. Track position age by lots instead of last top-up

- Priority: P1
- Status: Proposed
- Impact: Medium-high
- Problem: `days_held` is calculated from the latest buy. A small rebalance purchase can reset the minimum-hold clock for the entire position.
- Work:
  - Persist broker-confirmed lots or maintain a reconciled internal lot ledger.
  - Apply holding restrictions per lot, or document and implement a weighted/first-entry policy.
  - Do not derive live holding age from dry-run trades.
- Acceptance criteria:
  - Adding a small lot does not silently relock older shares.
  - Partial sales select lots using a documented rule and preserve correct remaining ages.

### 11. Improve sentiment data quality and prove incremental value

- Priority: P2
- Status: Proposed
- Impact: Medium
- Problem: Headline sentiment is noisy and a second LLM does not by itself prove predictive value.
- Work:
  - Deduplicate syndicated stories and cross-ticker copies.
  - Weight sources and article age; distinguish earnings, guidance, analyst actions, legal events, and general sector news.
  - Add deterministic earnings surprises and estimate revisions where available.
  - Compare no-sentiment, single-model, and consensus variants in walk-forward evaluation.
  - Add dual-model divergence handling only if it improves out-of-sample results after costs.
- Acceptance criteria:
  - Sentiment variants are compared on the same point-in-time test window.
  - The selected variant demonstrates incremental risk-adjusted value and stable turnover.

### 12. Strengthen operational observability and reconciliation

- Priority: P2
- Status: Proposed
- Impact: Medium
- Problem: Several data and logging errors are caught and reduced to warnings or empty values, and the immediate snapshot may not represent confirmed post-trade state.
- Work:
  - Emit structured run, decision, policy, order, fill, and reconciliation records with a shared run ID.
  - Distinguish recommendations, submitted orders, accepted orders, fills, rejects, dry-run orders, and current holdings.
  - Alert on stale data, empty universes, missing fields, debate exhaustion, execution uncertainty, and reconciliation mismatch.
  - Record strategy/config version with every decision.
- Acceptance criteria:
  - One run can be reconstructed end to end without parsing console prose.
  - Dashboard and alerts never label a recommendation or simulated order as an executed fill.

### 13. Add account selection and experiment comparison to the dashboard

- Priority: P2
- Status: Ready
- Impact: Medium
- Problem: The account-filtered frontend code protects the real default, but the deployed legacy UI has no account selector and cannot compare the two active paper policies. Newer paper rows may therefore be confusing until the updated frontend is deployed.
- Work:
  - Read friendly account names, type, status, policy name/version, and default selection from the BigQuery `accounts` registry.
  - Add a persistent account selector shared by every page; default to the single `is_dashboard_default` real account and never fall back to the globally newest row.
  - Scope every snapshot, trade, recommendation, risk-state, and performance query by the selected `account_id`.
  - Clearly badge `REAL`, `REAL_DRY_RUN`, and `PAPER`; distinguish recommendations, simulated orders, paper fills, broker fills, and current holdings.
  - Add a side-by-side experiment view for the two paper accounts showing policy JSON/hash, equity curve, return, drawdown, turnover, cash, holdings, fills, and performance versus SPY from the same start date.
  - Treat capital-adjustment snapshots as external cash flows so a deposit is not reported as investment return.
  - Keep the frontend read-only and free of Robinhood/MCP dependencies.
- Acceptance criteria:
  - Selecting an account changes every page consistently without cross-account rows.
  - Initial load still selects `real-48661`, even when a paper snapshot is newest globally.
  - Paper fills and real dry-run orders are never labeled as live broker fills.
  - The comparison view reconciles to BigQuery ledgers and computes return independently of the `$9,900` paper capital contribution.
  - Local Streamlit smoke tests and deterministic query-contract tests pass before deployment; deployment remains a separate explicit action.
- Dependencies: Use the completed account registry and shared ledger from item 5. Meaningful strategy conclusions still depend on the walk-forward and promotion gate in item 7.

## Completed work

Completed historical items remain documented in the root `TODO.md` until they are migrated with their verification evidence. New work and status changes belong in this file.

## Backlog maintenance

When completing or changing an item:

1. Update its status in the same change.
2. Record tests, eval results, backtest artifacts, or production evidence under the item.
3. Add newly discovered follow-up work at the correct impact rank; do not hide it in code comments or a final response only.
4. Reorder items when evidence changes expected impact, and update `Last reviewed`.
5. Keep implementation details concise enough that this remains a decision-oriented backlog rather than a design dump.
