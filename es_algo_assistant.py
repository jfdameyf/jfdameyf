"""
ES ALGO ASSISTANT - PRODUCTION VERSION (IMPROVED)
Features:
1. Daily Market Planner (Zones & Significance)
2. Dual-Engine Live Bot (2m Sniper + Blind Grid)
3. 1-Minute Pre-Alert System (Early Warning Confluence)

Improvements:
- Performance: Price bucketing for O(1) level lookups, async Discord posts
- Memory: Automatic cleanup of stale grid monitors
- Error Handling: Comprehensive try/except with reconnection logic
- Timezone: Standardized datetime handling (no mixed pd.Timestamp/datetime)
- Delta Convention: Clearly documented sign convention
- Signal Logging: All signals written to CSV with full metrics
"""

import pandas as pd
import numpy as np
import databento as db
import yfinance as yf
import joblib
import json
import os
import sys
import shutil
import requests
from datetime import datetime, time, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import pytz
import warnings
import asyncio
import threading
import logging
import csv
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Load from environment variables (security best practice)
API_KEY = os.getenv("DATABENTO_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_SIGNALS_WEBHOOK_URL = os.getenv("DISCORD_SIGNALS_WEBHOOK_URL", "")

# --- STRATEGY SETTINGS ---

# 1. MAIN TRIGGER (2-Minute Sniper)
# The high-confidence setup found in backtesting
LEVEL_ABS_THRESH = 6000
LEVEL_DELTA_THRESH = 700
LEVEL_TIMEFRAME = 2

# 2. PRE-ALERT (1-Minute Early Warning)
# Lighter threshold to signal potential incoming setups
PRE_ALERT_ABS_THRESH = 5000
PRE_ALERT_DELTA_THRESH = 700
PRE_ALERT_TIMEFRAME = 1

# 3. SAFETY NET (Blind Grid)
# Massive absorption required to trade without a level
BLIND_ABS_THRESH = 8000
BLIND_DELTA_THRESH = 700
BLIND_TIMEFRAME = 2

# Level proximity tolerance (points)
LEVEL_TOLERANCE = 3.0

# Grid monitor cleanup settings
GRID_CLEANUP_INTERVAL = 300  # seconds (5 minutes)
GRID_STALE_THRESHOLD = 600   # seconds (10 minutes)

# --- EXIT MONITORING SETTINGS ---
# These control when the bot suggests exiting a position

# Invalidation Thresholds
EXIT_COUNTER_ABS_THRESH = 4000      # Counter-absorption threshold (opposing wall forming)
EXIT_DELTA_REVERSAL_BARS = 3        # Consecutive bars of opposite delta to invalidate
EXIT_DELTA_REVERSAL_THRESH = 500    # Min delta magnitude per bar for reversal
EXIT_FAILED_FOLLOWTHROUGH_BARS = 5  # Bars without price progress = failed trade
EXIT_FAILED_FOLLOWTHROUGH_PTS = 2.0 # Minimum points of progress expected

# Profit-Taking Thresholds
EXIT_EXHAUSTION_DECAY_PCT = 0.5     # Delta decaying to 50% of entry delta = exhaustion
EXIT_EXHAUSTION_MIN_BARS = 3        # Minimum bars to detect exhaustion pattern
EXIT_TARGET_ABS_THRESH = 5000       # Absorption at target level = take profit zone
EXIT_DIVERGENCE_BARS = 4            # Bars to detect divergence pattern

SYMBOL = "ES.c.0"
LIVE_SYMBOL = "ES.c.0"
NY_TZ = pytz.timezone('America/New_York')

# Files
CRITICAL_LEVELS_FILE = "critical_levels_master_enhanced.csv"
OUTPUT_FILE = "daily_context_v2.json"
STATE_FILE = "strategy_state.json"
LOG_DIR = "logs"
SIGNALS_LOG_FILE = f"{LOG_DIR}/signals_{datetime.now().strftime('%Y%m%d')}.csv"

os.makedirs(LOG_DIR, exist_ok=True)

warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'{LOG_DIR}/es_bot_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==============================================================================
# DELTA SIGN CONVENTION (DOCUMENTED)
# ==============================================================================
"""
DELTA SIGN CONVENTION:
----------------------
This bot uses the following consistent convention for order flow delta:

  - POSITIVE DELTA (+): Net buying pressure (more aggressive buyers hitting asks)
  - NEGATIVE DELTA (-): Net selling pressure (more aggressive sellers hitting bids)

Trade Side Classification (from Databento):
  - Side 'A' (Ask): Buyer-initiated trade -> ADD to delta
  - Side 'B' (Bid): Seller-initiated trade -> SUBTRACT from delta

Signal Confirmation Logic:
  - SUPPORT (SUP): We need sellers to be absorbed, then buyers to step in
    * Absorption: Track seller volume (side 'B') hitting the level
    * Confirmation: Delta must be POSITIVE (buyers won) -> delta >= +threshold

  - RESISTANCE (RES): We need buyers to be absorbed, then sellers to step in
    * Absorption: Track buyer volume (side 'A') hitting the level
    * Confirmation: Delta must be NEGATIVE (sellers won) -> delta <= -threshold

This means:
  - Long signals trigger when: absorption at support + positive delta confirmation
  - Short signals trigger when: absorption at resistance + negative delta confirmation
"""


# ==============================================================================
# SIGNAL LOGGER
# ==============================================================================
@dataclass
class SignalRecord:
    """Structured signal record for logging."""
    timestamp: str
    signal_type: str  # PRE_ALERT, LEVEL_CONFIRMATION, INSTITUTIONAL_WALL
    direction: str    # LONG or SHORT
    price: float
    level_type: str   # SUP or RES
    absorption_volume: int
    candle_delta: int
    candle_timeframe: str  # 1m or 2m
    source_level_category: str = ""
    source_level_zone: str = ""
    notes: str = ""


@dataclass
class ActivePosition:
    """
    Tracks an active position for exit monitoring.

    Created when a signal fires, monitored until exit signal triggers.
    """
    position_id: str
    direction: str              # 'LONG' or 'SHORT'
    entry_price: float
    entry_time: datetime
    entry_absorption: int       # Absorption volume at entry
    entry_delta: int            # Delta at entry candle
    source: str                 # Signal source type
    entry_level_price: float    # The level that triggered entry

    # Tracking state
    bars_since_entry: int = 0
    max_favorable_price: float = 0.0
    min_favorable_price: float = 0.0
    delta_history: List[int] = field(default_factory=list)
    price_history: List[float] = field(default_factory=list)

    # Target level (next resistance for LONG, next support for SHORT)
    target_level: Optional[float] = None
    target_level_type: str = ""

    def __post_init__(self):
        if self.direction == 'LONG':
            self.max_favorable_price = self.entry_price
            self.min_favorable_price = self.entry_price
        else:
            self.max_favorable_price = self.entry_price
            self.min_favorable_price = self.entry_price


@dataclass
class ExitSignal:
    """Represents an exit recommendation."""
    position_id: str
    exit_type: str      # INVALIDATION, EXHAUSTION, TARGET_ABSORPTION, DIVERGENCE, COUNTER_ABSORPTION
    reason: str
    urgency: str        # 'IMMEDIATE' or 'CONSIDER'
    current_price: float
    entry_price: float
    pnl_points: float
    metrics: dict = field(default_factory=dict)


class SignalLogger:
    """Handles writing signals to CSV log file."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.lock = threading.Lock()
        self._init_csv()

    def _init_csv(self):
        """Initialize CSV file with headers if it doesn't exist."""
        if not os.path.exists(self.filepath):
            with open(self.filepath, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'timestamp', 'signal_type', 'direction', 'price',
                    'level_type', 'absorption_volume', 'candle_delta',
                    'candle_timeframe', 'source_level_category',
                    'source_level_zone', 'notes'
                ])
                writer.writeheader()
            logger.info(f"Created signal log file: {self.filepath}")

    def log_signal(self, record: SignalRecord):
        """Thread-safe signal logging."""
        with self.lock:
            try:
                with open(self.filepath, 'a', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=asdict(record).keys())
                    writer.writerow(asdict(record))
            except Exception as e:
                logger.error(f"Failed to write signal to log: {e}")


