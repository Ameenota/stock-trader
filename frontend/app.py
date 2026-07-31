"""Public Dash frontend for the autonomous stock trader."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html

import decision_logic
from data import DashboardData, fetch_spy_history, load_dashboard_data


TICKER_DOMAINS = {
    "NVDA": "nvidia.com", "AMD": "amd.com", "TSM": "tsmc.com",
    "MU": "micron.com", "SMCI": "supermicro.com", "DELL": "dell.com",
    "VRT": "vertiv.com", "ETN": "eaton.com", "CEG": "constellationenergy.com",
    "TLT": "ishares.com", "MSFT": "microsoft.com", "GOOGL": "google.com",
    "AMZN": "amazon.com", "META": "meta.com", "ORCL": "oracle.com",
    "AVGO": "broadcom.com", "ANET": "arista.com", "ARM": "arm.com",
    "SNPS": "synopsys.com", "CDNS": "cadence.com", "ASML": "asml.com",
    "AMAT": "appliedmaterials.com", "LRCX": "lamresearch.com", "KLAC": "kla.com",
    "INTC": "intel.com", "VST": "vistracorp.com", "GE": "ge.com",
    "MRVL": "marvell.com", "HPE": "hpe.com", "PLTR": "palantir.com",
    "IBM": "ibm.com", "NOW": "servicenow.com", "ADBE": "adobe.com",
    "SAP": "sap.com", "NET": "cloudflare.com", "DDOG": "datadoghq.com",
    "SNOW": "snowflake.com", "CRWD": "crowdstrike.com",
    "PANW": "paloaltonetworks.com", "QCOM": "qualcomm.com", "SNDK": "sandisk.com",
}


app = Dash(
    __name__,
    title="Autonomous Stock Trader Dashboard",
    suppress_callback_exceptions=True,
    update_title="Refreshing portfolio…",
)
server = app.server


@server.get("/health")
def health() -> tuple[dict[str, str], int]:
    return {"status": "ok"}, 200


def ticker_identity(ticker: str) -> html.Div:
    ticker = str(ticker).upper()
    children: list[Any] = []
    domain = TICKER_DOMAINS.get(ticker)
    if domain:
        children.append(
            html.Img(
                src=f"https://www.google.com/s2/favicons?domain={domain}&sz=32",
                className="ticker-icon",
                alt="",
            )
        )
    children.append(
        html.A(
            ticker,
            href=f"https://finance.yahoo.com/quote/{ticker}",
            target="_blank",
            rel="noopener noreferrer",
            className="ticker-link",
        )
    )
    return html.Div(children, className="ticker-identity")


def expandable_text(value: Any, max_chars: int = 90) -> Any:
    text = "" if value is None or pd.isna(value) else str(value)
    if len(text) <= max_chars:
        return text
    short = text[:max_chars].rsplit(" ", 1)[0]
    return html.Details(
        [html.Summary(f"{short}… more"), html.P(text)],
        className="inline-details",
    )


def money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def empty_message(message: str) -> html.Div:
    return html.Div(message, className="empty-message")


def metric_card(label: str, value: str, delta: str, tone: str = "neutral") -> html.Div:
    return html.Div(
        [
            html.Div(label, className="metric-label"),
            html.Div(value, className="metric-value"),
            html.Div(delta, className=f"metric-delta {tone}"),
        ],
        className="metric-card",
    )


def sentiment_figure(recommendations: pd.DataFrame) -> go.Figure:
    value = float(recommendations["raw_score"].mean()) if not recommendations.empty else 0.0
    figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            number={"font": {"size": 30, "color": "#0f172a"}, "valueformat": ".3f"},
            gauge={
                "axis": {"range": [-1.0, 1.0], "tickcolor": "#475569"},
                "bar": {"color": "rgba(0,0,0,0)"},
                "bgcolor": "rgba(0,0,0,0)",
                "borderwidth": 0,
                "steps": [
                    {"range": [-1.0, -0.2], "color": "#ff3b30"},
                    {"range": [-0.2, 0.2], "color": "#ffcc00"},
                    {"range": [0.2, 1.0], "color": "#34c759"},
                ],
                "threshold": {
                    "line": {"color": "#0f172a", "width": 7},
                    "thickness": 1,
                    "value": value,
                },
            },
        )
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=160,
        margin=dict(l=15, r=15, t=15, b=15),
        font={"family": "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"},
    )
    return figure


def performance_figure(history: pd.DataFrame) -> go.Figure | None:
    if history.empty:
        return None
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=6)
    inception_date = history["date"].iloc[0]
    first_equity = float(history["total_equity"].iloc[0])
    spy = fetch_spy_history(
        inception_date.strftime("%Y-%m-%d"),
        (end_date + timedelta(days=2)).strftime("%Y-%m-%d"),
    )
    if spy.empty:
        return None

    backbone = pd.DataFrame({"date": [start_date + timedelta(days=i) for i in range(7)]})
    merged = backbone.merge(history, on="date", how="left").merge(spy, on="date", how="left")
    merged["SPY"] = merged["SPY"].ffill().bfill()
    portfolio_rows = merged[merged["total_equity"].notna()]
    if not portfolio_rows.empty:
        merged = merged[merged["date"] >= portfolio_rows["date"].iloc[0]].copy()
    first_spy = float(spy["SPY"].dropna().iloc[0])
    merged["Agent Portfolio"] = merged["total_equity"] / first_equity * 100
    merged["S&P 500 (SPY)"] = merged["SPY"] / first_spy * 100
    plot_frame = merged.melt(
        id_vars=["date"],
        value_vars=["Agent Portfolio", "S&P 500 (SPY)"],
        var_name="Metric",
        value_name="Normalized Value",
    )
    figure = px.line(
        plot_frame,
        x="date",
        y="Normalized Value",
        color="Metric",
        markers=True,
        color_discrete_map={"Agent Portfolio": "#2563eb", "S&P 500 (SPY)": "#94a3b8"},
    )
    figure.update_traces(connectgaps=True, marker={"size": 6})
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=210,
        margin=dict(l=20, r=15, t=15, b=20),
        font={"family": "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"},
        xaxis={"gridcolor": "#f1f5f9", "title": "", "dtick": "D1", "tickformat": "%b %d"},
        yaxis={"gridcolor": "#f1f5f9", "title": "Normalized Return"},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    return figure


def allocation_table(snapshot: dict[str, Any]) -> html.Div:
    holdings = snapshot.get("holdings") or []
    rows = [{"asset": h["symbol"], "value": float(h["equity"])} for h in holdings]
    rows.append({"asset": "Cash", "value": float(snapshot["total_cash"])})
    total = sum(item["value"] for item in rows) or 1.0
    colors = ["#00c689", "#ffa26b", "#ff4c61", "#8b5cf6", "#14b8a6"]
    body = []
    color_index = 0
    for item in sorted(rows, key=lambda row: row["value"], reverse=True):
        pct = item["value"] / total * 100
        if item["asset"] == "Cash":
            identity: Any = html.Strong("Cash", className="cash-label")
            color = "#3f8cff"
        else:
            identity = ticker_identity(item["asset"])
            color = colors[color_index % len(colors)]
            color_index += 1
        body.append(
            html.Tr(
                [
                    html.Td(identity),
                    html.Td(money(item["value"])),
                    html.Td(
                        html.Div(
                            [
                                html.Strong(f"{pct:.1f}%"),
                                html.Div(
                                    html.Div(style={"width": f"{min(pct, 100):.1f}%", "backgroundColor": color}),
                                    className="allocation-bar",
                                ),
                            ],
                            className="allocation-cell",
                        )
                    ),
                ]
            )
        )
    return html.Div(
        [
            html.Div("Portfolio Allocation", className="panel-kicker"),
            html.Table(
                [html.Thead(html.Tr([html.Th("Asset"), html.Th("Value"), html.Th("Allocation")])), html.Tbody(body)],
                className="data-table compact-table",
            ),
        ],
        className="allocation-panel",
    )


def badge(value: str) -> html.Span:
    normalized = str(value).upper()
    if normalized in {"STRONG BUY", "BUY"}:
        tone = "buy"
    elif normalized in {"LIQUIDATE", "SELL"}:
        tone = "sell"
    else:
        tone = "hold"
    return html.Span(normalized, className=f"badge {tone}")


def recommendations_table(frame: pd.DataFrame) -> Any:
    if frame.empty:
        return empty_message("No daily recommendations logged yet.")
    headings = [
        ("Ticker", "Ticker and detailed technical metrics"),
        ("News Sentiment", "Gemini news sentiment score from -1.0 to +1.0"),
        ("Signal", "Action after technical, holding-period, and risk rules"),
        ("Price", "Latest price used by the decision record"),
        ("Analyst Consensus", "Wall Street consensus retrieved from Yahoo Finance"),
        ("AI Allocation", "Target share of total portfolio equity"),
        ("AI Agent Thesis", "The analyst's recorded justification"),
    ]
    body = []
    for _, row in frame.iterrows():
        ticker = str(row["ticker"])
        technical = (
            f"Forward P/E: {row.get('forward_pe', 'N/A')} | RSI: {row.get('rsi', 'N/A')} | "
            f"MACD/Signal: {row.get('macd', 'N/A')} / {row.get('macd_signal', 'N/A')} | "
            f"Drawdown: {row.get('drawdown_pct', 'N/A')} | EWMA: {row.get('sentiment_ewma', 'N/A')} | "
            f"Sentiment volatility: {row.get('sentiment_volatility', 'N/A')} | "
            f"20d SMA: {row.get('moving_average_20d', 'N/A')}"
        )
        target = row.get("target_weight")
        target_text = f"{float(target) * 100:.1f}%" if pd.notna(target) else "0.0%"
        body.append(
            html.Tr(
                [
                    html.Td(html.Div([ticker_identity(ticker), html.Span("ⓘ", title=technical, className="info-icon")], className="ticker-with-info")),
                    html.Td(f"{float(row['raw_score']):+.2f}"),
                    html.Td(badge(row["signal"])),
                    html.Td(money(row.get("current_price"))),
                    html.Td(row.get("analyst_consensus") or "N/A"),
                    html.Td(html.Strong(target_text) if pd.notna(target) and float(target) > 0 else target_text),
                    html.Td(expandable_text(row.get("thesis"))),
                ]
            )
        )
    return html.Div(
        html.Table(
            [html.Thead(html.Tr([html.Th(label, title=tip) for label, tip in headings])), html.Tbody(body)],
            className="data-table",
        ),
        className="table-scroll",
    )


def graveyard_table(frame: pd.DataFrame) -> Any:
    if frame.empty:
        return empty_message("No pre-screener graveyard logs found for today.")
    body = []
    for _, row in frame.iterrows():
        body.append(
            html.Tr(
                [
                    html.Td(ticker_identity(row["ticker"])),
                    html.Td(money(row.get("current_price"))),
                    html.Td(money(row.get("sma_50"))),
                    html.Td(f"{float(row['momentum']):.3f}" if pd.notna(row.get("momentum")) else "N/A"),
                    html.Td(row.get("thesis") or "", className="muted italic"),
                ]
            )
        )
    return html.Div(
        html.Table(
            [
                html.Thead(html.Tr([html.Th("Ticker"), html.Th("Price"), html.Th("50-Day SMA"), html.Th("Price / SMA"), html.Th("Filter Reason")])),
                html.Tbody(body),
            ],
            className="data-table",
        ),
        className="table-scroll",
    )


def normalized_trade_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    processed = frame[~frame["action"].isin(["HOLD"])].copy()
    processed["action"] = processed["action"].map(
        lambda value: {"STRONG BUY": "BUY", "LIQUIDATE": "SELL"}.get(value, value)
    )
    processed["timestamp"] = processed["timestamp"].map(lambda value: pd.to_datetime(value).isoformat())
    processed = processed.where(pd.notnull(processed), None)
    return processed.to_dict("records")


def trade_table(records: list[dict[str, Any]], search: str, action: str, show_simulated: bool) -> Any:
    filtered = records
    if not show_simulated:
        filtered = [row for row in filtered if not bool(row.get("dry_run", True))]
    search = (search or "").strip().upper()
    if search:
        filtered = [row for row in filtered if search in str(row.get("ticker", "")).upper()]
    if action and action != "All":
        filtered = [row for row in filtered if row.get("action") == action]
    if not filtered:
        return empty_message("No executed trades match the selected filters.")

    body = []
    for row in filtered:
        timestamp = pd.to_datetime(row["timestamp"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        local = timestamp.astimezone(ZoneInfo("America/Los_Angeles"))
        body.append(
            html.Tr(
                [
                    html.Td(local.strftime("%m/%d/%y, %I:%M %p %Z")),
                    html.Td(ticker_identity(row["ticker"])),
                    html.Td(badge(row["action"])),
                    html.Td(money(row.get("amount_usd"))),
                    html.Td(expandable_text(row.get("reasoning"), 110)),
                ]
            )
        )
    return html.Div(
        html.Table(
            [html.Thead(html.Tr([html.Th("Timestamp"), html.Th("Ticker"), html.Th("Action"), html.Th("Amount"), html.Th("Reasoning / Trade Thesis")])), html.Tbody(body)],
            className="data-table",
        ),
        className="table-scroll",
    )


def relative_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - value).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} minutes ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def section(title: str, description: str, content: Any, *, open_by_default: bool = True) -> html.Details:
    return html.Details(
        [html.Summary(title), html.P(description, className="section-description"), content],
        open=open_by_default,
        className="dashboard-section",
    )


def dashboard_layout(data: DashboardData) -> tuple[html.Main, list[dict[str, Any]]]:
    snapshot = data.snapshot
    history = data.portfolio_history
    recommendations = data.recommendations
    performance = performance_figure(history)
    first_equity = float(history["total_equity"].iloc[0]) if not history.empty else 0.0
    total_return = (
        (float(snapshot["total_equity"]) - first_equity) / first_equity * 100
        if first_equity > 0
        else float(snapshot["unrealized_gain_loss_percent"])
    )
    pending_cash = max(0.0, float(snapshot["total_cash"]) - float(snapshot["buying_power"]))
    gain_loss = float(snapshot["unrealized_gain_loss"])
    trades = normalized_trade_records(data.trades)

    children: list[Any] = [
        html.Header(
            [
                html.Div(
                    [
                        html.H1("Autonomous Stock Trader"),
                        html.P(
                            [
                                html.Strong("Fully end-to-end: "),
                                "Ingests market news, analyzes sentiment with Gemini, ranks conviction, and executes through guarded Robinhood MCP workflows.",
                            ],
                            className="subtitle",
                        ),
                    ]
                ),
                html.Nav(
                    [
                        html.A("Decision logic", href="/decision-logic", className="button secondary"),
                        html.A("Refresh data", href="/?refresh=1", className="button"),
                    ],
                    className="header-actions",
                ),
            ],
            className="page-heading",
        )
    ]
    if snapshot.get("summary"):
        children.append(
            html.Div(
                [
                    html.Div([html.Span("🤖"), " Latest Agent Recommendations"], className="callout-title"),
                    html.Div(str(snapshot["summary"]), className="callout-copy"),
                    html.A("See the documented rules →", href="/decision-logic"),
                ],
                className="recommendation-callout",
            )
        )

    children.extend(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Market Sentiment (Agent Mood)", className="chart-title"),
                            dcc.Graph(figure=sentiment_figure(recommendations), config={"displayModeBar": False}, responsive=True),
                        ],
                        className="chart-card gauge-card",
                    ),
                    html.Div(
                        [
                            html.Div("7-Day Performance vs. S&P 500", className="chart-title"),
                            dcc.Graph(figure=performance, config={"displayModeBar": False}, responsive=True)
                            if performance is not None
                            else empty_message("Performance comparison will populate once benchmark data is available."),
                        ],
                        className="chart-card performance-card",
                    ),
                ],
                className="chart-grid",
            ),
            html.Div(
                [
                    html.Span(["Account Managed: ", html.Strong(snapshot["account_number"])]),
                    html.Span(f"Last Snapshot: {relative_time(snapshot['timestamp'])}", className="italic"),
                ],
                className="snapshot-meta",
            ),
            html.Div(
                [
                    metric_card("Net Portfolio Value", money(snapshot["total_equity"]), f"{total_return:+.2f}% Total Return", "positive" if total_return >= 0 else "negative"),
                    metric_card("Settled Cash (Buying Power)", money(snapshot["buying_power"]), f"{money(pending_cash)} Pending" if pending_cash > 0.01 else "No Pending Cash"),
                    metric_card("Unrealized Gain / Loss", money(gain_loss), f"{gain_loss:+.2f} total", "positive" if gain_loss >= 0 else "negative"),
                    allocation_table(snapshot),
                ],
                className="metrics-grid",
            ),
        ]
    )
    if data.headlines:
        ticker_text = "   •   ".join(data.headlines)
        children.append(
            html.Div(
                html.Div(f"🔥 LATEST MARKET NEWS INGESTED BY SENTIMENT AGENT:   {ticker_text}", className="ticker-track"),
                className="news-ticker",
            )
        )
    children.extend(
        [
            section(
                "📈 Daily AI Stock Recommendations",
                "The screened universe is scored for sentiment and then evaluated by the multi-agent critique loop and deterministic portfolio policy.",
                recommendations_table(recommendations),
            ),
            section(
                "🛡️ Token-Saving Pre-Screener — Filtered Assets",
                "Assets with weak technical setups skip news ingestion and Gemini sentiment analysis, reducing inference cost.",
                graveyard_table(data.graveyard),
                open_by_default=False,
            ),
            section(
                "💼 Executed Trade History Log",
                "Live and simulated execution receipts recorded by the trading pipeline, with ticker and action filters.",
                html.Div(
                    [
                        html.Div(
                            [
                                dcc.Input(id="trade-search", type="text", placeholder="Filter ticker…", debounce=True),
                                dcc.Dropdown(id="trade-action", options=["All", "BUY", "SELL"], value="All", clearable=False),
                                dcc.Checklist(id="show-simulated", options=[{"label": "Show simulated / dry-run trades", "value": "show"}], value=[]),
                            ],
                            className="trade-controls",
                        ),
                        html.Div(id="trade-table"),
                    ]
                ),
            ),
        ]
    )
    return html.Main(children, className="app-shell"), trades


app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        dcc.Store(id="trade-records", storage_type="memory"),
        html.Div(id="page-content", children=html.Div("Loading dashboard…", className="loading-page")),
    ]
)


@app.callback(
    Output("page-content", "children"),
    Output("trade-records", "data"),
    Input("url", "pathname"),
    Input("url", "search"),
)
def route(pathname: str | None, search: str | None) -> tuple[Any, list[dict[str, Any]]]:
    if pathname in {"/decision-logic", "/Decision_Logic"}:
        return decision_logic.layout(), []
    if pathname not in {None, "", "/"}:
        return html.Main([html.H1("Page not found"), html.A("Return to dashboard", href="/")], className="app-shell"), []
    force_refresh = bool(parse_qs((search or "").lstrip("?")).get("refresh"))
    try:
        return dashboard_layout(load_dashboard_data(force_refresh=force_refresh))
    except Exception as exc:
        return (
            html.Main(
                [
                    html.H1("Dashboard temporarily unavailable"),
                    html.P("The server could not load the latest BigQuery data."),
                    html.Pre(str(exc), className="error-detail"),
                    html.A("Try again", href="/?refresh=1", className="button"),
                ],
                className="app-shell error-page",
            ),
            [],
        )


@app.callback(
    Output("trade-table", "children"),
    Input("trade-records", "data"),
    Input("trade-search", "value"),
    Input("trade-action", "value"),
    Input("show-simulated", "value"),
    prevent_initial_call=False,
)
def filter_trades(
    records: list[dict[str, Any]] | None,
    search: str | None,
    action: str | None,
    show_simulated: list[str] | None,
) -> Any:
    return trade_table(records or [], search or "", action or "All", "show" in (show_simulated or []))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
