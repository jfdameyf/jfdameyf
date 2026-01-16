"""
ES ALGO ASSISTANT - BACKTEST: EXIT MONITOR COMPARISON

Compares trading performance:
1. WITH order flow-based exit monitoring (dynamic exits)
2. WITHOUT exit monitoring (fixed stop loss / take profit)

This helps evaluate whether the exit monitoring system adds value.
"""

import pandas as pd
import numpy as np
import databento as db
import json
import os
import sys
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import pytz
import warnings
import logging
from enum import Enum

warnings.filterwarnings('ignore')

# ==============================================================================
# CONFIGURATION
# ==============================================================================

API_KEY = os.getenv("DATABENTO_API_KEY", "")
NY_TZ = pytz.timezone('America/New_York')

# Strategy Parameters (match live bot)
LEVEL_ABS_THRESH = 6000
LEVEL_DELTA_THRESH = 700
LEVEL_TIMEFRAME = 2

BLIND_ABS_THRESH = 8000
BLIND_DELTA_THRESH = 700

LEVEL_TOLERANCE = 3.0

# Exit Monitor Parameters
EXIT_COUNTER_ABS_THRESH = 4000
EXIT_DELTA_REVERSAL_BARS = 3
EXIT_DELTA_REVERSAL_THRESH = 500
EXIT_FAILED_FOLLOWTHROUGH_BARS = 5
EXIT_FAILED_FOLLOWTHROUGH_PTS = 2.0
EXIT_EXHAUSTION_DECAY_PCT = 0.5
EXIT_EXHAUSTION_MIN_BARS = 3
EXIT_DIVERGENCE_BARS = 4

# Fixed Exit Parameters (for comparison - NO exit monitor)
FIXED_STOP_LOSS_PTS = 4.0      # Fixed stop loss in points
FIXED_TAKE_PROFIT_PTS = 8.0    # Fixed take profit in points
FIXED_TIME_STOP_BARS = 15      # Exit after N bars if no target hit

# Backtest Settings
SYMBOL = "ES.c.0"
CONTEXT_FILE = "daily_context_v2.json"
LEVELS_FILE = "critical_levels_master_enhanced.csv"

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)


# ==============================================================================
# DATA STRUCTURES
# ==============================================================================

