"""
FastAPI Real-Time WebSocket Trading Terminal Server
Powers the Live Delta Exchange TradingView Chart, 1D/1H Levels, and Bot Engine.
"""
import asyncio
import json
import time
import sys
import os
import pandas as pd
from datetime import datetime
from typing import List, Set

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import Config
from delta_client import DeltaClient
from level_detector import MultiTimeframeLevelDetector
from confidence_engine import ConfidenceEngine
from strategy_engine import StrategyEngine
from paper_trader import PaperTrader

app = FastAPI(title="Delta BTC Algo & Pro Terminal")

# Core singletons
client = DeltaClient()
level_detector = MultiTimeframeLevelDetector()
conf_engine = ConfidenceEngine()
strategy = StrategyEngine(level_detector=level_detector, confidence_engine=conf_engine)
trader = PaperTrader(initial_balance=10000.0)

# Active WebSocket connections
connected_clients: Set[WebSocket] = set()

# Strategy Auto-Bot Toggle (False by default so user can manual trade without interference)
auto_bot_enabled = False

# State storage
latest_state = {
    "current_price": 0.0,
    "high_24h": 0.0,
    "low_24h": 0.0,
    "candles": [],
    "volumes": [],
    "levels": [],
    "active_trade": None,
    "portfolio": {},
    "auto_bot_enabled": False,
    "logs": ["Exchange Pro Terminal started. Live feed connected."]
}

def log_message(msg: str):
    timestamp = datetime.now().strftime('%H:%M:%S')
    entry = f"[{timestamp}] {msg}"
    print(entry, flush=True)
    latest_state["logs"].append(entry)
    if len(latest_state["logs"]) > 100:
        latest_state["logs"].pop(0)

class OpenTradeRequest(BaseModel):
    side: str  # 'BUY' or 'SELL'
    margin_amount: float
    leverage: int = 25
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    symbol: str = "BTCUSD"

class CloseTradeRequest(BaseModel):
    trade_id: Optional[str] = None
    reason: str = "Manual Market Exit"

class ResetAccountRequest(BaseModel):
    initial_balance: float = 10000.0

class ToggleBotRequest(BaseModel):
    enabled: bool

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/levels")
async def get_levels():
    """Return 1D and 1H Key Levels in JSON format."""
    return {"levels": latest_state["levels"], "current_price": latest_state["current_price"]}

@app.get("/api/pine-script")
async def get_pine_script():
    """Return Pine Script indicator source code for TradingView/Delta Exchange."""
    pine_path = os.path.join(os.path.dirname(__file__), "delta_algo_indicator.pine")
    with open(pine_path, "r", encoding="utf-8") as f:
        return {"code": f.read()}

