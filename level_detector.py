"""
Multi-Timeframe Level Detector Module
Extracts 1-Day and 1-Hour Key Levels (PDH/PDL, Swing High/Lows, S/R Zones, Liquidity Pools).
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from config import Config

class KeyLevel:
    def __init__(self, price: float, timeframe: str, level_type: str, description: str, weight: float = 1.0, category: str = 'MAIN_1D'):
        self.price = round(price, 2)
        self.timeframe = timeframe  # '1d' or '1h'
        self.level_type = level_type  # 'SUPPORT', 'RESISTANCE', 'PDH', 'PDL', 'SWING_HIGH', 'SWING_LOW'
        self.description = description
        self.weight = weight  # Confluence weight (higher for 1D than 1H)
        self.category = category  # 'MAIN_1D' or 'SMALL_1H'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'price': self.price,
            'timeframe': self.timeframe,
            'level_type': self.level_type,
            'description': self.description,
            'weight': self.weight,
            'category': self.category
        }

class MultiTimeframeLevelDetector:
    def __init__(self, proximity_pct: float = None):
        self.proximity_pct = proximity_pct or Config.LEVEL_PROXIMITY_PCT
        self.daily_levels: List[KeyLevel] = []
        self.hourly_levels: List[KeyLevel] = []
        self.all_levels: List[KeyLevel] = []
        self.current_trend: str = 'SIDEWAYS'  # 'BULLISH', 'BEARISH', 'SIDEWAYS'

    def _find_pivots(self, df: pd.DataFrame, window: int = 5) -> tuple:
        """Identify swing highs and swing lows using rolling window."""
        highs = []
        lows = []
        if len(df) < window * 2 + 1:
            return highs, lows
            
        for i in range(window, len(df) - window):
            current_high = df['high'].iloc[i]
            current_low = df['low'].iloc[i]
            
            # Check if swing high
            if current_high == df['high'].iloc[i-window : i+window+1].max():
                highs.append((df['time'].iloc[i], current_high))
                
            # Check if swing low
            if current_low == df['low'].iloc[i-window : i+window+1].min():
                lows.append((df['time'].iloc[i], current_low))
                
        return highs, lows

    def extract_daily_levels(self, df_1d: pd.DataFrame) -> List[KeyLevel]:
        """Extract 1-Day Key Levels: PDH, PDL, PDC, Daily Swing Points."""
        levels = []
        if df_1d is None or len(df_1d) < 2:
            return levels

        # 1. Previous Day High, Low, Close (PDH, PDL, PDC)
        prev_day = df_1d.iloc[-2]
        pdh = prev_day['high']
        pdl = prev_day['low']
        pdc = prev_day['close']
        
        levels.append(KeyLevel(pdh, '1d', 'RESISTANCE', 'PDH (Main Liquidity High)', weight=2.0, category='MAIN_1D'))
        levels.append(KeyLevel(pdl, '1d', 'SUPPORT', 'PDL (Main Liquidity Low)', weight=2.0, category='MAIN_1D'))
        levels.append(KeyLevel(pdc, '1d', 'PIVOT', 'PDC (Daily Pivot)', weight=1.5, category='MAIN_1D'))

        # 2. Daily Swing Highs & Lows (Pivots)
        highs, lows = self._find_pivots(df_1d, window=3)
        for _, h_price in highs[-5:]:
            levels.append(KeyLevel(h_price, '1d', 'RESISTANCE', 'Main Liquidity (1D Resistance)', weight=2.0, category='MAIN_1D'))
        for _, l_price in lows[-5:]:
            levels.append(KeyLevel(l_price, '1d', 'SUPPORT', 'Main Liquidity (1D Base Support)', weight=2.0, category='MAIN_1D'))

        self.daily_levels = levels
        return levels

    def extract_hourly_levels(self, df_1h: pd.DataFrame) -> List[KeyLevel]:
        """Extract 1-Hour Key Levels: 1H Swings, S/R Zones."""
        levels = []
        if df_1h is None or len(df_1h) < 10:
            return levels

        highs, lows = self._find_pivots(df_1h, window=4)
        for _, h_price in highs[-8:]:
            levels.append(KeyLevel(h_price, '1h', 'RESISTANCE', 'Small Liquidity (1H High)', weight=1.2, category='SMALL_1H'))
        for _, l_price in lows[-8:]:
            levels.append(KeyLevel(l_price, '1h', 'SUPPORT', 'Small Liquidity (1H Low)', weight=1.2, category='SMALL_1H'))

        self.hourly_levels = levels
        return levels

    def calculate_trend(self, df_1h: pd.DataFrame) -> str:
        """Determine Higher Timeframe Market Trend (BULLISH, BEARISH, SIDEWAYS)."""
        if df_1h is None or len(df_1h) < 20:
            return 'SIDEWAYS'
        
        close = df_1h['close']
        ema_fast = close.ewm(span=12, adjust=False).mean().iloc[-1]
        ema_slow = close.ewm(span=26, adjust=False).mean().iloc[-1]
        last_price = close.iloc[-1]
        
        if last_price > ema_fast > ema_slow:
            return 'BULLISH'
        elif last_price < ema_fast < ema_slow:
            return 'BEARISH'
        else:
            return 'SIDEWAYS'

    def update_levels(self, df_1d: pd.DataFrame, df_1h: pd.DataFrame) -> List[KeyLevel]:
        """Update and aggregate all HTF levels and current market trend."""
        d_levels = self.extract_daily_levels(df_1d)
        h_levels = self.extract_hourly_levels(df_1h)
        self.current_trend = self.calculate_trend(df_1h)
        
        # Merge and remove duplicate levels within 0.1% of each other
        combined = d_levels + h_levels
        unique_levels = []
        
        for lvl in combined:
            is_dup = False
            for existing in unique_levels:
                if abs(existing.price - lvl.price) / lvl.price < 0.001:
                    # Merge / boost weight
                    existing.weight = max(existing.weight, lvl.weight) + 0.5
                    is_dup = True
                    break
            if not is_dup:
                unique_levels.append(lvl)
                
        self.all_levels = unique_levels
        return self.all_levels

    def get_nearby_level(self, current_price: float, side: str = 'BUY') -> Optional[Dict[str, Any]]:
        """
        Check if current price is interacting with a key level.
        For BUY: looking for price testing a SUPPORT level (PDL, 1D/1H Swing Low).
        For SELL: looking for price testing a RESISTANCE level (PDH, 1D/1H Swing High).
        """
        target_type = 'SUPPORT' if side.upper() == 'BUY' else 'RESISTANCE'
        candidate_levels = [lvl for lvl in self.all_levels if lvl.level_type in (target_type, 'PIVOT')]
        
        nearest = None
        min_dist_pct = float('inf')
        
        for lvl in candidate_levels:
            dist_pct = abs(current_price - lvl.price) / lvl.price
            if dist_pct <= self.proximity_pct and dist_pct < min_dist_pct:
                min_dist_pct = dist_pct
                nearest = lvl

        if nearest:
            return {
                'level': nearest,
                'distance_pct': min_dist_pct,
                'is_near': True,
                'price': nearest.price,
                'type': nearest.level_type,
                'description': nearest.description,
                'weight': nearest.weight,
                'timeframe': nearest.timeframe,
                'category': nearest.category,
                'market_trend': self.current_trend
            }
        return None