class ExitReason(Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIME_STOP = "TIME_STOP"
    COUNTER_ABSORPTION = "COUNTER_ABSORPTION"
    DELTA_REVERSAL = "DELTA_REVERSAL"
    FAILED_FOLLOWTHROUGH = "FAILED_FOLLOWTHROUGH"
    EXHAUSTION = "EXHAUSTION"
    TARGET_REACHED = "TARGET_REACHED"
    DIVERGENCE = "DIVERGENCE"
    END_OF_DATA = "END_OF_DATA"


@dataclass
class BacktestTrade:
    """Represents a completed trade for analysis."""
    entry_time: datetime
    exit_time: datetime
    direction: str  # 'LONG' or 'SHORT'
    entry_price: float
    exit_price: float
    pnl_points: float
    exit_reason: ExitReason
    bars_held: int
    max_favorable_excursion: float  # Best price reached
    max_adverse_excursion: float    # Worst price reached
    entry_absorption: int
    entry_delta: int
    signal_source: str


@dataclass
class BacktestPosition:
    """Active position during backtest."""
    position_id: str
    direction: str
    entry_price: float
    entry_time: datetime
    entry_absorption: int
    entry_delta: int
    signal_source: str
    target_level: Optional[float] = None

    # Tracking
    bars_held: int = 0
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    delta_history: List[int] = field(default_factory=list)
    price_history: List[float] = field(default_factory=list)

    # Counter-absorption tracking
    counter_absorption: int = 0

    def __post_init__(self):
        self.max_favorable = self.entry_price
        self.max_adverse = self.entry_price


@dataclass
class BacktestResults:
    """Aggregated backtest results."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    max_drawdown: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_bars_held: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    avg_mfe: float = 0.0  # Average max favorable excursion
    avg_mae: float = 0.0  # Average max adverse excursion
    exit_breakdown: Dict[str, int] = field(default_factory=dict)
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)


# ==============================================================================
# ABSORPTION MONITOR (Simplified for backtest)
# ==============================================================================

class BacktestAbsorptionMonitor:
    """Simplified absorption monitor for backtesting."""

    def __init__(self, price_key: float, level_type: str, threshold: int):
        self.price_key = price_key
        self.level_type = level_type
        self.threshold = threshold
        self.cumulative_vol = 0
        self.state = "WATCHING"
        self.last_update = None

    def update(self, size: int, side: str, ts: datetime):
        # Check for reset (10 min timeout)
        if self.last_update and (ts - self.last_update).total_seconds() > 600:
            self.cumulative_vol = 0
            self.state = "WATCHING"
        self.last_update = ts

        # Track opposing flow
        is_opposing = (self.level_type == 'SUP' and side == 'B') or \
                      (self.level_type == 'RES' and side == 'A')
        if is_opposing:
            self.cumulative_vol += size

        if self.state == "WATCHING" and self.cumulative_vol >= self.threshold:
            self.state = "ABSORBING"

    def reset(self):
        self.cumulative_vol = 0
        self.state = "WATCHING"


# ==============================================================================
# BACKTEST ENGINE
# ==============================================================================

class BacktestEngine:
    """
    Runs backtest with configurable exit strategy.
    """

    def __init__(self, use_exit_monitor: bool = True):
        self.use_exit_monitor = use_exit_monitor
        self.positions: Dict[str, BacktestPosition] = {}
        self.completed_trades: List[BacktestTrade] = []
        self.position_counter = 0

        # Level monitors
        self.level_monitors: Dict[str, BacktestAbsorptionMonitor] = {}
        self.grid_monitors: Dict[float, Dict[str, BacktestAbsorptionMonitor]] = {}

        # Candle tracking
        self.candle_time: Optional[datetime] = None
        self.candle_delta = 0
        self.last_candle_delta = 0
        self.current_price = 0.0

        # Context levels
        self.support_levels: List[float] = []
        self.resistance_levels: List[float] = []

        # Equity tracking
        self.equity = 0.0
        self.peak_equity = 0.0
        self.max_drawdown = 0.0
        self.equity_curve: List[float] = []

    def load_levels(self, levels_file: str, context_file: str):
        """Load trading levels from files."""
        # Load from CSV
        if os.path.exists(levels_file):
            df = pd.read_csv(levels_file)
            if 'price' in df.columns:
                all_levels = df['price'].tolist()
                # We'll classify based on current price during backtest
                self.all_levels = all_levels
                logger.info(f"Loaded {len(all_levels)} levels from {levels_file}")

        # Load from context file
        if os.path.exists(context_file):
            try:
                with open(context_file, 'r') as f:
                    data = json.load(f)
                    if data:
                        latest = data[list(data.keys())[-1]]
                        levels = latest.get('levels', {})
                        for l in levels.get('raw_sup', []):
                            if 'price' in l:
                                self.support_levels.append(l['price'])
                        for l in levels.get('raw_res', []):
                            if 'price' in l:
                                self.resistance_levels.append(l['price'])
                logger.info(f"Context: {len(self.support_levels)} support, {len(self.resistance_levels)} resistance")
            except Exception as e:
                logger.warning(f"Could not load context: {e}")

        # Initialize level monitors
        for price in self.support_levels:
            key = f"{price}_SUP"
            self.level_monitors[key] = BacktestAbsorptionMonitor(price, 'SUP', LEVEL_ABS_THRESH)
        for price in self.resistance_levels:
            key = f"{price}_RES"
            self.level_monitors[key] = BacktestAbsorptionMonitor(price, 'RES', LEVEL_ABS_THRESH)

    def _find_target(self, entry_price: float, direction: str) -> Optional[float]:
        """Find target level for position."""
        if direction == 'LONG':
            for level in sorted(self.resistance_levels):
                if level > entry_price + 2.0:
                    return level
        else:
            for level in sorted(self.support_levels, reverse=True):
                if level < entry_price - 2.0:
                    return level
        return None

    def _floor_candle(self, ts: datetime) -> datetime:
        """Floor timestamp to candle boundary."""
        minute = (ts.minute // LEVEL_TIMEFRAME) * LEVEL_TIMEFRAME
        return ts.replace(minute=minute, second=0, microsecond=0)

    def process_tick(self, price: float, size: int, side: str, ts: datetime):
        """Process a single tick."""
        self.current_price = price

        # Handle candle boundaries
        candle_now = self._floor_candle(ts)
        if self.candle_time is None:
            self.candle_time = candle_now

        if candle_now > self.candle_time:
            # Candle closed - check signals and exits
            self.last_candle_delta = self.candle_delta
            self._on_candle_close(ts)
            self.candle_time = candle_now
            self.candle_delta = 0

        # Update candle delta
        if side == 'A':
            self.candle_delta += size
        else:
            self.candle_delta -= size

        # Update level monitors
        for key, monitor in self.level_monitors.items():
            if abs(price - monitor.price_key) <= LEVEL_TOLERANCE:
                monitor.update(size, side, ts)

        # Update grid monitors
        grid_key = round(price / 2.0) * 2.0
        if grid_key not in self.grid_monitors:
            self.grid_monitors[grid_key] = {
                'SUP': BacktestAbsorptionMonitor(grid_key, 'SUP', BLIND_ABS_THRESH),
                'RES': BacktestAbsorptionMonitor(grid_key, 'RES', BLIND_ABS_THRESH)
            }
        self.grid_monitors[grid_key]['SUP'].update(size, side, ts)
        self.grid_monitors[grid_key]['RES'].update(size, side, ts)

        # Update position tracking (for exit monitor mode)
        if self.use_exit_monitor:
            self._update_position_tick(price, size, side, ts)

    def _update_position_tick(self, price: float, size: int, side: str, ts: datetime):
        """Update positions on each tick (exit monitor mode)."""
        for pos_id, pos in self.positions.items():
            # Update MFE/MAE
            if pos.direction == 'LONG':
                pos.max_favorable = max(pos.max_favorable, price)
                pos.max_adverse = min(pos.max_adverse, price)
                # Track counter-absorption (buyers absorbed above = resistance forming)
                if price > pos.entry_price + 2.0 and side == 'A':
                    pos.counter_absorption += size
            else:
                pos.max_favorable = min(pos.max_favorable, price)
                pos.max_adverse = max(pos.max_adverse, price)
                # Track counter-absorption (sellers absorbed below = support forming)
                if price < pos.entry_price - 2.0 and side == 'B':
                    pos.counter_absorption += size

    def _on_candle_close(self, ts: datetime):
        """Process candle close - check entries and exits."""
        # Check for new entry signals
        self._check_entry_signals(ts)

        # Update positions and check exits
        positions_to_close = []

        for pos_id, pos in self.positions.items():
            pos.bars_held += 1
            pos.delta_history.append(self.last_candle_delta)
            pos.price_history.append(self.current_price)

            # Keep history bounded
            if len(pos.delta_history) > 20:
                pos.delta_history.pop(0)
            if len(pos.price_history) > 20:
                pos.price_history.pop(0)

            # Check exit conditions
            exit_reason = self._check_exit(pos)
            if exit_reason:
                positions_to_close.append((pos_id, exit_reason))

        # Close positions
        for pos_id, reason in positions_to_close:
            self._close_position(pos_id, reason, ts)

    def _check_entry_signals(self, ts: datetime):
        """Check for entry signals."""
        # Skip if we already have a position (single position mode for simplicity)
        if self.positions:
            return

        # Check level monitors
        for key, monitor in self.level_monitors.items():
            if monitor.state == "ABSORBING":
                l_type = 'SUP' if '_SUP' in key else 'RES'

                # Check delta confirmation
                if l_type == 'SUP' and self.last_candle_delta >= LEVEL_DELTA_THRESH:
                    self._open_position('LONG', monitor.price_key, ts,
                                       monitor.cumulative_vol, self.last_candle_delta, 'LEVEL')
                    monitor.reset()
                    return
                elif l_type == 'RES' and self.last_candle_delta <= -LEVEL_DELTA_THRESH:
                    self._open_position('SHORT', monitor.price_key, ts,
                                       monitor.cumulative_vol, self.last_candle_delta, 'LEVEL')
                    monitor.reset()
                    return

        # Check grid monitors
        for grid_price, pair in self.grid_monitors.items():
            for l_type, monitor in pair.items():
                if monitor.state == "ABSORBING":
                    if l_type == 'SUP' and self.last_candle_delta >= BLIND_DELTA_THRESH:
                        self._open_position('LONG', grid_price, ts,
                                           monitor.cumulative_vol, self.last_candle_delta, 'GRID')
                        monitor.reset()
                        return
                    elif l_type == 'RES' and self.last_candle_delta <= -BLIND_DELTA_THRESH:
                        self._open_position('SHORT', grid_price, ts,
                                           monitor.cumulative_vol, self.last_candle_delta, 'GRID')
                        monitor.reset()
                        return

    def _open_position(self, direction: str, price: float, ts: datetime,
                      absorption: int, delta: int, source: str):
        """Open a new position."""
        self.position_counter += 1
        pos_id = f"BT_{self.position_counter}"

        target = self._find_target(price, direction)

        self.positions[pos_id] = BacktestPosition(
            position_id=pos_id,
            direction=direction,
            entry_price=price,
            entry_time=ts,
            entry_absorption=absorption,
            entry_delta=delta,
            signal_source=source,
            target_level=target,
            max_favorable=price,
            max_adverse=price
        )

    def _check_exit(self, pos: BacktestPosition) -> Optional[ExitReason]:
        """Check if position should be exited."""
        price = self.current_price

        # Calculate current P&L
        if pos.direction == 'LONG':
            pnl = price - pos.entry_price
        else:
            pnl = pos.entry_price - price

        if self.use_exit_monitor:
            return self._check_exit_monitor(pos, price, pnl)
        else:
            return self._check_exit_fixed(pos, price, pnl)

    def _check_exit_fixed(self, pos: BacktestPosition, price: float, pnl: float) -> Optional[ExitReason]:
        """Fixed stop/target exit strategy."""
        # Stop loss
        if pnl <= -FIXED_STOP_LOSS_PTS:
            return ExitReason.STOP_LOSS

        # Take profit
        if pnl >= FIXED_TAKE_PROFIT_PTS:
            return ExitReason.TAKE_PROFIT

        # Time stop
        if pos.bars_held >= FIXED_TIME_STOP_BARS:
            return ExitReason.TIME_STOP

        return None

    def _check_exit_monitor(self, pos: BacktestPosition, price: float, pnl: float) -> Optional[ExitReason]:
        """Order flow-based exit strategy."""

        # 1. COUNTER-ABSORPTION
        if pos.counter_absorption >= EXIT_COUNTER_ABS_THRESH:
            return ExitReason.COUNTER_ABSORPTION

        # 2. DELTA REVERSAL
        if len(pos.delta_history) >= EXIT_DELTA_REVERSAL_BARS:
            recent = pos.delta_history[-EXIT_DELTA_REVERSAL_BARS:]
            if pos.direction == 'LONG':
                if all(d <= -EXIT_DELTA_REVERSAL_THRESH for d in recent):
                    return ExitReason.DELTA_REVERSAL
            else:
                if all(d >= EXIT_DELTA_REVERSAL_THRESH for d in recent):
                    return ExitReason.DELTA_REVERSAL

        # 3. FAILED FOLLOW-THROUGH
        if pos.bars_held >= EXIT_FAILED_FOLLOWTHROUGH_BARS:
            if pos.direction == 'LONG':
                progress = pos.max_favorable - pos.entry_price
            else:
                progress = pos.entry_price - pos.max_favorable
            if progress < EXIT_FAILED_FOLLOWTHROUGH_PTS:
                return ExitReason.FAILED_FOLLOWTHROUGH

        # Profit-taking only if profitable
        if pnl <= 0:
            return None

        # 4. EXHAUSTION
        if len(pos.delta_history) >= EXIT_EXHAUSTION_MIN_BARS and pos.entry_delta != 0:
            recent = pos.delta_history[-EXIT_EXHAUSTION_MIN_BARS:]
            if pos.direction == 'LONG' and pos.entry_delta > 0:
                avg = sum(max(0, d) for d in recent) / len(recent)
                decay = avg / pos.entry_delta
                extended = price > pos.entry_price + 3.0
                if decay < EXIT_EXHAUSTION_DECAY_PCT and extended:
                    return ExitReason.EXHAUSTION
            elif pos.direction == 'SHORT' and pos.entry_delta < 0:
                avg = sum(min(0, d) for d in recent) / len(recent)
                decay = avg / pos.entry_delta
                extended = price < pos.entry_price - 3.0
                if decay < EXIT_EXHAUSTION_DECAY_PCT and extended:
                    return ExitReason.EXHAUSTION

        # 5. TARGET REACHED
        if pos.target_level:
            dist = abs(price - pos.target_level)
            if dist <= 3.0:
                return ExitReason.TARGET_REACHED

        # 6. DIVERGENCE
        if len(pos.delta_history) >= EXIT_DIVERGENCE_BARS:
            prices = pos.price_history[-EXIT_DIVERGENCE_BARS:]
            deltas = pos.delta_history[-EXIT_DIVERGENCE_BARS:]

            if pos.direction == 'LONG':
                price_up = prices[-1] > prices[0]
                peaks = [d for d in deltas if d > 0]
                if len(peaks) >= 2 and price_up:
                    if peaks[-1] < peaks[0] * 0.7:
                        return ExitReason.DIVERGENCE
            else:
                price_down = prices[-1] < prices[0]
                troughs = [d for d in deltas if d < 0]
                if len(troughs) >= 2 and price_down:
                    if troughs[-1] > troughs[0] * 0.7:
                        return ExitReason.DIVERGENCE

        return None

    def _close_position(self, pos_id: str, reason: ExitReason, ts: datetime):
        """Close a position and record the trade."""
        pos = self.positions.pop(pos_id)

        exit_price = self.current_price
        if pos.direction == 'LONG':
            pnl = exit_price - pos.entry_price
            mfe = pos.max_favorable - pos.entry_price
            mae = pos.entry_price - pos.max_adverse
        else:
            pnl = pos.entry_price - exit_price
            mfe = pos.entry_price - pos.max_favorable
            mae = pos.max_adverse - pos.entry_price

        trade = BacktestTrade(
            entry_time=pos.entry_time,
            exit_time=ts,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            pnl_points=pnl,
            exit_reason=reason,
            bars_held=pos.bars_held,
            max_favorable_excursion=mfe,
            max_adverse_excursion=mae,
            entry_absorption=pos.entry_absorption,
            entry_delta=pos.entry_delta,
            signal_source=pos.signal_source
        )

        self.completed_trades.append(trade)

        # Update equity
        self.equity += pnl
        self.equity_curve.append(self.equity)
        self.peak_equity = max(self.peak_equity, self.equity)
        drawdown = self.peak_equity - self.equity
        self.max_drawdown = max(self.max_drawdown, drawdown)

    def finalize(self, ts: datetime):
        """Close any remaining positions at end of data."""
        for pos_id in list(self.positions.keys()):
            self._close_position(pos_id, ExitReason.END_OF_DATA, ts)

    def get_results(self) -> BacktestResults:
        """Calculate and return backtest results."""
        results = BacktestResults()
        results.trades = self.completed_trades
        results.equity_curve = self.equity_curve

        if not self.completed_trades:
            return results

        results.total_trades = len(self.completed_trades)

        wins = [t for t in self.completed_trades if t.pnl_points > 0]
        losses = [t for t in self.completed_trades if t.pnl_points <= 0]

        results.winning_trades = len(wins)
        results.losing_trades = len(losses)
        results.total_pnl = sum(t.pnl_points for t in self.completed_trades)
        results.gross_profit = sum(t.pnl_points for t in wins) if wins else 0
        results.gross_loss = abs(sum(t.pnl_points for t in losses)) if losses else 0
        results.max_drawdown = self.max_drawdown

        results.avg_win = results.gross_profit / len(wins) if wins else 0
        results.avg_loss = results.gross_loss / len(losses) if losses else 0
        results.avg_bars_held = sum(t.bars_held for t in self.completed_trades) / len(self.completed_trades)

        results.profit_factor = results.gross_profit / results.gross_loss if results.gross_loss > 0 else float('inf')
        results.win_rate = results.winning_trades / results.total_trades if results.total_trades > 0 else 0

        results.avg_mfe = sum(t.max_favorable_excursion for t in self.completed_trades) / len(self.completed_trades)
        results.avg_mae = sum(t.max_adverse_excursion for t in self.completed_trades) / len(self.completed_trades)

        # Exit breakdown
        for trade in self.completed_trades:
            reason = trade.exit_reason.value
            results.exit_breakdown[reason] = results.exit_breakdown.get(reason, 0) + 1

        return results


# ==============================================================================
# DATA LOADING
# ==============================================================================

def load_historical_data(start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """Load historical tick data from Databento."""
    if not API_KEY:
        logger.error("DATABENTO_API_KEY not set")
        return None

    try:
        client = db.Historical(API_KEY)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        logger.info(f"Fetching tick data from {start_date} to {end_date}...")

        data = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            schema="trades",
            symbols=[SYMBOL],
            stype_in="continuous",
            start=start_dt,
            end=end_dt
        )

        df = data.to_df()

        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        df = df.tz_convert(NY_TZ)

        # Filter to RTH only (9:30 AM - 4:00 PM ET)
        df = df.between_time('09:30', '16:00')

        logger.info(f"Loaded {len(df):,} ticks")
        return df

    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        return None


# ==============================================================================
# REPORT GENERATION
# ==============================================================================

def print_results(results: BacktestResults, label: str):
    """Print formatted results."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Total Trades:      {results.total_trades}")
    print(f"  Win Rate:          {results.win_rate:.1%}")
    print(f"  Winning Trades:    {results.winning_trades}")
    print(f"  Losing Trades:     {results.losing_trades}")
    print(f"  ")
    print(f"  Total P&L:         {results.total_pnl:+.2f} pts")
    print(f"  Gross Profit:      {results.gross_profit:+.2f} pts")
    print(f"  Gross Loss:        {results.gross_loss:-.2f} pts")
    print(f"  Profit Factor:     {results.profit_factor:.2f}")
    print(f"  Max Drawdown:      {results.max_drawdown:.2f} pts")
    print(f"  ")
    print(f"  Avg Win:           {results.avg_win:+.2f} pts")
    print(f"  Avg Loss:          {results.avg_loss:-.2f} pts")
    print(f"  Avg Bars Held:     {results.avg_bars_held:.1f}")
    print(f"  Avg MFE:           {results.avg_mfe:+.2f} pts")
    print(f"  Avg MAE:           {results.avg_mae:-.2f} pts")
    print(f"  ")
    print(f"  Exit Breakdown:")
    for reason, count in sorted(results.exit_breakdown.items()):
        pct = count / results.total_trades * 100 if results.total_trades > 0 else 0
        print(f"    {reason:25s} {count:4d} ({pct:5.1f}%)")


