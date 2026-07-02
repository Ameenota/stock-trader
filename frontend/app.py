import os
# Force native DNS resolution for gRPC to prevent macOS IPv6 resolution failures
os.environ["GRPC_DNS_RESOLVER"] = "native"

import json
import pandas as pd
import streamlit as st
import plotly.express as px
import yfinance as yf
from google.cloud import bigquery
from datetime import datetime, timezone

# 1. Page Configuration
st.set_page_config(
    page_title="Autonomous Stock Trader Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. Modern Custom Styling
st.markdown("""
<style>
    /* Premium font styling */
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    /* Title adjustments */
    h1 {
        font-weight: 700 !important;
        background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 2rem !important;
    }
    
    /* Metrics panel decoration */
    div[data-testid="metric-container"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
        transition: transform 0.2s;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px);
    }
    
    /* Custom divider line */
    hr {
        margin: 2.5rem 0 !important;
        border-color: #e2e8f0 !important;
    }
</style>
""", unsafe_allow_html=True)

# BigQuery client helper
@st.cache_resource
def get_bq_client():
    return bigquery.Client()

client = get_bq_client()
project = client.project
dataset_id = "portfolio_analytics"

# 3. Data Querying Helpers
@st.cache_data(ttl=3600)
def load_latest_snapshot() -> dict:
    """Loads the most recent portfolio snapshot from BigQuery."""
    query = f"""
        SELECT timestamp, account_number, total_equity, total_cash, buying_power, unrealized_gain_loss, unrealized_gain_loss_percent, holdings, summary
        FROM `{project}.{dataset_id}.portfolio_snapshot`
        ORDER BY timestamp DESC
        LIMIT 1
    """
    try:
        query_job = client.query(query)
        results = list(query_job.result())
        if results:
            row = results[0]
            bp = getattr(row, "buying_power", None)
            summary_val = getattr(row, "summary", None)
            return {
                "timestamp": row.timestamp,
                "account_number": row.account_number,
                "total_equity": row.total_equity,
                "total_cash": row.total_cash,
                "buying_power": bp if bp is not None else row.total_cash,
                "unrealized_gain_loss": row.unrealized_gain_loss,
                "unrealized_gain_loss_percent": row.unrealized_gain_loss_percent,
                "holdings": json.loads(row.holdings) if row.holdings else [],
                "summary": summary_val
            }
    except Exception as e:
        st.error(f"Error loading snapshot: {e}")
    
    # Fallback default structure
    return {
        "timestamp": datetime.now(timezone.utc),
        "account_number": "••••N/A",
        "total_equity": 100.0,
        "total_cash": 100.0,
        "buying_power": 100.0,
        "unrealized_gain_loss": 0.0,
        "unrealized_gain_loss_percent": 0.0,
        "holdings": []
    }

@st.cache_data(ttl=3600)
def load_latest_recommendations() -> pd.DataFrame:
    """Loads the market metrics and signals from the absolute latest batch run within the last 24 hours."""
    query = f"""
        SELECT ticker, raw_score, relative_rank, signal, current_price, moving_average_20d, analyst_consensus, thesis, timestamp, target_weight,
               rsi, macd, macd_signal, drawdown_pct, sentiment_ewma, sentiment_volatility, forward_pe
        FROM `{project}.{dataset_id}.infrastructure_market_metrics`
        WHERE timestamp = (
            SELECT MAX(timestamp) 
            FROM `{project}.{dataset_id}.infrastructure_market_metrics`
        )
        AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
        AND signal != 'FILTERED'
        ORDER BY relative_rank DESC
    """
    try:
        df = client.query(query).to_dataframe()
        return df
    except Exception as e:
        st.error(f"Error loading recommendations: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_latest_graveyard() -> pd.DataFrame:
    """Loads the pre-screener failed assets from the absolute latest batch run within the last 24 hours."""
    query = f"""
        SELECT ticker, current_price, moving_average_20d as sma_50, price_to_ma_ratio as momentum, thesis, timestamp
        FROM `{project}.{dataset_id}.infrastructure_market_metrics`
        WHERE timestamp = (
            SELECT MAX(timestamp) 
            FROM `{project}.{dataset_id}.infrastructure_market_metrics`
        )
        AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
        AND signal = 'FILTERED'
        ORDER BY ticker ASC
    """
    try:
        df = client.query(query).to_dataframe()
        return df
    except Exception as e:
        st.error(f"Error loading graveyard: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_latest_news_headlines() -> list:
    """Loads the raw news headlines from the absolute latest batch run within the last 24 hours."""
    query = f"""
        SELECT raw_news
        FROM `{project}.{dataset_id}.infrastructure_market_metrics`
        WHERE timestamp = (
            SELECT MAX(timestamp) 
            FROM `{project}.{dataset_id}.infrastructure_market_metrics`
        )
        AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
        AND signal != 'FILTERED'
        AND raw_news IS NOT NULL
    """
    try:
        query_job = client.query(query)
        headlines = []
        for row in query_job.result():
            if row.raw_news:
                try:
                    news_list = json.loads(row.raw_news)
                    if isinstance(news_list, list):
                        for news in news_list:
                            title = news.get("title")
                            if title:
                                headlines.append(title.strip())
                except Exception:
                    pass
        return headlines
    except Exception as e:
        st.error(f"Error loading news headlines: {e}")
        return []

@st.cache_data(ttl=3600)
def load_trade_history() -> pd.DataFrame:
    """Loads the entire execution trade history log."""
    query = f"""
        SELECT timestamp, ticker, action, amount_usd, reasoning, COALESCE(dry_run, TRUE) as dry_run
        FROM `{project}.{dataset_id}.trade_history`
        ORDER BY timestamp DESC
    """
    try:
        df = client.query(query).to_dataframe()
        return df
    except Exception as e:
        st.error(f"Error loading trade history: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_portfolio_history() -> pd.DataFrame:
    """Loads the history of portfolio total equity from BigQuery, returning the latest entry per day."""
    query = f"""
        SELECT DATE(timestamp) as date, total_equity
        FROM `{project}.{dataset_id}.portfolio_snapshot`
        QUALIFY ROW_NUMBER() OVER(PARTITION BY DATE(timestamp) ORDER BY timestamp DESC) = 1
        ORDER BY date ASC
    """
    try:
        df = client.query(query).to_dataframe()
        # Ensure the date column is parsed correctly as date objects
        if not df.empty:
            df['date'] = pd.to_datetime(df['date']).dt.date
        return df
    except Exception as e:
        st.error(f"Error loading portfolio history: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_spy_history(start_str: str, end_str: str) -> pd.DataFrame:
    """Fetches daily SPY closing prices from yfinance for the specified range, cached for 1 hour."""
    try:
        spy = yf.Ticker("SPY")
        spy_hist = spy.history(start=start_str, end=end_str)
        if not spy_hist.empty:
            spy_hist = spy_hist.reset_index()
            spy_hist['date'] = pd.to_datetime(spy_hist['Date']).dt.date
            return spy_hist[['date', 'Close']].rename(columns={'Close': 'SPY'})
    except Exception:
        pass
    return pd.DataFrame()

# Company Logo domain mapping and helper
TICKER_DOMAINS = {
    "NVDA": "nvidia.com",
    "AMD": "amd.com",
    "TSM": "tsmc.com",
    "MU": "micron.com",
    "SMCI": "supermicro.com",
    "DELL": "dell.com",
    "VRT": "vertiv.com",
    "ETN": "eaton.com",
    "CEG": "constellationenergy.com",
    "TLT": "ishares.com",
    "MSFT": "microsoft.com",
    "GOOGL": "google.com",
    "AMZN": "amazon.com",
    "META": "meta.com",
    "ORCL": "oracle.com",
    "AVGO": "broadcom.com",
    "ANET": "arista.com",
    "ARM": "arm.com",
    "SNPS": "synopsys.com",
    "CDNS": "cadence.com",
    "ASML": "asml.com",
    "AMAT": "appliedmaterials.com",
    "LRCX": "lamresearch.com",
    "KLAC": "kla.com",
    "INTC": "intel.com",
    "VST": "vistracorp.com",
    "GE": "ge.com",
    "MRVL": "marvell.com",
    "HPE": "hpe.com",
    "PLTR": "palantir.com",
    "IBM": "ibm.com",
    "NOW": "servicenow.com",
    "ADBE": "adobe.com",
    "SAP": "sap.com",
    "NET": "cloudflare.com",
    "DDOG": "datadoghq.com",
    "SNOW": "snowflake.com",
    "CRWD": "crowdstrike.com",
    "PANW": "paloaltonetworks.com",
    "QCOM": "qualcomm.com",
    "SNDK": "sandisk.com"
}

def get_logo_html(ticker: str) -> str:
    domain = TICKER_DOMAINS.get(ticker.upper())
    if domain:
        return f"<img src='https://www.google.com/s2/favicons?domain={domain}&sz=32' style='width: 16px; height: 16px; border-radius: 4px; margin-right: 6px; vertical-align: middle;' onerror='this.style.display=\"none\"' />"
    return ""

def format_thesis_html(text: str, max_chars: int = 60) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return f"<span style='font-size: 0.88rem; color: #334155; line-height: 1.45;'>{text}</span>"
    
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 30:
        truncated = truncated[:last_space]
        
    return f"""
    <details class="thesis-expander">
        <summary style="list-style: none; outline: none; cursor: pointer;">
            <span class="collapsed-text" style="font-size: 0.88rem; color: #334155; line-height: 1.45; white-space: normal;">
                {truncated}... <span style="color: #2563eb; font-weight: 600; white-space: nowrap;">more ▾</span>
            </span>
            <span class="expanded-text" style="font-size: 0.88rem; color: #334155; line-height: 1.45; white-space: normal;">
                {text} <span style="color: #2563eb; font-weight: 600; white-space: nowrap;">less ▴</span>
            </span>
        </summary>
    </details>
    """

# 4. Main App Rendering
st.title("Autonomous Stock Trader")
st.markdown("<p style='font-size: 1.1rem; color: #475569; margin-top: -1.5rem; margin-bottom: 2rem;'><strong>Fully end-to-end:</strong> Ingests daily market news via yfinance, analyzes sentiment with Gemini, deterministically ranks conviction, and executes live orders via <strong>MCP with Agentic Robinhood using real $$$</strong>.</p>", unsafe_allow_html=True)

# Load data
snap = load_latest_snapshot()
recs_df = load_latest_recommendations()
graveyard_df = load_latest_graveyard()
trades_df = load_trade_history()
headlines = load_latest_news_headlines()

# Render decision summary callout Above The Fold (ATF) if present
if snap.get("summary"):
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border-left: 5px solid #22c55e; padding: 1.1rem 1.4rem; border-radius: 8px; margin-top: -0.5rem; margin-bottom: 2rem; box-shadow: 0 4px 12px rgba(34, 197, 94, 0.08);">
        <div style="font-weight: 700; color: #166534; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.3rem; display: flex; align-items: center; justify-content: space-between; gap: 6px;">
            <div style="display: flex; align-items: center; gap: 6px;">
                <span>🤖</span> Latest Agent Recommendations
            </div>
            <a href="/Decision_Logic" target="_self" style="color: #166534; text-decoration: underline; font-weight: 600; font-size: 0.8rem; text-transform: none; letter-spacing: normal;">following rules documented here...</a>
        </div>
        <div style="color: #14532d; font-size: 0.95rem; line-height: 1.5; font-weight: 500;">
            {snap['summary']}
        </div>
    </div>
    """, unsafe_allow_html=True)

# Calculate average sentiment and render columns
if not recs_df.empty:
    avg_sentiment = float(recs_df["raw_score"].mean())
else:
    avg_sentiment = 0.0

col_gauge, col_perf = st.columns([1.5, 2.5])

with col_gauge:
    st.markdown("<div style='text-align: center; font-size: 1.05rem; font-weight: 600; color: #0f172a; margin-top: 0.5rem; margin-bottom: -1rem;'>Market Sentiment (Agent Mood)</div>", unsafe_allow_html=True)
    
    import plotly.graph_objects as go
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=avg_sentiment,
        number={'font': {'size': 32, 'color': '#0f172a', 'family': 'Outfit, sans-serif'}, 'valueformat': '.3f'},
        domain={'x': [0.25, 0.75], 'y': [0, 1]},
        gauge={
            'axis': {'range': [-1.0, 1.0], 'tickwidth': 1, 'tickcolor': "#475569"},
            'bar': {'color': "rgba(0,0,0,0)"},  # Transparent to let the pure steps colors pop
            'bgcolor': "rgba(0,0,0,0)",
            'borderwidth': 0,
            'steps': [
                {'range': [-1.0, -0.2], 'color': "#FF3B30"},  # Apple Vibrant Red
                {'range': [-0.2, 0.2], 'color': "#FFCC00"},   # Apple Vibrant Yellow
                {'range': [0.2, 1.0], 'color': "#34C759"}    # Apple Vibrant Green
            ],
            'threshold': {
                'line': {'color': "#0f172a", 'width': 7},   # High-contrast deep slate pointer
                'thickness': 1.0,
                'value': avg_sentiment
            }
        }
    ))
    
    fig_gauge.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font={'color': "#0f172a", 'family': "Outfit, sans-serif"},
        height=120,
        margin=dict(l=10, r=10, t=10, b=10)
    )
    st.plotly_chart(fig_gauge, use_container_width=True)

with col_perf:
    # 1. Load portfolio total value history from BigQuery (cached & daily-deduplicated)
    df_daily = load_portfolio_history()
    
    if df_daily.empty or len(df_daily) < 1:
        st.markdown("<div style='text-align: center; color: #475569; font-size: 0.9rem; margin-top: 2.5rem;'>Performance history comparison will populate once snapshots are logged.</div>", unsafe_allow_html=True)
    else:
        # Force a 7-day lookback range for daily visualization
        from datetime import datetime, timezone, timedelta
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=6) # 7 days total (today + 6 days back)
        
        # Download S&P 500 (SPY) for the same range (cached)
        try:
            start_str = start_date.strftime("%Y-%m-%d")
            end_str = (end_date + timedelta(days=2)).strftime("%Y-%m-%d")
            
            spy_df = fetch_spy_history(start_str, end_str)
            
            if not spy_df.empty:
                # Create a date backbone of all 7 days in the range
                date_range = [start_date + timedelta(days=i) for i in range(7)]
                backbone_df = pd.DataFrame({'date': date_range})
                
                # Merge backbone with portfolio and spy
                merged = pd.merge(backbone_df, df_daily, on='date', how='left')
                merged = pd.merge(merged, spy_df, on='date', how='left')
                
                # Forward-fill / backward-fill SPY prices to cover weekends/holidays
                merged['SPY'] = merged['SPY'].ffill().bfill()
                
                # Filter out any dates before the first portfolio snapshot date
                # to make sure the benchmark comparison starts exactly on the first portfolio day
                first_portfolio_row = merged[merged['total_equity'].notnull()]
                if not first_portfolio_row.empty:
                    first_valid_date = first_portfolio_row['date'].iloc[0]
                    merged = merged[merged['date'] >= first_valid_date].copy()
                
                # Calculate base-100 return starting on the first valid portfolio snapshot day
                merged_valid = merged.dropna(subset=['total_equity']).copy()
                
                if not merged_valid.empty:
                    first_equity = merged_valid['total_equity'].iloc[0]
                    first_spy = merged_valid['SPY'].iloc[0]
                    
                    merged['Agent Portfolio'] = (merged['total_equity'] / first_equity) * 100 if first_equity > 0 else 100.0
                    merged['S&P 500 (SPY)'] = (merged['SPY'] / first_spy) * 100 if first_spy > 0 else 100.0
                else:
                    merged['Agent Portfolio'] = pd.Series(dtype='float64')
                    merged['S&P 500 (SPY)'] = pd.Series(dtype='float64')
                
                # Melt for plotting
                plot_df = merged.melt(id_vars=['date'], value_vars=['Agent Portfolio', 'S&P 500 (SPY)'], var_name='Metric', value_name='Normalized Value')
                
                # Line chart
                fig_line = px.line(
                    plot_df,
                    x='date',
                    y='Normalized Value',
                    color='Metric',
                    color_discrete_map={
                        'Agent Portfolio': '#2563eb',
                        'S&P 500 (SPY)': '#94a3b8'
                    }
                )
                
                fig_line.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font={'color': "#0f172a", 'family': "Outfit, sans-serif"},
                    height=140,
                    margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(showgrid=True, gridcolor='#f1f5f9', title="", type='date', dtick="D1", tickformat="%b %d"),
                    yaxis=dict(showgrid=True, gridcolor='#f1f5f9', title="Normalized Return"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1)
                )
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.markdown("<div style='text-align: center; color: #475569; font-size: 0.9rem; margin-top: 2.5rem;'>Benchmark data unavailable (empty history).</div>", unsafe_allow_html=True)
        except Exception as e:
            st.markdown(f"<div style='text-align: center; color: #ef4444; font-size: 0.9rem; margin-top: 2.5rem;'>Error loading S&P 500 comparison: {e}</div>", unsafe_allow_html=True)

# Header details
col_left, col_right = st.columns(2)
with col_left:
    st.caption(f"Account Managed: **{snap['account_number']}**")
with col_right:
    # Format localized time as relative "X time ago"
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    diff = now - snap['timestamp']
    diff_hours = diff.total_seconds() / 3600.0
    if diff_hours < 1.0:
        diff_mins = diff.total_seconds() / 60.0
        time_ago = f"{int(diff_mins)} minutes ago" if diff_mins >= 1 else "just now"
    else:
        time_ago = f"{int(diff_hours)} hours ago" if int(diff_hours) > 1 else "1 hour ago"
        
    st.markdown(f"<div style='text-align: right; color: #475569; font-size: 0.82rem; font-style: italic;'>Last Snapshot: {time_ago}</div>", unsafe_allow_html=True)

# Metrics & Allocation Panel
m1, m2, m3, m4 = st.columns([1, 1, 1, 1.2])
with m1:
    st.metric(
        label="Net Portfolio Value",
        value=f"${snap['total_equity']:.2f}",
        delta=f"{snap['unrealized_gain_loss_percent']:.2f}% Total Return"
    )
with m2:
    pending_cash = max(0.0, snap['total_cash'] - snap['buying_power'])
    st.metric(
        label="Settled Cash (Buying Power)",
        value=f"${snap['buying_power']:.2f}",
        delta=f"${pending_cash:.2f} Pending" if pending_cash > 0.01 else "No Pending Cash",
        delta_color="off"
    )
with m3:
    gain_loss = snap['unrealized_gain_loss']
    val_sign = "" if gain_loss >= 0 else "-"
    delta_sign = "+" if gain_loss >= 0 else "-"
    st.metric(
        label="Unrealized Gain / Loss",
        value=f"{val_sign}${abs(gain_loss):.2f}",
        delta=f"{delta_sign}${abs(gain_loss):.2f} total"
    )
with m4:
    holdings_list = snap["holdings"]
    if not holdings_list:
        # 100% Cash allocation
        allocation_df = pd.DataFrame([{"Asset": "Cash", "Value (USD)": snap["total_cash"]}])
    else:
        # Sum of holdings + cash
        rows = [{"Asset": h["symbol"], "Value (USD)": h["equity"]} for h in holdings_list]
        rows.append({"Asset": "Cash", "Value (USD)": snap["total_cash"]})
        allocation_df = pd.DataFrame(rows)
        
    # Custom Styled Allocation Table
    total_val = allocation_df["Value (USD)"].sum()
    allocation_df["Allocation (%)"] = (allocation_df["Value (USD)"] / total_val) * 100
    allocation_df = allocation_df.sort_values(by="Value (USD)", ascending=False)

    st.markdown("""
    <style>
        .alloc-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.8rem;
            color: #0f172a;
            margin-top: 0.2rem;
        }
        .alloc-table th {
            background-color: #f1f5f9;
            border-bottom: 2px solid #e2e8f0;
            padding: 4px 6px;
            text-align: left;
            font-weight: 600;
            color: #475569;
            font-size: 0.72rem;
        }
        .alloc-table td {
            padding: 6px;
            border-bottom: 1px solid #e2e8f0;
            vertical-align: middle;
        }
        .alloc-table tr:hover {
            background-color: #f8fafc;
        }
    </style>
    <div style='text-align: center; font-size: 0.75rem; font-weight: 600; color: #475569; margin-bottom: 0.4rem; margin-top: -0.4rem;'>PORTFOLIO ALLOCATION</div>
    """, unsafe_allow_html=True)

    html_code = "<table class='alloc-table'><thead><tr><th>Asset</th><th>Value</th><th>Allocation</th></tr></thead><tbody>"
    
    other_colors = ["#00C689", "#FFA26B", "#FF4C61", "#D3D3D3"]
    color_idx = 0
    
    for _, row in allocation_df.iterrows():
        asset = row["Asset"]
        val = row["Value (USD)"]
        pct = row["Allocation (%)"]
        
        if asset == "Cash":
            color = "#3F8CFF"
            asset_display = "<strong style='color: #3F8CFF;'>Cash</strong>"
        else:
            color = other_colors[color_idx % len(other_colors)]
            color_idx += 1
            logo_img = get_logo_html(asset)
            asset_display = f"<div style='display: flex; align-items: center;'>{logo_img}<a class='ticker-link' href='https://finance.yahoo.com/quote/{asset}' target='_blank'>{asset}</a></div>"
            
        val_str = f"${val:,.2f}"
        pct_str = f"{pct:.1f}%"
        
        html_code += f"""
        <tr>
            <td>{asset_display}</td>
            <td>{val_str}</td>
            <td>
                <div style='display: flex; align-items: center; justify-content: space-between;'>
                    <span style='font-weight: 600;'>{pct_str}</span>
                    <div style='background-color: #e2e8f0; border-radius: 3px; width: 40px; height: 6px; margin-left: 8px; overflow: hidden; flex-shrink: 0;'>
                        <div style='background-color: {color}; width: {pct}%; height: 100%; border-radius: 3px;'></div>
                    </div>
                </div>
            </td>
        </tr>
        """
    html_code += "</tbody></table>"
    cleaned_html = "\n".join([line.strip() for line in html_code.split("\n")])
    st.markdown(cleaned_html, unsafe_allow_html=True)

st.markdown("<hr/>", unsafe_allow_html=True)

# Bloomberg Style Marquee Ticker Tape
if headlines:
    ticker_text = " | ".join(headlines)
    st.markdown(
        f"""
        <div style="background-color: #0f172a; border-radius: 6px; padding: 6px 12px; margin-top: -1.5rem; margin-bottom: 1.5rem; border: 1px solid #1e293b; overflow: hidden; white-space: nowrap;">
            <marquee style="font-family: 'Courier New', Courier, monospace; color: #34d399; font-weight: 600; font-size: 0.85rem;" scrollamount="6">
                🔥 LATEST MARKET NEWS INGESTED BY SENTIMENT AGENT: &nbsp;&nbsp;&nbsp;&nbsp; {ticker_text}
            </marquee>
        </div>
        """,
        unsafe_allow_html=True
    )

# 5. Latest Recommendations (Full Width Custom HTML Table)
with st.expander("📈 Daily AI Stock Recommendations", expanded=True):
    st.markdown("<p style='font-size: 0.85rem; color: #475569; margin-top: 0rem; margin-bottom: 1rem;'>We filter our 40-stock AI universe by 50-day SMA and price momentum to select the top 10 for sentiment analysis. A Multi-Agent Critique Loop (Analyst, Risk Advisor, and Escalation Checker) then debates and refines these inputs to finalize optimal target allocations and execution signals.</p>", unsafe_allow_html=True)
    if not recs_df.empty:
        # Inject Custom Table CSS
        st.markdown("""
        <style>
            .rec-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 1rem;
                font-size: 0.85rem;
                color: #0f172a;
            }
            .rec-table th {
                background-color: #f1f5f9;
                border-bottom: 2px solid #e2e8f0;
                padding: 10px;
                text-align: left;
                font-weight: 600;
                color: #475569;
            }
            .rec-table td {
                padding: 12px 10px;
                border-bottom: 1px solid #e2e8f0;
                vertical-align: top;
            }
            .rec-table tr:hover {
                background-color: #f8fafc;
            }
            .ticker-link {
                color: #2563eb;
                text-decoration: none;
                font-weight: 600;
            }
            .ticker-link:hover {
                text-decoration: underline;
            }
            .thesis-text {
                font-size: 0.78rem;
                color: #475569;
                line-height: 1.45;
                white-space: normal;
                word-break: break-word;
            }
            .signal-badge {
                padding: 3px 8px;
                border-radius: 4px;
                font-size: 0.75rem;
                font-weight: 600;
                display: inline-block;
            }
            .signal-buy {
                background-color: rgba(34, 197, 94, 0.15);
                color: #15803d;
            }
            .signal-liquidate {
                background-color: rgba(239, 68, 68, 0.15);
                color: #b91c1c;
            }
            .signal-hold {
                background-color: rgba(245, 158, 11, 0.15);
                color: #b45309;
            }
            
            /* Tooltip styling */
            .tooltip {
                position: relative;
                display: inline-block;
                cursor: help;
            }
            .tooltip .tooltiptext {
                visibility: hidden;
                width: 220px;
                background-color: #0f172a;
                color: #fff;
                text-align: center;
                border-radius: 6px;
                padding: 8px;
                position: absolute;
                z-index: 100;
                bottom: 125%;
                left: 50%;
                margin-left: -110px;
                opacity: 0;
                transition: opacity 0.2s;
                font-size: 0.74rem;
                font-weight: normal;
                line-height: 1.35;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                white-space: normal;
            }
            .tooltip:hover .tooltiptext {
                visibility: visible;
                opacity: 1;
            }
            .tooltip .tooltip-align-left {
                text-align: left !important;
                width: 250px !important;
                margin-left: -125px !important;
                padding: 10px !important;
                font-family: monospace;
                white-space: pre-wrap !important;
            }
            
            /* Inline Thesis Expander Styles */
            details.thesis-expander summary::-webkit-details-marker {
                display: none !important;
            }
            details.thesis-expander summary {
                list-style: none !important;
                outline: none;
                cursor: pointer;
            }
            details.thesis-expander .expanded-text {
                display: none;
            }
            details.thesis-expander[open] .collapsed-text {
                display: none;
            }
            details.thesis-expander[open] .expanded-text {
                display: inline;
            }
        </style>
        """, unsafe_allow_html=True)

        # Construct HTML Table
        html_code = """
    <table class='rec-table'>
        <thead>
            <tr>
                <th style='width: 12%'>Ticker</th>
                <th style='width: 14%; line-height: 1.25;'>
                    <div class='tooltip'>
                        News Sentiment <span style='font-size: 0.72rem; color: #2563eb;'>ⓘ</span>
                        <span class='tooltiptext'>Raw sentiment score (-1.0 to +1.0) assigned by the Gemini Sentiment Agent based on 24h news.</span>
                    </div>
                </th>
                <th style='width: 12%; line-height: 1.25;'>
                    <div class='tooltip'>
                        Signal <span style='font-size: 0.72rem; color: #2563eb;'>ⓘ</span>
                        <span class='tooltiptext'>Action signal assigned by combining baseline sentiment ranking with strict technical entry gates (RSI/MACD), holding period rules, and risk limits via the multi-agent debate loop.</span>
                    </div>
                </th>
                <th style='width: 11%'>Price</th>
                <th style='width: 11%; line-height: 1.25;'>
                    <div class='tooltip'>
                        Analyst Consensus <span style='font-size: 0.72rem; color: #2563eb;'>ⓘ</span>
                        <span class='tooltiptext'>Aggregated consensus recommendation key retrieved directly from Wall Street analysts via Yahoo Finance.</span>
                    </div>
                </th>
                <th style='width: 13%; line-height: 1.25;'>
                    <div class='tooltip'>
                        AI Recommended Allocation <span style='font-size: 0.72rem; color: #2563eb;'>ⓘ</span>
                        <span class='tooltiptext'>Target weight as a fraction of total portfolio equity, recommended by the multi-agent critique loop.</span>
                    </div>
                </th>
                <th style='width: 27%; line-height: 1.25;'>
                    <div class='tooltip'>
                        AI Agent Thesis <span style='font-size: 0.72rem; color: #2563eb;'>ⓘ</span>
                        <span class='tooltiptext' style='margin-left: -270px; width: 300px; text-align: left;'>Justification generated by the AI analyst.<br/><br/><b>Path A (Value/Dip Entry):</b> Triggered by a sustained RSI drop (RSI &lt; 30 for 3+ days). Requires drawdown &ge; 10% from 52w high, EWMA sentiment &gt; 0.1, and low sentiment volatility (SD &le; 0.4).<br/><br/><b>Path B (Momentum Breakout):</b> Triggered by a 20d high and MACD bullish cross. Bypasses drawdown and volatility limits.</span>
                    </div>
                </th>
            </tr>
        </thead>
        <tbody>
        """
        for _, row in recs_df.iterrows():
            ticker = row["ticker"]
            score = float(row["raw_score"])
            sig = row["signal"]
            price = row["current_price"]
            price_str = f"${price:.2f}" if pd.notnull(price) else "N/A"
            consensus = row["analyst_consensus"] or "N/A"
            thesis = row["thesis"] or ""
            target_weight = row.get("target_weight")
            if pd.notnull(target_weight) and target_weight > 0.0:
                target_weight_str = f"{target_weight * 100:.1f}%"
                weight_display = f"<span class='signal-badge signal-buy' style='font-weight: 700;'>{target_weight_str}</span>"
            else:
                target_weight_str = f"{target_weight * 100:.1f}%" if pd.notnull(target_weight) else "0.0%"
                weight_display = f"<span style='color: #64748b; font-weight: 500;'>{target_weight_str}</span>"
            
            # Format technical indicators for the row's details tooltip
            rsi = row.get("rsi")
            rsi_str = f"{rsi:.1f}" if pd.notnull(rsi) else "N/A"
            
            macd = row.get("macd")
            macd_sig = row.get("macd_signal")
            macd_str = f"{macd:+.2f} / {macd_sig:+.2f}" if pd.notnull(macd) and pd.notnull(macd_sig) else "N/A"
            
            drawdown = row.get("drawdown_pct")
            drawdown_str = f"{drawdown:.1f}%" if pd.notnull(drawdown) else "0.0%"
            
            ewma = row.get("sentiment_ewma")
            ewma_str = f"{ewma:+.2f}" if pd.notnull(ewma) else "N/A"
            
            vol = row.get("sentiment_volatility")
            vol_str = f"{vol:.2f}" if pd.notnull(vol) else "N/A"
            
            pe = row.get("forward_pe")
            pe_str = f"{pe:.1f}" if pd.notnull(pe) else "N/A"
            
            sma = row.get("moving_average_20d")
            sma_str = f"${sma:.2f}" if pd.notnull(sma) else "N/A"

            # Badge selection
            if sig == "STRONG BUY":
                badge_class = "signal-buy"
            elif sig == "LIQUIDATE":
                badge_class = "signal-liquidate"
            else:
                badge_class = "signal-hold"
                
            logo_img = get_logo_html(ticker)
            html_code += f"""
            <tr>
                <td>
                    <div style='display: flex; align-items: center; justify-content: space-between;'>
                        <div style='display: flex; align-items: center;'>
                            {logo_img}
                            <a class='ticker-link' href='https://finance.yahoo.com/quote/{ticker}' target='_blank'>{ticker}</a>
                        </div>
                        <div class='tooltip' style='margin-left: 6px;'>
                            <span style='font-size: 0.85rem; color: #2563eb; cursor: help;'>ⓘ</span>
                            <span class='tooltiptext tooltip-align-left'>
<strong style='color: #60a5fa;'>{ticker} Technical Metrics</strong>
• Forward P/E: {pe_str}
• 14-Day RSI: {rsi_str}
• MACD/Signal: {macd_str}
• Drawdown: {drawdown_str}
• 5d Sentiment: {ewma_str} (EWMA)
• Sent. Vol: {vol_str}
• 20d SMA: {sma_str}
                            </span>
                        </div>
                    </div>
                </td>
                <td>{score:+.2f}</td>
                <td><span class='signal-badge {badge_class}'>{sig}</span></td>
                <td>{price_str}</td>
                <td>{consensus}</td>
                <td style='vertical-align: middle;'>{weight_display}</td>
                <td>{format_thesis_html(thesis)}</td>
            </tr>
            """
        html_code += "</tbody></table>"
        # Clean leading whitespace to prevent Markdown from interpreting indentation as preformatted blocks
        cleaned_html = "\n".join([line.strip() for line in html_code.split("\n")])
        st.markdown(cleaned_html, unsafe_allow_html=True)
    else:
        st.info("No daily recommendations logged yet.")

# Token-Saving Pre-Screener (The Graveyard) Section
st.markdown("<div style='margin-top: 1.5rem;'></div>", unsafe_allow_html=True)
with st.expander("🛡️ Token-Saving Pre-Screener (The Graveyard) — Filtered Assets", expanded=False):
    st.markdown("<p style='font-size: 0.85rem; color: #475569; margin-top: 0rem; margin-bottom: 1.2rem;'>To minimize LLM inference costs and optimize execution speed, the pre-screener automatically filters out assets that have weak technical setups (e.g. trading below their 50-day SMA or falling outside the top momentum ranks). These assets completely skip news ingestion and Gemini sentiment analysis, <strong>saving 100% of LLM token costs</strong> for these stocks today.</p>", unsafe_allow_html=True)
    if not graveyard_df.empty:
        html_code_gy = """
<table class='rec-table'>
    <thead>
        <tr>
            <th style='width: 15%'>Ticker</th>
            <th style='width: 15%'>Price</th>
            <th style='width: 15%'>50-Day SMA</th>
            <th style='width: 15%'>Price / SMA Ratio</th>
            <th style='width: 40%'>Pre-Screener Filter Reason</th>
        </tr>
    </thead>
    <tbody>
        """
        for _, row in graveyard_df.iterrows():
            ticker = row["ticker"]
            price = row["current_price"]
            price_str = f"${price:.2f}" if pd.notnull(price) else "N/A"
            sma = row["sma_50"]
            sma_str = f"${sma:.2f}" if pd.notnull(sma) else "N/A"
            mom = row["momentum"]
            mom_str = f"{mom:.3f}" if pd.notnull(mom) else "N/A"
            reason = row["thesis"] or ""
            
            logo_img = get_logo_html(ticker)
            
            html_code_gy += f"""
        <tr>
            <td><div style='display: flex; align-items: center;'>{logo_img}<a class='ticker-link' href='https://finance.yahoo.com/quote/{ticker}' target='_blank'>{ticker}</a></div></td>
            <td>{price_str}</td>
            <td>{sma_str}</td>
            <td>{mom_str}</td>
            <td><span style='color: #64748b; font-style: italic;'>{reason}</span></td>
        </tr>
            """
        html_code_gy += "</tbody></table>"
        cleaned_html_gy = "\n".join([line.strip() for line in html_code_gy.split("\n")])
        st.markdown(cleaned_html_gy, unsafe_allow_html=True)
    else:
        st.info("No pre-screener graveyard logs found for today.")

st.markdown("<hr/>", unsafe_allow_html=True)

# 6. Paginated & Filterable Trade History
with st.expander("💼 Executed Trade History Log", expanded=True):
    st.markdown("<p style='font-size: 0.85rem; color: #475569; margin-top: 0rem; margin-bottom: 1.2rem;'>This log displays live execution receipts performed by the trading agent on Robinhood via Model Context Protocol (MCP) tool calls, including detailed justifications logged directly from the agent's execution loop.</p>", unsafe_allow_html=True)

    if not trades_df.empty:
        # Checkbox to toggle simulated / dry-runs (default off)
        show_simulated = st.checkbox("Show Simulated / Dry Run Trades", value=False)
        
        # Pre-process trades: Filter out HOLDs and normalize signal names to BUY / SELL
        processed_df = trades_df.copy()
        processed_df = processed_df[~processed_df["action"].isin(["HOLD"])]
        
        action_map = {
            "STRONG BUY": "BUY",
            "BUY": "BUY",
            "SELL": "SELL",
            "LIQUIDATE": "SELL"
        }
        processed_df["action"] = processed_df["action"].map(lambda a: action_map.get(a, a))
        
        # Filter out dry runs if checkbox is unchecked
        if not show_simulated:
            processed_df = processed_df[~processed_df["dry_run"]]
            
        if not processed_df.empty:
            # Filter controls
            col_search, col_action = st.columns([3, 1])
            with col_search:
                search_ticker = st.text_input("Filter by Ticker symbol:", "").strip().upper()
            with col_action:
                action_filter = st.selectbox("Filter by Action:", ["All", "BUY", "SELL"])
                
            filtered_df = processed_df.copy()
            
            # Apply search filter
            if search_ticker:
                filtered_df = filtered_df[filtered_df["ticker"].str.contains(search_ticker, case=False)]
                
            # Apply action dropdown filter
            if action_filter != "All":
                filtered_df = filtered_df[filtered_df["action"] == action_filter]
                
            if not filtered_df.empty:
                # Construct HTML Table for trades with styled badges and wrapping
                html_code_trades = """
    <table class='rec-table'>
        <thead>
            <tr>
                <th style='width: 20%'>Timestamp</th>
                <th style='width: 10%'>Ticker</th>
                <th style='width: 12%'>Action</th>
                <th style='width: 13%'>Amount</th>
                <th style='width: 45%'>Reasoning / Trade Thesis</th>
            </tr>
        </thead>
        <tbody>
                """
                for _, row in filtered_df.iterrows():
                    # Extract and format values (Convert UTC to Pacific Time)
                    from zoneinfo import ZoneInfo
                    ts_dt = pd.to_datetime(row["timestamp"])
                    if ts_dt.tzinfo is None:
                        ts_dt = ts_dt.tz_localize("UTC")
                    ts_local = ts_dt.astimezone(ZoneInfo("America/Los_Angeles"))
                    ts = ts_local.strftime("%m/%d/%y, %I:%M %p %Z")
                    raw_ticker = row["ticker"]
                    action = row["action"]
                    amount_val = row["amount_usd"]
                    
                    if isinstance(amount_val, (int, float)):
                        amount_str = f"${amount_val:.2f}"
                    else:
                        amount_str = str(amount_val)
                        if not amount_str.startswith("$"):
                            try:
                                amount_str = f"${float(amount_str):.2f}"
                            except ValueError:
                                pass
                    
                    reasoning = row["reasoning"] or ""
                    
                    # Badge selection
                    if action == "BUY":
                        badge_class = "signal-buy"
                    elif action == "SELL":
                        badge_class = "signal-liquidate"
                    else:
                        badge_class = "signal-hold"
                        
                    logo_img = get_logo_html(raw_ticker)
                    html_code_trades += f"""
            <tr>
                <td>{ts}</td>
                <td><div style='display: flex; align-items: center;'>{logo_img}<a class='ticker-link' href='https://finance.yahoo.com/quote/{raw_ticker}' target='_blank'>{raw_ticker}</a></div></td>
                <td><span class='signal-badge {badge_class}'>{action}</span></td>
                <td>{amount_str}</td>
                <td>{format_thesis_html(reasoning)}</td>
            </tr>
                    """
                html_code_trades += "</tbody></table>"
                # Clean leading whitespace to prevent Markdown from interpreting indentation as preformatted blocks
                cleaned_html_trades = "\n".join([line.strip() for line in html_code_trades.split("\n")])
                st.markdown(cleaned_html_trades, unsafe_allow_html=True)
            else:
                st.info("No executed trades match the search filters.")
        else:
            st.info("No live executed trades logged yet. (Check 'Show Simulated / Dry Run Trades' to view simulated execution logs).")
    else:
        st.info("No executed trades logged in the database yet.")