@app.post("/api/trade/open")
async def open_manual_trade(req: OpenTradeRequest):
    """Execute manual paper trade from user trading dock."""
    price = req.entry_price or latest_state.get("current_price", 0.0)
    if price <= 0:
        raise HTTPException(status_code=400, detail="Live market price not ready yet.")
        
    success, msg, trade = trader.execute_manual_trade(
        side=req.side.upper(),
        margin_amount=req.margin_amount,
        leverage=req.leverage,
        entry_price=price,
        sl_price=req.sl_price,
        tp_price=req.tp_price,
        symbol=req.symbol
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
        
    log_message(f"⚡ [MANUAL ORDER] {req.side} opened at ${price:,.2f} | Leverage: {req.leverage}x | Margin: ${req.margin_amount:.2f}")
    await broadcast_state()
    return {"success": True, "message": msg, "trade_id": trade.trade_id}

@app.post("/api/trade/close")
async def close_manual_trade(req: CloseTradeRequest):
    """Manually close active position at market price."""
    price = latest_state.get("current_price", 0.0)
    if price <= 0:
        raise HTTPException(status_code=400, detail="Live market price unavailable.")
        
    success, msg, event = trader.manual_close_trade(current_price=price, trade_id=req.trade_id, reason=req.reason)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
        
    log_message(f"🏁 [MANUAL CLOSE] Position closed at ${price:,.2f} | Net PnL: ${event['pnl']:,.2f}")
    await broadcast_state()
    return {"success": True, "message": msg, "pnl": event['pnl']}

@app.post("/api/trade/reset")
async def reset_paper_account(req: ResetAccountRequest):
    """Reset virtual balance to specified amount."""
    trader.reset_account(new_balance=req.initial_balance)
    log_message(f"🔄 [ACCOUNT RESET] Paper balance reset to ${req.initial_balance:,.2f}")
    await broadcast_state()
    return {"success": True, "balance": trader.balance}

@app.post("/api/bot/toggle")
async def toggle_auto_bot(req: ToggleBotRequest):
    """Enable or disable background automatic strategy bot."""
    global auto_bot_enabled
    auto_bot_enabled = req.enabled
    latest_state["auto_bot_enabled"] = auto_bot_enabled
    status_str = "ENABLED (Auto Trading Active)" if auto_bot_enabled else "PAUSED (Manual Mode Only)"
    log_message(f"🤖 [BOT MODE] Auto-Strategy Bot is now {status_str}")
    await broadcast_state()
    return {"success": True, "auto_bot_enabled": auto_bot_enabled}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        if latest_state["candles"]:
            await websocket.send_text(json.dumps(latest_state))
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        connected_clients.discard(websocket)

async def broadcast_state():
    """Broadcast state to all open browser tabs."""
    if not connected_clients:
        return
    message = json.dumps(latest_state)
    for ws in list(connected_clients):
        try:
            await ws.send_text(message)
        except Exception:
            connected_clients.discard(ws)

async def market_worker():
    """Continuous background loop running market data feed & strategy engine."""
    log_message("🚀 Background Market Feed started.")
    last_htf_update = 0
    
    while True:
        try:
            now_ts = time.time()
            
            # 1. Update 1D & 1H Levels every 5 minutes
            if now_ts - last_htf_update > 300:
                df_1d = client.get_candles('1d', limit=25)
                df_1h = client.get_candles('1h', limit=50)
                if len(df_1d) > 0 and len(df_1h) > 0:
                    levels = level_detector.update_levels(df_1d, df_1h)
                    latest_state["levels"] = [lvl.to_dict() for lvl in levels]
                    log_message(f"✅ Refreshed {len(levels)} 1D & 1H Key S/R & Liquidity Levels.")
                last_htf_update = now_ts

            # 2. Fetch Latest 1M Candles & Ticker
            df_1m = client.get_candles('1m', limit=100)
            ticker = client.get_ticker()

            if len(df_1m) > 0:
                # Format candles for TradingView Lightweight Charts
                formatted_candles = []
                formatted_vols = []
                for _, row in df_1m.iterrows():
                    candle_time = int(row['time'].timestamp())
                    formatted_candles.append({
                        "time": candle_time,
                        "open": float(row['open']),
                        "high": float(row['high']),
                        "low": float(row['low']),
                        "close": float(row['close'])
                    })
                    vol_color = '#2ea04388' if row['close'] >= row['open'] else '#f8514988'
                    formatted_vols.append({
                        "time": candle_time,
                        "value": float(row['volume']),
                        "color": vol_color
                    })
                latest_state["candles"] = formatted_candles
                latest_state["volumes"] = formatted_vols

            if ticker and 'close' in ticker:
                current_price = float(ticker['close'])
                latest_state["current_price"] = current_price
                latest_state["high_24h"] = float(ticker.get('high', 0))
                latest_state["low_24h"] = float(ticker.get('low', 0))
            elif len(df_1m) > 0:
                current_price = float(df_1m['close'].iloc[-1])
                latest_state["current_price"] = current_price
            else:
                await asyncio.sleep(2)
                continue

            # 3. Process Active Positions / Trailing SL & Multi-Stage Exits
            events = trader.update_market_price(current_price)
            for event in events:
                if event['event'] == 'STAGE_1_CTC_SHIFT':
                    log_message(f"🚀 [STAGE 1] 1:2 RR Hit! SL moved to CTC (${event['new_sl']:,.2f})")
                elif event['event'] == 'STAGE_2_PARTIAL_EXIT':
                    log_message(f"💰 [STAGE 2] 1:5 RR Hit! 50% Profit Booked (+${event['partial_pnl']:.2f})! SL locked at 1:2 (${event['new_sl']:,.2f})")
                elif event['event'] == 'STAGE_3_TRAIL_SHIFT':
                    log_message(f"🔥 [STAGE 3] 1:7 RR Hit! SL moved to 1:5 RR (${event['new_sl']:,.2f})")
                elif event['event'] == 'STAGE_4_PARTIAL_EXIT':
                    log_message(f"🎯 [STAGE 4] 1:10 RR Hit! 40% Profit Booked (+${event['partial_pnl']:.2f})! 10% Runner trailing with SL at 1:8 (${event['new_sl']:,.2f})")
                elif event['event'] == 'TRADE_CLOSED':
                    log_message(f"🏁 [TRADE CLOSED] {event['reason']} | Net PnL: ${event['pnl']:,.2f}")

            # 4. Check for New Setup Signals if auto-bot is enabled and no active trade
            if auto_bot_enabled and len(trader.active_trades) == 0 and len(df_1m) >= 10:
                signal = strategy.analyze_1m_candles(df_1m, current_price=current_price)
                if signal:
                    trade = trader.execute_signal(signal)
                    if trade:
                        log_message(f"⚡ [AUTO-BOT EXECUTED #{trader.daily_trades_count}] {trade.side} at ${trade.entry_price:,.2f} with {trade.leverage}x leverage (Margin: ${trade.margin_used:.2f} | Risk: ${trade.risk_amount:.2f}). SL: ${trade.current_sl:,.2f}")

            # 5. Format Active Trade for UI
            if len(trader.active_trades) > 0:
                act = trader.active_trades[0]
                latest_state["active_trade"] = {
                    "trade_id": act.trade_id,
                    "symbol": act.symbol,
                    "side": act.side,
                    "entry_price": act.entry_price,
                    "original_sl": act.original_sl,
                    "current_sl": act.current_sl,
                    "stage_1_tp": act.stage_1_tp,
                    "stage_2_tp": act.stage_2_tp,
                    "stage_3_tp": act.stage_3_tp,
                    "stage_4_tp": act.stage_4_tp,
                    "stage_5_tp": act.stage_5_tp,
                    "stage_6_tp": act.stage_6_tp,
                    "sl_1_2_price": act.sl_1_2_price,
                    "sl_1_5_price": act.sl_1_5_price,
                    "sl_1_7_price": act.sl_1_7_price,
                    "sl_1_15_price": act.sl_1_15_price,
                    "sl_1_20_price": act.sl_1_20_price,
                    "leverage": act.leverage,
                    "confidence_score": act.confidence_score,
                    "confidence_reasons": act.confidence_reasons,
                    "level_info": act.level_info,
                    "candle_a_high": act.candle_a_high,
                    "candle_a_low": act.candle_a_low,
                    "initial_qty": act.initial_qty,
                    "remaining_qty": act.remaining_qty,
                    "margin_used": act.margin_used,
                    "position_value": act.position_value,
                    "risk_amount": act.risk_amount,
                    "unrealized_pnl": act.get_unrealized_pnl(current_price),
                    "stage": act.stage,
                    "logs": act.history_logs
                }
            else:
                latest_state["active_trade"] = None

            # 6. Pending Setup Info (if any)
            if strategy.pending_setup:
                ps = strategy.pending_setup
                latest_state["pending_setup"] = {
                    "side": ps['side'],
                    "level_info": ps['level_info']['description'] if isinstance(ps['level_info'], dict) else str(ps['level_info']),
                    "candle_a_high": float(ps['candle_a']['high']),
                    "candle_a_low": float(ps['candle_a']['low']),
                    "candle_a_close": float(ps['candle_a']['close']),
                    "candle_a_open": float(ps['candle_a']['open']),
                }
            else:
                latest_state["pending_setup"] = None

            # 7. Portfolio & Trade History
            latest_state["portfolio"] = trader.get_performance_summary(current_price)
            latest_state["closed_trades"] = trader.closed_trades[-20:]  # Last 20 closed trades

            # 8. Push real-time update to browser
            await broadcast_state()

        except Exception as e:
            log_message(f"⚠️ Market loop error: {e}")

        # Poll interval: 1.5 seconds for real-time responsiveness
        await asyncio.sleep(1.5)

@app.get("/health")
@app.get("/healthz")
async def health_check():
    """Health check endpoint for Render / Cloud monitoring."""
    return {"status": "ok", "price": latest_state.get("current_price", 0), "timestamp": time.time()}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(market_worker())

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", 8501)))
    print(f"🚀 Starting Delta Algo Server on port {port}...")
    uvicorn.run("web_server:app", host="0.0.0.0", port=port, reload=False)
