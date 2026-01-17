"""
ES ALGO ASSISTANT - BACKTEST: EXIT MONITOR COMPARISON

Compares trading performance:
1. WITH order flow-based exit monitoring (dynamic exits)
2. WITHOUT exit monitoring (fixed stop loss / take profit)

Uses OHLCV-1m data with simulated delta (buy/sell volume estimation).
This is more practical than tick data for multi-week/month backtests.
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
import hashlib
import pickle

warnings.filterwarnings('ignore')

# ==============================================================================
# CONFIGURATION
# ==============================================================================

API_KEY = os.getenv("DATABENTO_API_KEY", "")
NY_TZ = pytz.timezone('America/New_York')

# Strategy Parameters (match live bot)
LEVEL_ABS_THRESH = 6000
LEVEL_DELTA_THRESH = 700
LEVEL_TIMEFRAME = 2  # 2-minute candles

BLIND_ABS_THRESH = 8000
BLIND_DELTA_THRESH = 700

LEVEL_TOLERANCE = 3.0

# Default Exit Monitor Parameters
DEFAULT_EXIT_PARAMS = {
    'counter_abs_thresh': 4000,
    'delta_reversal_bars': 3,
    'delta_reversal_thresh': 500,
    'failed_followthrough_bars': 5,
    'failed_followthrough_pts': 2.0,
    'exhaustion_decay_pct': 0.5,
    'exhaustion_min_bars': 3,
    'divergence_bars': 4,
}

# Default Fixed Exit Parameters (for comparison - NO exit monitor)
DEFAULT_FIXED_PARAMS = {
    'stop_loss_pts': 4.0,
    'take_profit_pts': 8.0,
    'time_stop_bars': 15,
}

# Parameter ranges for grid search optimization
# NOTE: Full grid = 576 combinations (reasonable for multi-day backtests)
# For longer backtests, use focused optimization or random sampling
PARAM_GRID = {
    # Counter absorption: higher = let winners run longer
    'counter_abs_thresh': [5000, 8000, 12000],

    # Delta reversal: bars x threshold
    'delta_reversal_bars': [3, 5],
    'delta_reversal_thresh': [500, 800],

    # Failed follow-through: key param - was cutting winners too early
    'failed_followthrough_bars': [6, 10, 15],
    'failed_followthrough_pts': [2.0, 4.0, 6.0],

    # Exhaustion: decay sensitivity
    'exhaustion_decay_pct': [0.4, 0.6],
    'exhaustion_min_bars': [4],

    # Divergence: lookback period
    'divergence_bars': [4, 6],
}

# Fixed exit parameters to test
FIXED_PARAM_GRID = {
    'stop_loss_pts': [3.0, 4.0, 5.0, 6.0],
    'take_profit_pts': [6.0, 8.0, 10.0, 12.0],
    'time_stop_bars': [10, 15, 20, 30],
}

# Backtest Settings
SYMBOL = "ES.c.0"
CONTEXT_FILE = "daily_context_v2.json"
LEVELS_FILE = "critical_levels_master_enhanced.csv"
CACHE_DIR = "backtest_cache"

os.makedirs(CACHE_DIR, exist_ok=True)

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
class ExitParams:
    """Parameters for exit monitor strategy."""
    counter_abs_thresh: int = 4000
    delta_reversal_bars: int = 3
    delta_reversal_thresh: int = 500
    failed_followthrough_bars: int = 5
    failed_followthrough_pts: float = 2.0
    exhaustion_decay_pct: float = 0.5
    exhaustion_min_bars: int = 3
    divergence_bars: int = 4

    @classmethod
    def from_dict(cls, d: dict) -> 'ExitParams':
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return {
            'counter_abs_thresh': self.counter_abs_thresh,
            'delta_reversal_bars': self.delta_reversal_bars,
            'delta_reversal_thresh': self.delta_reversal_thresh,
            'failed_followthrough_bars': self.failed_followthrough_bars,
            'failed_followthrough_pts': self.failed_followthrough_pts,
            'exhaustion_decay_pct': self.exhaustion_decay_pct,
            'exhaustion_min_bars': self.exhaustion_min_bars,
            'divergence_bars': self.divergence_bars,
        }

    def summary(self) -> str:
        return (f"CA:{self.counter_abs_thresh} DR:{self.delta_reversal_bars}x{self.delta_reversal_thresh} "
                f"FF:{self.failed_followthrough_bars}b/{self.failed_followthrough_pts}pt "
                f"EX:{self.exhaustion_decay_pct:.0%}/{self.exhaustion_min_bars}b DIV:{self.divergence_bars}b")


@dataclass
class FixedExitParams:
    """Parameters for fixed stop/target exit strategy."""
    stop_loss_pts: float = 4.0
    take_profit_pts: float = 8.0
    time_stop_bars: int = 15

    @classmethod
    def from_dict(cls, d: dict) -> 'FixedExitParams':
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return {
            'stop_loss_pts': self.stop_loss_pts,
            'take_profit_pts': self.take_profit_pts,
            'time_stop_bars': self.time_stop_bars,
        }

    def summary(self) -> str:
        return f"SL:{self.stop_loss_pts}pt TP:{self.take_profit_pts}pt TS:{self.time_stop_bars}bars"


@dataclass
class BacktestTrade:
    """Represents a completed trade for analysis."""
    entry_time: datetime
    exit_time: datetime
    direction: str
    entry_price: float
    exit_price: float
    pnl_points: float
    exit_reason: ExitReason
    bars_held: int
    max_favorable_excursion: float
    max_adverse_excursion: float
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

    bars_held: int = 0
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    delta_history: List[int] = field(default_factory=list)
    price_history: List[float] = field(default_factory=list)
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
    avg_mfe: float = 0.0
    avg_mae: float = 0.0
    exit_breakdown: Dict[str, int] = field(default_factory=dict)
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)


# ==============================================================================
# SIMULATED DELTA FROM OHLCV
# ==============================================================================

def estimate_delta_from_ohlcv(row: pd.Series) -> int:
    """
    Estimate order flow delta from OHLCV bar.

    Uses price action to infer buying/selling pressure:
    - If close > open: more buying (positive delta)
    - If close < open: more selling (negative delta)
    - Magnitude scaled by volume and bar range
    """
    open_p = row['open']
    high = row['high']
    low = row['low']
    close = row['close']
    volume = row.get('volume', row.get('vol', 1000))

    if high == low:
        return 0

    # Calculate where close is relative to bar range
    bar_range = high - low
    close_position = (close - low) / bar_range  # 0 to 1

    # Delta estimation: scale volume by close position
    # close_position > 0.5 = more buying, < 0.5 = more selling
    delta_ratio = (close_position - 0.5) * 2  # -1 to 1

    # Scale by volume (normalize to typical ES volume)
    estimated_delta = int(delta_ratio * volume * 0.5)

    return estimated_delta


def estimate_absorption_from_ohlcv(row: pd.Series, level_price: float,
                                    level_type: str, tolerance: float = 3.0) -> int:
    """
    Estimate absorption volume at a level from OHLCV.

    Absorption occurs when price touches a level but reverses.
    """
    high = row['high']
    low = row['low']
    close = row['close']
    volume = row.get('volume', row.get('vol', 1000))

    # Check if bar touched the level
    if level_type == 'SUP':
        # Support: check if low touched level
        if abs(low - level_price) <= tolerance:
            # Absorption = volume if price bounced (closed higher)
            if close > low + 0.5:
                return int(volume * 0.3)  # Estimate 30% was absorption
    else:  # RES
        # Resistance: check if high touched level
        if abs(high - level_price) <= tolerance:
            # Absorption = volume if price rejected (closed lower)
            if close < high - 0.5:
                return int(volume * 0.3)

    return 0


# ==============================================================================
# BACKTEST ENGINE (OHLCV-based)
# ==============================================================================

class BacktestEngine:
    """
    Runs backtest using OHLCV data with simulated order flow.
    """

    def __init__(self, use_exit_monitor: bool = True,
                 exit_params: Optional[ExitParams] = None,
                 fixed_params: Optional[FixedExitParams] = None):
        self.use_exit_monitor = use_exit_monitor
        self.exit_params = exit_params or ExitParams()
        self.fixed_params = fixed_params or FixedExitParams()

        self.positions: Dict[str, BacktestPosition] = {}
        self.completed_trades: List[BacktestTrade] = []
        self.position_counter = 0

        # Level tracking
        self.level_absorption: Dict[str, int] = {}  # level_key -> cumulative absorption
        self.level_last_touch: Dict[str, datetime] = {}

        # Context levels (loaded per-day)
        self.support_levels: List[float] = []
        self.resistance_levels: List[float] = []
        self.context_data: Dict = {}  # Full context file data
        self.current_date: Optional[str] = None  # Track current trading day

        # Bar aggregation for 2-min candles
        self.bar_buffer: List[pd.Series] = []
        self.last_2m_bar: Optional[pd.Series] = None
        self.last_2m_delta = 0

        # Equity tracking
        self.equity = 0.0
        self.peak_equity = 0.0
        self.max_drawdown = 0.0
        self.equity_curve: List[float] = []

    def load_context_file(self, context_file: str):
        """Load the full context file for date-based level lookup."""
        if os.path.exists(context_file):
            try:
                with open(context_file, 'r') as f:
                    self.context_data = json.load(f)
                logger.info(f"Loaded context with {len(self.context_data)} dates")
            except Exception as e:
                logger.warning(f"Could not load context: {e}")
                self.context_data = {}

    def load_levels_for_date(self, trade_date: str, current_price: float):
        """
        Load levels for a specific trading date.
        Uses the PREVIOUS day's context (what would be known at market open).
        """
        # Find the most recent context date before trade_date
        available_dates = sorted(self.context_data.keys())
        context_date = None

        for d in reversed(available_dates):
            if d < trade_date:
                context_date = d
                break

        if not context_date:
            # No prior context available, use earliest if any
            if available_dates:
                context_date = available_dates[0]
            else:
                return

        # Clear existing levels
        self.support_levels = []
        self.resistance_levels = []
        self.level_absorption = {}

        # Load levels from the context date
        day_data = self.context_data.get(context_date, {})
        levels = day_data.get('levels', {})

        for l in levels.get('raw_sup', []):
            if 'price' in l:
                self.support_levels.append(l['price'])
        for l in levels.get('raw_res', []):
            if 'price' in l:
                self.resistance_levels.append(l['price'])

        # Sort levels relative to current price
        self.support_levels = sorted([p for p in self.support_levels if p < current_price + 10], reverse=True)
        self.resistance_levels = sorted([p for p in self.resistance_levels if p > current_price - 10])

        # Initialize absorption tracking
        for price in self.support_levels[:15]:  # Only track nearest 15
            self.level_absorption[f"{price}_SUP"] = 0
        for price in self.resistance_levels[:15]:
            self.level_absorption[f"{price}_RES"] = 0

    def load_levels(self, levels_file: str, context_file: str, current_price: float = 5000):
        """Load trading levels from files (legacy method for compatibility)."""
        # Load context file for date-based lookups
        self.load_context_file(context_file)

        # If no context data, fall back to CSV (but limit levels)
        if not self.context_data and os.path.exists(levels_file):
            try:
                df = pd.read_csv(levels_file)
                if 'price' in df.columns:
                    all_levels = df['price'].tolist()
                    # Only use levels near current price (within 50 points)
                    self.support_levels = sorted(
                        [p for p in all_levels if current_price - 50 < p < current_price],
                        reverse=True
                    )[:15]
                    self.resistance_levels = sorted(
                        [p for p in all_levels if current_price < p < current_price + 50]
                    )[:15]
                    logger.info(f"Loaded {len(self.support_levels)} sup / {len(self.resistance_levels)} res from CSV (filtered)")
            except Exception as e:
                logger.warning(f"Could not load levels file: {e}")

        # Initialize absorption tracking
        for price in self.support_levels:
            self.level_absorption[f"{price}_SUP"] = 0
        for price in self.resistance_levels:
            self.level_absorption[f"{price}_RES"] = 0

    def _find_target(self, entry_price: float, direction: str) -> Optional[float]:
        """Find target level for position."""
        if direction == 'LONG':
            for level in self.resistance_levels:
                if level > entry_price + 2.0:
                    return level
        else:
            for level in self.support_levels:
                if level < entry_price - 2.0:
                    return level
        return None

    def process_bar(self, bar: pd.Series, timestamp: datetime):
        """Process a single 1-minute OHLCV bar."""
        # Check if date changed - reload levels for new trading day
        bar_date = timestamp.strftime('%Y-%m-%d')
        if bar_date != self.current_date and self.context_data:
            self.current_date = bar_date
            self.load_levels_for_date(bar_date, bar['close'])

        self.bar_buffer.append(bar)

        # Aggregate to 2-minute bars
        if len(self.bar_buffer) >= 2:
            # Create aggregated 2m bar
            bars = self.bar_buffer[-2:]
            agg_bar = pd.Series({
                'open': bars[0]['open'],
                'high': max(b['high'] for b in bars),
                'low': min(b['low'] for b in bars),
                'close': bars[-1]['close'],
                'volume': sum(b.get('volume', b.get('vol', 0)) for b in bars)
            })

            # Calculate 2m delta
            self.last_2m_delta = sum(estimate_delta_from_ohlcv(b) for b in bars)
            self.last_2m_bar = agg_bar

            # Process on 2m bar close
            self._on_2m_bar_close(agg_bar, timestamp)

            # Keep only last bar for next aggregation
            self.bar_buffer = [self.bar_buffer[-1]]

        # Update level absorption estimates from 1m bar
        self._update_level_absorption(bar, timestamp)

        # Update position tracking
        self._update_positions(bar, timestamp)

    def _update_level_absorption(self, bar: pd.Series, timestamp: datetime):
        """Update absorption estimates at levels."""
        # Reset stale levels (10 min timeout)
        stale_keys = []
        for key, last_touch in self.level_last_touch.items():
            if (timestamp - last_touch).total_seconds() > 600:
                stale_keys.append(key)
        for key in stale_keys:
            self.level_absorption[key] = 0
            del self.level_last_touch[key]

        # Check support levels
        for price in self.support_levels[:10]:  # Check nearest 10
            key = f"{price}_SUP"
            absorption = estimate_absorption_from_ohlcv(bar, price, 'SUP', LEVEL_TOLERANCE)
            if absorption > 0:
                self.level_absorption[key] = self.level_absorption.get(key, 0) + absorption
                self.level_last_touch[key] = timestamp

        # Check resistance levels
        for price in self.resistance_levels[:10]:
            key = f"{price}_RES"
            absorption = estimate_absorption_from_ohlcv(bar, price, 'RES', LEVEL_TOLERANCE)
            if absorption > 0:
                self.level_absorption[key] = self.level_absorption.get(key, 0) + absorption
                self.level_last_touch[key] = timestamp

    def _update_positions(self, bar: pd.Series, timestamp: datetime):
        """Update position MFE/MAE and counter-absorption."""
        close = bar['close']
        high = bar['high']
        low = bar['low']
        volume = bar.get('volume', bar.get('vol', 1000))

        for pos_id, pos in self.positions.items():
            if pos.direction == 'LONG':
                pos.max_favorable = max(pos.max_favorable, high)
                pos.max_adverse = min(pos.max_adverse, low)
                # Counter-absorption: estimate resistance forming above
                if high > pos.entry_price + 2.0:
                    # If price went up but closed lower, that's absorption
                    if close < high - 0.5:
                        pos.counter_absorption += int(volume * 0.2)
            else:
                pos.max_favorable = min(pos.max_favorable, low)
                pos.max_adverse = max(pos.max_adverse, high)
                # Counter-absorption: estimate support forming below
                if low < pos.entry_price - 2.0:
                    if close > low + 0.5:
                        pos.counter_absorption += int(volume * 0.2)

    def _on_2m_bar_close(self, bar: pd.Series, timestamp: datetime):
        """Process 2-minute bar close - check entries and exits."""
        close = bar['close']

        # Check for new entry signals
        self._check_entry_signals(bar, timestamp)

        # Update positions and check exits
        positions_to_close = []

        for pos_id, pos in self.positions.items():
            pos.bars_held += 1
            pos.delta_history.append(self.last_2m_delta)
            pos.price_history.append(close)

            if len(pos.delta_history) > 20:
                pos.delta_history.pop(0)
            if len(pos.price_history) > 20:
                pos.price_history.pop(0)

            exit_reason = self._check_exit(pos, close)
            if exit_reason:
                positions_to_close.append((pos_id, exit_reason, close))

        for pos_id, reason, price in positions_to_close:
            self._close_position(pos_id, reason, timestamp, price)

    def _check_entry_signals(self, bar: pd.Series, timestamp: datetime):
        """Check for entry signals."""
        if self.positions:
            return  # Single position mode

        close = bar['close']
        delta = self.last_2m_delta

        # Check level signals
        for key, absorption in self.level_absorption.items():
            if absorption >= LEVEL_ABS_THRESH:
                price_str, l_type = key.rsplit('_', 1)
                level_price = float(price_str)

                # Check delta confirmation
                if l_type == 'SUP' and delta >= LEVEL_DELTA_THRESH:
                    self._open_position('LONG', level_price, timestamp, absorption, delta, 'LEVEL')
                    self.level_absorption[key] = 0  # Reset
                    return
                elif l_type == 'RES' and delta <= -LEVEL_DELTA_THRESH:
                    self._open_position('SHORT', level_price, timestamp, absorption, delta, 'LEVEL')
                    self.level_absorption[key] = 0
                    return

        # Check blind grid signals (high absorption anywhere)
        # For OHLCV backtest, we simplify this to large delta + price at round number
        grid_price = round(close / 2.0) * 2.0
        bar_volume = bar.get('volume', bar.get('vol', 0))

        if bar_volume > 50000:  # High volume bar
            if delta >= BLIND_DELTA_THRESH * 1.5:  # Higher threshold for blind
                self._open_position('LONG', grid_price, timestamp, int(bar_volume * 0.3), delta, 'GRID')
                return
            elif delta <= -BLIND_DELTA_THRESH * 1.5:
                self._open_position('SHORT', grid_price, timestamp, int(bar_volume * 0.3), delta, 'GRID')
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

    def _check_exit(self, pos: BacktestPosition, price: float) -> Optional[ExitReason]:
        """Check if position should be exited."""
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
        fp = self.fixed_params
        if pnl <= -fp.stop_loss_pts:
            return ExitReason.STOP_LOSS
        if pnl >= fp.take_profit_pts:
            return ExitReason.TAKE_PROFIT
        if pos.bars_held >= fp.time_stop_bars:
            return ExitReason.TIME_STOP
        return None

    def _check_exit_monitor(self, pos: BacktestPosition, price: float, pnl: float) -> Optional[ExitReason]:
        """Order flow-based exit strategy."""
        ep = self.exit_params

        # 1. COUNTER-ABSORPTION
        if pos.counter_absorption >= ep.counter_abs_thresh:
            return ExitReason.COUNTER_ABSORPTION

        # 2. DELTA REVERSAL
        if len(pos.delta_history) >= ep.delta_reversal_bars:
            recent = pos.delta_history[-ep.delta_reversal_bars:]
            if pos.direction == 'LONG':
                if all(d <= -ep.delta_reversal_thresh for d in recent):
                    return ExitReason.DELTA_REVERSAL
            else:
                if all(d >= ep.delta_reversal_thresh for d in recent):
                    return ExitReason.DELTA_REVERSAL

        # 3. FAILED FOLLOW-THROUGH
        if pos.bars_held >= ep.failed_followthrough_bars:
            if pos.direction == 'LONG':
                progress = pos.max_favorable - pos.entry_price
            else:
                progress = pos.entry_price - pos.max_favorable
            if progress < ep.failed_followthrough_pts:
                return ExitReason.FAILED_FOLLOWTHROUGH

        # Profit-taking only if profitable
        if pnl <= 0:
            return None

        # 4. EXHAUSTION
        if len(pos.delta_history) >= ep.exhaustion_min_bars and pos.entry_delta != 0:
            recent = pos.delta_history[-ep.exhaustion_min_bars:]
            if pos.direction == 'LONG' and pos.entry_delta > 0:
                avg = sum(max(0, d) for d in recent) / len(recent)
                decay = avg / pos.entry_delta if pos.entry_delta else 1
                if decay < ep.exhaustion_decay_pct and price > pos.entry_price + 3.0:
                    return ExitReason.EXHAUSTION
            elif pos.direction == 'SHORT' and pos.entry_delta < 0:
                avg = sum(min(0, d) for d in recent) / len(recent)
                decay = avg / pos.entry_delta if pos.entry_delta else 1
                if decay < ep.exhaustion_decay_pct and price < pos.entry_price - 3.0:
                    return ExitReason.EXHAUSTION

        # 5. TARGET REACHED
        if pos.target_level and abs(price - pos.target_level) <= 3.0:
            return ExitReason.TARGET_REACHED

        # 6. DIVERGENCE
        if len(pos.delta_history) >= ep.divergence_bars:
            prices = pos.price_history[-ep.divergence_bars:]
            deltas = pos.delta_history[-ep.divergence_bars:]

            if len(prices) >= ep.divergence_bars:
                if pos.direction == 'LONG':
                    price_up = prices[-1] > prices[0]
                    peaks = [d for d in deltas if d > 0]
                    if len(peaks) >= 2 and price_up and peaks[-1] < peaks[0] * 0.7:
                        return ExitReason.DIVERGENCE
                else:
                    price_down = prices[-1] < prices[0]
                    troughs = [d for d in deltas if d < 0]
                    if len(troughs) >= 2 and price_down and troughs[-1] > troughs[0] * 0.7:
                        return ExitReason.DIVERGENCE

        return None

    def _close_position(self, pos_id: str, reason: ExitReason, ts: datetime, exit_price: float):
        """Close a position and record the trade."""
        pos = self.positions.pop(pos_id)

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

        self.equity += pnl
        self.equity_curve.append(self.equity)
        self.peak_equity = max(self.peak_equity, self.equity)
        drawdown = self.peak_equity - self.equity
        self.max_drawdown = max(self.max_drawdown, drawdown)

    def finalize(self, ts: datetime, last_price: float):
        """Close any remaining positions at end of data."""
        for pos_id in list(self.positions.keys()):
            self._close_position(pos_id, ExitReason.END_OF_DATA, ts, last_price)

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

        for trade in self.completed_trades:
            reason = trade.exit_reason.value
            results.exit_breakdown[reason] = results.exit_breakdown.get(reason, 0) + 1

        return results


# ==============================================================================
# DATA LOADING WITH CACHING
# ==============================================================================

def get_cache_path(start_date: str, end_date: str) -> str:
    """Generate cache file path."""
    key = f"{SYMBOL}_{start_date}_{end_date}"
    hash_key = hashlib.md5(key.encode()).hexdigest()[:8]
    return os.path.join(CACHE_DIR, f"ohlcv_{hash_key}.pkl")


def load_historical_data(start_date: str, end_date: str, use_cache: bool = True) -> Optional[pd.DataFrame]:
    """Load historical OHLCV-1m data from Databento with caching."""

    cache_path = get_cache_path(start_date, end_date)

    # Try cache first
    if use_cache and os.path.exists(cache_path):
        try:
            with open(cache_path, 'rb') as f:
                df = pickle.load(f)
            logger.info(f"Loaded {len(df):,} bars from cache")
            return df
        except Exception as e:
            logger.warning(f"Cache load failed: {e}")

    if not API_KEY:
        logger.error("DATABENTO_API_KEY environment variable not set")
        print("\nERROR: Set DATABENTO_API_KEY environment variable")
        return None

    try:
        client = db.Historical(API_KEY)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        logger.info(f"Fetching OHLCV-1m data from {start_date} to {end_date}...")
        print(f"  This may take a moment for longer date ranges...")

        data = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            schema="ohlcv-1m",
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

        logger.info(f"Loaded {len(df):,} 1-minute bars")

        # Cache the data
        if use_cache:
            try:
                with open(cache_path, 'wb') as f:
                    pickle.dump(df, f)
                logger.info(f"Cached data to {cache_path}")
            except Exception as e:
                logger.warning(f"Cache save failed: {e}")

        return df

    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        import traceback
        traceback.print_exc()
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
    print(f"  Avg Bars Held:     {results.avg_bars_held:.1f} (2m bars)")
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

        if name in ["Win Rate", "Total P&L (pts)", "Profit Factor", "Avg Win (pts)", "Avg MFE (pts)"]:
            better = ">" if val1 > val2 else "<" if val2 > val1 else "="
        elif name in ["Max Drawdown (pts)", "Avg Loss (pts)", "Avg MAE (pts)"]:
            better = "<" if val1 < val2 else ">" if val2 < val1 else "="
        else:
            better = "="

        indicator = " *" if better == ">" else " x" if better == "<" else ""
        print(f"  {name:<25} {v1:>18} {v2:>18}{indicator}")

    print(f"  {'-'*65}")
    print(f"  * = Exit Monitor better | x = Fixed Stops better")

    pnl_diff = with_monitor.total_pnl - without_monitor.total_pnl
    winner = "Exit Monitor" if pnl_diff > 0 else "Fixed Stops"
    print(f"\n  P&L Difference: {pnl_diff:+.2f} pts ({winner} wins)")


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
# SINGLE BACKTEST RUN
# ==============================================================================

def run_single_backtest(df: pd.DataFrame, use_exit_monitor: bool,
                        exit_params: Optional[ExitParams] = None,
                        fixed_params: Optional[FixedExitParams] = None,
                        current_price: float = 5000,
                        verbose: bool = True) -> BacktestResults:
    """Run a single backtest with specified parameters."""
    engine = BacktestEngine(
        use_exit_monitor=use_exit_monitor,
        exit_params=exit_params,
        fixed_params=fixed_params
    )
    engine.load_levels(LEVELS_FILE, CONTEXT_FILE, current_price)

    total_bars = len(df)
    for i, (timestamp, row) in enumerate(df.iterrows()):
        engine.process_bar(row, timestamp)
        if verbose and (i + 1) % 5000 == 0:
            print(f"  Processing: {i+1:,}/{total_bars:,} bars ({(i+1)/total_bars*100:.0f}%)", end='\r')

    engine.finalize(df.index[-1], df['close'].iloc[-1])
    results = engine.get_results()

    if verbose:
        print(f"  Completed: {results.total_trades} trades                    ")

    return results


def run_backtest(start_date: str, end_date: str, save_trades: bool = True,
                 exit_params: Optional[ExitParams] = None,
                 fixed_params: Optional[FixedExitParams] = None):
    """Run full backtest comparison."""
    exit_params = exit_params or ExitParams.from_dict(DEFAULT_EXIT_PARAMS)
    fixed_params = fixed_params or FixedExitParams.from_dict(DEFAULT_FIXED_PARAMS)

    print("\n" + "="*70)
    print("  ES ALGO ASSISTANT - EXIT MONITOR BACKTEST")
    print("="*70)
    print(f"  Period: {start_date} to {end_date}")
    print(f"  Data: OHLCV-1m bars (RTH only)")
    print(f"  ")
    print(f"  Strategy Parameters:")
    print(f"    Level Absorption:    {LEVEL_ABS_THRESH}")
    print(f"    Level Delta:         {LEVEL_DELTA_THRESH}")
    print(f"    Grid Absorption:     {BLIND_ABS_THRESH}")
    print(f"    Grid Delta:          {BLIND_DELTA_THRESH}")
    print(f"  ")
    print(f"  Exit Monitor Parameters:")
    print(f"    {exit_params.summary()}")
    print(f"  ")
    print(f"  Fixed Exit Parameters (baseline):")
    print(f"    {fixed_params.summary()}")

    # Load data
    df = load_historical_data(start_date, end_date)
    if df is None or df.empty:
        print("\nNo data available for backtest.")
        return None, None

    current_price = df['close'].iloc[0]

    # Run WITH exit monitor
    print("\n[1/2] Running backtest WITH Exit Monitor...")
    results_with = run_single_backtest(df, True, exit_params, fixed_params, current_price)

    # Run WITHOUT exit monitor
    print("[2/2] Running backtest WITHOUT Exit Monitor (Fixed Stops)...")
    results_without = run_single_backtest(df, False, exit_params, fixed_params, current_price)

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


# ==============================================================================
# PARAMETER OPTIMIZATION / GRID SEARCH
# ==============================================================================

@dataclass
class OptimizationResult:
    """Result of a single parameter combination test."""
    params: dict
    total_trades: int
    win_rate: float
    total_pnl: float
    profit_factor: float
    max_drawdown: float
    avg_win: float
    avg_loss: float
    avg_bars_held: float
    is_exit_monitor: bool = True

    def score(self, metric: str = 'pnl') -> float:
        """Calculate score for ranking. Higher is better."""
        if metric == 'pnl':
            return self.total_pnl
        elif metric == 'pf':
            return self.profit_factor if self.profit_factor < 100 else 0
        elif metric == 'sharpe':
            # Simplified: PnL / DrawDown ratio
            return self.total_pnl / self.max_drawdown if self.max_drawdown > 0 else 0
        elif metric == 'combined':
            # Balanced score: PnL * profit_factor / (1 + drawdown)
            pf = min(self.profit_factor, 5)  # Cap PF
            return self.total_pnl * pf / (1 + self.max_drawdown / 100)
        return self.total_pnl


def generate_param_combinations(param_grid: dict, sample_size: Optional[int] = None) -> List[dict]:
    """Generate all combinations or random sample from parameter grid."""
    from itertools import product
    import random

    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]

    all_combos = [dict(zip(keys, combo)) for combo in product(*values)]

    if sample_size and sample_size < len(all_combos):
        return random.sample(all_combos, sample_size)
    return all_combos


def run_optimization(start_date: str, end_date: str,
                     optimize_exit_monitor: bool = True,
                     param_grid: Optional[dict] = None,
                     max_combinations: Optional[int] = None,
                     sort_metric: str = 'pnl') -> List[OptimizationResult]:
    """
    Run grid search optimization over parameter space.

    Args:
        start_date: Start date for backtest
        end_date: End date for backtest
        optimize_exit_monitor: If True, optimize exit monitor params; else fixed params
        param_grid: Custom parameter grid (uses defaults if None)
        max_combinations: Limit number of combinations to test (random sample)
        sort_metric: Metric to sort results by ('pnl', 'pf', 'sharpe', 'combined')

    Returns:
        List of OptimizationResult sorted by score (best first)
    """
    if param_grid is None:
        param_grid = PARAM_GRID if optimize_exit_monitor else FIXED_PARAM_GRID

    combinations = generate_param_combinations(param_grid, max_combinations)

    print("\n" + "="*70)
    print("  ES ALGO ASSISTANT - PARAMETER OPTIMIZATION")
    print("="*70)
    print(f"  Period: {start_date} to {end_date}")
    print(f"  Mode: {'Exit Monitor' if optimize_exit_monitor else 'Fixed Stops'}")
    print(f"  Combinations to test: {len(combinations)}")
    print(f"  Ranking metric: {sort_metric}")

    # Load data once
    df = load_historical_data(start_date, end_date)
    if df is None or df.empty:
        print("\nNo data available for optimization.")
        return []

    current_price = df['close'].iloc[0]
    results: List[OptimizationResult] = []

    print(f"\nRunning optimization...")
    start_time = datetime.now()

    for i, params in enumerate(combinations):
        # Progress update
        if (i + 1) % 10 == 0 or i == 0:
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(combinations) - i - 1) / rate if rate > 0 else 0
            print(f"  Testing combination {i+1}/{len(combinations)} "
                  f"({rate:.1f}/sec, ETA: {eta:.0f}s)    ", end='\r')

        if optimize_exit_monitor:
            exit_params = ExitParams.from_dict(params)
            fixed_params = FixedExitParams.from_dict(DEFAULT_FIXED_PARAMS)
        else:
            exit_params = ExitParams.from_dict(DEFAULT_EXIT_PARAMS)
            fixed_params = FixedExitParams.from_dict(params)

        # Run backtest silently
        bt_results = run_single_backtest(
            df, optimize_exit_monitor, exit_params, fixed_params, current_price, verbose=False
        )

        if bt_results.total_trades > 0:
            results.append(OptimizationResult(
                params=params,
                total_trades=bt_results.total_trades,
                win_rate=bt_results.win_rate,
                total_pnl=bt_results.total_pnl,
                profit_factor=bt_results.profit_factor,
                max_drawdown=bt_results.max_drawdown,
                avg_win=bt_results.avg_win,
                avg_loss=bt_results.avg_loss,
                avg_bars_held=bt_results.avg_bars_held,
                is_exit_monitor=optimize_exit_monitor
            ))

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n  Completed {len(combinations)} combinations in {elapsed:.1f}s")

    # Sort by score
    results.sort(key=lambda x: x.score(sort_metric), reverse=True)

    return results


def print_optimization_results(results: List[OptimizationResult], top_n: int = 20):
    """Print formatted optimization results."""
    if not results:
        print("\nNo results to display.")
        return

    print("\n" + "="*100)
    print("  TOP PARAMETER COMBINATIONS")
    print("="*100)

    # Header
    print(f"{'Rank':<5} {'P&L':>10} {'WinRate':>8} {'PF':>6} {'MaxDD':>8} "
          f"{'AvgWin':>8} {'AvgLoss':>8} {'Trades':>7} {'Parameters'}")
    print("-"*100)

    for i, r in enumerate(results[:top_n]):
        # Format parameters compactly
        if r.is_exit_monitor:
            param_str = (f"CA:{r.params.get('counter_abs_thresh', '-')} "
                        f"DR:{r.params.get('delta_reversal_bars', '-')}x{r.params.get('delta_reversal_thresh', '-')} "
                        f"FF:{r.params.get('failed_followthrough_bars', '-')}b/{r.params.get('failed_followthrough_pts', '-')}pt "
                        f"EX:{r.params.get('exhaustion_decay_pct', '-')}/{r.params.get('exhaustion_min_bars', '-')}b "
                        f"DIV:{r.params.get('divergence_bars', '-')}b")
        else:
            param_str = (f"SL:{r.params.get('stop_loss_pts', '-')}pt "
                        f"TP:{r.params.get('take_profit_pts', '-')}pt "
                        f"TS:{r.params.get('time_stop_bars', '-')}bars")

        pf_str = f"{r.profit_factor:.2f}" if r.profit_factor < 100 else "INF"
        print(f"{i+1:<5} {r.total_pnl:>+10.2f} {r.win_rate:>7.1%} {pf_str:>6} "
              f"{r.max_drawdown:>8.2f} {r.avg_win:>+8.2f} {r.avg_loss:>8.2f} "
              f"{r.total_trades:>7}")
        print(f"      {param_str}")

    # Best vs worst summary
    if len(results) > 1:
        best = results[0]
        worst = results[-1]
        print("\n" + "-"*100)
        print(f"  Best P&L:  {best.total_pnl:+.2f} pts (Rank #1)")
        print(f"  Worst P&L: {worst.total_pnl:+.2f} pts (Rank #{len(results)})")
        print(f"  Spread:    {best.total_pnl - worst.total_pnl:.2f} pts")


def save_optimization_results(results: List[OptimizationResult], filename: str):
    """Save optimization results to CSV."""
    rows = []
    for i, r in enumerate(results):
        row = {
            'rank': i + 1,
            'total_pnl': r.total_pnl,
            'win_rate': r.win_rate,
            'profit_factor': r.profit_factor,
            'max_drawdown': r.max_drawdown,
            'avg_win': r.avg_win,
            'avg_loss': r.avg_loss,
            'total_trades': r.total_trades,
            'avg_bars_held': r.avg_bars_held,
        }
        row.update(r.params)
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(filename, index=False)
    logger.info(f"Saved optimization results to {filename}")


def run_focused_optimization(start_date: str, end_date: str,
                             focus_params: List[str],
                             base_params: Optional[dict] = None) -> List[OptimizationResult]:
    """
    Run optimization focusing on specific parameters while holding others fixed.

    This is useful for fine-tuning specific exit conditions without testing
    the full combinatorial space.

    Args:
        start_date: Start date
        end_date: End date
        focus_params: List of parameter names to optimize
        base_params: Base parameters to use for non-focused params

    Returns:
        Sorted optimization results
    """
    base = base_params or DEFAULT_EXIT_PARAMS.copy()

    # Build focused grid
    focused_grid = {k: PARAM_GRID[k] for k in focus_params if k in PARAM_GRID}

    print(f"\nFocused optimization on: {', '.join(focus_params)}")
    print(f"Base parameters: {base}")

    combinations = generate_param_combinations(focused_grid)
    print(f"Testing {len(combinations)} combinations...")

    df = load_historical_data(start_date, end_date)
    if df is None or df.empty:
        return []

    current_price = df['close'].iloc[0]
    results = []

    for i, focused_params in enumerate(combinations):
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/{len(combinations)}", end='\r')

        # Merge base with focused
        params = base.copy()
        params.update(focused_params)

        exit_params = ExitParams.from_dict(params)
        bt_results = run_single_backtest(
            df, True, exit_params, None, current_price, verbose=False
        )

        if bt_results.total_trades > 0:
            results.append(OptimizationResult(
                params=params,
                total_trades=bt_results.total_trades,
                win_rate=bt_results.win_rate,
                total_pnl=bt_results.total_pnl,
                profit_factor=bt_results.profit_factor,
                max_drawdown=bt_results.max_drawdown,
                avg_win=bt_results.avg_win,
                avg_loss=bt_results.avg_loss,
                avg_bars_held=bt_results.avg_bars_held
            ))

    results.sort(key=lambda x: x.total_pnl, reverse=True)
    return results


def get_date_range() -> Tuple[str, str]:
    """Get date range from user input."""
    print("\nEnter backtest date range:")
    start = input("  Start Date (YYYY-MM-DD) [default: 2025-01-02]: ").strip()
    end = input("  End Date (YYYY-MM-DD) [default: 2025-01-10]: ").strip()

    if not start:
        start = "2025-01-02"
    if not end:
        end = "2025-01-10"

    try:
        datetime.strptime(start, "%Y-%m-%d")
        datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        print("Invalid date format. Use YYYY-MM-DD")
        return None, None

    return start, end


def main():
    """Main entry point with mode selection."""
    print("\n" + "="*60)
    print("  ES ALGO ASSISTANT - BACKTEST & OPTIMIZATION")
    print("="*60)
    print("\nThis uses OHLCV-1m data with simulated order flow.")
    print("Longer date ranges are now supported.\n")

    print("Select mode:")
    print("  1. Single Backtest (compare exit monitor vs fixed stops)")
    print("  2. Optimize Exit Monitor Parameters")
    print("  3. Optimize Fixed Stop Parameters")
    print("  4. Focused Optimization (specific parameters only)")
    print("  5. Quick Test (random sample of 50 combinations)")
    print()

    mode = input("Enter mode (1-5) [default: 1]: ").strip()
    if not mode:
        mode = "1"

    start, end = get_date_range()
    if start is None:
        return

    if mode == "1":
        # Single backtest comparison
        run_backtest(start, end)

    elif mode == "2":
        # Full exit monitor optimization
        total_combos = 1
        for v in PARAM_GRID.values():
            total_combos *= len(v)
        print(f"\nFull grid has {total_combos:,} combinations.")
        limit = input(f"  Max combinations to test [default: all]: ").strip()
        max_combos = int(limit) if limit else None

        metric = input("  Sort metric (pnl/pf/sharpe/combined) [default: pnl]: ").strip()
        if not metric:
            metric = "pnl"

        results = run_optimization(start, end, True, None, max_combos, metric)
        print_optimization_results(results, top_n=25)

        save = input("\nSave results to CSV? (y/n) [default: y]: ").strip().lower()
        if save != 'n':
            os.makedirs('logs', exist_ok=True)
            filename = f"logs/optimization_exit_monitor_{start}_{end}.csv"
            save_optimization_results(results, filename)

    elif mode == "3":
        # Fixed stops optimization
        total_combos = 1
        for v in FIXED_PARAM_GRID.values():
            total_combos *= len(v)
        print(f"\nFixed params grid has {total_combos} combinations.")

        results = run_optimization(start, end, False)
        print_optimization_results(results, top_n=25)

        save = input("\nSave results to CSV? (y/n) [default: y]: ").strip().lower()
        if save != 'n':
            os.makedirs('logs', exist_ok=True)
            filename = f"logs/optimization_fixed_stops_{start}_{end}.csv"
            save_optimization_results(results, filename)

    elif mode == "4":
        # Focused optimization
        print("\nAvailable parameters:")
        for i, param in enumerate(PARAM_GRID.keys()):
            values = PARAM_GRID[param]
            print(f"  {i+1}. {param}: {values}")

        selected = input("\nEnter parameter numbers to optimize (comma-separated): ").strip()
        if not selected:
            print("No parameters selected.")
            return

        param_names = list(PARAM_GRID.keys())
        try:
            indices = [int(x.strip()) - 1 for x in selected.split(',')]
            focus_params = [param_names[i] for i in indices if 0 <= i < len(param_names)]
        except (ValueError, IndexError):
            print("Invalid selection.")
            return

        if not focus_params:
            print("No valid parameters selected.")
            return

        results = run_focused_optimization(start, end, focus_params)
        print_optimization_results(results, top_n=25)

    elif mode == "5":
        # Quick test with random sample
        print("\nRunning quick test with 50 random parameter combinations...")
        results = run_optimization(start, end, True, None, max_combinations=50)
        print_optimization_results(results, top_n=20)

    else:
        print("Invalid mode. Running single backtest...")
        run_backtest(start, end)


if __name__ == "__main__":
    main()
