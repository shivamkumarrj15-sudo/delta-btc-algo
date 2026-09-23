"""
Main Engine Runner for Delta Exchange BTC Multi-Timeframe Algo Bot
Coordinates:
- Delta Exchange live data feed (1D, 1H, 1M candles)
- Multi-Timeframe Level Detection & Updates
- Strategy Signal Generation (Fight & Candle A/B Breakout)
- Multi-Stage Trade Execution & Risk Management (1:2 CTC, 1:5 Half Out, 1:10 TP)
- Paper Trading Simulator / Live Execution
"""
import time
import sys
import os
import functools
import pandas as pd
from datetime import datetime

# Force unbuffered output and utf-8
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

print = functools.partial(print, flush=True)

from config import Config


from delta_client import DeltaClient
from level_detector import MultiTimeframeLevelDetector
from confidence_engine import ConfidenceEngine
from strategy_engine import StrategyEngine
from paper_trader import PaperTrader

def main():
    Config.display_summary()

    # Initialize components
    client = DeltaClient()
    level_detector = MultiTimeframeLevelDetector()
    conf_engine = ConfidenceEngine()
    strategy = StrategyEngine(level_detector=level_detector, confidence_engine=conf_engine)
    trader = PaperTrader()

    print("\n[INIT] Connecting to Delta Exchange and fetching Multi-Timeframe data...")
    
    # 1. Fetch 1D and 1H Historical Candles for Level Mapping
    try:
        df_1d = client.get_candles('1d', limit=30)
        df_1h = client.get_candles('1h', limit=60)
        
        if len(df_1d) > 0 and len(df_1h) > 0:
            levels = level_detector.update_levels(df_1d, df_1h)
            print(f"✅ Loaded {len(levels)} Key S/R & Liquidity Levels from 1D & 1H charts.")
            for lvl in levels[:6]:
                print(f"   • [{lvl.timeframe.upper()} {lvl.level_type}] ${lvl.price:,.2f} - {lvl.description}")
        else:
            print("⚠️ Warning: Could not fetch initial HTF candles, will retry in loop.")
    except Exception as e:
        print(f"⚠️ Error fetching HTF candles: {e}")

    last_htf_update = time.time()
    loop_count = 0

    print("\n🚀 [BOT RUNNING] Monitoring BTC 1-Minute Fight & Liquidity Breakouts (Press Ctrl+C to stop)...")
    print("-" * 75)

    while True:
        try:
            loop_count += 1
            now = datetime.now().strftime('%H:%M:%S')

            # 1. Refresh 1D and 1H Levels every 15 minutes
            if time.time() - last_htf_update > 900:
                df_1d = client.get_candles('1d', limit=30)
                df_1h = client.get_candles('1h', limit=60)
                if len(df_1d) > 0 and len(df_1h) > 0:
                    level_detector.update_levels(df_1d, df_1h)
                last_htf_update = time.time()

            # 2. Fetch Latest 1M Candles & Live Price
            df_1m = client.get_candles('1m', limit=25)
            ticker = client.get_ticker()
            
            if ticker and 'close' in ticker:
                current_price = float(ticker['close'])
            elif len(df_1m) > 0:
                current_price = float(df_1m['close'].iloc[-1])
            else:
                # Delta API fallback or wait
                time.sleep(5)
                continue

            # 3. Update Existing Active Trades
            events = trader.update_market_price(current_price)
            for event in events:
                if event['event'] == 'STAGE_1_CTC_SHIFT':
                    print(f"[{now}] 🛡️ [STAGE 1] SL moved to CTC (${event['new_sl']:,.2f}) for Trade {event['trade'].trade_id}")
                elif event['event'] == 'STAGE_2_PARTIAL_EXIT':
                    print(f"[{now}] 💰 [STAGE 2] 50% Profit Booked (+${event['partial_pnl']:.2f})! SL locked at 1:2 (${event['new_sl']:,.2f})")
                elif event['event'] == 'TRADE_CLOSED':
                    print(f"[{now}] 🏁 [TRADE CLOSED] {event['reason']} | Net PnL: ${event['pnl']:,.2f}")

            # 4. Check for New Setup Signals if no open position
            if len(trader.active_trades) == 0:
                signal = strategy.analyze_1m_candles(df_1m, current_price=current_price)
                if signal:
                    trader.execute_signal(signal)

            # 5. Print Live Status Heartbeat every 10 iterations (~30-50s)
            if loop_count % 10 == 0:
                summary = trader.get_performance_summary(current_price)
                active_str = f"Active Trade: {len(trader.active_trades)}" if trader.active_trades else "No Open Trade (Waiting for setup)"
                print(f"[{now}] BTC: ${current_price:,.2f} | Balance: ${summary['current_balance']:.2f} (Equity: ${summary['total_equity']:.2f}) | {active_str} | Win Rate: {summary['win_rate_pct']}% ({summary['total_trades']} trades)")

            # Sleep 4 seconds between poll intervals
            time.sleep(4)

        except KeyboardInterrupt:
            print("\n\n🛑 Bot stopped by user.")
            summary = trader.get_performance_summary(current_price if 'current_price' in locals() else 0)
            print("\n" + "="*50)
            print("📊 FINAL PERFORMANCE SUMMARY:")
            print(f"   Initial Balance: ${summary['initial_balance']}")
            print(f"   Final Balance:   ${summary['current_balance']}")
            print(f"   Net PnL:         ${summary['net_pnl']} ({summary['return_pct']}%)")
            print(f"   Win Rate:        {summary['win_rate_pct']}% ({summary['win_trades']}W / {summary['loss_trades']}L / {summary['breakeven_trades']}BE)")
            print(f"   Max Drawdown:    {summary['max_drawdown_pct']}%")
            print("="*50)
            break
        except Exception as e:
            print(f"[{now}] ⚠️ Error in main loop: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()