# ==============================================================================
# ASYNC DISCORD NOTIFIER
# ==============================================================================
class AsyncDiscordNotifier:
    """Non-blocking Discord notifications using a thread pool."""

    def __init__(self, max_workers: int = 2):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="discord")
        self.enabled = bool(DISCORD_WEBHOOK_URL or DISCORD_SIGNALS_WEBHOOK_URL)

    def _post_webhook(self, webhook_url: str, payload: dict):
        """Actual HTTP POST (runs in thread pool)."""
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            if response.status_code >= 400:
                logger.warning(f"Discord webhook returned {response.status_code}")
        except requests.RequestException as e:
            logger.warning(f"Discord webhook failed: {e}")

    def send_signal(self, price: float, direction: str, source: str, message: str):
        """Queue a signal notification (non-blocking)."""
        if not self.enabled:
            return

        webhook = DISCORD_SIGNALS_WEBHOOK_URL or DISCORD_WEBHOOK_URL
        if not webhook:
            return

        # Color coding: Yellow for Pre-Alert, Green/Red for Signals
        if source == "PRE_ALERT":
            color = 0xF1C40F  # Yellow
            title = f"ES 1m PRE-ALERT ({direction})"
        else:
            color = 0x00ff00 if direction == "LONG" else 0xff0000
            title = f"ES {direction} SIGNAL"

        embed = {
            "title": title,
            "description": f"**Price:** {price:.2f}\n**Type:** {source}\n**Info:** {message}",
            "color": color,
            "footer": {"text": f"ES Bot - {source}"}
        }

        # Submit to thread pool (non-blocking)
        self.executor.submit(self._post_webhook, webhook, {"embeds": [embed]})

    def send_exit_signal(self, exit_signal: 'ExitSignal'):
        """Queue an exit signal notification (non-blocking)."""
        if not self.enabled:
            return

        webhook = DISCORD_SIGNALS_WEBHOOK_URL or DISCORD_WEBHOOK_URL
        if not webhook:
            return

        # Color coding based on exit type and urgency
        if exit_signal.urgency == 'IMMEDIATE':
            # Red/Orange for immediate exits (invalidation)
            color = 0xE74C3C if exit_signal.pnl_points < 0 else 0xE67E22
            emoji = "X" if exit_signal.pnl_points < 0 else "!!"
        else:
            # Blue for consideration exits (profit-taking)
            color = 0x3498DB
            emoji = "$"

        # P&L formatting
        pnl_str = f"+{exit_signal.pnl_points:.2f}" if exit_signal.pnl_points >= 0 else f"{exit_signal.pnl_points:.2f}"

        embed = {
            "title": f"{emoji} EXIT SIGNAL: {exit_signal.exit_type}",
            "description": (
                f"**Urgency:** {exit_signal.urgency}\n"
                f"**Entry:** {exit_signal.entry_price:.2f}\n"
                f"**Current:** {exit_signal.current_price:.2f}\n"
                f"**P&L:** {pnl_str} pts\n\n"
                f"**Reason:** {exit_signal.reason}"
            ),
            "color": color,
            "footer": {"text": f"ES Bot - Exit Monitor | {exit_signal.position_id}"}
        }

        self.executor.submit(self._post_webhook, webhook, {"embeds": [embed]})

    def send_plan(self, plan: dict):
        """Queue a daily plan notification (non-blocking)."""
        if not DISCORD_WEBHOOK_URL:
            return

        sup_str = "\n".join(plan['levels']['sup_distributed'][:8]) if plan['levels']['sup_distributed'] else "None"
        res_str = "\n".join(plan['levels']['res_distributed'][:8]) if plan['levels']['res_distributed'] else "None"

        embed = {
            "title": f"ES Daily Plan | {plan['timestamp'].split(' ')[0]}",
            "color": 0x3498db,
            "fields": [
                {"name": "Context", "value": f"{plan['context_location']} -> {plan['context_insight']}", "inline": False},
                {"name": "Key Support", "value": f"```\n{sup_str}\n```", "inline": True},
                {"name": "Key Resistance", "value": f"```\n{res_str}\n```", "inline": True},
                {"name": "Profile Data", "value": f"POC: {plan['pd_profile']['POC']:.2f} | VAH: {plan['pd_profile']['VAH']:.2f} | VAL: {plan['pd_profile']['VAL']:.2f}", "inline": False}
            ],
            "footer": {"text": "ES Algo Assistant - Daily Context"}
        }

        self.executor.submit(self._post_webhook, DISCORD_WEBHOOK_URL, {"embeds": [embed]})

    def shutdown(self):
        """Clean shutdown of thread pool."""
        self.executor.shutdown(wait=True)


# ==============================================================================
# CORE LOGIC: ABSORPTION MONITOR
# ==============================================================================
class AbsorptionMonitor:
    """
    Tracks cumulative opposing volume at a price level.

    For SUPPORT levels: tracks seller volume (side 'B') being absorbed
    For RESISTANCE levels: tracks buyer volume (side 'A') being absorbed
    """

    def __init__(self, price_key: float, level_type: str, abs_threshold: int,
                 category: str = "", zone: str = ""):
        self.price_key = price_key
        self.level_type = level_type  # 'SUP' or 'RES'
        self.ABSORPTION_THRESHOLD = abs_threshold
        self.category = category
        self.zone = zone

        # State
        self.state = "WATCHING"
        self.last_update_time: Optional[datetime] = None
        self.cumulative_opposing_vol = 0

        # Cleanup timer (10 mins for ES)
        self.RESET_TIMEOUT = 600

    def update(self, size: int, side: str, current_time: datetime) -> None:
        """
        Update absorption state with new trade.

        Args:
            size: Trade size (contracts)
            side: 'A' (ask/buyer-initiated) or 'B' (bid/seller-initiated)
            current_time: Trade timestamp (must be datetime with timezone)
        """
        # Validate inputs
        if not isinstance(current_time, datetime):
            logger.warning(f"Invalid current_time type: {type(current_time)}, expected datetime")
            return

        if side not in ('A', 'B'):
            logger.warning(f"Invalid trade side: {side}, expected 'A' or 'B'")
            return

        if size <= 0:
            return

        if self.last_update_time is None:
            self.last_update_time = current_time

        # Check for stale data - reset if no activity for RESET_TIMEOUT
        try:
            time_diff = (current_time - self.last_update_time).total_seconds()
            if time_diff > self.RESET_TIMEOUT:
                self._reset()
        except (TypeError, AttributeError) as e:
            logger.warning(f"Error calculating time difference: {e}")
            self._reset()

        self.last_update_time = current_time

        # Classify Volume (Opposing Flow Only)
        # SUP needs Sellers (B) to be absorbed -> track side 'B'
        # RES needs Buyers (A) to be absorbed -> track side 'A'
        is_opposing = False
        if self.level_type == 'SUP' and side == 'B':
            is_opposing = True
        elif self.level_type == 'RES' and side == 'A':
            is_opposing = True

        if is_opposing:
            self.cumulative_opposing_vol += size

        # Trigger State Change
        if self.state == "WATCHING" and self.cumulative_opposing_vol >= self.ABSORPTION_THRESHOLD:
            self.state = "ABSORBING"

    def _reset(self) -> None:
        """Reset monitor to initial watching state."""
        self.state = "WATCHING"
        self.cumulative_opposing_vol = 0
        self.last_update_time = None

    def get_metrics(self) -> dict:
        """Return current monitor metrics for logging."""
        return {
            'price': self.price_key,
            'type': self.level_type,
            'state': self.state,
            'absorption': self.cumulative_opposing_vol,
            'threshold': self.ABSORPTION_THRESHOLD,
            'category': self.category,
            'zone': self.zone
        }


