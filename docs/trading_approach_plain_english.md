# Trading Approach in Plain English

## The approach in one sentence

The system looks for a small number of large, established AI-related companies that are either temporarily cheap or moving strongly upward, uses AI to interpret recent news, and then lets strict Python rules decide whether a trade is actually permitted.

It manages risk by holding no more than three positions, keeping cash available, limiting position size, avoiding rapid selling, and automatically exiting when predefined danger signals appear.

## How a typical day works

### 1. Start with a controlled shopping list

The system only considers 40 approved, generally large and liquid companies connected to AI infrastructure: chips, cloud computing, power, software, and security.

It reduces those 40 to a daily watchlist of 10:

- Anything already owned stays on the watchlist so it cannot be forgotten.
- It generally prefers stocks trading above their average price over the previous 50 trading days.
- A stock below that average can still qualify if it appears extremely oversold.
- Among the remaining stocks, it favors those with the strongest recent upward trend.

For example, suppose a stock's average price over the last 50 market days is $90:

- At $100, it has a positive trend.
- At $85, it would normally be excluded.
- If it fell unusually quickly and its RSI is below 25, it may stay on the list as a possible bargain.

**RSI** is essentially a speedometer for recent buying and selling. A very low number suggests selling may have become unusually intense. It does not guarantee a rebound.

### 2. Read the news and measure its tone

Gemini examines recent news and gives each watched stock a score from -1 to +1:

- `+1`: extremely positive
- `0`: neutral
- `-1`: extremely negative

The strategy does not rely only on today's score. It uses a five-day weighted average called an **EWMA**, which gives more importance to recent days without completely forgetting earlier news.

For example, imagine a stock has strong positive news on Monday, positive news on Tuesday, neutral news on Wednesday, slightly negative news on Thursday, and no meaningful news on Friday. Its combined score may remain mildly positive instead of changing direction because of one quiet or negative day.

If there is no new news, the old score is multiplied by 0.7, gradually allowing stale optimism or pessimism to fade.

Stocks are also ranked against one another. A low relative rank can generate a liquidation recommendation, but it does not automatically cause a sale. The deterministic exit rules still have to authorize it.

### 3. Look for one of two reasons to buy

A new stock must normally target 30% of the account and qualify through one of two paths.

#### Path A: A promising company on sale

The stock must:

- Be at least 10% below its highest price of the past year.
- Have a five-day news score above `+0.10`.
- Have reasonably consistent news sentiment: the volatility score must be `0.40` or lower.
- Have a forward P/E no higher than 80, when that number is available.

For example, a stock reached $100 during the year but now trades at $87. That is a 13% decline. If its recent news remains positive and reasonably stable, the system may treat the decline as a buying opportunity rather than evidence that the company is failing.

**Forward P/E** compares the share price with expected future profits. A very high value means investors are paying an unusually large amount for each expected dollar of profit. The ceiling of 80 is intended to avoid the most expensive candidates.

#### Path B: A stock breaking upward

Alternatively, a stock may qualify when:

- It reaches a 20-day high.
- Its MACD produces a bullish cross.
- Sentiment volatility is no higher than `0.85`.
- Its forward P/E is no higher than 80, when known.

A **MACD bullish cross** means short-term price momentum has recently moved above longer-term momentum. In plain language, the stock is not merely high; it appears to be accelerating upward.

For example, a stock has traded between $45 and $50 for several weeks. It closes above that range while its recent price movement begins accelerating. Path B can allow a purchase even though the stock is not cheap.

The two buying philosophies are therefore:

- Path A: "Good news, but the price has fallen enough to offer a discount."
- Path B: "The price is strong and appears to be breaking into a new upward move."

### 4. Have two AI roles debate the proposal

One Gemini agent acts like a portfolio analyst and proposes what to own. Another acts like a risk reviewer and can reject the proposal. They may revise it for up to five rounds.

AI approval alone is not enough. A deterministic Python policy independently checks every important rule. This is the real authorization boundary: the AI recommends and explains; ordinary code decides whether the plan is safe enough to reach the broker.

If anything required is missing, stale, contradictory, or malformed, the entire plan is cancelled.

## What a $100 portfolio might look like

The normal target is:

- Stock A: $30
- Stock B: $30
- Stock C: $30
- Cash: $10

