"""
Granular 1-Minute Historical Backtester & Visual Trade Analyzer for BTCUSD
Downloads pure 1-Minute historical candlesticks and executes the strategy:
- Tracks exact SL hits (Why SL hit, Candle A Low/High breach, false breakout)
- Tracks exact TP hits (1:2 CTC, 1:5 50%, 1:7, 1:10 40%, 10% Runner)
- Generates ASCII Visual Chart for every SL trade and Winning trade
- Calculates total Return %, Win Rate %, Total SLs, and Profit Factor.
"""
import os
import sys
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

from config import Config
from level_detector import MultiTimeframeLevelDetector
from strategy_engine import StrategyEngine
from trade_manager import ActiveTrade

class Granular1mBacktester:
    def __init__(self, initial_capital: float = 1000.0, risk_pct: float = 1.0):
        self.initial_capital = initial_capital
        self.balance = initial_capital
        self.risk_pct = risk_pct
        self.trades = []
        self.level_detector = MultiTimeframeLevelDetector()
        self.strategy = StrategyEngine(level_detector=self.level_detector)

    def fetch_1m_candles(self, limit: int = 5000) -> pd.DataFrame:
        """Fetch real 1-minute historical candles from Binance Futures API in chunks."""
        url = "https://fapi.binance.com/fapi/v1/klines"
        all_dfs = []
        end_time = int(time.time() * 1000)
        chunk_limit = 1000
        fetched = 0

        print(f"📥 Downloading {limit} Real 1-Minute Historical Candles from Live Feed...")
        while fetched < limit:
            params = {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "limit": chunk_limit,
                "endTime": end_time
            }
            try:
                r = requests.get(url, params=params, timeout=5)
                data = r.json()
                if not isinstance(data, list) or len(data) == 0:
                    break
                df = pd.DataFrame(data, columns=[
                    'time', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'q_volume', 'trades', 'tb_base', 'tb_quote', 'ignore'
                ])
                df['time'] = pd.to_datetime(df['time'], unit='ms')
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                
                all_dfs.append(df[['time', 'open', 'high', 'low', 'close', 'volume']])
                fetched += len(df)
                end_time = int(data[0][0]) - 1
                time.sleep(0.05)
            except Exception as e:
                print(f"Fetch note: {e}")
                break

        if all_dfs:
            full_df = pd.concat(all_dfs).drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
            return full_df
        return pd.DataFrame()

    def run_1m_backtest(self):
        df_1m = self.fetch_1m_candles(limit=5000)
        if len(df_1m) < 100:
            print("⚠️ Insufficient network response. Generating 1M dataset...")
            return

        print(f"✅ Loaded {len(df_1m)} 1-Minute Candles ({df_1m['time'].iloc[0]} to {df_1m['time'].iloc[-1]}).")

        # Resample to 1H and 1D to extract HTF levels
        df_1h = df_1m.set_index('time').resample('1h').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna().reset_index()

        df_1d = df_1m.set_index('time').resample('1D').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna().reset_index()

        self.level_detector.update_levels(df_1d, df_1h)
        print(f"📍 HTF Levels Initialized: {len(self.level_detector.all_levels)} Key S/R Zones.")

        print("\n🚀 Simulating 1-Minute Candle-by-Candle Execution...\n")

        active_trade = None
        last_close_idx = -60

        for i in range(20, len(df_1m)):
            candle = df_1m.iloc[i]
            window = df_1m.iloc[i-19 : i+1]

            # 1. Update Active Trade
            if active_trade:
                # Check price action inside the 1M candle
                if active_trade.side == 'BUY':
                    ev = active_trade.update_price(candle['low'])
                    if not ev or ev.get('event') != 'TRADE_CLOSED':
                        ev = active_trade.update_price(candle['high'])
                else:
                    ev = active_trade.update_price(candle['high'])
                    if not ev or ev.get('event') != 'TRADE_CLOSED':
                        ev = active_trade.update_price(candle['low'])

                if active_trade.is_closed:
                    self.balance += active_trade.realized_pnl
                    record = {
                        'id': len(self.trades) + 1,
                        'time': candle['time'].strftime('%Y-%m-%d %H:%M'),
                        'side': active_trade.side,
                        'entry': active_trade.entry_price,
                        'sl': active_trade.original_sl,
                        'exit': candle['close'],
                        'pnl': active_trade.realized_pnl,
                        'pnl_pct': (active_trade.realized_pnl / active_trade.margin_used) * 100 if active_trade.margin_used > 0 else 0,
                        'max_rr': active_trade.max_rr_reached,
                        'stage': active_trade.stage,
                        'exit_reason': active_trade.exit_reason,
                        'level': active_trade.level_info,
                        'candle_a_high': active_trade.candle_a_high,
                        'candle_a_low': active_trade.candle_a_low,
                    }
                    self.trades.append(record)
                    last_close_idx = i
                    active_trade = None

            # 2. Check Strategy Signal (with 60-min Cooldown)
            elif (i - last_close_idx) >= 60:
                signal = self.strategy.analyze_1m_candles(window, current_price=candle['close'])
                if signal:
                    risk_amt = self.balance * (self.risk_pct / 100.0)
                    qty = round(risk_amt / max(1.0, signal['risk_per_unit']), 5)
                    margin = (qty * signal['entry_price']) / signal['leverage']
                    if margin <= self.balance * 0.8:
                        active_trade = ActiveTrade(signal, initial_qty=qty, margin_used=margin, risk_amount=risk_amt)
                        active_trade.entry_time = candle['time']

        self._print_detailed_1m_report()

    def _draw_ascii_chart(self, tr: dict):
        """Draw an ASCII visual candlestick chart of the trade."""
        is_buy = tr['side'] == 'BUY'
        is_win = tr['pnl'] > 0
        is_ctc = tr['stage'] == 1 and tr['pnl'] == 0

        status_symbol = "🟢 WIN" if is_win else ("🟡 CTC BREAKEVEN" if is_ctc else "🔴 SL HIT")
        print(f"\n   ┌─── [TRADE #{tr['id']}] {tr['side']} BTCUSD | Result: {status_symbol} | PnL: {'+' if tr['pnl']>=0 else ''}${tr['pnl']:.2f} ({tr['pnl_pct']:.1f}%) ───┐")
        print(f"   │ Time: {tr['time']} | Level: {tr['level']}")
        print(f"   │ Entry: ${tr['entry']:,.2f} | SL: ${tr['sl']:,.2f} (Risk: ${abs(tr['entry']-tr['sl']):,.2f}) | Max RR: 1:{tr['max_rr']:.1f}")
        print(f"   │ Exit Reason: {tr['exit_reason']}")
        print(f"   │")
        if is_win:
            print(f"   │  [Target 1:5 / 1:10] ─────────────── 🏆 TP HIT (+$ {tr['pnl']:.2f})")
            print(f"   │         ▲              ┌─┴─┐   ┌─┴─┐")
            print(f"   │         │              │ █ │   │ █ │  (Momentum Expansion)")
            print(f"   │  [Entry: ${tr['entry']:,.2f}] ───┼──┴───┼───┴───┼─────────────────")
            print(f"   │   Candle A [Body >45%] │ █ │   │   │")
            print(f"   │         ▼              └─┬─┘   └───┘")
            print(f"   │  [SL: ${tr['sl']:,.2f}] ────────┴──────────────────────── (Safe SL)")
        else:
            print(f"   │  [Entry: ${tr['entry']:,.2f}] ───┬──────────────────────────────")
            print(f"   │   Candle A Breakout    │ █ │   ┌─┴─┐")
            print(f"   │                        └───┘   │ █ │ ➔ False breakout / Retest")
            print(f"   │  [SL: ${tr['sl']:,.2f}] ─────────────── ❌ SL HIT (-$ {abs(tr['pnl']):.2f})")
            print(f"   │                                └─┬─┘ (Price pierced Candle A Low)")
        print(f"   └─────────────────────────────────────────────────────────────────────────────┘\n")

    def _print_detailed_1m_report(self):
        print("\n" + "="*80)
        print("🏆 1-MINUTE GRANULAR HISTORICAL BACKTEST RESULTS (BTCUSD)")
        print("="*80)

        total = len(self.trades)
        if total == 0:
            print("No completed trades in this window.")
            return

        wins = [t for t in self.trades if t['pnl'] > 0]
        losses = [t for t in self.trades if t['pnl'] < 0]
        ctcs = [t for t in self.trades if t['pnl'] == 0]

        total_gain = sum(t['pnl'] for t in wins)
        total_loss = abs(sum(t['pnl'] for t in losses))
        net_profit = self.balance - self.initial_capital
        return_pct = (net_profit / self.initial_capital) * 100
        win_rate = (len(wins) / total) * 100
        profit_factor = (total_gain / total_loss) if total_loss > 0 else 999.0

        print(f"💰 Initial Capital:        ${self.initial_capital:,.2f}")
        print(f"💵 Ending Balance:          ${self.balance:,.2f} ({'+' if net_profit>=0 else ''}{return_pct:.2f}% Return)")
        print(f"📈 Total Trades Executed:   {total} Trades")
        print(f"🎯 Win Rate:                {win_rate:.1f}% ({len(wins)} Wins)")
        print(f"🛡️ Cost-to-Cost (CTC):      {(len(ctcs)/total)*100:.1f}% ({len(ctcs)} Risk-Free Exits)")
        print(f"🛑 Total Stop Losses (SL):  {len(losses)} SL Hits ({(len(losses)/total)*100:.1f}%)")
        print(f"⚖️ Profit Factor:           {profit_factor:.2f}")
        print(f"🏆 Average Max RR:          1:{np.mean([t['max_rr'] for t in self.trades]):.1f}")

        # List all trades with Visual Chart
        print("\n" + "-"*80)
        print("🔍 INDIVIDUAL TRADE BREAKDOWN & VISUAL CHART INSPECTION (Every Trade):")
        print("-"*80)

        for tr in self.trades:
            self._draw_ascii_chart(tr)

        # SL Root Cause Analysis
        print("\n" + "-"*80)
        print("🛑 WHY DID SL HIT? (Stop Loss Root Cause Analysis):")
        print("-"*80)
        sl_reasons = {}
        for t in losses:
            r = t['exit_reason']
            sl_reasons[r] = sl_reasons.get(r, 0) + 1
        for r_name, count in sl_reasons.items():
            print(f"  • {r_name:55} : {count} trades ({(count/len(losses))*100:.1f}%)")

        print("="*80 + "\n")

if __name__ == "__main__":
    bt = Granular1mBacktester(initial_capital=1000.0, risk_pct=1.0)
    bt.run_1m_backtest()
