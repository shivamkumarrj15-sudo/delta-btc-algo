"""
Interactive Streamlit Web Dashboard for Delta Exchange BTC Algo Bot
Run with: streamlit run dashboard.py
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
from datetime import datetime
from config import Config
from delta_client import DeltaClient
from level_detector import MultiTimeframeLevelDetector
from paper_trader import PaperTrader

st.set_page_config(
    page_title="Delta BTC Multi-Timeframe Algo Bot",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for dark crypto trading terminal aesthetic
st.markdown("""
<style>
    .main { background-color: #0b0e14; }
    .stMetric { background-color: #151924; border-radius: 8px; padding: 12px; border: 1px solid #242b3d; }
    .card { background-color: #151924; border-radius: 8px; padding: 18px; border: 1px solid #242b3d; margin-bottom: 15px; }
    h1, h2, h3, h4 { color: #f0f4f8; }
</style>
""", unsafe_allow_html=True)

# Initialize
client = DeltaClient()
level_detector = MultiTimeframeLevelDetector()
trader = PaperTrader()

# Sidebar
st.sidebar.title("⚡ Delta BTC Algo Engine")
st.sidebar.markdown(f"**Region:** Delta Exchange ({Config.REGION.upper()})")
st.sidebar.markdown(f"**Symbol:** `{Config.SYMBOL}`")
st.sidebar.markdown(f"**Mode:** `{'PAPER TRADING ($1,000)' if Config.PAPER_TRADING else 'REAL MONEY ⚠️'}`")
st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 Strategy Rules")
st.sidebar.markdown("""
- **1D / 1H:** HTF S/R & Liquidity Zones
- **1M:** Fight & Rejection at Level
- **Candle A:** Solid Body Dominance Candle
- **Candle B:** High Breakout Entry
- **SL:** Low of Candle A
- **Leverage:** 20x - 35x Dynamic
- **Exits:**
  - 🚀 **1:2 RR:** SL $\\rightarrow$ Cost-to-Cost (CTC)
  - 💰 **1:5 RR:** Exit 50% & SL $\\rightarrow$ 1:2
  - 🎯 **1:10 RR:** Full Exit (Remaining 50%)
""")

# Top Header
st.title("⚡ BTC/USD Multi-Timeframe Trading Terminal")

# Fetch latest market data
try:
    df_1d = client.get_candles('1d', limit=20)
    df_1h = client.get_candles('1h', limit=40)
    df_1m = client.get_candles('1m', limit=40)
    
    if len(df_1d) > 0 and len(df_1h) > 0:
        level_detector.update_levels(df_1d, df_1h)
except Exception as e:
    st.error(f"Error connecting to Delta Exchange API: {e}")
    df_1m = pd.DataFrame()

current_price = float(df_1m['close'].iloc[-1]) if len(df_1m) > 0 else 65000.0
summary = trader.get_performance_summary(current_price)

# Top Metrics Row
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Total Equity", f"${summary['total_equity']:,.2f}", delta=f"{summary['net_pnl']:+,.2f} ({summary['return_pct']}%)")
with col2:
    st.metric("Win Rate", f"{summary['win_rate_pct']}%", f"{summary['win_trades']}W / {summary['loss_trades']}L / {summary['breakeven_trades']}BE")
with col3:
    st.metric("Profit Factor", f"{summary['profit_factor']:.2f}")
with col4:
    st.metric("Max Drawdown", f"{summary['max_drawdown_pct']}%")
with col5:
    st.metric("Live BTC Price", f"${current_price:,.2f}")

# Main Chart & Active Trade Section
st.markdown("---")
chart_col, trade_col = st.columns([2.2, 1.0])

with chart_col:
    st.subheader("📊 1-Minute Live Candlestick & HTF Key Levels")
    if len(df_1m) > 0:
        fig = go.Figure()
        
        # Candlestick Trace
        fig.add_trace(go.Candlestick(
            x=df_1m['time'],
            open=df_1m['open'],
            high=df_1m['high'],
            low=df_1m['low'],
            close=df_1m['close'],
            name="1M BTC Candles",
            increasing_line_color='#00c087',
            decreasing_line_color='#ff3b69'
        ))

        # Add HTF Key Level Lines
        for lvl in level_detector.all_levels:
            # Show levels close to current price range
            if abs(lvl.price - current_price) / current_price < 0.03:
                line_color = '#00c087' if 'SUPPORT' in lvl.level_type or 'PDL' in lvl.description else '#ff3b69'
                fig.add_hline(
                    y=lvl.price,
                    line_dash="dot",
                    line_color=line_color,
                    line_width=1.5,
                    annotation_text=f"{lvl.description} (${lvl.price:,.0f})",
                    annotation_position="top left",
                    annotation_font_color=line_color
                )

        fig.update_layout(
            height=500,
            template="plotly_dark",
            margin=dict(l=10, r=10, t=20, b=20),
            xaxis_rangeslider_visible=False,
            yaxis=dict(side="right")
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Awaiting live candles from Delta Exchange...")

with trade_col:
    st.subheader("⚡ Live Trade Status")
    
    if len(trader.active_trades) > 0:
        for trade in trader.active_trades:
            unrealized_pnl = trade.get_unrealized_pnl(current_price)
            pnl_color = "#00c087" if unrealized_pnl >= 0 else "#ff3b69"
            
            st.markdown(f"""
            <div class="card">
                <h3 style="margin:0; color:{pnl_color};">{trade.side} BTC (${unrealized_pnl:+,.2f})</h3>
                <p style="color:#8b949e; font-size:12px;">ID: {trade.trade_id} | Leverage: {trade.leverage}x | Qty: {trade.remaining_qty} BTC</p>
                <table style="width:100%; font-size:13px; color:#c9d1d9;">
                    <tr><td><b>Entry:</b></td><td>${trade.entry_price:,.2f}</td></tr>
                    <tr><td><b>Current SL:</b></td><td><span style="color:#ff3b69;">${trade.current_sl:,.2f}</span></td></tr>
                    <tr><td><b>1:2 RR (CTC):</b></td><td>${trade.stage_1_tp:,.2f} {'✅ (Hit)' if trade.stage >= 1 else '⏳'}</td></tr>
                    <tr><td><b>1:5 RR (50%):</b></td><td>${trade.stage_2_tp:,.2f} {'✅ (Hit)' if trade.stage >= 2 else '⏳'}</td></tr>
                    <tr><td><b>1:10 RR (Full):</b></td><td>${trade.stage_3_tp:,.2f} {'✅ (Hit)' if trade.stage >= 3 else '⏳'}</td></tr>
                </table>
            </div>
            """, unsafe_allow_html=True)
            
            # Progress bar for stages
            stage_pct = [0.1, 0.35, 0.70, 1.0][min(3, trade.stage)]
            stage_label = ["Stage 0: Active (SL at Candle A)", "Stage 1: 1:2 Hit (SL @ CTC)", "Stage 2: 1:5 Hit (50% Banked, SL @ 1:2)", "Stage 3: 1:10 Target Done"][min(3, trade.stage)]
            st.progress(stage_pct, text=stage_label)
    else:
        st.markdown("""
        <div class="card" style="text-align:center; padding:30px;">
            <p style="font-size:16px; color:#8b949e; margin:0;">🔍 <b>Scanning for Strategy Setup...</b></p>
            <p style="font-size:12px; color:#57606a;">Waiting for price to reach 1D/1H Key Level $\\rightarrow$ Buyer vs Seller Fight $\\rightarrow$ Candle A Body $\\rightarrow$ Candle B Breakout</p>
        </div>
        """, unsafe_allow_html=True)

# Closed Trades History
st.markdown("---")
st.subheader("📜 Trade History & Performance Logs")
if len(trader.closed_trades) > 0:
    history_df = pd.DataFrame(trader.closed_trades)
    display_cols = ['trade_id', 'side', 'entry_price', 'leverage', 'realized_pnl', 'pnl_percent', 'exit_reason', 'entry_time', 'exit_time']
    avail_cols = [c for c in display_cols if c in history_df.columns]
    st.dataframe(history_df[avail_cols], use_container_width=True)
else:
    st.caption("No closed trades yet in this session.")