The system allows at most three active positions. It will not split the account among many tiny positions merely to use every dollar.

If only one stock qualifies, the result can be:

- Stock A: $30
- Cash: $70

Keeping extra cash is acceptable. The system does not purchase weak candidates merely to become fully invested.

A position targeting 30% has a tolerance range of 27% to 33%. If a $30 position rises to $32 in a $100 account, the system leaves it alone. This reduces unnecessary trading.

No plan may invest more than 95% of the portfolio, so at least 5% must remain as cash. A single order is also capped at the smaller of 35% of the account or $35.

## When the system sells

Buying rules and selling rules are separate. A stock failing today's buying test does not mean an existing position should immediately be sold.

There are two kinds of exits:

- A normal exit is permitted after at least 21 completed days when the stock has a `LIQUIDATE` signal and its news score is below `+0.05`.
- An emergency exit can happen at any time if sentiment falls below `-0.50`, the price breaches its trailing safety line, or the broader market enters risk-off mode.

For example, suppose the system buys a stock on July 1:

- On July 10, the stock becomes less attractive but has no serious danger signal. It must normally continue holding.
- On July 10, if sentiment collapses to `-0.65`, it may sell early.
- On July 10, if the price falls through the mechanical trailing stop, it may also sell early.
- After 21 days, a weaker combination of poor ranking and slightly negative sentiment can authorize a normal exit.

## The two major emergency controls

### ATR trailing stop

**ATR** measures how much a stock normally moves each day. A volatile stock receives a wider safety margin than a quiet stock.

The stop is approximately:

```text
recent high - (3 x normal daily movement)
```

For example, a stock's recent high is $100 and its normal daily movement is $4. The safety line would be approximately:

```text
$100 - (3 x $4) = $88
```

If the stock later rises, the stop can rise with it. It never moves downward. If the closing price falls below the previously established stop, the system can exit even during the 21-day minimum holding period.

### Broad-market circuit breaker

The system compares SPY, an ETF representing the broad U.S. stock market, with its average closing price over the last 200 sessions.

If SPY falls below that average, the system treats the market as **risk-off**. It exits ordinary equity positions through a deterministic sell-only plan rather than asking the AI debate loop to reinterpret the situation.

Once equities have been cleared on an earlier market date, a later run can establish a defensive posture of approximately:

- TLT Treasury-bond ETF: 30%
- Cash: 70%

## Why selling and buying happen on different days

If the desired portfolio requires selling one stock and buying another, the system will not do both on the same market date.

For example:

- Current portfolio: $30 of Stock A and $70 cash
- Desired portfolio: $30 of Stock B and $70 cash

It first sells Stock A. Stock B is not automatically purchased afterward. A fresh run on a later market date must re-check prices, account balances, news, and risk conditions before approving the buy.

This prevents an unsuccessful or uncertain sale from being followed by a purchase based on money the account may not actually have.

## Additional safeguards

The code also requires:

- The correct Robinhood account ending in `48661`.
- A ticker from the approved universe.
- Fresh, plausible market prices.
- Confirmed cash, holdings, and buying power from Robinhood.
- Final risk-advisor approval.
- A unique daily decision ID, preventing a retry from duplicating orders.
- A plan that expires after five minutes.
- No mixture of buys and sells on the same market date.
- A kill switch that can cancel execution.
- `SKIP_LIVE_TRADES=true` by default, which simulates orders instead of submitting them.

Broker or data failures do not become optimistic assumptions. If the system cannot confidently determine the account state or price, it cancels rather than trading.

## Important limitation

This is presently a highly concentrated strategy. Three 30% positions can still represent nearly the same underlying bet. For example, three semiconductor stocks may all decline together even though they are three separate companies.

The strategy also still needs a proper walk-forward simulation, which means replaying historical days without using future information, to demonstrate performance after spreads, slippage, and other trading costs. The system has strong execution safeguards, but profitability and risk-adjusted superiority have not yet been established.

The authoritative implementation is in:

- [`agent/app/agent.py`](../agent/app/agent.py)
- [`agent/app/trading_policy.py`](../agent/app/trading_policy.py)
- [`agent/app/risk_controls.py`](../agent/app/risk_controls.py)
- [`agent/app/broker_executor.py`](../agent/app/broker_executor.py)

Remaining limitations and planned improvements are tracked in [`docs/backlog.md`](backlog.md).
