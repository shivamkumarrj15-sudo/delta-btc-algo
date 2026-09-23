"""
Strategy Engine Module
Executes Multi-Timeframe Strategy Logic:
1. Detects Level Interaction (1D/1H Support/Resistance)
2. Tracks 1-Minute Buyer vs Seller Fight & Seller Exhaustion
3. Identifies Candle A (Solid Body Dominance Candle)
4. Detects Candle B Breakout Trigger (Breaking High of Candle A for BUY)
5. Sets SL at Candle A Low and calculates 1:2, 1:5, 1:10 TP levels.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from config import Config
from level_detector import MultiTimeframeLevelDetector
from confidence_engine import ConfidenceEngine

class StrategyEngine:
    def __init__(self, level_detector: MultiTimeframeLevelDetector, confidence_engine: ConfidenceEngine = None):
        self.level_detector = level_detector
        self.confidence_engine = confidence_engine or ConfidenceEngine()
        self.pending_setup = None  # Holds candidate Candle A while waiting for Candle B trigger

    def analyze_1m_candles(self, df_1m: pd.DataFrame, current_price: float = None) -> Optional[Dict[str, Any]]:
        """
        Analyze 1-minute candlestick stream for the strategy setup.
        df_1m: DataFrame containing at least 20 recent 1M candles [time, open, high, low, close, volume]
        """
        if df_1m is None or len(df_1m) < 10:
            return None

        current_price = current_price or df_1m['close'].iloc[-1]
        
        # -------------------------------------------------------------
        # 1. Check if we already have a pending Candle A waiting for trigger
        # -------------------------------------------------------------
        if self.pending_setup:
            setup = self.pending_setup
            candle_a = setup['candle_a']
            side = setup['side']
            
            # Check expiration: Candle B must trigger within 1-2 candles after Candle A
            candles_since = len(df_1m) - setup['candle_a_index']
            if candles_since > 3:  # Expired if no breakout within 2 candles
                self.pending_setup = None
            else:
                # Check for Candle B Breakout Trigger
                if side == 'BUY':
                    if current_price > candle_a['high']:
                        # TRIGGER HIT!
                        signal = self._build_execution_signal(setup, current_price, df_1m)
                        self.pending_setup = None
                        return signal
                    elif current_price < candle_a['low']:
                        # Invalidation: price fell below SL before triggering
                        self.pending_setup = None
                elif side == 'SELL':
                    if current_price < candle_a['low']:
                        # TRIGGER HIT!
                        signal = self._build_execution_signal(setup, current_price, df_1m)
                        self.pending_setup = None
                        return signal
                    elif current_price > candle_a['high']:
                        # Invalidation
                        self.pending_setup = None

        # -------------------------------------------------------------
        # 2. Check for New Setup (Candle A Formation)
        # -------------------------------------------------------------
        # Candle A is the most recently closed 1M candle (iloc[-2]) or current candle
        candle_a = df_1m.iloc[-2]
        prev_candles = df_1m.iloc[-7:-2]  # Recent 5 candles representing the fight/pullback

        # Check for BUY Setup at Key Support
        buy_level = self.level_detector.get_nearby_level(candle_a['low'], side='BUY')
        if buy_level and self._is_trend_allowed('BUY', buy_level):
            is_valid_buy_a = self._verify_buy_candle_a(candle_a, prev_candles)
            if is_valid_buy_a:
                self.pending_setup = {
                    'side': 'BUY',
                    'candle_a': candle_a,
                    'candle_a_index': len(df_1m) - 2,
                    'level_info': buy_level,
                    'timestamp': candle_a['time']
                }
                # Check if current candle (Candle B) is already breaking Candle A high
                if current_price > candle_a['high']:
                    signal = self._build_execution_signal(self.pending_setup, current_price, df_1m)
                    self.pending_setup = None
                    return signal

        # Check for SELL Setup at Key Resistance
        sell_level = self.level_detector.get_nearby_level(candle_a['high'], side='SELL')
        if sell_level and self._is_trend_allowed('SELL', sell_level):
            is_valid_sell_a = self._verify_sell_candle_a(candle_a, prev_candles)
            if is_valid_sell_a:
                self.pending_setup = {
                    'side': 'SELL',
                    'candle_a': candle_a,
                    'candle_a_index': len(df_1m) - 2,
                    'level_info': sell_level,
                    'timestamp': candle_a['time']
                }
                if current_price < candle_a['low']:
                    signal = self._build_execution_signal(self.pending_setup, current_price, df_1m)
                    self.pending_setup = None
                    return signal

        return None

    def _is_trend_allowed(self, side: str, level_info: Dict[str, Any]) -> bool:
        """
        Trend Alignment Rules:
        1. For 1H Small Liquidity: MUST trade in direction of the trend (e.g. Bullish -> BUY only; Bearish -> SELL only).
        2. For 1D Main Liquidity (PDH/PDL/1D Base): Counter-Trend / Reversal trades are explicitly allowed.
        """
        category = level_info.get('category', 'MAIN_1D')
        trend = level_info.get('market_trend', 'SIDEWAYS')
        
        # Main 1D Liquidity allows all setups (both trend-following and counter-trend reversals)
        if category == 'MAIN_1D':
            return True
            
        # Small 1H Liquidity requires trend alignment
        if trend == 'BULLISH' and side == 'SELL':
            return False  # Do not short 1H resistance against a strong bullish trend
        if trend == 'BEARISH' and side == 'BUY':
            return False  # Do not buy 1H support against a strong bearish trend
            
        return True

    def _verify_buy_candle_a(self, candle_a: pd.Series, prev_candles: pd.DataFrame) -> bool:
        """
        Verify:
        1. Candle A is a solid GREEN body candle (Close > Open)
        2. Body / Range ratio >= 45% (Strong buyer dominance)
        3. Preceding candles had sellers pushing (pullback/fight) that exhausted:
           Seller push -> Buyer response -> Seller retest -> Buyer absorption (Tug-of-war)
        """
        candle_range = candle_a['high'] - candle_a['low']
        if candle_range <= 0:
            return False

        body = candle_a['close'] - candle_a['open']
        # Must be green candle
        if body <= 0:
            return False

        body_ratio = body / candle_range
        if body_ratio < 0.45:  # Must have solid body
            return False

        # Preceding fight check (Tug of war at liquidity level):
        # Look for at least 1 seller push and buyer rejection in the last 5 candles
        seller_candles = 0
        rejection_wicks = 0
        for _, c in prev_candles.tail(5).iterrows():
            c_range = c['high'] - c['low']
            if c_range > 0:
                lower_wick = min(c['open'], c['close']) - c['low']
                if lower_wick / c_range > 0.3:
                    rejection_wicks += 1
            if c['close'] <= c['open'] or c['low'] <= candle_a['low']:
                seller_candles += 1

        return seller_candles >= 1 or rejection_wicks >= 1

    def _verify_sell_candle_a(self, candle_a: pd.Series, prev_candles: pd.DataFrame) -> bool:
        """
        Verify solid RED body candle after buyers fail at resistance:
        Buyer push -> Seller response -> Buyer retest -> Seller absorption
        """
        candle_range = candle_a['high'] - candle_a['low']
        if candle_range <= 0:
            return False

        body = candle_a['open'] - candle_a['close']
        if body <= 0:
            return False

        body_ratio = body / candle_range
        if body_ratio < 0.45:
            return False

        buyer_candles = 0
        upper_wicks = 0
        for _, c in prev_candles.tail(5).iterrows():
            c_range = c['high'] - c['low']
            if c_range > 0:
                upper_wick = c['high'] - max(c['open'], c['close'])
                if upper_wick / c_range > 0.3:
                    upper_wicks += 1
            if c['close'] >= c['open'] or c['high'] >= candle_a['high']:
                buyer_candles += 1

        return buyer_candles >= 1 or upper_wicks >= 1

    def _build_execution_signal(self, setup: Dict[str, Any], trigger_price: float, df_1m: pd.DataFrame) -> Dict[str, Any]:
        """Construct full trade order signal with exact SL and 1:2, 1:5, 1:10 TP levels."""
        side = setup['side']
        candle_a = setup['candle_a']
        level_info = setup['level_info']

        # Confidence & Dynamic Leverage calculation
        conf = self.confidence_engine.calculate_confidence(level_info, candle_a, df_1m, side=side)
        leverage = conf['leverage']
        confidence_score = conf['confidence_score']

        # Entry & Stop Loss strictly on Candle A
        if side == 'BUY':
            entry_price = round(trigger_price, 2)
            # SL placed slightly below Candle A's low (buffer $2 on BTC)
            sl_price = round(candle_a['low'] - 2.0, 2)
            risk_per_unit = max(10.0, entry_price - sl_price)

            stage_1_tp = round(entry_price + (risk_per_unit * Config.STAGE_1_RR), 2)   # 1:2 RR
            stage_2_tp = round(entry_price + (risk_per_unit * Config.STAGE_2_RR), 2)   # 1:5 RR
            stage_3_tp = round(entry_price + (risk_per_unit * Config.STAGE_3_RR), 2)   # 1:7 RR
            stage_4_tp = round(entry_price + (risk_per_unit * Config.STAGE_4_RR), 2)   # 1:10 RR
            stage_5_tp = round(entry_price + (risk_per_unit * Config.STAGE_5_RR), 2)   # 1:20 RR
            stage_6_tp = round(entry_price + (risk_per_unit * Config.STAGE_6_RR), 2)   # 1:25 RR

            sl_1_2_price = round(entry_price + (risk_per_unit * 2.0), 2)
            sl_1_5_price = round(entry_price + (risk_per_unit * 5.0), 2)
            sl_1_7_price = round(entry_price + (risk_per_unit * 7.0), 2)
            sl_1_15_price = round(entry_price + (risk_per_unit * 15.0), 2)
            sl_1_20_price = round(entry_price + (risk_per_unit * 20.0), 2)
        else:
            entry_price = round(trigger_price, 2)
            # SL placed slightly above Candle A's high (buffer $2 on BTC)
            sl_price = round(candle_a['high'] + 2.0, 2)
            risk_per_unit = max(10.0, sl_price - entry_price)

            stage_1_tp = round(entry_price - (risk_per_unit * Config.STAGE_1_RR), 2)   # 1:2 RR
            stage_2_tp = round(entry_price - (risk_per_unit * Config.STAGE_2_RR), 2)   # 1:5 RR
            stage_3_tp = round(entry_price - (risk_per_unit * Config.STAGE_3_RR), 2)   # 1:7 RR
            stage_4_tp = round(entry_price - (risk_per_unit * Config.STAGE_4_RR), 2)   # 1:10 RR
            stage_5_tp = round(entry_price - (risk_per_unit * Config.STAGE_5_RR), 2)   # 1:20 RR
            stage_6_tp = round(entry_price - (risk_per_unit * Config.STAGE_6_RR), 2)   # 1:25 RR

            sl_1_2_price = round(entry_price - (risk_per_unit * 2.0), 2)
            sl_1_5_price = round(entry_price - (risk_per_unit * 5.0), 2)
            sl_1_7_price = round(entry_price - (risk_per_unit * 7.0), 2)
            sl_1_15_price = round(entry_price - (risk_per_unit * 15.0), 2)
            sl_1_20_price = round(entry_price - (risk_per_unit * 20.0), 2)

        return {
            'timestamp': pd.Timestamp.now(),
            'symbol': Config.SYMBOL,
            'side': side,
            'entry_price': entry_price,
            'sl_price': sl_price,
            'risk_per_unit': round(risk_per_unit, 2),
            'stage_1_tp': stage_1_tp,    # 1:2 CTC
            'stage_2_tp': stage_2_tp,    # 1:5 50% exit
            'stage_3_tp': stage_3_tp,    # 1:7 SL to 1:5
            'stage_4_tp': stage_4_tp,    # 1:10 40% exit + SL to 1:7
            'stage_5_tp': stage_5_tp,    # 1:20 SL to 1:15
            'stage_6_tp': stage_6_tp,    # 1:25 SL to 1:20
            'sl_1_2_price': sl_1_2_price,
            'sl_1_5_price': sl_1_5_price,
            'sl_1_7_price': sl_1_7_price,
            'sl_1_15_price': sl_1_15_price,
            'sl_1_20_price': sl_1_20_price,
            'leverage': leverage,
            'confidence_score': confidence_score,
            'confidence_reasons': conf['reasons'],
            'level_info': level_info['description'],
            'candle_a_high': candle_a['high'],
            'candle_a_low': candle_a['low']
        }


