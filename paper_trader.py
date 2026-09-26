"""
Paper Trading Simulator Engine
Simulates real-world market execution with:
- $1,000 virtual balance
- 2% daily risk guard
- Max 4 trades per day limit
- 1-Hour (60 min) cooldown between trades
- Dynamic leverage (20x-35x) and capital allocation breakdown
"""
import os
import sys
import json
import time
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Any, Optional
from config import Config
from trade_manager import ActiveTrade

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

class PaperTrader:
    def __init__(self, initial_balance: float = None, save_path: str = "paper_trades.json"):
        self.initial_balance = initial_balance or Config.INITIAL_PAPER_BALANCE
        self.balance = self.initial_balance
        self.save_path = save_path
        self.active_trades: List[ActiveTrade] = []
        self.closed_trades: List[Dict[str, Any]] = []
        
        self.daily_starting_balance = self.initial_balance
        self.daily_realized_pnl = 0.0
        self.current_trading_day = date.today().isoformat()
        self.daily_trades_count = 0
        self.last_trade_closed_time = 0.0  # Unix timestamp
        
        self.peak_balance = self.initial_balance
        self.max_drawdown = 0.0
        self._load_state()

    def _save_state(self):
        """Save paper trading portfolio history to JSON."""
        data = {
            'balance': self.balance,
            'daily_realized_pnl': self.daily_realized_pnl,
            'daily_trades_count': self.daily_trades_count,
            'current_trading_day': self.current_trading_day,
            'last_trade_closed_time': self.last_trade_closed_time,
            'peak_balance': self.peak_balance,
            'max_drawdown': self.max_drawdown,
            'closed_trades': self.closed_trades
        }
        try:
            with open(self.save_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            print(f"Error saving paper state: {e}")

    def _load_state(self):
        """Load portfolio history if exists."""
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, 'r') as f:
                    data = json.load(f)
                    self.balance = data.get('balance', self.initial_balance)
                    self.daily_realized_pnl = data.get('daily_realized_pnl', 0.0)
                    self.daily_trades_count = data.get('daily_trades_count', 0)
                    self.current_trading_day = data.get('current_trading_day', date.today().isoformat())
                    self.last_trade_closed_time = data.get('last_trade_closed_time', 0.0)
                    self.peak_balance = data.get('peak_balance', self.initial_balance)
                    self.max_drawdown = data.get('max_drawdown', 0.0)
                    self.closed_trades = data.get('closed_trades', [])
                    
                    # Reset daily counter if day has changed
                    if self.current_trading_day != date.today().isoformat():
                        self.current_trading_day = date.today().isoformat()
                        self.daily_trades_count = 0
                        self.daily_realized_pnl = 0.0
                        self.daily_starting_balance = self.balance
            except Exception:
                pass

    def _check_day_reset(self):
        """Reset daily metrics when a new day starts."""
        today_str = date.today().isoformat()
        if self.current_trading_day != today_str:
            self.current_trading_day = today_str
            self.daily_trades_count = 0
            self.daily_realized_pnl = 0.0
            self.daily_starting_balance = self.balance

    def can_open_trade(self) -> tuple[bool, str]:
        """Check all risk and rule limits before opening a new trade."""
        self._check_day_reset()

        # 1. Check max open positions (1 at a time)
        if len(self.active_trades) >= 1:
            return False, "An active trade is already in progress."

        # 2. Check 1-Hour Cooldown Period (60 minutes since last trade closed)
        if self.last_trade_closed_time > 0:
            elapsed_sec = time.time() - self.last_trade_closed_time
            cooldown_sec = Config.COOLDOWN_MINUTES * 60
            if elapsed_sec < cooldown_sec:
                rem_mins = int((cooldown_sec - elapsed_sec) / 60) + 1
                return False, f"⏳ 1-Hour Cooldown active ({rem_mins} mins remaining). No trade allowed yet."

        # 3. Check Daily Max Trades Limit (Max 4 trades/day)
        if self.daily_trades_count >= Config.MAX_DAILY_TRADES:
            return False, f"🛑 Daily Max Trades limit reached ({self.daily_trades_count}/{Config.MAX_DAILY_TRADES} trades). Trading paused for today."

        # 4. Daily Max Risk Check (2% of daily balance)
        max_daily_loss = self.daily_starting_balance * (Config.DAILY_MAX_RISK_PERCENT / 100.0)
        if self.daily_realized_pnl <= -max_daily_loss:
            return False, f"⚠️ Daily Max Risk reached (-${abs(self.daily_realized_pnl):.2f} / -${max_daily_loss:.2f}). Trading paused for today."

        return True, "Ready"

    def execute_signal(self, signal: Dict[str, Any]) -> Optional[ActiveTrade]:
        """Calculate position size, margin, and open new paper trade."""
        can_trade, reason = self.can_open_trade()
        if not can_trade:
            # Silent skip or log
            return None

        entry_price = signal['entry_price']
        sl_price = signal['sl_price']
        leverage = signal['leverage']
        risk_per_unit = signal['risk_per_unit']

        # 1% risk per trade on current balance
        risk_amount = self.balance * (Config.PER_TRADE_RISK_PERCENT / 100.0)  # e.g. $10 on $1000
        
        # Position sizing: Qty = Risk_Amount / Distance_to_SL
        raw_qty = risk_amount / max(1.0, risk_per_unit)
        qty = round(raw_qty, 5)  # BTC precision
        
        total_position_val = qty * entry_price
        margin_required = total_position_val / leverage

        # Ensure margin doesn't exceed 80% of available balance
        if margin_required > self.balance * 0.8:
            margin_required = self.balance * 0.8
            total_position_val = margin_required * leverage
            qty = round(total_position_val / entry_price, 5)
            risk_amount = qty * risk_per_unit

        trade = ActiveTrade(signal, initial_qty=qty, margin_used=margin_required, risk_amount=risk_amount)
        self.active_trades.append(trade)
        self.daily_trades_count += 1
        self._save_state()
        
        print("\n" + "="*65)
        print(f"⚡ [PAPER TRADE EXECUTED #{self.daily_trades_count}] {trade.side} {trade.symbol}")
        print(f"   Entry:        ${entry_price:,.2f}")
        print(f"   SL:           ${sl_price:,.2f} (Candle A Low)")
        print(f"   Targets:      1:2 -> ${signal['stage_1_tp']:,.2f} | 1:5 -> ${signal['stage_2_tp']:,.2f} | 1:7 -> ${signal['stage_3_tp']:,.2f} | 1:10 -> ${signal['stage_4_tp']:,.2f}")
        print(f"   Capital Used: ${margin_required:.2f} Margin ({leverage}x Leverage = ${total_position_val:,.2f} Position)")
        print(f"   Free Capital: ${self.balance - margin_required:,.2f} | Risk at stake: ${risk_amount:.2f}")
        print(f"   Confidence:   {signal['confidence_score']*100:.0f}% ({signal['level_info']})")
        print("="*65 + "\n")
        return trade

    def update_market_price(self, current_price: float) -> List[Dict[str, Any]]:
        """Process price ticks against all active trades."""
        events = []
        remaining_active = []

        for trade in self.active_trades:
            event = trade.update_price(current_price)
            if event:
                events.append(event)
                if event['event'] in ('STAGE_2_PARTIAL_EXIT', 'STAGE_4_PARTIAL_EXIT'):
                    # Bank partial profit into balance
                    self.balance += event['partial_pnl']
                    self.daily_realized_pnl += event['partial_pnl']
                elif event['event'] == 'TRADE_CLOSED':
                    # Trade fully closed
                    self.balance += trade.realized_pnl
                    self.daily_realized_pnl += trade.realized_pnl
                    self.last_trade_closed_time = time.time()  # Start 1-Hour Cooldown!
                    self._record_closed_trade(trade)
                    continue
            
            if not trade.is_closed:
                remaining_active.append(trade)

        self.active_trades = remaining_active
        
        # Update peak balance and drawdown
        current_equity = self.get_total_equity(current_price)
        if current_equity > self.peak_balance:
            self.peak_balance = current_equity
        if self.peak_balance > 0:
            dd = (self.peak_balance - current_equity) / self.peak_balance * 100
            if dd > self.max_drawdown:
                self.max_drawdown = round(dd, 2)

        self._save_state()
        return events

    def _record_closed_trade(self, trade: ActiveTrade):
        """Record trade to closed trade history with A-Z diagnostic details."""
        record = {
            'trade_id': trade.trade_id,
            'symbol': trade.symbol,
            'side': trade.side,
            'entry_price': trade.entry_price,
            'original_sl': trade.original_sl,
            'final_sl': trade.current_sl,
            'initial_qty': trade.initial_qty,
            'margin_used': round(trade.margin_used, 2),
            'position_value': round(trade.position_value, 2),
            'risk_amount': round(trade.risk_amount, 2),
            'leverage': trade.leverage,
            'confidence_score': trade.confidence_score,
            'confidence_reasons': trade.confidence_reasons,
            'level_info': trade.level_info,
            'candle_a_high': trade.candle_a_high,
            'candle_a_low': trade.candle_a_low,
            'entry_time': trade.entry_time.strftime('%Y-%m-%d %H:%M:%S'),
            'exit_time': trade.exit_time.strftime('%Y-%m-%d %H:%M:%S') if trade.exit_time else '',
            'realized_pnl': round(trade.realized_pnl, 2),
            'pnl_percent': round((trade.realized_pnl / trade.margin_used) * 100, 2) if trade.margin_used > 0 else 0,
            'exit_reason': trade.exit_reason,
            'stage_reached': trade.stage,
            'max_rr_reached': round(trade.max_rr_reached, 2),
            'logs': trade.history_logs
        }
        self.closed_trades.append(record)


    def get_total_equity(self, current_price: float) -> float:
        """Calculate total account equity = Balance + Unrealized PnL."""
        unrealized = sum(t.get_unrealized_pnl(current_price) for t in self.active_trades)
        return round(self.balance + unrealized, 2)

    def get_margin_in_use(self) -> float:
        """Calculate total margin currently committed to open trades."""
        return sum(t.margin_used for t in self.active_trades)

    def get_cooldown_remaining(self) -> int:
        """Return remaining cooldown in seconds (0 if ready)."""
        if self.last_trade_closed_time <= 0:
            return 0
        elapsed = time.time() - self.last_trade_closed_time
        total_cooldown = Config.COOLDOWN_MINUTES * 60
        return max(0, int(total_cooldown - elapsed))

    def get_performance_summary(self, current_price: float = 0.0) -> Dict[str, Any]:
        """Compute key portfolio metrics with capital breakdown and cooldown."""
        self._check_day_reset()
        total_trades = len(self.closed_trades)
        wins = [t for t in self.closed_trades if t['realized_pnl'] > 0]
        losses = [t for t in self.closed_trades if t['realized_pnl'] < 0]
        breakevens = [t for t in self.closed_trades if t['realized_pnl'] == 0]

        total_gain = sum(t['realized_pnl'] for t in wins)
        total_loss = abs(sum(t['realized_pnl'] for t in losses))
        
        win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0
        profit_factor = (total_gain / total_loss) if total_loss > 0 else (total_gain if total_gain > 0 else 1.0)
        net_pnl = self.balance - self.initial_balance
        return_pct = (net_pnl / self.initial_balance) * 100

        margin_used = self.get_margin_in_use()
        free_capital = max(0.0, self.balance - margin_used)
        cooldown_sec = self.get_cooldown_remaining()

        return {
            'initial_balance': self.initial_balance,
            'current_balance': round(self.balance, 2),
            'margin_in_use': round(margin_used, 2),
            'free_capital': round(free_capital, 2),
            'total_equity': self.get_total_equity(current_price) if current_price > 0 else round(self.balance, 2),
            'net_pnl': round(net_pnl, 2),
            'return_pct': round(return_pct, 2),
            'total_trades': total_trades,
            'win_trades': len(wins),
            'loss_trades': len(losses),
            'breakeven_trades': len(breakevens),
            'win_rate_pct': round(win_rate, 1),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown_pct': self.max_drawdown,
            'active_trades_count': len(self.active_trades),
            'daily_trades_taken': self.daily_trades_count,
            'max_daily_trades': Config.MAX_DAILY_TRADES,
            'cooldown_remaining_sec': cooldown_sec
        }

    def execute_manual_trade(self, side: str, margin_amount: float, leverage: int = 25, 
                             entry_price: float = None, sl_price: float = None, tp_price: float = None,
                             symbol: str = "BTCUSD") -> tuple[bool, str, Optional[ActiveTrade]]:
        """Manually execute a paper trade from the user trading dock."""
        if len(self.active_trades) >= 1:
            return False, "An active trade is already open. Close it first or wait for target.", None
            
        if self.balance < margin_amount or margin_amount <= 0:
            return False, f"Insufficient margin balance. Available: ${self.balance:.2f}", None
            
        if not entry_price or entry_price <= 0:
            return False, "Invalid entry price.", None
            
        leverage = max(1, min(100, int(leverage)))
        position_value = margin_amount * leverage
        qty = round(position_value / entry_price, 5)
        
        # Default 1% SL distance if not specified
        if not sl_price or sl_price <= 0:
            if side == 'BUY':
                sl_price = round(entry_price * 0.99, 2)
            else:
                sl_price = round(entry_price * 1.01, 2)
                
        risk_per_unit = max(1.0, abs(entry_price - sl_price))
        risk_amount = qty * risk_per_unit
        
        # Targets calculation
        if side == 'BUY':
            stage_1_tp = round(entry_price + (risk_per_unit * 2.0), 2)
            stage_2_tp = tp_price if tp_price and tp_price > entry_price else round(entry_price + (risk_per_unit * 5.0), 2)
            stage_3_tp = round(entry_price + (risk_per_unit * 7.0), 2)
            stage_4_tp = round(entry_price + (risk_per_unit * 10.0), 2)
            stage_5_tp = round(entry_price + (risk_per_unit * 20.0), 2)
            stage_6_tp = round(entry_price + (risk_per_unit * 25.0), 2)
            sl_1_2_price = round(entry_price + (risk_per_unit * 2.0), 2)
            sl_1_5_price = round(entry_price + (risk_per_unit * 5.0), 2)
            sl_1_7_price = round(entry_price + (risk_per_unit * 7.0), 2)
            sl_1_15_price = round(entry_price + (risk_per_unit * 15.0), 2)
            sl_1_20_price = round(entry_price + (risk_per_unit * 20.0), 2)
        else:
            stage_1_tp = round(entry_price - (risk_per_unit * 2.0), 2)
            stage_2_tp = tp_price if tp_price and tp_price < entry_price else round(entry_price - (risk_per_unit * 5.0), 2)
            stage_3_tp = round(entry_price - (risk_per_unit * 7.0), 2)
            stage_4_tp = round(entry_price - (risk_per_unit * 10.0), 2)
            stage_5_tp = round(entry_price - (risk_per_unit * 20.0), 2)
            stage_6_tp = round(entry_price - (risk_per_unit * 25.0), 2)
            sl_1_2_price = round(entry_price - (risk_per_unit * 2.0), 2)
            sl_1_5_price = round(entry_price - (risk_per_unit * 5.0), 2)
            sl_1_7_price = round(entry_price - (risk_per_unit * 7.0), 2)
            sl_1_15_price = round(entry_price - (risk_per_unit * 15.0), 2)
            sl_1_20_price = round(entry_price - (risk_per_unit * 20.0), 2)
            
        signal = {
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'sl_price': sl_price,
            'risk_per_unit': risk_per_unit,
            'stage_1_tp': stage_1_tp,
            'stage_2_tp': stage_2_tp,
            'stage_3_tp': stage_3_tp,
            'stage_4_tp': stage_4_tp,
            'stage_5_tp': stage_5_tp,
            'stage_6_tp': stage_6_tp,
            'sl_1_2_price': sl_1_2_price,
            'sl_1_5_price': sl_1_5_price,
            'sl_1_7_price': sl_1_7_price,
            'sl_1_15_price': sl_1_15_price,
            'sl_1_20_price': sl_1_20_price,
            'leverage': leverage,
            'confidence_score': 1.0,
            'confidence_reasons': ['👤 Manual User Order'],
            'level_info': 'Manual Execution'
        }
        
        trade = ActiveTrade(signal, initial_qty=qty, margin_used=margin_amount, risk_amount=risk_amount)
        self.active_trades.append(trade)
        self.daily_trades_count += 1
        self._save_state()
        return True, "Trade executed successfully", trade

    def manual_close_trade(self, current_price: float, trade_id: str = None, reason: str = "Manual Market Exit") -> tuple[bool, str, Optional[Dict[str, Any]]]:
        """Manually close the active trade at market price."""
        if not self.active_trades:
            return False, "No active position to close.", None
            
        trade = self.active_trades[0]
        if trade_id and trade.trade_id != trade_id:
            return False, f"Trade ID {trade_id} not found.", None
            
        event = trade.manual_close(current_price, reason=reason)
        self.balance += trade.realized_pnl
        self.daily_realized_pnl += trade.realized_pnl
        self.last_trade_closed_time = time.time()
        self._record_closed_trade(trade)
        self.active_trades = []
        self._save_state()
        return True, f"Closed position with Net PnL: ${trade.realized_pnl:,.2f}", event

    def reset_account(self, new_balance: float = 10000.0):
        """Reset virtual paper trading balance and trade history."""
        self.initial_balance = new_balance
        self.balance = new_balance
        self.active_trades = []
        self.closed_trades = []
        self.daily_starting_balance = new_balance
        self.daily_realized_pnl = 0.0
        self.daily_trades_count = 0
        self.last_trade_closed_time = 0.0
        self.peak_balance = new_balance
        self.max_drawdown = 0.0
        self._save_state()
