"""Static decision-logic content shared by the Dash router."""

from dash import html


def _phase(title: str, icon: str, items: list[object]) -> html.Div:
    return html.Div(
        [
            html.Div([html.Span(icon), title], className="phase-title"),
            html.Ul([html.Li(item, className="gate-item") for item in items]),
        ],
        className="phase-card",
    )


def layout() -> html.Main:
    return html.Main(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H1("Portfolio Decision Logic"),
                            html.P(
                                "A concise reference for the five-phase quantitative "
                                "and qualitative engine determining daily allocations.",
                                className="subtitle",
                            ),
                        ]
                    ),
                    html.A("← Dashboard", href="/", className="button secondary"),
                ],
                className="page-heading",
            ),
            _phase(
                "Phase 1: Watchlist Screening (Pre-Filtering & Momentum)",
                "🔍",
                [
                    html.Span(
                        [
                            "We download stock data from yfinance and use owned-position "
                            "status, the 21-day cool-down, 50-day SMA, and 14-day RSI to "
                            "create the initial list passed to the next gate."
                        ]
                    ),
                    html.Span(
                        [
                            html.Strong("Example: "),
                            "A non-owned stock below its 50-day SMA with RSI 30 is filtered; "
                            "one above its SMA, or deeply oversold with RSI below 25, passes.",
                        ]
                    ),
                ],
            ),
            _phase(
                "Phase 2: Technical Formulation",
                "📊",
                [
                    "Additional indicators—including 20-day SMA, 52-week drawdown, and "
                    "MACD—are calculated for shortlisted stocks. No filtering occurs here."
                ],
            ),
            _phase(
                "Phase 3: Sentiment Scoring & Baseline Ranking",
                "✍️",
                [
                    html.Span(
                        [
                            html.Strong("Gemini analyst scoring: "),
                            "Gemini Flash scans recent news and scores conviction from -1.0 "
                            "to +1.0. Weekday tickers with no news decay by 30%.",
                        ]
                    ),
                    html.Span(
                        [
                            html.Strong("EWMA and volatility: "),
                            "Today's score is combined with four days of history to calculate "
                            "five-day EWMA sentiment and volatility.",
                        ]
                    ),
                    html.Span(
                        [
                            html.Strong("Baseline signals: "),
                            "Assets are ranked by raw sentiment before deterministic entry, "
                            "holding, exit, and risk rules are applied.",
                        ]
                    ),
                    html.Span(
                        [
                            html.Strong("Weekend pause: "),
                            "News scraping and decay pause on weekends, carrying Friday's "
                            "EWMA sentiment forward.",
                        ]
                    ),
                ],
            ),
            _phase(
                "Phase 4: Multi-Agent Portfolio Debate (The Critic Loop)",
                "🧠",
                [
                    html.Span(
                        [
                            html.Strong("Portfolio sizing: "),
                            "The analyst proposes allocations, while deterministic policy "
                            "enforces exposure, position, cash, and action constraints.",
                        ]
                    ),
                    html.Span(
                        [
                            html.Strong("Path A — value/dip entry: "),
                            "Requires a qualifying drawdown, bullish EWMA sentiment, and "
                            "acceptable sentiment volatility.",
                        ]
                    ),
                    html.Span(
                        [
                            html.Strong("Path B — momentum breakout: "),
                            "Uses completed-bar breakout and MACD confirmation rules.",
                        ]
                    ),
                    html.Span(
                        [
                            html.Strong("Downside guards: "),
                            "Minimum holding rules, ATR stops, sustained negative sentiment, "
                            "and the SPY regime policy determine whether risk can be added or exited.",
                        ]
                    ),
                ],
            ),
            _phase(
                "Phase 5: Order Sizing & Execution Guards",
                "⚡",
                [
                    html.Span(
                        [
                            html.Strong("Tolerance band: "),
                            "Small allocation adjustments are skipped unless opening or fully "
                            "closing a position.",
                        ]
                    ),
                    html.Span(
                        [
                            html.Strong("Execution policy: "),
                            "Account, ticker, quote freshness, buying power, duplicate-run, "
                            "sell-only, and advisor-approval checks must all pass before orders.",
                        ]
                    ),
                ],
            ),
        ],
        className="app-shell",
    )
