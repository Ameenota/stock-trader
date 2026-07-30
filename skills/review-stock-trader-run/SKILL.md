---
name: review-stock-trader-run
description: Review and summarize a stock-trader daily pipeline run from scheduler logs in /tmp/stock-trader. Use when asked how today's run did, whether the pipeline completed, what each account decided or executed, whether trading was live or dry-run, or whether the run contained errors or safety anomalies.
---

# Review Stock Trader Run

Use `/tmp/stock-trader` as the sole source unless the user explicitly asks for BigQuery, Robinhood, dashboard, or other corroboration. Keep the review read-only.

## Workflow

1. List `/tmp/stock-trader/*.log` with modification times and select the newest log for the requested local date. If the date is ambiguous, state which file and timestamp are being reviewed.
2. Read the entire selected log. Large logs may be inspected in sequential chunks, but include both the beginning and tail so startup and final completion are verified.
3. Determine the overall outcome from explicit evidence:
   - startup and completion markers;
   - traceback, exception, error, rejection, abort, reconciliation failure, or timeout messages;
   - completion-ping and notification results.
4. For every `=== ACCOUNT:` block, extract:
   - account name, ID, and mode (`PAPER`, `REAL_DRY_RUN`, or `LIVE`);
   - starting cash, holdings, and total equity when logged;
   - advisor-approved target allocations;
   - deterministic policy result and reason codes;
   - execution actions and their logged outcomes;
   - final snapshot or audit-log result.
5. Separate recommendations and planned trades from completed fills. Never describe a planned `ENTER` or `EXIT` as executed unless the execution section explicitly records success or a fill. In `REAL_DRY_RUN`, say no live order was placed.
6. Call out material anomalies even when the run completed, including repeated liquidation attempts, empty target allocations, bypassed debate, stale data, broker errors, or inconsistent signals.

## Response Shape

Lead with one sentence: clean success, success with warnings, partial failure, or failure. Then summarize:

- real account outcome and safety mode;
- paper-account outcomes;
- key signals or allocation changes;
- operational health and noteworthy warnings.

Include the reviewed log path. Keep routine recaps concise, but preserve exact account IDs, tickers, amounts, and reason codes when they explain the result.
