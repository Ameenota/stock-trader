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
st.markdown("<p class='subtitle'>A concise reference for the 5-phase quantitative and qualitative engine determining our daily allocations.</p>", unsafe_allow_html=True)

# Phase 1
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>🔍</span> Phase 1: Watchlist Screening (Pre-Filtering & Momentum)</div>
    <ul class="gate-list">
        <li class="gate-item">We download stock data from <strong>yfinance</strong> and use the following indicators (<strong>Owned Position status, 21-day cool-down, 50-day SMA, and 14-day RSI</strong>) to create our initial filter of stocks to pass to the next gate.</li>
        <li class="gate-item"><strong>Example:</strong> If a non-owned stock is trading below its 50-day SMA and has an RSI of 30, it is not picked; if it is trading above its 50-day SMA (or has a deeply oversold RSI < 25), it passes.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# Phase 2
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>📊</span> Phase 2: Technical Formulation</div>
    <ul class="gate-list">
        <li class="gate-item">We calculate additional technical indicators (such as 20-day SMA, 52-week drawdown, and MACD) for the shortlisted stocks. <strong>No filtering is performed at this phase.</strong></li>
    </ul>
</div>
""", unsafe_allow_html=True)

# Phase 3
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>✍️</span> Phase 3: Sentiment Scoring & Baseline Ranking</div>
    <ul class="gate-list">
        <li class="gate-item"><span class="gate-name">Gemini Analyst Scoring:</span> Gemini-Flash scans 24h news to score conviction from -1.0 (extremely negative) to +1.0 (extremely positive). Tickers with no news on weekdays are decayed by 30%.</li>
        <li class="gate-item"><span class="gate-name">EWMA & Volatility Formulation:</span> Combines today's score with the past 4 days of history to calculate the 5-day EWMA and 5-day sentiment volatility.</li>
        <li class="gate-item"><span class="gate-name">Baseline Signals:</span> Ranks the 11 assets by raw sentiment. The bottom 3 are marked as LIQUIDATE (unless EWMA >= +0.05, which overrides to HOLD), and the top 8 are marked as STRONG BUY (if raw score > 0.2) or HOLD.</li>
        <li class="gate-item"><span class="gate-name">Weekend Pause:</span> News scraping and decay rules are paused on weekends, carrying Friday's EWMA sentiment forward.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# Phase 4
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>🧠</span> Phase 4: Multi-Agent Portfolio Debate (The Critic Loop)</div>
    <ul class="gate-list">
        <li class="gate-item"><span class="gate-name">Portfolio Sizing Rules:</span> Target maximum of 3 active equity holdings at 30% weight each, leaving a 10% cash buffer.</li>
        <li class="gate-item"><span class="gate-name">Path A (Value/Dip Entry):</span> Requires drawdown >= 10% from 52-week high, bullish EWMA sentiment > 0.1, and low sentiment volatility (<= 0.4).</li>
        <li class="gate-item"><span class="gate-name">Path B (Momentum Breakout):</span> Bypasses drawdown and volatility checks for stocks hitting 20-day highs with MACD bullish crosses.</li>
        <li class="gate-item"><span class="gate-name">Core Guardrails:</span> Enforces a minimum 21-day holding period (unless EWMA < -0.5) and rejects buys if Forward P/E exceeds 80. We fall back to treasury bonds when the market is bearish.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

# Phase 5
st.markdown("""
<div class="phase-card">
    <div class="phase-title"><span>⚡</span> Phase 5: Order Sizing & Execution Guards</div>
    <ul class="gate-list">
        <li class="gate-item"><span class="gate-name">Tolerance Band Filter:</span> Skip trades where the allocation adjustment is within +/- 3% of total equity, unless initiating or fully liquidating.</li>
        <li class="gate-item"><span class="gate-name">Buying Power Guard:</span> Prevents account overdrafts by maintaining a post-execution cash reserve of at least 5% of total equity.</li>
    </ul>
</div>
""", unsafe_allow_html=True)

st.info("💡 Navigate back to the **Dashboard** using the sidebar on the left.")
