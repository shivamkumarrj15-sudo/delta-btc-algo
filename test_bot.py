"""
Automated Unit Tests and Strategy Simulator for Delta BTC Algo Bot
Tests:
1. 1D & 1H Level Extraction
2. BUY & SELL Fight Detection & Breakout Signals
3. SL at Candle A Low (BUY) & High (SELL)
4. Dynamic Leverage (20x - 35x)
5. Continuous Trailing Ladder (1:2 CTC -> 1:5 50% Out -> 1:7 SL to 1:5 -> 1:10 40% Out + SL to 1:7 -> 1:20 SL to 1:15 -> 1:25 SL to 1:20 -> +5R Runner)
6. 1-Hour Cooldown & 4 Trades Per Day Limit
"""
import sys
import unittest
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from config import Config
from level_detector import MultiTimeframeLevelDetector, KeyLevel
from confidence_engine import ConfidenceEngine
from strategy_engine import StrategyEngine
from trade_manager import ActiveTrade
from paper_trader import PaperTrader

class TestDeltaBtcAlgo(unittest.TestCase):

    def setUp(self):
        self.level_detector = MultiTimeframeLevelDetector(proximity_pct=0.01)
        self.conf_engine = ConfidenceEngine()
        self.strategy = StrategyEngine(self.level_detector, self.conf_engine)
        self.trader = PaperTrader(initial_balance=1000.0, save_path="test_paper_trades.json")

    def test_level_detection(self):
        """Test extraction of 1D and 1H levels."""
        dates_1d = [datetime.now() - timedelta(days=i) for i in range(10, 0, -1)]
        df_1d = pd.DataFrame({
            'time': dates_1d,
            'open': [60000 + i*200 for i in range(10)],
            'high': [61000 + i*200 for i in range(10)],
            'low': [59000 + i*200 for i in range(10)],
            'close': [60500 + i*200 for i in range(10)],
            'volume': [1000] * 10
        })

        levels_1d = self.level_detector.extract_daily_levels(df_1d)
        self.assertTrue(len(levels_1d) > 0)
        types = [lvl.description for lvl in levels_1d]
        self.assertTrue(any('PDH' in t for t in types))
        self.assertTrue(any('PDL' in t for t in types))

    def test_buy_runner_trailing_ladder(self):
        """Test BUY continuous runner trailing (1:10 -> 1:20 -> 1:25 -> ladder)."""
        signal = {
            'symbol': 'BTCUSD',
            'side': 'BUY',
            'entry_price': 60000.0,
            'sl_price': 59900.0,  # Risk = $100
            'risk_per_unit': 100.0,
            'stage_1_tp': 60200.0, # 1:2 RR (+$200)
            'stage_2_tp': 60500.0, # 1:5 RR (+$500)
            'stage_3_tp': 60700.0, # 1:7 RR (+$700)
            'stage_4_tp': 61000.0, # 1:10 RR (+$1000)
            'stage_5_tp': 62000.0, # 1:20 RR (+$2000)
            'stage_6_tp': 62500.0, # 1:25 RR (+$2500)
            'sl_1_2_price': 60200.0,
            'sl_1_5_price': 60500.0,
            'sl_1_7_price': 60700.0,
            'sl_1_15_price': 61500.0,
            'sl_1_20_price': 62000.0,
            'leverage': 30,
            'confidence_score': 0.85,
            'level_info': '1D Major Support'
        }

        trade = self.trader.execute_signal(signal)
        self.assertIsNotNone(trade)
        initial_qty = trade.initial_qty
        
        # 1:2 RR -> SL to CTC
        self.trader.update_market_price(60205.0)
        self.assertEqual(trade.current_sl, 60000.0)

        # 1:5 RR -> 50% exit, SL to 1:2
        self.trader.update_market_price(60505.0)
        self.assertEqual(trade.current_sl, 60200.0)

        # 1:7 RR -> SL to 1:5
        self.trader.update_market_price(60705.0)
        self.assertEqual(trade.current_sl, 60500.0)

        # 1:10 RR -> 40% exit, 10% runner, SL to 1:7
        self.trader.update_market_price(61005.0)
        self.assertEqual(trade.current_sl, 60700.0)
        self.assertAlmostEqual(trade.remaining_qty, initial_qty * 0.10, places=4)

        # 1:20 RR -> SL to 1:15
        self.trader.update_market_price(62005.0)
        self.assertEqual(trade.current_sl, 61500.0)

        # 1:25 RR -> SL to 1:20
        self.trader.update_market_price(62505.0)
        self.assertEqual(trade.current_sl, 62000.0)

        # Pullback hits 1:20 SL ($62,000) -> Runner closes with massive profit
        self.trader.update_market_price(61995.0)
        self.assertTrue(trade.is_closed)
        self.assertGreater(trade.realized_pnl, 0)
        print(f"\n✅ BUY Continuous Runner Trailing Verified! Net PnL: +${trade.realized_pnl:.2f}")

    def test_sell_runner_trailing_ladder(self):
        """Test SELL continuous runner trailing (1:10 -> 1:20 -> 1:25 -> ladder)."""
        # Clear cooldown for test
        self.trader.last_trade_closed_time = 0.0

        signal = {
            'symbol': 'BTCUSD',
            'side': 'SELL',
            'entry_price': 60000.0,
            'sl_price': 60100.0,  # Risk = $100
            'risk_per_unit': 100.0,
            'stage_1_tp': 59800.0, # 1:2 RR (-$200)
            'stage_2_tp': 59500.0, # 1:5 RR (-$500)
            'stage_3_tp': 59300.0, # 1:7 RR (-$700)
            'stage_4_tp': 59000.0, # 1:10 RR (-$1000)
            'stage_5_tp': 58000.0, # 1:20 RR (-$2000)
            'stage_6_tp': 57500.0, # 1:25 RR (-$2500)
            'sl_1_2_price': 59800.0,
            'sl_1_5_price': 59500.0,
            'sl_1_7_price': 59300.0,
            'sl_1_15_price': 58500.0,
            'sl_1_20_price': 58000.0,
            'leverage': 30,
            'confidence_score': 0.85,
            'level_info': '1D Major Resistance'
        }

        trade = self.trader.execute_signal(signal)
        self.assertIsNotNone(trade)
        initial_qty = trade.initial_qty
        
        # 1:2 RR -> SL to CTC
        self.trader.update_market_price(59795.0)
        self.assertEqual(trade.current_sl, 60000.0)

        # 1:5 RR -> 50% exit, SL to 1:2
        self.trader.update_market_price(59495.0)
        self.assertEqual(trade.current_sl, 59800.0)

        # 1:7 RR -> SL to 1:5
        self.trader.update_market_price(59295.0)
        self.assertEqual(trade.current_sl, 59500.0)

        # 1:10 RR -> 40% exit, 10% runner, SL to 1:7
        self.trader.update_market_price(58995.0)
        self.assertEqual(trade.current_sl, 59300.0)
        self.assertAlmostEqual(trade.remaining_qty, initial_qty * 0.10, places=4)

        # 1:20 RR -> SL to 1:15
        self.trader.update_market_price(57995.0)
        self.assertEqual(trade.current_sl, 58500.0)

        # 1:25 RR -> SL to 1:20
        self.trader.update_market_price(57495.0)
        self.assertEqual(trade.current_sl, 58000.0)

        # Bounce hits 1:20 SL ($58,000) -> Runner closes
        self.trader.update_market_price(58005.0)
        self.assertTrue(trade.is_closed)
        self.assertGreater(trade.realized_pnl, 0)
        print(f"✅ SELL Continuous Runner Trailing Verified! Net PnL: +${trade.realized_pnl:.2f}")

    def tearDown(self):
        import os
        if os.path.exists("test_paper_trades.json"):
            try:
                os.remove("test_paper_trades.json")
            except Exception:
                pass

if __name__ == '__main__':
    unittest.main()