# ==============================================================================
# PRICE BUCKET INDEX (Performance Optimization)
# ==============================================================================
class PriceBucketIndex:
    """
    Spatial index for O(1) level proximity lookups.

    Instead of iterating all monitors for each tick, we bucket monitors
    by price and only check relevant buckets.
    """

    def __init__(self, bucket_size: float = 1.0, tolerance: float = 3.0):
        self.bucket_size = bucket_size
        self.tolerance = tolerance
        self.buckets: Dict[int, List[str]] = defaultdict(list)  # bucket_id -> list of monitor keys

    def _get_bucket_id(self, price: float) -> int:
        """Get bucket ID for a price."""
        return int(price / self.bucket_size)

    def add_level(self, price: float, monitor_key: str) -> None:
        """Add a level to the index."""
        bucket_id = self._get_bucket_id(price)
        if monitor_key not in self.buckets[bucket_id]:
            self.buckets[bucket_id].append(monitor_key)

    def get_nearby_keys(self, price: float) -> List[str]:
        """Get all monitor keys within tolerance of price (O(1) average)."""
        center_bucket = self._get_bucket_id(price)
        # Check buckets within tolerance range
        bucket_range = int(self.tolerance / self.bucket_size) + 1

        nearby_keys = []
        for offset in range(-bucket_range, bucket_range + 1):
            bucket_id = center_bucket + offset
            if bucket_id in self.buckets:
                nearby_keys.extend(self.buckets[bucket_id])

        return nearby_keys

    def clear(self) -> None:
        """Clear all buckets."""
        self.buckets.clear()


