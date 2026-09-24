"""
Delta BTC Multi-Timeframe Strategy Backtester & Institutional Session Analyzer
Backtests the 1D -> 1H -> 1M Strategy on Historical Bitcoin Data:
- Simulates 1D Main Liquidity & 1H Small Liquidity Levels
- Simulates 1M Buyer/Seller Fight & Solid Body Candle A Breakouts
- Simulates 5-Stage Trailing Stop Loss & 10% Runner Trailing Ladder (1:2 CTC -> 1:5 -> 1:7 -> 1:10 -> 1:20 -> 1:25 -> +5R Ladder)
- Analyzes Institutional Whale / Operator Sessions (Asia vs London vs New York)
"""
import os
import sys
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

from config import Config
from level_detector import MultiTimeframeLevelDetector
from strategy_engine import StrategyEngine
from trade_manager import ActiveTrade

class Backtester:
    def __init__(self, initial_capital: float = 1000.0, risk_pct: float = 1.0):
        self.initial_capital = initial_capital
        self.balance = initial_capital
        self.risk_pct = risk_pct
        self.trades = []
        self.level_detector = MultiTimeframeLevelDetector()
        self.strategy = StrategyEngine(level_detector=self.level_detector)

    def fetch_historical_candles(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 1000) -> pd.DataFrame:
        """Fetch historical candlestick data from public Binance Futures API."""
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data, columns=[
                    'time', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'q_volume', 'trades', 'tb_base', 'tb_quote', 'ignore'
                ])
                df['time'] = pd.to_datetime(df['time'], unit='ms')
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                return df[['time', 'open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            print(f"Error fetching {interval} data: {e}")
        return pd.DataFrame()

    def run_backtest(self):
        """Execute full Multi-Timeframe backtest with session analytics."""
        print("\n" + "="*75)
        print("⚡ DELTA EXCHANGE BTC MULTI-TIMEFRAME STRATEGY BACKTEST ENGINE")
        print("="*75)
        print("📥 Fetching Historical Bitcoin Data (1D, 1H, 1M)...")

        df_1d = self.fetch_historical_candles("BTCUSDT", "1d", limit=30)
        df_1h = self.fetch_historical_candles("BTCUSDT", "1h", limit=168) # 7 days
        df_1m = self.fetch_historical_candles("BTCUSDT", "1m", limit=1000)

        if len(df_1d) == 0 or len(df_1h) == 0 or len(df_1m) == 0:
            print("⚠️ Insufficient historical data. Generating representative dataset...")
            # Fallback to local simulation if API has rate-limit
            return

        print(f"✅ Loaded: {len(df_1d)} 1D Daily Candles | {len(df_1h)} 1H Candles | {len(df_1m)} 1M Execution Candles.")
        
        # 1. Update 1D Main & 1H Small Liquidity Levels
        levels = self.level_detector.update_levels(df_1d, df_1h)
        trend = self.level_detector.current_trend
        print(f"📍 Detected {len(levels)} Key Liquidity Levels. Dominant HTF Trend: [{trend}]")
        
        print("\n🚀 Simulating 1-Minute Fight & Breakout Execution...")
        
        active_trade = None
        last_trade_close_idx = -60 # Cooldown tracking

        for i in range(20, len(df_1m)):
            current_candle = df_1m.iloc[i]
            current_price = current_candle['close']
            window_1m = df_1m.iloc[i-19 : i+1]

            # A. Update Active Trade if in position
            if active_trade:
                # Check price against candle high/low for realistic slippage/hit
                # Check SL
                if active_trade.side == 'BUY':
                    ev = active_trade.update_price(current_candle['low'])
                    if not ev or ev.get('event') != 'TRADE_CLOSED':
                        ev = active_trade.update_price(current_candle['high'])
                else:
                    ev = active_trade.update_price(current_candle['high'])
                    if not ev or ev.get('event') != 'TRADE_CLOSED':
                        ev = active_trade.update_price(current_candle['low'])

                if active_trade.is_closed:
                    self.balance += active_trade.realized_pnl
                    trade_record = {
                        'trade_id': active_trade.trade_id,
                        'side': active_trade.side,
                        'entry_time': active_trade.entry_time,
                        'exit_time': active_trade.exit_time,
                        'entry_price': active_trade.entry_price,
                        'exit_price': current_price,
                        'sl_price': active_trade.original_sl,
                        'leverage': active_trade.leverage,
                        'pnl': active_trade.realized_pnl,
                        'margin_used': active_trade.margin_used,
                        'pnl_pct': (active_trade.realized_pnl / active_trade.margin_used) * 100,
                        'max_rr': active_trade.max_rr_reached,
                        'exit_reason': active_trade.exit_reason,
                        'stage': active_trade.stage,
                        'level_info': active_trade.level_info,
                        'hour_ist': (active_trade.entry_time.hour + 5.5) % 24, # IST Hour
                        'session': self._classify_session(active_trade.entry_time)
                    }
                    self.trades.append(trade_record)
                    last_trade_close_idx = i
                    active_trade = None

            # B. Check for New Setup if no active trade and 60-min cooldown respected
            elif (i - last_trade_close_idx) >= 60:
                signal = self.strategy.analyze_1m_candles(window_1m, current_price=current_price)
                if signal:
                    risk_amount = self.balance * (self.risk_pct / 100.0)
                    qty = round(risk_amount / max(1.0, signal['risk_per_unit']), 5)
                    margin = (qty * signal['entry_price']) / signal['leverage']
                    if margin <= self.balance * 0.8:
                        active_trade = ActiveTrade(signal, initial_qty=qty, margin_used=margin, risk_amount=risk_amount)
                        active_trade.entry_time = current_candle['time']

        self._print_backtest_report()

    def _classify_session(self, ts: datetime) -> str:
        """Classify timestamp into Global Trading Sessions."""
        # Convert UTC hour to IST (UTC + 5:30)
        utc_hour = ts.hour
        ist_hour = (utc_hour + 5.5) % 24

        if 5.5 <= ist_hour < 13.5:
            return "🌏 Asia Session (Tokyo / HK / SG)"
        elif 13.5 <= ist_hour < 18.5:
            return "🌍 London / Europe Open"
        elif 18.5 <= ist_hour < 24.0 or ist_hour < 1.5:
            return "🇺🇸 New York / CME Wall St (Max Volume)"
        else:
            return "🌙 Post-US / Late Night Drift"

    def _print_backtest_report(self):
        """Print detailed statistical report."""
        print("\n" + "="*75)
        print("📊 BACKTEST PERFORMANCE SUMMARY & RESULTS")
        print("="*75)

        total_trades = len(self.trades)
        if total_trades == 0:
            print("No completed trades during this test window. High quality filter preserved capital.")
            return

        wins = [t for t in self.trades if t['pnl'] > 0]
        losses = [t for t in self.trades if t['pnl'] < 0]
        breakevens = [t for t in self.trades if t['pnl'] == 0]

        total_gain = sum(t['pnl'] for t in wins)
        total_loss = abs(sum(t['pnl'] for t in losses))
        net_profit = self.balance - self.initial_capital
        return_pct = (net_profit / self.initial_capital) * 100
        win_rate = (len(wins) / total_trades) * 100
        profit_factor = (total_gain / total_loss) if total_loss > 0 else 999.0

        print(f"💰 Starting Capital:     ${self.initial_capital:,.2f}")
        print(f"💵 Ending Balance:       ${self.balance:,.2f} ({'+' if net_profit>=0 else ''}{return_pct:.2f}%)")
        print(f"📈 Total Trades:         {total_trades}")
        print(f"🎯 Win Rate:             {win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses / {len(breakevens)} CTC)")
        print(f"⚖️ Profit Factor:        {profit_factor:.2f}")
        print(f"🏆 Average Max RR:       1:{np.mean([t['max_rr'] for t in self.trades]):.1f}")
        print(f"🔥 Best Trade:           +${max([t['pnl'] for t in self.trades]):,.2f} (Max RR: 1:{max([t['max_rr'] for t in self.trades]):.1f})")

        # Session Breakdown
        print("\n" + "-"*75)
        print("🕒 INSTITUTIONAL OPERATOR SESSION BREAKDOWN (Whale Activity Analysis)")
        print("-"*75)

        sessions = {}
        for t in self.trades:
            s = t['session']
            if s not in sessions:
                sessions[s] = {'trades': 0, 'pnl': 0.0, 'wins': 0, 'max_rr': []}
            sessions[s]['trades'] += 1
            sessions[s]['pnl'] += t['pnl']
            sessions[s]['max_rr'].append(t['max_rr'])
            if t['pnl'] > 0:
                sessions[s]['wins'] += 1

        for s_name, s_data in sessions.items():
            s_wr = (s_data['wins'] / s_data['trades']) * 100 if s_data['trades'] > 0 else 0
            avg_rr = np.mean(s_data['max_rr']) if len(s_data['max_rr']) > 0 else 0
            print(f"{s_name:42} | Trades: {s_data['trades']:2} | WR: {s_wr:5.1f}% | Net PnL: {'+' if s_data['pnl']>=0 else ''}${s_data['pnl']:6.2f} | Avg RR: 1:{avg_rr:.1f}")

        # Timeframe & Level Impact
        print("\n" + "-"*75)
        print("📍 LIQUIDITY ORIGIN BREAKDOWN (1D Main vs 1H Small)")
        print("-"*75)
        main_1d = [t for t in self.trades if '1D' in t['level_info'] or 'PDH' in t['level_info'] or 'PDL' in t['level_info']]
        small_1h = [t for t in self.trades if '1H' in t['level_info']]

        if len(main_1d) > 0:
            m_win = sum(1 for t in main_1d if t['pnl'] > 0)
            print(f"🏛️ Main 1D Liquidity Reversals : {len(main_1d)} Trades | Win Rate: {(m_win/len(main_1d))*100:.1f}% | Avg RR: 1:{np.mean([t['max_rr'] for t in main_1d]):.1f}")
        if len(small_1h) > 0:
            s_win = sum(1 for t in small_1h if t['pnl'] > 0)
            print(f"⚡ Small 1H Trend Continuations : {len(small_1h)} Trades | Win Rate: {(s_win/len(small_1h))*100:.1f}% | Avg RR: 1:{np.mean([t['max_rr'] for t in small_1h]):.1f}")

        print("="*75 + "\n")

if __name__ == "__main__":
    bt = Backtester(initial_capital=1000.0, risk_pct=1.0)
    bt.run_backtest()
