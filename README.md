# ⚡ Delta Exchange BTC Multi-Timeframe Algo & Trading Terminal

An automated institutional algorithmic trading terminal and bot for Bitcoin perpetual futures (`BTCUSD`) on **Delta Exchange** (India & Global).

Built with **Multi-Timeframe Strategy Execution (1D ➔ 1H ➔ 1M)**, **Dynamic Leverage Engine (20x - 35x)**, **Continuous Trailing Stop Loss & Partial Exit Ladder**, and a real-time **TradingView Web Terminal**.

---

## 🎯 Core Strategy & Architecture

### 1. Multi-Timeframe Hierarchy
- **1-Day (1D) Higher Timeframe**: Identifies **Main Liquidity** (PDH - Previous Day High, PDL - Previous Day Low, PDC - Previous Day Close, 1D Swing Points).
- **1-Hour (1H) Higher Timeframe**: Identifies **Small Liquidity** (1H Swing Highs & Lows, intermediate S/R zones) and calculates market trend (`BULLISH`, `BEARISH`, `SIDEWAYS`).
- **1-Minute (1M) Execution**: Scans for the **Buyer vs Seller Fight / Tug-of-war** at key liquidity levels, validates **Solid Body Candle A (>45% Body Ratio)**, and triggers instant execution on **Candle B breakout**.

---

### 2. Trend & Reversal Rules
- **Small Liquidity (1H)**: Only trades in the direction of the dominant trend (Bullish ➔ BUY only at 1H Support; Bearish ➔ SELL only at 1H Resistance).
- **Main 1D Liquidity**: Major turning point levels allow and prioritize **Counter-Trend Reversals** after multi-wave buyer/seller exhaustion!

---

### 3. Continuous 5-Stage Trailing & Runner Ladder
| Stage | Risk:Reward (RR) | Action / Trailing Update | Profit & Risk State |
| :--- | :--- | :--- | :--- |
| **Stage 1** | **1:2 RR** | SL shifts to **Cost-to-Cost (CTC / Breakeven)** | Zero Risk Free Trade |
| **Stage 2** | **1:5 RR** | **50% Quantity Exit (Half Banked)** & SL locks at **1:2 RR** | +2R Profit Locked |
| **Stage 3** | **1:7 RR** | SL shifts to **1:5 RR** | +5R Profit Locked |
| **Stage 4** | **1:10 RR** | **40% Quantity Exit (Total 90% Banked)** & SL shifts to **1:7 RR** | **10% Runner Trailing** |
| **Stage 5** | **1:20 RR** | 10% Runner SL shifts to **1:15 RR** | +15R Locked |
| **Stage 6** | **1:25 RR** | 10% Runner SL shifts to **1:20 RR** | +20R Locked |
| **Stage 7+**| **1:30+ RR** | Har +5R par SL **+5R step-by-step** trail hota rahega | Infinite Runner Ride |

---

## 🛡️ Risk Management
- **Account Balance**: Virtual $1,000 Paper Trading Simulator.
- **Risk Per Trade**: Strictly 1% ($10 risk per trade).
- **Daily Max Risk**: 2% daily loss limit (Automatic circuit breaker).
- **Daily Max Trades**: Maximum 4 trades per day.
- **Trade Cooldown**: Mandatory 1-Hour (60 min) cooldown after any trade closes.

---

## 💻 Installation & Quickstart

### 1. Clone the repository
```bash
git clone https://github.com/<YOUR-USERNAME>/delta-btc-algo.git
cd delta-btc-algo
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
Copy `.env.example` to `.env`:
```bash
copy .env.example .env
```
Set your Delta Exchange API credentials:
```env
DELTA_API_KEY=your_api_key_here
DELTA_API_SECRET=your_api_secret_here
DELTA_ENV=india
PAPER_TRADING=true
INITIAL_PAPER_BALANCE=1000.0
```

### 4. Run the Terminal Server
```bash
python web_server.py
```
Open **`http://localhost:8501`** in your browser to access the live trading terminal!

---

## 🧪 Unit Tests
Run the test suite to verify level detection, breakout execution, and the 5-stage trailing runner ladder:
```bash
python test_bot.py
```

---

## 🌲 Pine Script Indicator
Copy the source code from `delta_algo_indicator.pine` and paste it into the **TradingView Pine Editor** to overlay all levels and breakout arrows directly on Delta Exchange or TradingView charts!