# ==============================================================================
# EXIT MONITOR (Order Flow Based Exit Signals)
# ==============================================================================
class ExitMonitor:
    """
    Monitors active positions for exit signals based on order flow.

    Exit Types:
    -----------
    INVALIDATION signals (suggests stopping out):
    1. COUNTER_ABSORPTION: Opposing wall forming ahead of position
    2. DELTA_REVERSAL: Sustained opposite delta (momentum shift)
    3. FAILED_FOLLOWTHROUGH: Price not moving as expected

    PROFIT-TAKING signals (suggests taking profits):
    4. EXHAUSTION: Delta magnitude fading while price extends
    5. TARGET_ABSORPTION: Absorption detected at target level
    6. DIVERGENCE: Price making new highs/lows but delta failing
    """

    def __init__(self, context: dict, signal_logger: 'SignalLogger'):
        self.context = context
        self.signal_logger = signal_logger
        self.positions: Dict[str, ActivePosition] = {}
        self.position_counter = 0

        # Counter-absorption monitors (tracks opposing walls forming)
        self.counter_monitors: Dict[str, AbsorptionMonitor] = {}

        # Build target level lookup from context
        self.resistance_levels: List[float] = []
        self.support_levels: List[float] = []
        self._build_level_lookup()

    def _build_level_lookup(self) -> None:
        """Build sorted lists of levels for target finding."""
        if not self.context:
            return

        levels = self.context.get('levels', {})

        for level in levels.get('raw_res', []):
            if 'price' in level:
                self.resistance_levels.append(level['price'])

        for level in levels.get('raw_sup', []):
            if 'price' in level:
                self.support_levels.append(level['price'])

        self.resistance_levels.sort()
        self.support_levels.sort(reverse=True)

        logger.debug(f"ExitMonitor: Loaded {len(self.resistance_levels)} resistance, {len(self.support_levels)} support levels")

    def _find_target_level(self, entry_price: float, direction: str) -> Tuple[Optional[float], str]:
        """
        Find the next target level for a position.

        For LONG: next resistance above entry
        For SHORT: next support below entry
        """
        if direction == 'LONG':
            for level in self.resistance_levels:
                if level > entry_price + 1.0:  # At least 1 point above
                    return level, 'RES'
        else:  # SHORT
            for level in self.support_levels:
                if level < entry_price - 1.0:  # At least 1 point below
                    return level, 'SUP'

        return None, ''

    def register_position(self, signal: dict, current_price: float,
                         current_time: datetime) -> str:
        """
        Register a new position for exit monitoring.

        Args:
            signal: The entry signal dict from StrategyManager
            current_price: Current market price
            current_time: Current timestamp

        Returns:
            Position ID for tracking
        """
        self.position_counter += 1
        position_id = f"POS_{current_time.strftime('%H%M%S')}_{self.position_counter}"

        direction = 'LONG' if signal['type'] == 'SUP' else 'SHORT'
        target_level, target_type = self._find_target_level(signal['price'], direction)

        position = ActivePosition(
            position_id=position_id,
            direction=direction,
            entry_price=signal['price'],
            entry_time=current_time,
            entry_absorption=signal.get('absorption', 0),
            entry_delta=signal.get('delta', 0),
            source=signal['source'],
            entry_level_price=signal['price'],
            target_level=target_level,
            target_level_type=target_type
        )

        self.positions[position_id] = position

        # Create counter-absorption monitor
        # For LONG: watch for buyer absorption above (resistance forming)
        # For SHORT: watch for seller absorption below (support forming)
        counter_type = 'RES' if direction == 'LONG' else 'SUP'
        self.counter_monitors[position_id] = AbsorptionMonitor(
            price_key=current_price,  # Will track dynamically
            level_type=counter_type,
            abs_threshold=EXIT_COUNTER_ABS_THRESH
        )

        logger.info(f"ExitMonitor: Registered {direction} position {position_id} @ {signal['price']:.2f}, target={target_level}")

        return position_id

    def remove_position(self, position_id: str) -> None:
        """Remove a position from monitoring."""
        if position_id in self.positions:
            del self.positions[position_id]
        if position_id in self.counter_monitors:
            del self.counter_monitors[position_id]
        logger.info(f"ExitMonitor: Removed position {position_id}")

    def update_on_candle_close(self, current_price: float, candle_delta: int,
                               current_time: datetime) -> List[ExitSignal]:
        """
        Update positions on candle close and check for exit signals.

        Called at the end of each 2m candle.
        """
        exit_signals = []

        for position_id, position in list(self.positions.items()):
            # Update tracking data
            position.bars_since_entry += 1
            position.delta_history.append(candle_delta)
            position.price_history.append(current_price)

            # Keep history bounded
            if len(position.delta_history) > 20:
                position.delta_history.pop(0)
            if len(position.price_history) > 20:
                position.price_history.pop(0)

            # Update extreme prices
            if position.direction == 'LONG':
                position.max_favorable_price = max(position.max_favorable_price, current_price)
            else:
                position.min_favorable_price = min(position.min_favorable_price, current_price)

            # Calculate P&L
            if position.direction == 'LONG':
                pnl = current_price - position.entry_price
            else:
                pnl = position.entry_price - current_price

            # Check all exit conditions
            exit_signal = self._check_exit_conditions(position, current_price, candle_delta, pnl)

            if exit_signal:
                exit_signals.append(exit_signal)
                self._log_exit_signal(exit_signal, current_time)

        return exit_signals

    def update_on_tick(self, price: float, size: int, side: str,
                      current_time: datetime) -> None:
        """
        Update counter-absorption monitors on each tick.

        This tracks if an opposing wall is forming ahead of the position.
        """
        for position_id, position in self.positions.items():
            monitor = self.counter_monitors.get(position_id)
            if not monitor:
                continue

            # Only track absorption in the direction of potential exit
            # LONG position: track absorption above current price (resistance forming)
            # SHORT position: track absorption below current price (support forming)
            if position.direction == 'LONG':
                # Track buyer absorption above entry (would-be resistance)
                if price > position.entry_price + 2.0:
                    monitor.price_key = price  # Update tracking price
                    monitor.update(size, side, current_time)
            else:
                # Track seller absorption below entry (would-be support)
                if price < position.entry_price - 2.0:
                    monitor.price_key = price
                    monitor.update(size, side, current_time)

    def _check_exit_conditions(self, position: ActivePosition, current_price: float,
                               candle_delta: int, pnl: float) -> Optional[ExitSignal]:
        """
        Check all exit conditions for a position.

        Returns ExitSignal if any condition triggers, None otherwise.
        Priority: Invalidation signals take precedence over profit-taking.
        """
        position_id = position.position_id

        # =====================================================================
        # INVALIDATION CHECKS (Stop Loss Signals)
        # =====================================================================

        # 1. COUNTER-ABSORPTION: Opposing wall forming
        counter_monitor = self.counter_monitors.get(position_id)
        if counter_monitor and counter_monitor.state == "ABSORBING":
            return ExitSignal(
                position_id=position_id,
                exit_type='COUNTER_ABSORPTION',
                reason=f"Opposing wall detected: {counter_monitor.cumulative_opposing_vol} contracts absorbed",
                urgency='IMMEDIATE',
                current_price=current_price,
                entry_price=position.entry_price,
                pnl_points=pnl,
                metrics={
                    'counter_absorption': counter_monitor.cumulative_opposing_vol,
                    'wall_price': counter_monitor.price_key
                }
            )

        # 2. DELTA REVERSAL: Sustained opposite delta
        if len(position.delta_history) >= EXIT_DELTA_REVERSAL_BARS:
            recent_deltas = position.delta_history[-EXIT_DELTA_REVERSAL_BARS:]

            if position.direction == 'LONG':
                # For LONG: consecutive negative deltas = bearish reversal
                reversal = all(d <= -EXIT_DELTA_REVERSAL_THRESH for d in recent_deltas)
            else:
                # For SHORT: consecutive positive deltas = bullish reversal
                reversal = all(d >= EXIT_DELTA_REVERSAL_THRESH for d in recent_deltas)

            if reversal:
                avg_reversal_delta = sum(recent_deltas) / len(recent_deltas)
                return ExitSignal(
                    position_id=position_id,
                    exit_type='DELTA_REVERSAL',
                    reason=f"{EXIT_DELTA_REVERSAL_BARS} consecutive bars of opposing delta (avg {avg_reversal_delta:+.0f})",
                    urgency='IMMEDIATE',
                    current_price=current_price,
                    entry_price=position.entry_price,
                    pnl_points=pnl,
                    metrics={
                        'reversal_deltas': recent_deltas,
                        'bars': EXIT_DELTA_REVERSAL_BARS
                    }
                )

        # 3. FAILED FOLLOW-THROUGH: Price not progressing
        if position.bars_since_entry >= EXIT_FAILED_FOLLOWTHROUGH_BARS:
            if position.direction == 'LONG':
                progress = position.max_favorable_price - position.entry_price
            else:
                progress = position.entry_price - position.min_favorable_price

            if progress < EXIT_FAILED_FOLLOWTHROUGH_PTS:
                return ExitSignal(
                    position_id=position_id,
                    exit_type='FAILED_FOLLOWTHROUGH',
                    reason=f"Only {progress:.2f}pts progress in {position.bars_since_entry} bars",
                    urgency='IMMEDIATE',
                    current_price=current_price,
                    entry_price=position.entry_price,
                    pnl_points=pnl,
                    metrics={
                        'bars_elapsed': position.bars_since_entry,
                        'max_progress': progress,
                        'required': EXIT_FAILED_FOLLOWTHROUGH_PTS
                    }
                )

        # =====================================================================
        # PROFIT-TAKING CHECKS (Only if position is profitable)
        # =====================================================================

        if pnl <= 0:
            return None  # Don't suggest profit-taking on losing positions

        # 4. EXHAUSTION: Delta magnitude fading while price extends
        if len(position.delta_history) >= EXIT_EXHAUSTION_MIN_BARS and position.entry_delta != 0:
            recent_deltas = position.delta_history[-EXIT_EXHAUSTION_MIN_BARS:]

            if position.direction == 'LONG':
                # For LONG: entry delta was positive, check if recent deltas are weaker
                if position.entry_delta > 0:
                    avg_recent = sum(max(0, d) for d in recent_deltas) / len(recent_deltas)
                    decay_ratio = avg_recent / position.entry_delta if position.entry_delta else 1
                    price_extended = current_price > position.entry_price + 3.0

                    if decay_ratio < EXIT_EXHAUSTION_DECAY_PCT and price_extended:
                        return ExitSignal(
                            position_id=position_id,
                            exit_type='EXHAUSTION',
                            reason=f"Delta decayed to {decay_ratio:.0%} of entry while +{pnl:.1f}pts",
                            urgency='CONSIDER',
                            current_price=current_price,
                            entry_price=position.entry_price,
                            pnl_points=pnl,
                            metrics={
                                'entry_delta': position.entry_delta,
                                'recent_avg_delta': avg_recent,
                                'decay_ratio': decay_ratio
                            }
                        )
            else:
                # For SHORT: entry delta was negative, check if recent deltas are weaker
                if position.entry_delta < 0:
                    avg_recent = sum(min(0, d) for d in recent_deltas) / len(recent_deltas)
                    decay_ratio = avg_recent / position.entry_delta if position.entry_delta else 1
                    price_extended = current_price < position.entry_price - 3.0

                    if decay_ratio < EXIT_EXHAUSTION_DECAY_PCT and price_extended:
                        return ExitSignal(
                            position_id=position_id,
                            exit_type='EXHAUSTION',
                            reason=f"Delta decayed to {decay_ratio:.0%} of entry while +{pnl:.1f}pts",
                            urgency='CONSIDER',
                            current_price=current_price,
                            entry_price=position.entry_price,
                            pnl_points=pnl,
                            metrics={
                                'entry_delta': position.entry_delta,
                                'recent_avg_delta': avg_recent,
                                'decay_ratio': decay_ratio
                            }
                        )

        # 5. TARGET ABSORPTION: Approaching target level with absorption
        if position.target_level:
            distance_to_target = abs(current_price - position.target_level)

            if distance_to_target <= 3.0:  # Within 3 points of target
                return ExitSignal(
                    position_id=position_id,
                    exit_type='TARGET_REACHED',
                    reason=f"Price within {distance_to_target:.1f}pts of target {position.target_level:.2f}",
                    urgency='CONSIDER',
                    current_price=current_price,
                    entry_price=position.entry_price,
                    pnl_points=pnl,
                    metrics={
                        'target_level': position.target_level,
                        'distance': distance_to_target
                    }
                )

        # 6. DIVERGENCE: Price making new extremes but delta failing
        if len(position.delta_history) >= EXIT_DIVERGENCE_BARS and len(position.price_history) >= EXIT_DIVERGENCE_BARS:
            recent_prices = position.price_history[-EXIT_DIVERGENCE_BARS:]
            recent_deltas = position.delta_history[-EXIT_DIVERGENCE_BARS:]

            if position.direction == 'LONG':
                # Check if price making higher highs but delta making lower highs
                price_higher = recent_prices[-1] > recent_prices[0]
                delta_peaks = [d for d in recent_deltas if d > 0]

                if len(delta_peaks) >= 2 and price_higher:
                    delta_weakening = delta_peaks[-1] < delta_peaks[0] * 0.7
                    if delta_weakening:
                        return ExitSignal(
                            position_id=position_id,
                            exit_type='DIVERGENCE',
                            reason=f"Price rising but delta weakening ({delta_peaks[0]:+d} -> {delta_peaks[-1]:+d})",
                            urgency='CONSIDER',
                            current_price=current_price,
                            entry_price=position.entry_price,
                            pnl_points=pnl,
                            metrics={
                                'price_change': recent_prices[-1] - recent_prices[0],
                                'delta_peaks': delta_peaks
                            }
                        )
            else:
                # Check if price making lower lows but delta making higher lows
                price_lower = recent_prices[-1] < recent_prices[0]
                delta_troughs = [d for d in recent_deltas if d < 0]

                if len(delta_troughs) >= 2 and price_lower:
                    delta_weakening = delta_troughs[-1] > delta_troughs[0] * 0.7
                    if delta_weakening:
                        return ExitSignal(
                            position_id=position_id,
                            exit_type='DIVERGENCE',
                            reason=f"Price falling but delta weakening ({delta_troughs[0]:+d} -> {delta_troughs[-1]:+d})",
                            urgency='CONSIDER',
                            current_price=current_price,
                            entry_price=position.entry_price,
                            pnl_points=pnl,
                            metrics={
                                'price_change': recent_prices[-1] - recent_prices[0],
                                'delta_troughs': delta_troughs
                            }
                        )

        return None

    def _log_exit_signal(self, signal: ExitSignal, current_time: datetime) -> None:
        """Log exit signal to CSV."""
        self.signal_logger.log_signal(SignalRecord(
            timestamp=current_time.strftime('%Y-%m-%d %H:%M:%S'),
            signal_type=f'EXIT_{signal.exit_type}',
            direction='EXIT',
            price=signal.current_price,
            level_type=signal.exit_type,
            absorption_volume=signal.metrics.get('counter_absorption', 0),
            candle_delta=signal.metrics.get('entry_delta', 0),
            candle_timeframe='2m',
            source_level_category=signal.urgency,
            source_level_zone='',
            notes=f"PnL: {signal.pnl_points:+.2f}pts | {signal.reason}"
        ))

    def get_active_positions(self) -> Dict[str, ActivePosition]:
        """Return all active positions."""
        return self.positions.copy()

    def get_position_status(self, position_id: str) -> Optional[dict]:
        """Get status summary for a position."""
        position = self.positions.get(position_id)
        if not position:
            return None

        return {
            'position_id': position_id,
            'direction': position.direction,
            'entry_price': position.entry_price,
            'bars_since_entry': position.bars_since_entry,
            'entry_delta': position.entry_delta,
            'recent_deltas': position.delta_history[-5:] if position.delta_history else [],
            'target_level': position.target_level,
            'max_favorable': position.max_favorable_price if position.direction == 'LONG' else position.min_favorable_price
        }