def print_comparison(with_monitor: BacktestResults, without_monitor: BacktestResults):
    """Print side-by-side comparison."""
    print(f"\n{'='*70}")
    print(f"  COMPARISON: EXIT MONITOR vs FIXED STOPS")
    print(f"{'='*70}")
    print(f"  {'Metric':<25} {'With Monitor':>18} {'Fixed Stops':>18}")
    print(f"  {'-'*65}")

    def fmt(val, is_pct=False, is_pts=False):
        if is_pct:
            return f"{val:.1%}"
        elif is_pts:
            return f"{val:+.2f}"
        else:
            return f"{val:.2f}"

    metrics = [
        ("Total Trades", with_monitor.total_trades, without_monitor.total_trades, False, False),
        ("Win Rate", with_monitor.win_rate, without_monitor.win_rate, True, False),
        ("Total P&L (pts)", with_monitor.total_pnl, without_monitor.total_pnl, False, True),
        ("Profit Factor", with_monitor.profit_factor, without_monitor.profit_factor, False, False),
        ("Max Drawdown (pts)", with_monitor.max_drawdown, without_monitor.max_drawdown, False, False),
        ("Avg Win (pts)", with_monitor.avg_win, without_monitor.avg_win, False, True),
        ("Avg Loss (pts)", with_monitor.avg_loss, without_monitor.avg_loss, False, False),
        ("Avg Bars Held", with_monitor.avg_bars_held, without_monitor.avg_bars_held, False, False),
        ("Avg MFE (pts)", with_monitor.avg_mfe, without_monitor.avg_mfe, False, True),
        ("Avg MAE (pts)", with_monitor.avg_mae, without_monitor.avg_mae, False, False),
    ]

    for name, val1, val2, is_pct, is_pts in metrics:
        v1 = fmt(val1, is_pct, is_pts)
        v2 = fmt(val2, is_pct, is_pts)

        # Highlight winner
        if name in ["Win Rate", "Total P&L (pts)", "Profit Factor", "Avg Win (pts)", "Avg MFE (pts)"]:
            better = ">" if val1 > val2 else "<" if val2 > val1 else "="
        elif name in ["Max Drawdown (pts)", "Avg Loss (pts)", "Avg MAE (pts)"]:
            better = "<" if val1 < val2 else ">" if val2 < val1 else "="
        else:
            better = "="

        indicator = " *" if better != "=" else ""
        print(f"  {name:<25} {v1:>18} {v2:>18}{indicator}")

    print(f"  {'-'*65}")
    print(f"  * indicates better performance")

    # Net improvement
    pnl_diff = with_monitor.total_pnl - without_monitor.total_pnl
    print(f"\n  P&L Difference: {pnl_diff:+.2f} pts {'(Exit Monitor better)' if pnl_diff > 0 else '(Fixed Stops better)'}")


