"""
Multi-Stage Trade Manager Module
Manages:
- Position Sizing with Dynamic Leverage (20x-35x) and 1% risk per trade
- Capital Allocation Tracking (Initial, Margin Used, Position Value, Free Capital)
- Continuous Trailing Stop Loss & Partial Profit Booking:
    Stage 1: 1:2 RR hit -> Move SL to Cost to Cost (CTC / Breakeven)
    Stage 2: 1:5 RR hit -> Exit 50% Initial Qty & Shift SL to 1:2 RR
    Stage 3: 1:7 RR hit -> Shift SL to 1:5 RR (Locking in +5R profit)
    Stage 4: 1:10 RR hit -> Exit 40% Initial Qty & Shift SL to 1:7 RR (10% Runner remains)
    Stage 5: 1:20 RR hit -> Shift SL to 1:15 RR (+15R locked)
    Stage 6: 1:25 RR hit -> Shift SL to 1:20 RR (+20R locked)
    Stage 7+: Infinite +5R Trailing Ladder (1:30 -> SL 1:25, 1:35 -> SL 1:30...)
"""
import uuid
import pandas as pd
from typing import Dict, Any, Optional
from config import Config

class ActiveTrade:
    def __init__(self, signal: Dict[str, Any], initial_qty: float, margin_used: float, risk_amount: float):
        self.trade_id = str(uuid.uuid4())[:8]
        self.symbol = signal['symbol']
        self.side = signal['side']  # 'BUY' or 'SELL'
        self.entry_price = signal['entry_price']
        self.original_sl = signal['sl_price']
        self.current_sl = signal['sl_price']
        self.risk_per_unit = signal['risk_per_unit']
        
        # Target Price Levels
        self.stage_1_tp = signal['stage_1_tp']  # 1:2 RR (CTC Trigger)
        self.stage_2_tp = signal['stage_2_tp']  # 1:5 RR (50% Exit)
        self.stage_3_tp = signal['stage_3_tp']  # 1:7 RR (SL to 1:5)
        self.stage_4_tp = signal['stage_4_tp']  # 1:10 RR (40% Exit)
        self.stage_5_tp = signal['stage_5_tp']  # 1:20 RR (SL to 1:15)
        self.stage_6_tp = signal['stage_6_tp']  # 1:25 RR (SL to 1:20)
        
        self.sl_1_2_price = signal['sl_1_2_price']
        self.sl_1_5_price = signal['sl_1_5_price']
        self.sl_1_7_price = signal['sl_1_7_price']
        self.sl_1_15_price = signal['sl_1_15_price']
        self.sl_1_20_price = signal['sl_1_20_price']
        
        self.leverage = signal['leverage']
        self.confidence_score = signal['confidence_score']
        self.confidence_reasons = signal.get('confidence_reasons', [])
        self.level_info = signal['level_info']
        self.candle_a_high = signal.get('candle_a_high', 0.0)
        self.candle_a_low = signal.get('candle_a_low', 0.0)
        
        # Capital Allocation Tracking
        self.initial_qty = initial_qty
        self.remaining_qty = initial_qty
        self.margin_used = margin_used
        self.risk_amount = risk_amount
        self.position_value = initial_qty * self.entry_price

        
        self.entry_time = pd.Timestamp.now()
        self.exit_time = None
        
        # Stages:
        # 0: Open (SL at Candle A low/high)
        # 1: 1:2 RR Hit (SL @ CTC)
        # 2: 1:5 RR Hit (50% exited, SL @ 1:2)
        # 3: 1:7 RR Hit (SL @ 1:5)
        # 4: 1:10 RR Hit (40% exited, 10% runner, SL @ 1:7)
        # 5: 1:20 RR Hit (SL @ 1:15)
        # 6: 1:25 RR Hit (SL @ 1:20)
        # 7+: Infinite +5R Trail
        self.stage = 0
        self.max_rr_reached = 0.0
        self.realized_pnl = 0.0
        self.exit_reason = None
        self.is_closed = False
        self.history_logs = [f"[{self.entry_time.strftime('%H:%M:%S')}] Trade opened at ${self.entry_price} with {self.leverage}x leverage (Margin: ${self.margin_used:.2f} | Risk: ${self.risk_amount:.2f})."]

    def update_price(self, current_price: float) -> Optional[Dict[str, Any]]:
        """
        Check incoming price against SL, CTC, 1:2, 1:5, 1:7, 1:10, 1:20, 1:25+ RR stages.
        """
        if self.is_closed:
            return None

        now_str = pd.Timestamp.now().strftime('%H:%M:%S')

        if self.side == 'BUY':
            current_rr = max(0.0, (current_price - self.entry_price) / max(1.0, self.risk_per_unit))
            self.max_rr_reached = max(self.max_rr_reached, current_rr)

            # -------------------------------------------------------------
            # 1. Stop Loss Hit
            # -------------------------------------------------------------
            if current_price <= self.current_sl:
                loss_per_unit = current_price - self.entry_price
                exit_pnl = loss_per_unit * self.remaining_qty
                self.realized_pnl += exit_pnl
                self.remaining_qty = 0
                self.is_closed = True
                self.exit_time = pd.Timestamp.now()
                
                if self.stage == 0:
                    self.exit_reason = "Initial SL Hit (Candle A Low)"
                elif self.stage == 1:
                    self.exit_reason = "Cost-to-Cost (CTC Breakeven) Hit"
                elif self.stage == 2:
                    self.exit_reason = "Trailing SL Hit at 1:2 RR (+2R Locked)"
                elif self.stage == 3:
                    self.exit_reason = "Trailing SL Hit at 1:5 RR (+5R Locked)"
                elif self.stage == 4:
                    self.exit_reason = "Trailing SL Hit on 10% Runner at 1:7 RR (+7R Locked)"
                elif self.stage == 5:
                    self.exit_reason = "Trailing SL Hit on 10% Runner at 1:15 RR (+15R Locked)"
                elif self.stage == 6:
                    self.exit_reason = "Trailing SL Hit on 10% Runner at 1:20 RR (+20R Locked)"
                else:
                    self.exit_reason = f"Trailing SL Hit on Runner (+{self.max_rr_reached-5:.1f}R Locked)"
                    
                self.history_logs.append(f"[{self.exit_time.strftime('%H:%M:%S')}] {self.exit_reason} at ${current_price:.2f}. Total PnL: ${self.realized_pnl:.2f}")
                return {'event': 'TRADE_CLOSED', 'trade': self, 'pnl': self.realized_pnl, 'reason': self.exit_reason}

            # -------------------------------------------------------------
            # 2. Stage 1: 1:2 RR Hit -> Move SL to CTC
            # -------------------------------------------------------------
            if self.stage == 0 and current_price >= self.stage_1_tp:
                self.stage = 1
                self.current_sl = self.entry_price
                self.history_logs.append(f"[{now_str}] 🚀 1:2 RR Hit at ${current_price:.2f}! SL moved to Cost-to-Cost (${self.entry_price:.2f}). Risk-Free Trade!")
                return {'event': 'STAGE_1_CTC_SHIFT', 'trade': self, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 3. Stage 2: 1:5 RR Hit -> Exit 50% Qty & Shift SL to 1:2 RR
            # -------------------------------------------------------------
            if self.stage == 1 and current_price >= self.stage_2_tp:
                self.stage = 2
                exit_qty = round(self.initial_qty * 0.5, 6)
                gain_per_unit = current_price - self.entry_price
                partial_pnl = gain_per_unit * exit_qty
                self.realized_pnl += partial_pnl
                self.remaining_qty -= exit_qty
                self.current_sl = self.sl_1_2_price
                self.history_logs.append(f"[{now_str}] 💰 1:5 RR Hit at ${current_price:.2f}! Exited 50% qty (+${partial_pnl:.2f}). SL shifted to 1:2 RR (${self.current_sl:.2f}).")
                return {'event': 'STAGE_2_PARTIAL_EXIT', 'trade': self, 'partial_pnl': partial_pnl, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 4. Stage 3: 1:7 RR Hit -> Shift SL to 1:5 RR
            # -------------------------------------------------------------
            if self.stage == 2 and current_price >= self.stage_3_tp:
                self.stage = 3
                self.current_sl = self.sl_1_5_price
                self.history_logs.append(f"[{now_str}] 🔥 1:7 RR Hit at ${current_price:.2f}! SL moved to 1:5 RR (${self.current_sl:.2f}).")
                return {'event': 'STAGE_3_TRAIL_SHIFT', 'trade': self, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 5. Stage 4: 1:10 RR Hit -> Exit 40% Qty & Shift SL to 1:7 RR (10% Runner remains)
            # -------------------------------------------------------------
            if self.stage == 3 and current_price >= self.stage_4_tp:
                self.stage = 4
                exit_qty = round(self.initial_qty * 0.4, 6)
                gain_per_unit = current_price - self.entry_price
                partial_pnl = gain_per_unit * exit_qty
                self.realized_pnl += partial_pnl
                self.remaining_qty -= exit_qty
                self.current_sl = self.sl_1_7_price  # SL to 1:7
                self.history_logs.append(f"[{now_str}] 🎯 1:10 RR Hit at ${current_price:.2f}! Exited 40% qty (+${partial_pnl:.2f}). 10% Runner trailing with SL at 1:7 RR (${self.current_sl:.2f})!")
                return {'event': 'STAGE_4_PARTIAL_EXIT', 'trade': self, 'partial_pnl': partial_pnl, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 6. Stage 5: 1:20 RR Hit -> Shift SL to 1:15 RR
            # -------------------------------------------------------------
            if self.stage == 4 and current_price >= self.stage_5_tp:
                self.stage = 5
                self.current_sl = self.sl_1_15_price
                self.history_logs.append(f"[{now_str}] 🚀 1:20 RR Hit at ${current_price:.2f}! SL moved to 1:15 RR (${self.current_sl:.2f}).")
                return {'event': 'STAGE_5_TRAIL_SHIFT', 'trade': self, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 7. Stage 6: 1:25 RR Hit -> Shift SL to 1:20 RR
            # -------------------------------------------------------------
            if self.stage == 5 and current_price >= self.stage_6_tp:
                self.stage = 6
                self.current_sl = self.sl_1_20_price
                self.history_logs.append(f"[{now_str}] 💎 1:25 RR Hit at ${current_price:.2f}! SL moved to 1:20 RR (${self.current_sl:.2f}).")
                return {'event': 'STAGE_6_TRAIL_SHIFT', 'trade': self, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 8. Stage 7+: Dynamic +5R Trailing Ladder (1:30 -> SL 1:25, 1:35 -> SL 1:30...)
            # -------------------------------------------------------------
            if self.stage >= 6:
                next_ladder_rr = 25.0 + ((self.stage - 5) * 5.0)  # 30, 35, 40...
                if current_rr >= next_ladder_rr:
                    self.stage += 1
                    trail_rr = next_ladder_rr - 5.0
                    self.current_sl = round(self.entry_price + (self.risk_per_unit * trail_rr), 2)
                    self.history_logs.append(f"[{now_str}] 🏆 1:{next_ladder_rr:.0f} RR Hit at ${current_price:.2f}! SL dynamically trailed to 1:{trail_rr:.0f} RR (${self.current_sl:.2f})!")
                    return {'event': 'STAGE_LADDER_TRAIL', 'trade': self, 'new_sl': self.current_sl}

        elif self.side == 'SELL':
            current_rr = max(0.0, (self.entry_price - current_price) / max(1.0, self.risk_per_unit))
            self.max_rr_reached = max(self.max_rr_reached, current_rr)

            # -------------------------------------------------------------
            # 1. Stop Loss Hit
            # -------------------------------------------------------------
            if current_price >= self.current_sl:
                loss_per_unit = self.entry_price - current_price
                exit_pnl = loss_per_unit * self.remaining_qty
                self.realized_pnl += exit_pnl
                self.remaining_qty = 0
                self.is_closed = True
                self.exit_time = pd.Timestamp.now()
                
                if self.stage == 0:
                    self.exit_reason = "Initial SL Hit (Candle A High)"
                elif self.stage == 1:
                    self.exit_reason = "Cost-to-Cost (CTC Breakeven) Hit"
                elif self.stage == 2:
                    self.exit_reason = "Trailing SL Hit at 1:2 RR (+2R Locked)"
                elif self.stage == 3:
                    self.exit_reason = "Trailing SL Hit at 1:5 RR (+5R Locked)"
                elif self.stage == 4:
                    self.exit_reason = "Trailing SL Hit on 10% Runner at 1:7 RR (+7R Locked)"
                elif self.stage == 5:
                    self.exit_reason = "Trailing SL Hit on 10% Runner at 1:15 RR (+15R Locked)"
                elif self.stage == 6:
                    self.exit_reason = "Trailing SL Hit on 10% Runner at 1:20 RR (+20R Locked)"
                else:
                    self.exit_reason = f"Trailing SL Hit on Runner (+{self.max_rr_reached-5:.1f}R Locked)"
                    
                self.history_logs.append(f"[{self.exit_time.strftime('%H:%M:%S')}] {self.exit_reason} at ${current_price:.2f}. Total PnL: ${self.realized_pnl:.2f}")
                return {'event': 'TRADE_CLOSED', 'trade': self, 'pnl': self.realized_pnl, 'reason': self.exit_reason}

            # -------------------------------------------------------------
            # 2. Stage 1: 1:2 RR Hit -> Move SL to CTC
            # -------------------------------------------------------------
            if self.stage == 0 and current_price <= self.stage_1_tp:
                self.stage = 1
                self.current_sl = self.entry_price
                self.history_logs.append(f"[{now_str}] 🚀 1:2 RR Hit at ${current_price:.2f}! SL moved to CTC (${self.entry_price:.2f}).")
                return {'event': 'STAGE_1_CTC_SHIFT', 'trade': self, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 3. Stage 2: 1:5 RR Hit -> Exit 50% Qty & Shift SL to 1:2 RR
            # -------------------------------------------------------------
            if self.stage == 1 and current_price <= self.stage_2_tp:
                self.stage = 2
                exit_qty = round(self.initial_qty * 0.5, 6)
                gain_per_unit = self.entry_price - current_price
                partial_pnl = gain_per_unit * exit_qty
                self.realized_pnl += partial_pnl
                self.remaining_qty -= exit_qty
                self.current_sl = self.sl_1_2_price
                self.history_logs.append(f"[{now_str}] 💰 1:5 RR Hit at ${current_price:.2f}! Exited 50% qty (+${partial_pnl:.2f}). SL shifted to 1:2 RR (${self.current_sl:.2f}).")
                return {'event': 'STAGE_2_PARTIAL_EXIT', 'trade': self, 'partial_pnl': partial_pnl, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 4. Stage 3: 1:7 RR Hit -> Shift SL to 1:5 RR
            # -------------------------------------------------------------
            if self.stage == 2 and current_price <= self.stage_3_tp:
                self.stage = 3
                self.current_sl = self.sl_1_5_price
                self.history_logs.append(f"[{now_str}] 🔥 1:7 RR Hit at ${current_price:.2f}! SL moved to 1:5 RR.")
                return {'event': 'STAGE_3_TRAIL_SHIFT', 'trade': self, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 5. Stage 4: 1:10 RR Hit -> Exit 40% Qty & Shift SL to 1:7 RR (10% Runner remains)
            # -------------------------------------------------------------
            if self.stage == 3 and current_price <= self.stage_4_tp:
                self.stage = 4
                exit_qty = round(self.initial_qty * 0.4, 6)
                gain_per_unit = self.entry_price - current_price
                partial_pnl = gain_per_unit * exit_qty
                self.realized_pnl += partial_pnl
                self.remaining_qty -= exit_qty
                self.current_sl = self.sl_1_7_price  # SL to 1:7
                self.history_logs.append(f"[{now_str}] 🎯 1:10 RR Hit at ${current_price:.2f}! Exited 40% qty (+${partial_pnl:.2f}). 10% Runner trailing with SL at 1:7 RR!")
                return {'event': 'STAGE_4_PARTIAL_EXIT', 'trade': self, 'partial_pnl': partial_pnl, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 6. Stage 5: 1:20 RR Hit -> Shift SL to 1:15 RR
            # -------------------------------------------------------------
            if self.stage == 4 and current_price <= self.stage_5_tp:
                self.stage = 5
                self.current_sl = self.sl_1_15_price
                self.history_logs.append(f"[{now_str}] 🚀 1:20 RR Hit at ${current_price:.2f}! SL moved to 1:15 RR (${self.current_sl:.2f}).")
                return {'event': 'STAGE_5_TRAIL_SHIFT', 'trade': self, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 7. Stage 6: 1:25 RR Hit -> Shift SL to 1:20 RR
            # -------------------------------------------------------------
            if self.stage == 5 and current_price <= self.stage_6_tp:
                self.stage = 6
                self.current_sl = self.sl_1_20_price
                self.history_logs.append(f"[{now_str}] 💎 1:25 RR Hit at ${current_price:.2f}! SL moved to 1:20 RR (${self.current_sl:.2f}).")
                return {'event': 'STAGE_6_TRAIL_SHIFT', 'trade': self, 'new_sl': self.current_sl}

            # -------------------------------------------------------------
            # 8. Stage 7+: Dynamic +5R Trailing Ladder
            # -------------------------------------------------------------
            if self.stage >= 6:
                next_ladder_rr = 25.0 + ((self.stage - 5) * 5.0)
                if current_rr >= next_ladder_rr:
                    self.stage += 1
                    trail_rr = next_ladder_rr - 5.0
                    self.current_sl = round(self.entry_price - (self.risk_per_unit * trail_rr), 2)
                    self.history_logs.append(f"[{now_str}] 🏆 1:{next_ladder_rr:.0f} RR Hit at ${current_price:.2f}! SL dynamically trailed to 1:{trail_rr:.0f} RR (${self.current_sl:.2f})!")
                    return {'event': 'STAGE_LADDER_TRAIL', 'trade': self, 'new_sl': self.current_sl}

        return None

    def get_unrealized_pnl(self, current_price: float) -> float:
        """Calculate live unrealized PnL on remaining open quantity."""
        if self.is_closed or self.remaining_qty <= 0:
            return 0.0
        if self.side == 'BUY':
            return (current_price - self.entry_price) * self.remaining_qty
        else:
            return (self.entry_price - current_price) * self.remaining_qty
