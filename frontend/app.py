import os
# Force native DNS resolution for gRPC to prevent macOS IPv6 resolution failures
os.environ["GRPC_DNS_RESOLVER"] = "native"

import json
import pandas as pd
import streamlit as st
import plotly.express as px
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
        background: linear-gradient(135deg, #6C5DD3 0%, #3F8CFF 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 2rem !important;
    }
    
    /* Metrics panel decoration */
    div[data-testid="metric-container"] {
        background-color: #1e1e24;
        border: 1px solid #2e2e38;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        transition: transform 0.2s;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px);
    }
    
    /* Custom divider line */
    hr {
        margin: 2.5rem 0 !important;
        border-color: #2e2e38 !important;
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
def load_latest_snapshot() -> dict:
    """Loads the most recent portfolio snapshot from BigQuery."""
    query = f"""
        SELECT timestamp, account_number, total_equity, total_cash, unrealized_gain_loss, unrealized_gain_loss_percent, holdings
        FROM `{project}.{dataset_id}.portfolio_snapshot`
        ORDER BY timestamp DESC
        LIMIT 1
    """
    try:
        query_job = client.query(query)
        results = list(query_job.result())
        if results:
            row = results[0]
            return {
                "timestamp": row.timestamp,
                "account_number": row.account_number,
                "total_equity": row.total_equity,
                "total_cash": row.total_cash,
                "unrealized_gain_loss": row.unrealized_gain_loss,
                "unrealized_gain_loss_percent": row.unrealized_gain_loss_percent,
                "holdings": json.loads(row.holdings) if row.holdings else []
            }
    except Exception as e:
        st.error(f"Error loading snapshot: {e}")
    
    # Fallback default structure
    return {
        "timestamp": datetime.now(timezone.utc),
        "account_number": "••••N/A",
        "total_equity": 100.0,
        "total_cash": 100.0,
        "unrealized_gain_loss": 0.0,
        "unrealized_gain_loss_percent": 0.0,
        "holdings": []
    }

def load_latest_recommendations() -> pd.DataFrame:
    """Loads the latest market metrics and signals logged today."""
    query = f"""
        SELECT ticker, raw_score, relative_rank, signal, current_price, moving_average_20d, analyst_consensus, thesis, timestamp
        FROM `{project}.{dataset_id}.infrastructure_market_metrics`
        WHERE DATE(timestamp) = (
            SELECT DATE(MAX(timestamp)) 
            FROM `{project}.{dataset_id}.infrastructure_market_metrics`
        )
        ORDER BY relative_rank DESC
    """
    try:
        df = client.query(query).to_dataframe()
        return df
    except Exception as e:
        st.error(f"Error loading recommendations: {e}")
        return pd.DataFrame()

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

# 4. Main App Rendering
st.title("Autonomous Stock Trader")
st.markdown("<p style='font-size: 1.1rem; color: #a0a0b0; margin-top: -1.5rem; margin-bottom: 2rem;'><strong>Fully end-to-end:</strong> Ingests daily market news via yfinance, analyzes sentiment with Gemini, deterministically ranks conviction, and executes live orders via <strong>MCP with Agentic Robinhood using real $$$</strong>.</p>", unsafe_allow_html=True)

# Load data
snap = load_latest_snapshot()
recs_df = load_latest_recommendations()
trades_df = load_trade_history()

# Header details
col_left, col_right = st.columns(2)
with col_left:
    st.caption(f"Account Managed: **{snap['account_number']}**")
with col_right:
    # Format localized time
    local_time = snap['timestamp'].strftime("%Y-%m-%d %H:%M:%S UTC")
    st.markdown(f"<div style='text-align: right; color: gray;'>Last Snapshot: {local_time}</div>", unsafe_allow_html=True)

# Metrics Panel
m1, m2, m3 = st.columns(3)
with m1:
    st.metric(
        label="Net Portfolio Value",
        value=f"${snap['total_equity']:.2f}",
        delta=f"{snap['unrealized_gain_loss_percent']:.2f}% Total Return"
    )
with m2:
    st.metric(
        label="Available Cash (Buying Power)",
        value=f"${snap['total_cash']:.2f}"
    )
with m3:
    gain_loss = snap['unrealized_gain_loss']
    gain_loss_prefix = "+" if gain_loss >= 0 else ""
    st.metric(
        label="Unrealized Gain / Loss",
        value=f"{gain_loss_prefix}${gain_loss:.2f}",
        delta=f"{gain_loss_prefix}${gain_loss:.2f} total",
        delta_color="normal" if gain_loss >= 0 else "inverse"
    )

st.markdown("<hr/>", unsafe_allow_html=True)

# 5. Asset Allocation & Latest Recommendations
col_charts, col_recs = st.columns([2, 3])

with col_charts:
    st.subheader("Portfolio Allocation")
    holdings_list = snap["holdings"]
    
    if not holdings_list:
        # 100% Cash allocation
        allocation_df = pd.DataFrame([{"Asset": "Cash", "Value (USD)": snap["total_cash"]}])
    else:
        # Sum of holdings + cash
        rows = [{"Asset": h["symbol"], "Value (USD)": h["equity"]} for h in holdings_list]
        rows.append({"Asset": "Cash", "Value (USD)": snap["total_cash"]})
        allocation_df = pd.DataFrame(rows)
        
    # Plotly donut chart
    fig = px.pie(
        allocation_df,
        values="Value (USD)",
        names="Asset",
        hole=0.4,
        color_discrete_sequence=["#6C5DD3", "#3F8CFF", "#00C689", "#FFA26B", "#FF4C61", "#D3D3D3"]
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font_color="white"
    )
    st.plotly_chart(fig, use_container_width=True)

with col_recs:
    st.subheader("Daily AI Stock Recommendations")
    if not recs_df.empty:
        # Select key columns for display
        disp_df = recs_df[[
            "ticker", "raw_score", "relative_rank", "signal", 
            "current_price", "analyst_consensus", "thesis"
        ]].copy()
        
        # Format columns
        disp_df["ticker"] = disp_df["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
        disp_df["raw_score"] = disp_df["raw_score"].map(lambda x: f"{x:.2f}")
        disp_df["current_price"] = disp_df["current_price"].map(lambda x: f"${x:.2f}" if pd.notnull(x) else "N/A")
        disp_df.columns = ["Ticker", "Sentiment Score", "Rank", "Signal", "Price", "Consensus", "Thesis"]
        
        st.dataframe(
            disp_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Ticker": st.column_config.LinkColumn("Ticker", display_text=r"https://finance\.yahoo\.com/quote/(.*)", width="small"),
                "Sentiment Score": st.column_config.TextColumn(width="small"),
                "Rank": st.column_config.NumberColumn(width="small"),
                "Signal": st.column_config.TextColumn(width="small"),
                "Price": st.column_config.TextColumn(width="small"),
                "Consensus": st.column_config.TextColumn(width="small"),
                "Thesis": st.column_config.TextColumn(width="large")
            }
        )
    else:
        st.info("No daily recommendations logged yet.")

st.markdown("<hr/>", unsafe_allow_html=True)

# 6. Paginated & Filterable Trade History
st.subheader("Executed Trade History Log")
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
            # Format and present trade table
            filtered_df["amount_usd"] = filtered_df["amount_usd"].map(lambda x: f"${x:.2f}")
            # Convert timestamp to human-readable datetime string
            filtered_df["timestamp"] = pd.to_datetime(filtered_df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
            
            # Select columns to display (hide dry_run column)
            disp_df = filtered_df[["timestamp", "ticker", "action", "amount_usd", "reasoning"]].copy()
            disp_df["ticker"] = disp_df["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
            disp_df.columns = ["Timestamp (UTC)", "Ticker", "Action", "Amount", "Reasoning / Trade Thesis"]
            
            # Paginate by showing standard Streamlit scrollable dataframe
            st.dataframe(
                disp_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Timestamp (UTC)": st.column_config.TextColumn(width="medium"),
                    "Ticker": st.column_config.LinkColumn("Ticker", display_text=r"https://finance\.yahoo\.com/quote/(.*)", width="small"),
                    "Action": st.column_config.TextColumn(width="small"),
                    "Amount": st.column_config.TextColumn(width="small"),
                    "Reasoning / Trade Thesis": st.column_config.TextColumn(width="large")
                }
            )
        else:
            st.info("No executed trades match the search filters.")
    else:
        st.info("No live executed trades logged yet. (Check 'Show Simulated / Dry Run Trades' to view simulated execution logs).")
else:
    st.info("No executed trades logged in the database yet.")