# ==============================================================================
# STRATEGY MANAGER (Tri-Engine: Pre-Alert + Sniper + Grid)
# ==============================================================================
class StrategyManager:
    """
    Manages three signal engines:
    1. Pre-Alert (1m): Early warning on context levels
    2. Level Sniper (2m): High-confidence context level signals
    3. Blind Grid (2m): Institutional walls at any price
    """

    def __init__(self, signal_logger: SignalLogger):
        self.signal_logger = signal_logger
        self.context = self.load_latest_context()

        # --- ENGINE 1: MAIN LEVEL MONITORS (2-Min) ---
        self.main_monitors: Dict[str, AbsorptionMonitor] = {}
        # --- ENGINE 2: PRE-ALERT MONITORS (1-Min) ---
        self.pre_monitors: Dict[str, AbsorptionMonitor] = {}
        # Pre-alert cooldown tracking (prevent spam)
        self.pre_alert_cooldowns: Dict[str, datetime] = {}
        self.PRE_ALERT_COOLDOWN = 300  # 5 minute cooldown per level

        # Price bucket index for O(1) lookups
        self.level_index = PriceBucketIndex(bucket_size=1.0, tolerance=LEVEL_TOLERANCE)

        self._init_level_monitors()

        # --- ENGINE 3: BLIND GRID (2-Min) ---
        self.grid_monitors: Dict[float, Dict[str, AbsorptionMonitor]] = {}
        self.GRID_SIZE = 2.0
        self.last_grid_cleanup = datetime.now(NY_TZ)

        # Candle State (Independent tracking for 1m and 2m)
        # Using datetime consistently (no pd.Timestamp)
        self.candle_2m_time: Optional[datetime] = None
        self.candle_2m_delta = 0
        self.last_close_delta_2m = 0

        self.candle_1m_time: Optional[datetime] = None
        self.candle_1m_delta = 0
        self.last_close_delta_1m = 0

        # --- ENGINE 4: EXIT MONITOR ---
        self.exit_monitor = ExitMonitor(self.context, signal_logger)

        # Track current price for exit monitoring
        self.current_price = 0.0

    def _init_level_monitors(self) -> None:
        """Initialize both Main (2m) and Pre-Alert (1m) monitors for every level."""
        if not self.context:
            logger.warning("No context loaded - level monitors not initialized")
            return

        def add_monitors(levels: List[dict], l_type: str) -> None:
            for level in levels:
                price = level.get('price')
                if price is None:
                    continue

                key = f"{price}_{l_type}"
                category = level.get('category', '')
                zone = level.get('zone', '')

                # 1. Main Monitor (6000 Abs threshold)
                self.main_monitors[key] = AbsorptionMonitor(
                    price, l_type, LEVEL_ABS_THRESH, category, zone
                )
                # 2. Pre-Alert Monitor (5000 Abs threshold)
                self.pre_monitors[key] = AbsorptionMonitor(
                    price, l_type, PRE_ALERT_ABS_THRESH, category, zone
                )
                # Add to spatial index
                self.level_index.add_level(price, key)

        levels_data = self.context.get('levels', {})
        add_monitors(levels_data.get('raw_sup', []), 'SUP')
        add_monitors(levels_data.get('raw_res', []), 'RES')

        logger.info(f"Initialized {len(self.main_monitors)} level monitors")

    def _floor_to_candle(self, current_time: datetime, timeframe_minutes: int) -> datetime:
        """
        Floor datetime to candle boundary.

        Standardized method - always works with datetime objects.
        """
        minute = (current_time.minute // timeframe_minutes) * timeframe_minutes
        return current_time.replace(minute=minute, second=0, microsecond=0)

    def _cleanup_stale_grid_monitors(self, current_time: datetime) -> None:
        """Remove grid monitors that haven't been updated recently."""
        if (current_time - self.last_grid_cleanup).total_seconds() < GRID_CLEANUP_INTERVAL:
            return

        stale_keys = []
        for price_key, pair in self.grid_monitors.items():
            # Check if both monitors are stale
            all_stale = True
            for l_type, monitor in pair.items():
                if monitor.last_update_time is not None:
                    age = (current_time - monitor.last_update_time).total_seconds()
                    if age < GRID_STALE_THRESHOLD:
                        all_stale = False
                        break
                elif monitor.cumulative_opposing_vol > 0:
                    all_stale = False
                    break

            if all_stale:
                stale_keys.append(price_key)

        for key in stale_keys:
            del self.grid_monitors[key]

        if stale_keys:
            logger.debug(f"Cleaned up {len(stale_keys)} stale grid monitors")

        self.last_grid_cleanup = current_time

    def process_trade_tick(self, price: float, size: int, side: str,
                          current_time: datetime) -> Tuple[List[dict], List[ExitSignal]]:
        """
        Process a single trade tick through all engines.

        Args:
            price: Trade price
            size: Trade size (contracts)
            side: 'A' (buyer-initiated) or 'B' (seller-initiated)
            current_time: Trade timestamp (datetime with timezone)

        Returns:
            Tuple of (entry_signals, exit_signals)
        """
        entry_triggers = []
        exit_signals = []

        # Validate inputs
        if not isinstance(current_time, datetime):
            logger.error(f"Invalid current_time type: {type(current_time)}")
            return entry_triggers, exit_signals

        if price <= 0 or size <= 0:
            return entry_triggers, exit_signals

        if side not in ('A', 'B'):
            return entry_triggers, exit_signals

        # Track current price for exit monitoring
        self.current_price = price

        # --- A. HANDLE 1-MINUTE CANDLE (Pre-Alerts) ---
        candle_1m_now = self._floor_to_candle(current_time, PRE_ALERT_TIMEFRAME)

        if self.candle_1m_time is None:
            self.candle_1m_time = candle_1m_now

        if candle_1m_now > self.candle_1m_time:
            # 1m Candle Closed
            self.last_close_delta_1m = self.candle_1m_delta
            entry_triggers.extend(self._check_1m_pre_alerts(current_time))
            self.candle_1m_time = candle_1m_now
            self.candle_1m_delta = 0

        # Update 1m Delta (consistent convention: + for buyers, - for sellers)
        if side == 'A':
            self.candle_1m_delta += size
        elif side == 'B':
            self.candle_1m_delta -= size

        # --- B. HANDLE 2-MINUTE CANDLE (Main Signals + Exit Checks) ---
        candle_2m_now = self._floor_to_candle(current_time, LEVEL_TIMEFRAME)

        if self.candle_2m_time is None:
            self.candle_2m_time = candle_2m_now

        if candle_2m_now > self.candle_2m_time:
            # 2m Candle Closed
            self.last_close_delta_2m = self.candle_2m_delta

            # Check entry signals first
            new_signals = self._check_2m_signals(current_time)
            entry_triggers.extend(new_signals)

            # Register new positions with exit monitor
            for signal in new_signals:
                if signal['source'] != 'PRE_ALERT':  # Only track confirmed signals
                    self.exit_monitor.register_position(signal, price, current_time)

            # Check exit signals for active positions
            exit_signals = self.exit_monitor.update_on_candle_close(
                price, self.last_close_delta_2m, current_time
            )

            self.candle_2m_time = candle_2m_now
            self.candle_2m_delta = 0

        # Update 2m Delta
        if side == 'A':
            self.candle_2m_delta += size
        elif side == 'B':
            self.candle_2m_delta -= size

        # --- C. UPDATE LEVEL MONITORS (Using spatial index for O(1) lookup) ---
        nearby_keys = self.level_index.get_nearby_keys(price)
        for key in nearby_keys:
            if key in self.main_monitors:
                monitor = self.main_monitors[key]
                if abs(price - monitor.price_key) <= LEVEL_TOLERANCE:
                    monitor.update(size, side, current_time)
                    # Update corresponding pre-monitor
                    if key in self.pre_monitors:
                        self.pre_monitors[key].update(size, side, current_time)

        # --- D. UPDATE BLIND GRID MONITORS ---
        grid_key = round(price / self.GRID_SIZE) * self.GRID_SIZE
        if grid_key not in self.grid_monitors:
            self.grid_monitors[grid_key] = {
                'SUP': AbsorptionMonitor(grid_key, 'SUP', BLIND_ABS_THRESH),
                'RES': AbsorptionMonitor(grid_key, 'RES', BLIND_ABS_THRESH)
            }
        self.grid_monitors[grid_key]['SUP'].update(size, side, current_time)
        self.grid_monitors[grid_key]['RES'].update(size, side, current_time)

        # --- E. UPDATE EXIT MONITOR ON TICK (for counter-absorption tracking) ---
        self.exit_monitor.update_on_tick(price, size, side, current_time)

        # --- F. PERIODIC GRID CLEANUP ---
        self._cleanup_stale_grid_monitors(current_time)

        return entry_triggers, exit_signals

    def get_active_positions(self) -> Dict[str, ActivePosition]:
        """Get all positions being monitored for exits."""
        return self.exit_monitor.get_active_positions()

    def acknowledge_exit(self, position_id: str) -> None:
        """Remove a position after exit signal is acknowledged."""
        self.exit_monitor.remove_position(position_id)

    def _check_1m_pre_alerts(self, current_time: datetime) -> List[dict]:
        """
        Check 1-minute Pre-Alerts (Context Levels Only).

        Includes cooldown to prevent alert spam.
        """
        alerts = []
        for key, monitor in self.pre_monitors.items():
            if monitor.state != "ABSORBING":
                continue

            # Check cooldown
            if key in self.pre_alert_cooldowns:
                time_since_last = (current_time - self.pre_alert_cooldowns[key]).total_seconds()
                if time_since_last < self.PRE_ALERT_COOLDOWN:
                    continue

            # Check 1m Delta Threshold
            # SUP: need positive delta (buyers winning after absorption)
            # RES: need negative delta (sellers winning after absorption)
            is_valid = False
            if monitor.level_type == 'SUP' and self.last_close_delta_1m >= PRE_ALERT_DELTA_THRESH:
                is_valid = True
            if monitor.level_type == 'RES' and self.last_close_delta_1m <= -PRE_ALERT_DELTA_THRESH:
                is_valid = True

            if is_valid:
                direction = "LONG" if monitor.level_type == 'SUP' else "SHORT"
                desc = f"1m Pre-Alert | Abs {monitor.cumulative_opposing_vol} | Delta {self.last_close_delta_1m:+d}"

                alerts.append({
                    'price': monitor.price_key,
                    'type': monitor.level_type,
                    'source': 'PRE_ALERT',
                    'desc': desc,
                    'absorption': monitor.cumulative_opposing_vol,
                    'delta': self.last_close_delta_1m,
                    'category': monitor.category,
                    'zone': monitor.zone
                })

                # Log to CSV
                self.signal_logger.log_signal(SignalRecord(
                    timestamp=current_time.strftime('%Y-%m-%d %H:%M:%S'),
                    signal_type='PRE_ALERT',
                    direction=direction,
                    price=monitor.price_key,
                    level_type=monitor.level_type,
                    absorption_volume=monitor.cumulative_opposing_vol,
                    candle_delta=self.last_close_delta_1m,
                    candle_timeframe='1m',
                    source_level_category=monitor.category,
                    source_level_zone=monitor.zone
                ))

                # Set cooldown
                self.pre_alert_cooldowns[key] = current_time

        return alerts

    def _check_2m_signals(self, current_time: datetime) -> List[dict]:
        """Check 2-minute Main Signals (Levels + Blind Grid)."""
        signals = []

        # 1. Context Levels
        for key, monitor in self.main_monitors.items():
            if monitor.state != "ABSORBING":
                continue

            # Check delta confirmation
            # SUP: positive delta (buyers won) | RES: negative delta (sellers won)
            is_valid = False
            if monitor.level_type == 'SUP' and self.last_close_delta_2m >= LEVEL_DELTA_THRESH:
                is_valid = True
            if monitor.level_type == 'RES' and self.last_close_delta_2m <= -LEVEL_DELTA_THRESH:
                is_valid = True

            if is_valid:
                direction = "LONG" if monitor.level_type == 'SUP' else "SHORT"
                desc = f"2m SIGNAL | Abs {monitor.cumulative_opposing_vol} | Delta {self.last_close_delta_2m:+d}"

                signals.append({
                    'price': monitor.price_key,
                    'type': monitor.level_type,
                    'source': 'LEVEL_CONFIRMATION',
                    'desc': desc,
                    'absorption': monitor.cumulative_opposing_vol,
                    'delta': self.last_close_delta_2m,
                    'category': monitor.category,
                    'zone': monitor.zone
                })

                # Log to CSV
                self.signal_logger.log_signal(SignalRecord(
                    timestamp=current_time.strftime('%Y-%m-%d %H:%M:%S'),
                    signal_type='LEVEL_CONFIRMATION',
                    direction=direction,
                    price=monitor.price_key,
                    level_type=monitor.level_type,
                    absorption_volume=monitor.cumulative_opposing_vol,
                    candle_delta=self.last_close_delta_2m,
                    candle_timeframe='2m',
                    source_level_category=monitor.category,
                    source_level_zone=monitor.zone
                ))

                # Reset monitor after signal
                monitor._reset()

                # Also reset corresponding pre-alert monitor
                if key in self.pre_monitors:
                    self.pre_monitors[key]._reset()

        # 2. Blind Grid
        for price_key, pair in self.grid_monitors.items():
            for l_type, monitor in pair.items():
                if monitor.state != "ABSORBING":
                    continue

                # Check delta confirmation
                is_valid = False
                if l_type == 'SUP' and self.last_close_delta_2m >= BLIND_DELTA_THRESH:
                    is_valid = True
                if l_type == 'RES' and self.last_close_delta_2m <= -BLIND_DELTA_THRESH:
                    is_valid = True

                if is_valid:
                    direction = "LONG" if l_type == 'SUP' else "SHORT"
                    desc = f"Blind Wall | Abs {monitor.cumulative_opposing_vol} | Delta {self.last_close_delta_2m:+d}"

                    signals.append({
                        'price': price_key,
                        'type': l_type,
                        'source': 'INSTITUTIONAL_WALL',
                        'desc': desc,
                        'absorption': monitor.cumulative_opposing_vol,
                        'delta': self.last_close_delta_2m,
                        'category': 'BLIND_GRID',
                        'zone': ''
                    })

                    # Log to CSV
                    self.signal_logger.log_signal(SignalRecord(
                        timestamp=current_time.strftime('%Y-%m-%d %H:%M:%S'),
                        signal_type='INSTITUTIONAL_WALL',
                        direction=direction,
                        price=price_key,
                        level_type=l_type,
                        absorption_volume=monitor.cumulative_opposing_vol,
                        candle_delta=self.last_close_delta_2m,
                        candle_timeframe='2m',
                        source_level_category='BLIND_GRID',
                        source_level_zone='',
                        notes='Detected at grid level without predefined context'
                    ))

                    # Reset monitor after signal
                    monitor._reset()

        return signals

    def load_latest_context(self) -> dict:
        """Load the most recent daily context from file."""
        if not os.path.exists(OUTPUT_FILE):
            logger.warning(f"Context file not found: {OUTPUT_FILE}")
            return {}
        try:
            with open(OUTPUT_FILE, 'r') as f:
                data = json.load(f)
                if not data:
                    return {}
                # Get the most recent date's context
                latest_key = sorted(data.keys())[-1]
                return data.get(latest_key, {})
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load context: {e}")
            return {}


# ==============================================================================
# MARKET PLANNER
# ==============================================================================
class MarketPlanner:
    """Daily market context generator."""

    def __init__(self):
        if not API_KEY:
            logger.error("DATABENTO_API_KEY environment variable not set")
            print("ERROR: Please set DATABENTO_API_KEY environment variable")
            sys.exit(1)

        self.client = db.Historical(API_KEY)
        self.discord = AsyncDiscordNotifier()
        self.levels_df = self._load_levels()
        self.simulated_now: Optional[datetime] = None

        if not os.path.exists(CRITICAL_LEVELS_FILE):
            logger.warning(f"Levels file not found: {CRITICAL_LEVELS_FILE}")

    def _load_levels(self) -> pd.DataFrame:
        """Load critical levels from CSV."""
        try:
            if os.path.exists(CRITICAL_LEVELS_FILE):
                df = pd.read_csv(CRITICAL_LEVELS_FILE)
                if 'score' not in df.columns:
                    df['score'] = 1.0
                if 'category' not in df.columns:
                    df['category'] = 'Level'
                logger.info(f"Loaded {len(df)} levels from {CRITICAL_LEVELS_FILE}")
                return df
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Failed to load levels: {e}")
            return pd.DataFrame()

    def calculate_volume_profile_levels(self, df: pd.DataFrame,
                                        value_area_pct: float = 0.70) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Calculate POC, VAH, VAL from OHLCV data."""
        if df.empty:
            return None, None, None

        try:
            vol_col = 'volume' if 'volume' in df.columns else 'vol'
            price_volume = df.groupby('close')[vol_col].sum().sort_index()
            poc_price = price_volume.idxmax()
            total_volume = price_volume.sum()
            target_va_volume = total_volume * value_area_pct

            current_volume = price_volume.loc[poc_price]
            vah_price, val_price = poc_price, poc_price

            above = price_volume.loc[poc_price:].iloc[1:]
            below = price_volume.loc[:poc_price].iloc[:-1].sort_index(ascending=False)

            i_a, i_b = 0, 0
            while current_volume < target_va_volume:
                vol_a = above.iloc[i_a] if i_a < len(above) else 0
                vol_b = below.iloc[i_b] if i_b < len(below) else 0

                if vol_a == 0 and vol_b == 0:
                    break

                if vol_a >= vol_b:
                    current_volume += vol_a
                    vah_price = above.index[i_a]
                    i_a += 1
                else:
                    current_volume += vol_b
                    val_price = below.index[i_b]
                    i_b += 1

            return float(poc_price), float(vah_price), float(val_price)
        except Exception as e:
            logger.error(f"Failed to calculate volume profile: {e}")
            return None, None, None

    def _get_market_data(self) -> Optional[pd.DataFrame]:
        """Fetch market data from Databento."""
        buffer_time = datetime.now(NY_TZ) - timedelta(minutes=60)
        end_dt = buffer_time if self.simulated_now > buffer_time else self.simulated_now
        start_dt = end_dt - timedelta(days=10)

        try:
            print("   Fetching ES data...", end="\r")
            df = self.client.timeseries.get_range(
                dataset="GLBX.MDP3",
                schema="ohlcv-1m",
                symbols=[SYMBOL],
                stype_in="continuous",
                start=start_dt,
                end=end_dt
            ).to_df()

            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC')
            df = df.tz_convert(NY_TZ)

            logger.info(f"Fetched {len(df)} bars of market data")
            return df
        except Exception as e:
            logger.error(f"Failed to fetch market data: {e}")
            return None

    def _get_previous_day_profile(self, df: pd.DataFrame) -> dict:
        """Calculate previous day's volume profile."""
        target_date = self.simulated_now.date()

        for i in range(1, 6):
            check_date = target_date - timedelta(days=i)
            day_slice = df[df.index.date == check_date]
            rth = day_slice.between_time('09:30', '16:00')

            if not rth.empty:
                poc, vah, val = self.calculate_volume_profile_levels(rth)
                if poc:
                    return {
                        'date': check_date.strftime('%Y-%m-%d'),
                        'POC': poc,
                        'VAH': vah,
                        'VAL': val
                    }

        return {'date': 'UNKNOWN', 'POC': 0, 'VAH': 0, 'VAL': 0}

    def _determine_context_edge(self, current_price: float, pd_profile: dict) -> Tuple[str, str]:
        """Determine market context relative to value area."""
        if pd_profile['POC'] == 0:
            return "Unknown", "Insufficient Data"

        if current_price > pd_profile['VAH']:
            return "Above Value", "Gap Up. Trend Risk!"
        if current_price < pd_profile['VAL']:
            return "Below Value", "Gap Down. Buy Support (+EV)."

        return "Inside Value", "Balance (Mean Reversion)."

    def _get_smart_levels(self, current_price: float) -> dict:
        """Get proximity-distributed levels."""
        if self.levels_df.empty:
            return {
                'sup_distributed': [], 'res_distributed': [],
                'raw_sup': [], 'raw_res': []
            }

        candidates = self.levels_df.copy()
        candidates['dist'] = abs(candidates['price'] - current_price)

        bins = [0, 15, 30, 50, 1000]
        labels = ['Zone 1', 'Zone 2', 'Zone 3', 'Zone 4']
        candidates['zone'] = pd.cut(
            candidates['dist'], bins=bins, labels=labels, include_lowest=True
        ).astype(str)

        res_candidates = candidates[
            (candidates['price'] > current_price) & (candidates['zone'] != 'nan')
        ].copy()
        sup_candidates = candidates[
            (candidates['price'] < current_price) & (candidates['zone'] != 'nan')
        ].copy()

        def select_top_per_zone(df: pd.DataFrame, ascending_price: bool = True) -> List[dict]:
            if df.empty:
                return []

            selected_records = []
            df_unique = df.sort_values('score', ascending=False).drop_duplicates('price').copy()

            for zone in ['Zone 1', 'Zone 2', 'Zone 3', 'Zone 4']:
                zone_levels = df_unique[df_unique['zone'] == zone].copy()
                zone_levels = zone_levels.sort_values(
                    by=['score', 'dist'], ascending=[False, True]
                )
                selected_records.extend(zone_levels.head(2).to_dict('records'))

            if not selected_records:
                return []

            return pd.DataFrame(selected_records).sort_values(
                'price', ascending=ascending_price
            ).to_dict('records')

        raw_res = select_top_per_zone(res_candidates, ascending_price=True)
        raw_sup = select_top_per_zone(sup_candidates, ascending_price=False)

        res_fmt = [f"{r['price']:.2f} [{r['zone']}] ({r['category']})" for r in raw_res]
        sup_fmt = [f"{r['price']:.2f} [{r['zone']}] ({r['category']})" for r in raw_sup]

        return {
            'res_distributed': res_fmt,
            'sup_distributed': sup_fmt,
            'raw_res': raw_res,
            'raw_sup': raw_sup
        }

    def run(self) -> None:
        """Run the market planner."""
        print("\n==========================================")
        print("   ES MARKET PLANNER (ZONED & DEDUPE)")
        print("==========================================")

        user_input = input("Enter Date (YYYY-MM-DD) or [Enter] for Today: ").strip()

        if not user_input:
            target_date = datetime.now(NY_TZ).date()
        else:
            try:
                target_date = datetime.strptime(user_input, "%Y-%m-%d").date()
            except ValueError:
                print("Invalid Date format. Use YYYY-MM-DD")
                return

        self.simulated_now = datetime.now(NY_TZ).replace(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day
        )

        print(f"\n   Processing ES Plan for: {target_date}")

        df = self._get_market_data()
        if df is None or df.empty:
            print("No Data Available.")
            return

        pd_profile = self._get_previous_day_profile(df)
        current_price = df['close'].iloc[-1]
        ctx_loc, ctx_insight = self._determine_context_edge(current_price, pd_profile)

        print(f"   Context: {ctx_loc} -> {ctx_insight}")

        levels = self._get_smart_levels(current_price)

        plan = {
            'timestamp': str(self.simulated_now),
            'current_price': float(current_price),
            'pd_profile': pd_profile,
            'context_location': ctx_loc,
            'context_insight': ctx_insight,
            'levels': levels
        }

        try:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump({str(target_date): plan}, f, indent=4)
            print(f"   Saved to {OUTPUT_FILE}")
        except IOError as e:
            logger.error(f"Failed to save plan: {e}")

        self.discord.send_plan(plan)
        self.discord.shutdown()


# ==============================================================================
# LIVE BOT
# ==============================================================================
class LiveBot:
    """Real-time trading signal bot."""

    # Reconnection settings
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_BASE_DELAY = 2  # seconds

    def __init__(self):
        if not API_KEY:
            logger.error("DATABENTO_API_KEY environment variable not set")
            print("ERROR: Please set DATABENTO_API_KEY environment variable")
            sys.exit(1)

        print("\n INITIALIZING ES LIVE BOT...")
        print(f"   ENTRY ENGINES:")
        print(f"   1. Pre-Alert (1m): Abs {PRE_ALERT_ABS_THRESH} / Delta {PRE_ALERT_DELTA_THRESH}")
        print(f"   2. Level Signal (2m): Abs {LEVEL_ABS_THRESH} / Delta {LEVEL_DELTA_THRESH}")
        print(f"   3. Blind Grid (2m): Abs {BLIND_ABS_THRESH} / Delta {BLIND_DELTA_THRESH}")
        print(f"   EXIT MONITOR:")
        print(f"   - Counter-Absorption: {EXIT_COUNTER_ABS_THRESH} contracts")
        print(f"   - Delta Reversal: {EXIT_DELTA_REVERSAL_BARS} bars @ {EXIT_DELTA_REVERSAL_THRESH}")
        print(f"   - Failed Follow-through: {EXIT_FAILED_FOLLOWTHROUGH_BARS} bars / {EXIT_FAILED_FOLLOWTHROUGH_PTS}pts")
        print(f"   - Exhaustion Decay: {EXIT_EXHAUSTION_DECAY_PCT:.0%} threshold")
        print(f"   Signal Log: {SIGNALS_LOG_FILE}")

        self.signal_logger = SignalLogger(SIGNALS_LOG_FILE)
        self.strategy = StrategyManager(self.signal_logger)
        self.discord = AsyncDiscordNotifier()
        self.live_client: Optional[db.Live] = None

        self.tick_count = 0
        self.last_status_time = datetime.now()
        self.running = True

    def _create_client(self) -> db.Live:
        """Create a new Databento live client."""
        return db.Live(API_KEY)

    def _handle_entry_signal(self, trigger: dict) -> None:
        """Process and alert a triggered entry signal."""
        direction = "LONG" if trigger['type'] == 'SUP' else "SHORT"

        # Console output
        print(f"\n{'='*50}")
        print(f"  ENTRY: {direction} ({trigger['source']}) @ {trigger['price']:.2f}")
        print(f"  {trigger['desc']}")
        print(f"{'='*50}\n")

        # Discord notification (async)
        self.discord.send_signal(
            trigger['price'],
            direction,
            trigger['source'],
            trigger['desc']
        )

    def _handle_exit_signal(self, exit_signal: ExitSignal) -> None:
        """Process and alert an exit signal."""
        # Console output with visual distinction based on urgency
        if exit_signal.urgency == 'IMMEDIATE':
            border = "!" * 50
            label = "EXIT NOW"
        else:
            border = "-" * 50
            label = "CONSIDER EXIT"

        pnl_str = f"+{exit_signal.pnl_points:.2f}" if exit_signal.pnl_points >= 0 else f"{exit_signal.pnl_points:.2f}"

        print(f"\n{border}")
        print(f"  {label}: {exit_signal.exit_type}")
        print(f"  Entry: {exit_signal.entry_price:.2f} | Current: {exit_signal.current_price:.2f} | P&L: {pnl_str}pts")
        print(f"  Reason: {exit_signal.reason}")
        print(f"{border}\n")

        # Discord notification (async)
        self.discord.send_exit_signal(exit_signal)

        # Auto-acknowledge IMMEDIATE exits (position should be closed)
        if exit_signal.urgency == 'IMMEDIATE':
            self.strategy.acknowledge_exit(exit_signal.position_id)
            logger.info(f"Auto-acknowledged exit for {exit_signal.position_id}")

    def start(self) -> None:
        """Start the live trading bot with reconnection logic."""
        print(f"\n Connecting to Databento Live Stream ({LIVE_SYMBOL})...")

        reconnect_attempts = 0

        while self.running and reconnect_attempts < self.MAX_RECONNECT_ATTEMPTS:
            try:
                self.live_client = self._create_client()
                self.live_client.subscribe(
                    dataset="GLBX.MDP3",
                    schema="trades",
                    stype_in="continuous",
                    symbols=[LIVE_SYMBOL]
                )

                # Reset reconnect counter on successful connection
                reconnect_attempts = 0
                logger.info("Connected to Databento live stream")
                print(" Connected! Monitoring for signals...")

                for record in self.live_client:
                    if not self.running:
                        break

                    # Validate record
                    if not hasattr(record, 'price') or record.price <= 0:
                        continue

                    try:
                        price = record.price / 1e9
                        size = record.size
                        side = record.side
                        current_time_dt = datetime.now(NY_TZ)

                        entry_triggers, exit_signals = self.strategy.process_trade_tick(
                            price, size, side, current_time_dt
                        )

                        # Handle entry signals
                        for trigger in entry_triggers:
                            self._handle_entry_signal(trigger)

                        # Handle exit signals
                        for exit_signal in exit_signals:
                            self._handle_exit_signal(exit_signal)

                        self.tick_count += 1

                        # Periodic status update
                        if (datetime.now() - self.last_status_time).seconds >= 300:
                            active_positions = len(self.strategy.get_active_positions())
                            logger.info(f"Active | Ticks: {self.tick_count} | Grid: {len(self.strategy.grid_monitors)} | Positions: {active_positions}")
                            print(f"[{datetime.now().strftime('%H:%M')}] Active | Ticks: {self.tick_count} | Positions: {active_positions}")
                            self.last_status_time = datetime.now()

                    except (ValueError, TypeError, AttributeError) as e:
                        logger.warning(f"Error processing tick: {e}")
                        continue

            except KeyboardInterrupt:
                print("\n Bot stopped by user.")
                self.running = False
                break

            except Exception as e:
                reconnect_attempts += 1
                delay = self.RECONNECT_BASE_DELAY * (2 ** (reconnect_attempts - 1))

                logger.error(f"Connection error: {e}")
                logger.info(f"Reconnect attempt {reconnect_attempts}/{self.MAX_RECONNECT_ATTEMPTS} in {delay}s")

                if reconnect_attempts < self.MAX_RECONNECT_ATTEMPTS:
                    print(f" Connection lost. Reconnecting in {delay}s...")
                    import time
                    time.sleep(delay)
                else:
                    print(f" Max reconnection attempts reached. Exiting.")
                    break

        self._shutdown()

    def _shutdown(self) -> None:
        """Clean shutdown of all resources."""
        logger.info("Shutting down bot...")
        self.running = False

        if self.live_client:
            try:
                self.live_client.close()
            except Exception:
                pass

        self.discord.shutdown()
        logger.info(f"Bot shutdown complete. Total ticks processed: {self.tick_count}")
        print(f"\n Shutdown complete. Processed {self.tick_count} ticks.")
        print(f"   Signal log saved to: {SIGNALS_LOG_FILE}")


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
def main():
    """Main entry point."""
    print("==========================================")
    print("   ES ALGO ASSISTANT: PLANNER & SIGNALS   ")
    print("==========================================")
    print("1. Run Market Planner (Generate Daily Plan)")
    print("2. Run Live Signals (Real-time Feed)")
    print("")

    choice = input("Select Mode [1/2]: ").strip()

    if choice == "1":
        MarketPlanner().run()
    elif choice == "2":
        bot = LiveBot()
        bot.start()
    else:
        print("Invalid choice. Please enter 1 or 2.")


if __name__ == "__main__":
    main()
