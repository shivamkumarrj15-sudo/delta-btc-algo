"""
Confidence & Dynamic Leverage Engine
Calculates trade confidence score based on HTF confluence, volume surge, and candle body quality.
Maps confidence to leverage between 20x and 35x.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any
from config import Config

class ConfidenceEngine:
    def __init__(self, min_leverage: int = None, max_leverage: int = None):
        self.min_leverage = min_leverage or Config.MIN_LEVERAGE
        self.max_leverage = max_leverage or Config.MAX_LEVERAGE

    def calculate_confidence(self, level_info: Dict[str, Any], candle_a: pd.Series, 
                             candles_1m: pd.DataFrame, side: str = 'BUY') -> Dict[str, Any]:
        """
        Evaluate confidence score (0.0 to 1.0) based on:
        1. HTF Level Strength (1D vs 1H, weight)
        2. Candle A Body-to-Range ratio (Solid Body strength)
        3. Volume surge on Candle A vs 20-SMA volume
        4. Clear Seller Exhaustion pattern
        """
        score = 0.0
        reasons = []

        # 1. HTF Level Confluence
        level_weight = level_info.get('weight', 1.0) if level_info else 1.0
        if level_weight >= 2.0:  # 1D Level (PDH/PDL or 1D Swing)
            score += 0.35
            reasons.append("1D Major Key Level Confluence (+35%)")
        elif level_weight >= 1.2:  # 1H Level
            score += 0.20
            reasons.append("1H Key Level Confluence (+20%)")
        else:
            score += 0.10
            reasons.append("Minor Zone Confluence (+10%)")

        # 2. Candle A Quality (Solid Body Ratio)
        candle_range = max(0.001, candle_a['high'] - candle_a['low'])
        candle_body = abs(candle_a['close'] - candle_a['open'])
        body_ratio = candle_body / candle_range

        if body_ratio >= 0.70:
            score += 0.30
            reasons.append(f"High Dominance Solid Body Candle ({body_ratio*100:.1f}% body, +30%)")
        elif body_ratio >= 0.50:
            score += 0.15
            reasons.append(f"Moderate Solid Body Candle ({body_ratio*100:.1f}% body, +15%)")

        # 3. Volume Surge Check
        if 'volume' in candles_1m.columns and len(candles_1m) >= 20:
            avg_vol = candles_1m['volume'].iloc[-21:-1].mean()
            current_vol = candle_a['volume']
            vol_ratio = current_vol / max(1.0, avg_vol)

            if vol_ratio >= 2.0:
                score += 0.25
                reasons.append(f"Massive Volume Surge ({vol_ratio:.1f}x avg volume, +25%)")
            elif vol_ratio >= 1.3:
                score += 0.15
                reasons.append(f"Above Average Volume ({vol_ratio:.1f}x avg volume, +15%)")
        else:
            score += 0.10

        # 4. Rejection Wick / Liquidity Sweep Check
        if side == 'BUY':
            lower_wick = min(candle_a['open'], candle_a['close']) - candle_a['low']
            if lower_wick / candle_range >= 0.20:
                score += 0.10
                reasons.append("Buyer Liquidity Sweep Rejection Wick (+10%)")
        else:
            upper_wick = candle_a['high'] - max(candle_a['open'], candle_a['close'])
            if upper_wick / candle_range >= 0.20:
                score += 0.10
                reasons.append("Seller Liquidity Sweep Rejection Wick (+10%)")

        # Cap score at 1.0
        final_score = min(1.0, round(score, 2))

        # Dynamic Leverage Mapping:
        # Score < 0.50 -> 20x
        # Score 0.50 - 0.70 -> 25x
        # Score 0.70 - 0.85 -> 30x
        # Score >= 0.85 -> 35x
        if final_score >= 0.85:
            leverage = self.max_leverage  # 35x
        elif final_score >= 0.70:
            leverage = 30
        elif final_score >= 0.50:
            leverage = 25
        else:
            leverage = self.min_leverage  # 20x

        # Keep within configured min/max
        leverage = max(self.min_leverage, min(self.max_leverage, leverage))

        return {
            'confidence_score': final_score,
            'leverage': leverage,
            'reasons': reasons,
            'body_ratio': round(body_ratio, 2)
        }
