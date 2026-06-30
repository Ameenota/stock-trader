import streamlit as st

# 1. Page Configuration
st.set_page_config(
    page_title="Portfolio Decision Logic - Autonomous Stock Trader",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="auto"
)

# 2. Modern Custom Styling matching the main dashboard
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
        margin-bottom: 0.5rem !important;
    }
    
    .subtitle {
        font-size: 1.1rem;
        color: #475569;
        margin-bottom: 2rem;
    }
    
    /* Phase Card Styling */
    .phase-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
        margin-bottom: 1.5rem;
    }
    
    .phase-title {
        font-weight: 700;
        color: #1e293b;
        font-size: 1.15rem;
        margin-bottom: 0.75rem;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    .gate-list {
        margin-left: 1.25rem;
        margin-bottom: 0px;
    }
    
    .gate-item {
        margin-bottom: 0.5rem;
        line-height: 1.5;
        font-size: 0.92rem;
    }
    
    .gate-name {
        font-weight: 600;
        color: #2563eb;
    }
    
    /* Custom divider line */
    hr {
        margin: 2rem 0 !important;
        border-color: #e2e8f0 !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("Portfolio Decision Logic")
st.markdown("<p class='subtitle'>A concise reference for the 6-phase quantitative and qualitative engine determining our daily allocations.</p>", unsafe_allow_html=True)

# Phase 1
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>🔍</span> Phase 1: Watchlist Screening (Pre-Filtering & Momentum)</div>
    <ul class="gate-list">
        <li class="gate-item"><span class="gate-name">Owned Position Promotion:</span> Any stock currently held in the portfolio is automatically force-included in the active watchlist.</li>
        <li class="gate-item"><span class="gate-name">Cool-down Filter:</span> Live assets sold within the last 21 days are excluded from the watchlist to prevent rapid buy-sell-buy chop.</li>
        <li class="gate-item"><span class="gate-name">Trend & RSI Bypass:</span> Stocks must trade above their 50-day SMA, unless deeply oversold with a 14-day RSI < 25 (deep pullback value entries).</li>
        <li class="gate-item"><span class="gate-name">Momentum Scoring:</span> Eligible stocks are ranked by trend momentum (Current Price / 50-day SMA) to fill the 11-stock active watchlist.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# Phase 2
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>📊</span> Phase 2: Market Ingestion & Indicator Formulation</div>
    <ul class="gate-list">
        <li class="gate-item"><span class="gate-name">Technical Indicators:</span> Formulates key short-term metrics including 20-day SMA, RSI (14-period), 52-week drawdown, and MACD bullish crossovers.</li>
        <li class="gate-item"><span class="gate-name">Historical Sentiment tracking:</span> Computes 5-day EWMA (medium-term narrative trend) and 5-day sentiment volatility (standard deviation).</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# Phase 3
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>✍️</span> Phase 3: Sentiment Score Generation</div>
    <ul class="gate-list">
        <li class="gate-item"><span class="gate-name">Gemini Analyst Scoring:</span> Gemini-Flash scans 24h news to score conviction from -1.0 (extremely negative) to +1.0 (extremely positive).</li>
        <li class="gate-item"><span class="gate-name">No-News Decay (Weekdays):</span> If a ticker lacks recent news, prior EWMA sentiment is mathematically decayed by 30% to prevent stale signals.</li>
        <li class="gate-item"><span class="gate-name">Weekend Pause:</span> On weekends, news scraping and decay rules are paused, carrying Friday's EWMA sentiment forward unchanged.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# Phase 4
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>⚖️</span> Phase 4: Baseline Ranking & Initial Signals</div>
    <ul class="gate-list">
        <li class="gate-item"><span class="gate-name">Bottom-3 Conviction:</span> Rank 1 to 3 assets receive a LIQUIDATE signal, overridden to HOLD if 5-day EWMA sentiment is positive (>= +0.05).</li>
        <li class="gate-item"><span class="gate-name">Top-8 Conviction:</span> Rank 4 to 11 assets receive a STRONG BUY signal if raw sentiment is > 0.2, otherwise they receive a HOLD signal.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# Phase 5
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>🧠</span> Phase 5: Multi-Agent Portfolio Debate (The Critic Loop)</div>
    <ul class="gate-list">
        <li class="gate-item"><span class="gate-name">Portfolio Sizing Rules:</span> Target maximum of 3 active equity holdings at 30% weight each, leaving a 10% cash buffer, fallback to TLT if defensive.</li>
        <li class="gate-item"><span class="gate-name">Path A (Value/Dip Entry):</span> Requires drawdown >= 10% from 52-week high, bullish EWMA sentiment > 0.1, and low sentiment volatility (<= 0.4).</li>
        <li class="gate-item"><span class="gate-name">Path B (Momentum Breakout):</span> Bypasses drawdown and volatility checks for stocks hitting 20-day highs with MACD bullish crosses.</li>
        <li class="gate-item"><span class="gate-name">Core Guardrails:</span> Enforces a minimum 21-day holding period (unless EWMA < -0.5) and rejects non-Treasury buys if Forward P/E exceeds 80.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# Phase 6
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>⚡</span> Phase 6: Order Sizing & Execution Guards</div>
    <ul class="gate-list">
        <li class="gate-item"><span class="gate-name">Tolerance Band Filter:</span> Skip trades where the allocation adjustment is within +/- 3% of total equity, unless initiating or fully liquidating.</li>
        <li class="gate-item"><span class="gate-name">Buying Power Guard:</span> Prevents account overdrafts by maintaining a post-execution cash reserve of at least 5% of total equity.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

st.info("💡 Navigate back to the **Dashboard** using the sidebar on the left.")