def save_trades_to_csv(results: BacktestResults, filename: str):
    """Save trade details to CSV."""
    if not results.trades:
        return

    rows = []
    for t in results.trades:
        rows.append({
            'entry_time': t.entry_time.strftime('%Y-%m-%d %H:%M:%S'),
            'exit_time': t.exit_time.strftime('%Y-%m-%d %H:%M:%S'),
            'direction': t.direction,
            'entry_price': t.entry_price,
            'exit_price': t.exit_price,
            'pnl_points': t.pnl_points,
            'exit_reason': t.exit_reason.value,
            'bars_held': t.bars_held,
            'mfe': t.max_favorable_excursion,
            'mae': t.max_adverse_excursion,
            'entry_absorption': t.entry_absorption,
            'entry_delta': t.entry_delta,
            'signal_source': t.signal_source
        })

    df = pd.DataFrame(rows)
    df.to_csv(filename, index=False)
    logger.info(f"Saved {len(rows)} trades to {filename}")


# ==============================================================================
# MAIN
# ==============================================================================

def run_backtest(start_date: str, end_date: str, save_trades: bool = True):
    """Run full backtest comparison."""

    print("\n" + "="*70)
    print("  ES ALGO ASSISTANT - EXIT MONITOR BACKTEST")
    print("="*70)
    print(f"  Period: {start_date} to {end_date}")
    print(f"  ")
    print(f"  Strategy Parameters:")
    print(f"    Level Absorption:    {LEVEL_ABS_THRESH}")
    print(f"    Level Delta:         {LEVEL_DELTA_THRESH}")
    print(f"    Grid Absorption:     {BLIND_ABS_THRESH}")
    print(f"    Grid Delta:          {BLIND_DELTA_THRESH}")
    print(f"  ")
    print(f"  Exit Monitor Parameters:")
    print(f"    Counter-Absorption:  {EXIT_COUNTER_ABS_THRESH}")
    print(f"    Delta Reversal:      {EXIT_DELTA_REVERSAL_BARS} bars @ {EXIT_DELTA_REVERSAL_THRESH}")
    print(f"    Failed Follow-through: {EXIT_FAILED_FOLLOWTHROUGH_BARS} bars / {EXIT_FAILED_FOLLOWTHROUGH_PTS}pts")
    print(f"    Exhaustion Decay:    {EXIT_EXHAUSTION_DECAY_PCT:.0%}")
    print(f"  ")
    print(f"  Fixed Exit Parameters (for comparison):")
    print(f"    Stop Loss:           {FIXED_STOP_LOSS_PTS} pts")
    print(f"    Take Profit:         {FIXED_TAKE_PROFIT_PTS} pts")
    print(f"    Time Stop:           {FIXED_TIME_STOP_BARS} bars")

    # Load data
    df = load_historical_data(start_date, end_date)
    if df is None or df.empty:
        print("\nNo data available for backtest.")
        return

    # Run WITH exit monitor
    print("\n[1/2] Running backtest WITH Exit Monitor...")
    engine_with = BacktestEngine(use_exit_monitor=True)
    engine_with.load_levels(LEVELS_FILE, CONTEXT_FILE)

    for idx, row in df.iterrows():
        price = row['price'] / 1e9 if row['price'] > 10000 else row['price']
        size = row['size']
        side = row['side']
        engine_with.process_tick(price, size, side, idx)

    engine_with.finalize(df.index[-1])
    results_with = engine_with.get_results()

    # Run WITHOUT exit monitor
    print("[2/2] Running backtest WITHOUT Exit Monitor (Fixed Stops)...")
    engine_without = BacktestEngine(use_exit_monitor=False)
    engine_without.load_levels(LEVELS_FILE, CONTEXT_FILE)

    for idx, row in df.iterrows():
        price = row['price'] / 1e9 if row['price'] > 10000 else row['price']
        size = row['size']
        side = row['side']
        engine_without.process_tick(price, size, side, idx)

    engine_without.finalize(df.index[-1])
    results_without = engine_without.get_results()

    # Print results
    print_results(results_with, "WITH EXIT MONITOR (Dynamic Exits)")
    print_results(results_without, "WITHOUT EXIT MONITOR (Fixed Stop/Target)")
    print_comparison(results_with, results_without)

    # Save trades
    if save_trades:
        os.makedirs('logs', exist_ok=True)
        save_trades_to_csv(results_with, f"logs/backtest_with_monitor_{start_date}_{end_date}.csv")
        save_trades_to_csv(results_without, f"logs/backtest_fixed_stops_{start_date}_{end_date}.csv")

    return results_with, results_without


def main():
    """Main entry point."""
    print("\n" + "="*50)
    print("  EXIT MONITOR BACKTEST")
    print("="*50)

    # Get date range from user
    print("\nEnter backtest date range:")
    start = input("  Start Date (YYYY-MM-DD) [default: 2024-01-02]: ").strip()
    end = input("  End Date (YYYY-MM-DD) [default: 2024-01-05]: ").strip()

    if not start:
        start = "2024-01-02"
    if not end:
        end = "2024-01-05"

    try:
        datetime.strptime(start, "%Y-%m-%d")
        datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        print("Invalid date format. Use YYYY-MM-DD")
        return

    run_backtest(start, end)


if __name__ == "__main__":
    main()
