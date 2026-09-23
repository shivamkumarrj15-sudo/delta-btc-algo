"""
Configuration Module for Delta Exchange BTC Multi-Timeframe Algo Bot
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

class Config:
    # Delta Exchange Endpoints
    REGION = os.getenv('DELTA_EXCHANGE_REGION', 'india').lower()
    
    if REGION == 'india':
        REST_BASE_URL = 'https://api.india.delta.exchange'
        WS_URL = 'wss://socket.india.delta.exchange'
    else:
        REST_BASE_URL = 'https://api.delta.exchange'
        WS_URL = 'wss://socket.delta.exchange'
        
    API_KEY = os.getenv('DELTA_API_KEY', '')
    API_SECRET = os.getenv('DELTA_API_SECRET', '')
    
    # Paper Trading vs Real Money
    PAPER_TRADING = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
    INITIAL_PAPER_BALANCE = float(os.getenv('INITIAL_PAPER_BALANCE', 1000.0))
    
    # Asset Symbol
    SYMBOL = os.getenv('SYMBOL', 'BTCUSD')
    
    # Risk Management & Trade Limits
    DAILY_MAX_RISK_PERCENT = float(os.getenv('DAILY_MAX_RISK_PERCENT', 2.0))
    PER_TRADE_RISK_PERCENT = float(os.getenv('PER_TRADE_RISK_PERCENT', 1.0))
    MAX_DAILY_TRADES = int(os.getenv('MAX_DAILY_TRADES', 4))
    COOLDOWN_MINUTES = int(os.getenv('COOLDOWN_MINUTES', 60))
    
    # Dynamic Leverage
    MIN_LEVERAGE = int(os.getenv('MIN_LEVERAGE', 20))
    MAX_LEVERAGE = int(os.getenv('MAX_LEVERAGE', 35))
    
    # Multi-Stage Partial Exit & Continuous Trailing RR Settings
    STAGE_1_RR = 2.0      # At 1:2 -> Move SL to CTC (Cost to Cost / Breakeven)
    STAGE_2_RR = 5.0      # At 1:5 -> Exit 50% Qty & Move SL to 1:2 RR
    STAGE_3_RR = 7.0      # At 1:7 -> Move SL to 1:5 RR
    STAGE_4_RR = 10.0     # At 1:10 -> Exit 40% Qty (10% Runner remains) & Move SL to 1:7 RR
    STAGE_5_RR = 20.0     # At 1:20 -> Move SL to 1:15 RR
    STAGE_6_RR = 25.0     # At 1:25 -> Move SL to 1:20 RR
    TRAIL_LADDER_STEP = 5.0 # Continuous +5R ladder (1:30 -> SL 1:25, 1:35 -> SL 1:30...)
    
    # Timeframe intervals
    HTF_DAILY = '1d'
    HTF_HOURLY = '1h'
    LTF_EXECUTION = '1m'
    
    # Level Proximity Buffer (Percentage of price to consider level touched, e.g. 0.15% for BTC)
    LEVEL_PROXIMITY_PCT = 0.0015  # ~0.15%

    @classmethod
    def display_summary(cls):
        print("="*60)
        print("🤖 DELTA EXCHANGE BTC ALGO BOT - CONFIGURATION")
        print("="*60)
        print(f"🌍 Region:           Delta Exchange ({cls.REGION.upper()})")
        print(f"📊 Symbol:           {cls.SYMBOL}")
        print(f"🧪 Trading Mode:     {'PAPER TRADING ($1,000)' if cls.PAPER_TRADING else 'REAL MONEY ⚠️'}")
        print(f"🛡️ Daily Limits:     Max {cls.MAX_DAILY_TRADES} Trades/Day | Max {cls.DAILY_MAX_RISK_PERCENT}% Risk/Day")
        print(f"⏳ Trade Cooldown:   {cls.COOLDOWN_MINUTES} Minutes after each trade")
        print(f"🎯 Dynamic Leverage: {cls.MIN_LEVERAGE}x - {cls.MAX_LEVERAGE}x")
        print(f"📈 Exit Plan:        1:2 (CTC) -> 1:5 (50% Out + SL@1:2) -> 1:7 (SL@1:5) -> 1:10 (40% Out + SL@1:7) -> 1:20 (SL@1:15) -> 1:25 (SL@1:20) -> Continuous Trail")
        print("="*60)


