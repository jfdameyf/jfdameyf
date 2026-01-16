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
FIXED_STOP_LOSS_PTS = 4.0
FIXED_TAKE_PROFIT_PTS = 8.0
FIXED_TIME_STOP_BARS = 15

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

    def __init__(self, use_exit_monitor: bool = True):
        self.use_exit_monitor = use_exit_monitor
        self.positions: Dict[str, BacktestPosition] = {}
        self.completed_trades: List[BacktestTrade] = []
        self.position_counter = 0

        # Level tracking
        self.level_absorption: Dict[str, int] = {}  # level_key -> cumulative absorption
        self.level_last_touch: Dict[str, datetime] = {}

        # Context levels
        self.support_levels: List[float] = []
        self.resistance_levels: List[float] = []
        self.all_levels: List[float] = []

        # Bar aggregation for 2-min candles
        self.bar_buffer: List[pd.Series] = []
        self.last_2m_bar: Optional[pd.Series] = None
        self.last_2m_delta = 0

        # Equity tracking
        self.equity = 0.0
        self.peak_equity = 0.0
        self.max_drawdown = 0.0
        self.equity_curve: List[float] = []

    def load_levels(self, levels_file: str, context_file: str, current_price: float = 5000):
        """Load trading levels from files."""
        # Load from CSV
        if os.path.exists(levels_file):
            try:
                df = pd.read_csv(levels_file)
                if 'price' in df.columns:
                    self.all_levels = df['price'].tolist()
                    # Classify relative to approximate current price
                    self.support_levels = sorted([p for p in self.all_levels if p < current_price], reverse=True)
                    self.resistance_levels = sorted([p for p in self.all_levels if p > current_price])
                    logger.info(f"Loaded {len(self.all_levels)} levels from {levels_file}")
            except Exception as e:
                logger.warning(f"Could not load levels file: {e}")

        # Load from context file
        if os.path.exists(context_file):
            try:
                with open(context_file, 'r') as f:
                    data = json.load(f)
                    if data:
                        latest = data[list(data.keys())[-1]]
                        levels = latest.get('levels', {})
                        for l in levels.get('raw_sup', []):
                            if 'price' in l and l['price'] not in self.support_levels:
                                self.support_levels.append(l['price'])
                        for l in levels.get('raw_res', []):
                            if 'price' in l and l['price'] not in self.resistance_levels:
                                self.resistance_levels.append(l['price'])
                        self.support_levels = sorted(self.support_levels, reverse=True)
                        self.resistance_levels = sorted(self.resistance_levels)
                logger.info(f"Context: {len(self.support_levels)} support, {len(self.resistance_levels)} resistance")
            except Exception as e:
                logger.warning(f"Could not load context: {e}")

        # Initialize absorption tracking for all levels
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
        if pnl <= -FIXED_STOP_LOSS_PTS:
            return ExitReason.STOP_LOSS
        if pnl >= FIXED_TAKE_PROFIT_PTS:
            return ExitReason.TAKE_PROFIT
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
                decay = avg / pos.entry_delta if pos.entry_delta else 1
                if decay < EXIT_EXHAUSTION_DECAY_PCT and price > pos.entry_price + 3.0:
                    return ExitReason.EXHAUSTION
            elif pos.direction == 'SHORT' and pos.entry_delta < 0:
                avg = sum(min(0, d) for d in recent) / len(recent)
                decay = avg / pos.entry_delta if pos.entry_delta else 1
                if decay < EXIT_EXHAUSTION_DECAY_PCT and price < pos.entry_price - 3.0:
                    return ExitReason.EXHAUSTION

        # 5. TARGET REACHED
        if pos.target_level and abs(price - pos.target_level) <= 3.0:
            return ExitReason.TARGET_REACHED

        # 6. DIVERGENCE
        if len(pos.delta_history) >= EXIT_DIVERGENCE_BARS:
            prices = pos.price_history[-EXIT_DIVERGENCE_BARS:]
            deltas = pos.delta_history[-EXIT_DIVERGENCE_BARS:]

            if len(prices) >= EXIT_DIVERGENCE_BARS:
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
# MAIN
# ==============================================================================

def run_backtest(start_date: str, end_date: str, save_trades: bool = True):
    """Run full backtest comparison."""

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
    print(f"    Counter-Absorption:  {EXIT_COUNTER_ABS_THRESH}")
    print(f"    Delta Reversal:      {EXIT_DELTA_REVERSAL_BARS} bars @ {EXIT_DELTA_REVERSAL_THRESH}")
    print(f"    Failed Follow-through: {EXIT_FAILED_FOLLOWTHROUGH_BARS} bars / {EXIT_FAILED_FOLLOWTHROUGH_PTS}pts")
    print(f"    Exhaustion Decay:    {EXIT_EXHAUSTION_DECAY_PCT:.0%}")
    print(f"  ")
    print(f"  Fixed Exit Parameters (baseline):")
    print(f"    Stop Loss:           {FIXED_STOP_LOSS_PTS} pts")
    print(f"    Take Profit:         {FIXED_TAKE_PROFIT_PTS} pts")
    print(f"    Time Stop:           {FIXED_TIME_STOP_BARS} bars")

    # Load data
    df = load_historical_data(start_date, end_date)
    if df is None or df.empty:
        print("\nNo data available for backtest.")
        return None, None

    # Get approximate current price for level classification
    current_price = df['close'].iloc[0]

    # Run WITH exit monitor
    print("\n[1/2] Running backtest WITH Exit Monitor...")
    engine_with = BacktestEngine(use_exit_monitor=True)
    engine_with.load_levels(LEVELS_FILE, CONTEXT_FILE, current_price)

    bar_count = 0
    total_bars = len(df)
    for timestamp, row in df.iterrows():
        engine_with.process_bar(row, timestamp)
        bar_count += 1
        if bar_count % 5000 == 0:
            print(f"  Processing: {bar_count:,}/{total_bars:,} bars ({bar_count/total_bars*100:.0f}%)", end='\r')

    engine_with.finalize(df.index[-1], df['close'].iloc[-1])
    results_with = engine_with.get_results()
    print(f"  Completed: {results_with.total_trades} trades                    ")

    # Run WITHOUT exit monitor
    print("[2/2] Running backtest WITHOUT Exit Monitor (Fixed Stops)...")
    engine_without = BacktestEngine(use_exit_monitor=False)
    engine_without.load_levels(LEVELS_FILE, CONTEXT_FILE, current_price)

    bar_count = 0
    for timestamp, row in df.iterrows():
        engine_without.process_bar(row, timestamp)
        bar_count += 1
        if bar_count % 5000 == 0:
            print(f"  Processing: {bar_count:,}/{total_bars:,} bars ({bar_count/total_bars*100:.0f}%)", end='\r')

    engine_without.finalize(df.index[-1], df['close'].iloc[-1])
    results_without = engine_without.get_results()
    print(f"  Completed: {results_without.total_trades} trades                    ")

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
    print("\nThis uses OHLCV-1m data with simulated order flow.")
    print("Longer date ranges are now supported.\n")

    # Get date range from user
    print("Enter backtest date range:")
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
        return

    run_backtest(start, end)


if __name__ == "__main__":
    main()
