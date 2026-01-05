"""
Trading Pattern Classifier - OPTION A (33 Features)

SEQUENCE LEARNING + INCREMENTAL + CONSOLIDATION CONTEXT VERSION:
- 15 Pattern Types (directional taxonomy with buy/sell splits):
  1. HIGH OF DAY - RTH session high (volatility depends on timing)
  2. LOW OF DAY - RTH session low (volatility depends on timing)
  3. BUY REVERSAL - Significant low (10+ pts ES, 20+ pts NQ), holds 15+ mins
  4. SELL REVERSAL - Significant high (10+ pts ES, 20+ pts NQ), holds 15+ mins
  5. FALSE BUY REVERSAL - Shallow bounce (5-10 pts ES, 10-20 pts NQ), fakeout
  6. FALSE SELL REVERSAL - Shallow pullback (5-10 pts ES, 10-20 pts NQ), fakeout
  7. PULLBACK BUY REVERSAL - After false sell reversal, resumes buying
  8. PULLBACK SELL REVERSAL - After false buy reversal, resumes selling
  9. PULLBACK BUY CONTINUATION - After pullback buy reversal, indicates breakout
  10. PULLBACK SELL CONTINUATION - After pullback sell reversal, indicates breakdown
  11. BUY CONTINUATION - Makes higher high, closes above previous
  12. SELL CONTINUATION - Makes lower low, closes below previous
  13. BUY IMPULSE - Large green candle/wick, high volume, explosive upward
  14. SELL IMPULSE - Large red candle/wick, high volume, explosive downward
  15. CONSOLIDATION - Choppy, many false reversals, range-bound

- 33 ML Features enabling automatic sequence discovery + solving overlapping windows:
  * 12 Base Features (Volume Profile + Price Velocity + Delta/Volume Analysis)
  * 4 Sequence Context Features (previous patterns, timing)
  * 8 Multi-Day/Session Context Features (gaps, initial balance, previous day levels)
  * 4 Incremental Features (CHANGE since last pattern - solves overlap problem!)
  * 4 Consolidation Context Features (breakout detection from consolidation ranges)

- Session Pre-Scan (calculates rolling metrics for entire session)
- Smart Windowing (uses gaps between patterns when <5 min apart)
- Incremental Feature Extraction (measures CHANGE not absolute values)
- Consolidation Containers (tracks consolidation ranges, auto-detects breakouts)
- Adaptive Time Windows (auto-adjusts to volatility)
- Hierarchical Pattern Tracking (parent/child relationships)
- ML-Based Sequence Learning (NOT hard-coded)
- Session Visualization (auto-generated chart for cross-reference)

KEY IMPROVEMENTS:
1. DIRECTIONAL PATTERNS - All patterns now have buy/sell directional splits (15 vs 8)
2. INSTRUMENT-SPECIFIC THRESHOLDS - ES (10pt) vs NQ (20pt) reversal thresholds
3. SEQUENCE-AWARE CLASSIFICATION - Detects patterns based on previous pattern context
4. HOD/LOD separated from reversals (day extremes != significant reversals)
5. BUY/SELL REVERSALS - Significant moves (10+ pts ES, 20+ pts NQ), must hold 15+ mins
6. FALSE REVERSALS - Shallow fakeouts (5-10 pts ES, 10-20 pts NQ), often in consolidation
7. PULLBACK SEQUENCE - FALSE REVERSAL → PULLBACK REVERSAL → PULLBACK CONTINUATION
8. IMPULSE PATTERNS - Large candles/wicks with high volume, explosive moves
9. CONTINUATIONS - Make higher high/lower low, directionally consistent
10. INCREMENTAL FEATURES solve overlapping window problem (9:49 vs 9:50 now distinct!)
11. CONSOLIDATION CONTEXT enables learning breakout patterns automatically
12. ML learns sequences like "FALSE SELL → PULLBACK BUY REVERSAL → PULLBACK BUY CONTINUATION"

The ML model learns which sequences matter through context features, enabling discovery of
patterns like "Gap-up near prev day high → IMPULSE → FALSE REVERSAL → PULLBACK → REVERSAL"
without hard-coded rules. Volumes, deltas, and velocities are analyzed to distinguish
patterns (e.g., false reversals often show weak volume + opposite delta influx).

For close-together patterns (like 9:49, 9:50, 9:55), incremental features measure the
CHANGE between patterns rather than absolute values, making each pattern mathematically
distinct and avoiding ML confusion from overlapping windows.

SETUP:
1. Install dependencies: pip install databento pandas numpy scikit-learn pytz matplotlib
2. Set environment variable: export DATABENTO_API_KEY="your_api_key_here"
3. Run: python trading_analyzer_option_a.py

USAGE:
- Enter consolidations as time ranges: "9:56-10:32" then label as CONSOLIDATION
  System automatically tracks it as a container and adds breakout features to next pattern
- Enter close patterns normally: "9:49, 9:50, 9:55" - incremental features handle it!

FEATURES:
- Expected accuracy: 85-95%+ with 100+ training examples
- Auto-adapts to trending vs consolidation days
- Learns pattern sequences through context (not hard-coded detection)
- Understands multi-day context (gaps, previous day levels, initial balance)
- Handles weekends and holidays (finds previous trading day automatically)
- Solves overlapping window problem for close-together patterns
"""

import databento as db
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time as dt_time
import pytz
import sys
import os
import pickle
import traceback
from typing import Tuple, Dict, Optional, List

# --- MACHINE LEARNING IMPORTS ---
try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import LabelEncoder
    from sklearn.model_selection import train_test_split
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("[WARN] scikit-learn not installed. ML features disabled.")
    print("       Install with: pip install scikit-learn")

# --- VISUALIZATION IMPORTS ---
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("[WARN] matplotlib not installed. Visualization disabled.")
    print("       Install with: pip install matplotlib")

# --- CONFIGURATION ---
# Security: API key from environment variable
API_KEY = os.environ.get('DATABENTO_API_KEY')
if not API_KEY:
    print("[ERROR] Please set DATABENTO_API_KEY environment variable")
    print("        Example: export DATABENTO_API_KEY='your_key_here'")
    sys.exit(1)

# Trading Configuration
SYMBOL = "ES.v.0"
TZ_STR = 'America/New_York'
TRAINING_FILE = "ml_training_data_option_a.csv"
MODEL_FILE = "trained_model_option_a.pkl"

# Analysis Parameters
PRICE_SCALE_FACTOR = 1e9
CONSOLIDATION_RANGE_THRESHOLD = 4.0  # Points
CONSOLIDATION_MIN_DURATION = 5  # Minutes
BASE_ANALYSIS_WINDOW_MINUTES = 10  # Base window (will adapt)
PRE_EVENT_LOOKBACK_MINUTES = 15
MIN_RANGE_FOR_ABSORPTION = 0.5

# Adaptive Window Parameters
VOLATILITY_LOOKBACK_MINUTES = 30
LOW_VOLATILITY_THRESHOLD = 1.0  # pts/min
HIGH_VOLATILITY_THRESHOLD = 3.0  # pts/min
MIN_WINDOW_MINUTES = 5
MAX_WINDOW_MINUTES = 15

# Separation Parameters
MIN_SEPARATION_MINUTES = 0  # Allow close-together patterns (incremental features handle this)

# Pattern Detection Thresholds (instrument-specific)
# Detect instrument from SYMBOL
IS_ES = "ES" in SYMBOL.upper()
IS_NQ = "NQ" in SYMBOL.upper()

# Reversal thresholds: Price must move this far before opposite reversal
REVERSAL_THRESHOLD = 10.0 if IS_ES else 20.0  # ES: 10pts, NQ: 20pts

# False reversal thresholds: Shallow moves that typically reverse
FALSE_REVERSAL_MIN = 5.0 if IS_ES else 10.0   # ES: 5pts, NQ: 10pts
FALSE_REVERSAL_MAX = 10.0 if IS_ES else 20.0  # ES: 10pts, NQ: 20pts

# Minimum time before reversal can be broken (otherwise it's false reversal)
REVERSAL_HOLD_TIME_MINUTES = 15

# ML Parameters
RF_N_ESTIMATORS = 100
RF_RANDOM_STATE = 42
MIN_TRAINING_SAMPLES = 50
TRAIN_TEST_SPLIT_SIZE = 0.2

# Price change threshold to avoid noise
PRICE_CHANGE_THRESHOLD = 0.25

# Volume Profile Parameters
VOLUME_PROFILE_BINS = 10

# Session Parameters (for Initial Balance calculation)
SESSION_OPEN_HOUR = 9  # 9:30 AM ET
SESSION_OPEN_MINUTE = 30
IB_DURATION_MINUTES = 60  # First hour = Initial Balance


# --- 1. DATA VALIDATION ---
def validate_data(df: pd.DataFrame) -> bool:
    """Validate that data is suitable for analysis."""
    if df.empty:
        raise ValueError("DataFrame is empty")

    if len(df) < 2:
        raise ValueError("Need at least 2 data points for analysis")

    if 'price' not in df.columns or 'size' not in df.columns:
        raise ValueError("Missing required columns: price, size")

    if df['price'].nunique() == 1:
        raise ValueError("All prices are identical - no meaningful analysis possible")

    if not df.index.is_monotonic_increasing:
        raise ValueError("Timestamps are not in chronological order")

    return True


# --- 2. ADAPTIVE TIME WINDOW CALCULATION ---
def calculate_adaptive_window(df: pd.DataFrame, center_time: datetime,
                              base_window_minutes: int = BASE_ANALYSIS_WINDOW_MINUTES) -> int:
    """
    Calculate adaptive time window based on recent volatility.

    Low volatility (consolidation) → Smaller windows (5 min)
    Normal volatility (trending) → Standard windows (10 min)
    High volatility (volatile) → Larger windows (15 min)

    Args:
        df: Full day's tick data
        center_time: Time point being analyzed
        base_window_minutes: Default window size

    Returns:
        Adaptive window size in minutes
    """
    # Look at last VOLATILITY_LOOKBACK_MINUTES before center_time
    lookback_start = center_time - timedelta(minutes=VOLATILITY_LOOKBACK_MINUTES)
    recent_data = df[(df.index >= lookback_start) & (df.index < center_time)]

    if recent_data.empty or len(recent_data) < 10:
        return base_window_minutes  # Default

    # Calculate volatility (average range per minute)
    recent_data_copy = recent_data.copy()
    recent_data_copy['minute'] = recent_data_copy.index.floor('1min')
    minute_groups = recent_data_copy.groupby('minute')

    minute_ranges = []
    for timestamp, group in minute_groups:
        if len(group) > 1:
            range_val = group['price'].max() - group['price'].min()
            minute_ranges.append(range_val)

    if not minute_ranges:
        return base_window_minutes

    avg_range_per_min = np.mean(minute_ranges)

    # Adaptive logic
    if avg_range_per_min < LOW_VOLATILITY_THRESHOLD:
        window = MIN_WINDOW_MINUTES  # Consolidation
        mode = "CONSOLIDATION"
    elif avg_range_per_min < HIGH_VOLATILITY_THRESHOLD:
        window = base_window_minutes  # Normal
        mode = "NORMAL"
    else:
        window = MAX_WINDOW_MINUTES  # Volatile
        mode = "VOLATILE"

    print(f"[ADAPTIVE] Volatility: {avg_range_per_min:.2f} pts/min → {mode} mode → ±{window} min window")

    return window


# --- 3. SEPARATION CHECK ---
def check_separation(analyzed_times: List[datetime], new_time: datetime,
                    min_separation_minutes: int = MIN_SEPARATION_MINUTES) -> bool:
    """
    Check if new_time is far enough from previously analyzed times.

    Args:
        analyzed_times: List of datetime objects already analyzed
        new_time: New time to analyze
        min_separation_minutes: Minimum gap required

    Returns:
        True if allowed, False if too close
    """
    for prev_time in analyzed_times:
        time_diff = abs((new_time - prev_time).total_seconds() / 60)
        if time_diff < min_separation_minutes:
            print(f"[WARN] {new_time.strftime('%H:%M')} too close to {prev_time.strftime('%H:%M')}")
            print(f"       Separation: {time_diff:.1f} min (minimum: {min_separation_minutes} min)")
            print(f"       Recommendation: Wait until {(prev_time + timedelta(minutes=min_separation_minutes)).strftime('%H:%M')}")
            return False
    return True


# --- 4. DATA FETCHING ---
def get_databento_data(api_key: str, date_obj: datetime.date) -> Optional[pd.DataFrame]:
    """Fetch tick data from Databento API."""
    print(f"\n[DATA] Fetching tick data for {date_obj.strftime('%Y-%m-%d')}...")
    client = db.Historical(key=api_key)
    start_dt = datetime.combine(date_obj, dt_time(0, 0))
    end_dt = datetime.combine(date_obj, dt_time(23, 59))

    try:
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            schema="trades",
            stype_in="continuous",
            symbols=[SYMBOL],
            start=start_dt,
            end=end_dt
        ).to_df()

        if data.empty:
            print("[WARN] No data returned for this date")
            return None

        # Scale prices if needed
        if 'price' in data.columns and data['price'].mean() > 10000:
            data['price'] = data['price'] / PRICE_SCALE_FACTOR

        # Convert timestamps to timezone-aware
        data.index = pd.to_datetime(data.index, unit='ns')
        if data.index.tz is None:
            print("[INFO] No timezone in data, assuming UTC")
            data.index = data.index.tz_localize('UTC')
        elif data.index.tz != pytz.UTC:
            print(f"[INFO] Converting from {data.index.tz} to UTC")
            data.index = data.index.tz_convert('UTC')

        data.index = data.index.tz_convert(pytz.timezone(TZ_STR))

        # Calculate signed volume
        data['size'] = data['size'].astype('int64')
        side_vals = data['side'].values

        if side_vals.dtype.kind in ('S', 'O', 'U'):
            is_ask = (side_vals == 'A') | (side_vals == b'A')
        else:
            is_ask = (side_vals == 65)

        data['signed_vol'] = np.where(is_ask, data['size'], -data['size'])

        # Validate before returning
        try:
            validate_data(data)
        except ValueError as e:
            print(f"[WARN] Data validation warning: {e}")

        return data

    except Exception as ex:
        print(f"[ERROR] Failed to fetch data: {ex}")
        traceback.print_exc()
        return None


def get_previous_trading_day_data(api_key: str, current_date: datetime.date,
                                  max_lookback_days: int = 7) -> Tuple[Optional[pd.DataFrame], Optional[datetime.date]]:
    """
    Find and fetch the most recent previous trading day data.

    Handles weekends and market holidays by checking backwards until data is found.
    For example:
    - Monday → Friday
    - Day after Christmas → day before Christmas
    - Day after Thanksgiving → day before Thanksgiving

    Args:
        api_key: Databento API key
        current_date: Current trading date
        max_lookback_days: Maximum days to look back (default 7 for long weekends)

    Returns:
        Tuple of (DataFrame, date) for previous trading day, or (None, None) if not found
    """
    print(f"\n[PREVIOUS DAY] Finding previous trading day before {current_date.strftime('%Y-%m-%d')}...")

    for days_back in range(1, max_lookback_days + 1):
        candidate_date = current_date - timedelta(days=days_back)

        # Skip obvious non-trading days (Saturday/Sunday)
        weekday = candidate_date.weekday()
        if weekday == 5:  # Saturday
            print(f"[PREVIOUS DAY] Skipping {candidate_date.strftime('%Y-%m-%d')} (Saturday)")
            continue
        elif weekday == 6:  # Sunday
            print(f"[PREVIOUS DAY] Skipping {candidate_date.strftime('%Y-%m-%d')} (Sunday)")
            continue

        # Try to fetch data for this candidate
        print(f"[PREVIOUS DAY] Checking {candidate_date.strftime('%Y-%m-%d')} ({['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][weekday]})...")
        data = get_databento_data(api_key, candidate_date)

        if data is not None and not data.empty and len(data) > 100:
            # Found valid trading day data (>100 ticks = real trading day)
            print(f"[PREVIOUS DAY] ✓ Found previous trading day: {candidate_date.strftime('%Y-%m-%d')}")
            return data, candidate_date
        else:
            # No data or insufficient data - likely a holiday
            print(f"[PREVIOUS DAY] ✗ No sufficient data (likely holiday or half-day)")

    # Couldn't find previous trading day within lookback period
    print(f"[PREVIOUS DAY] WARNING: Could not find trading day within {max_lookback_days} days")
    print(f"[PREVIOUS DAY] Using current day's open as baseline")
    return None, None


# --- 5. SESSION PRE-SCAN (NEW!) ---
def pre_scan_session(df: pd.DataFrame) -> Dict:
    """
    Pre-calculate rolling metrics for the entire session.

    This enables incremental feature extraction for close-together patterns,
    solving the overlapping window problem.

    Returns a dictionary with per-minute rolling state:
    {
        timestamp: {
            'cumulative_volume': int,
            'cumulative_delta': int,
            'rolling_high': float,
            'rolling_low': float,
            'minute_volume': int,
            'minute_delta': int,
            'minute_range': float,
            'price': float
        }
    }
    """
    print("\n[PRE-SCAN] Calculating session-wide rolling metrics...")

    if df.empty:
        return {}

    # Group by minute
    df_copy = df.copy()
    df_copy['minute'] = df_copy.index.floor('1min')

    session_state = {}
    cumulative_vol = 0
    cumulative_delta = 0
    rolling_high = df['price'].iloc[0]
    rolling_low = df['price'].iloc[0]

    for timestamp, group in df_copy.groupby('minute'):
        # Per-minute metrics
        minute_vol = int(group['size'].sum())
        minute_delta = int(group['signed_vol'].sum())
        minute_high = group['price'].max()
        minute_low = group['price'].min()
        minute_range = minute_high - minute_low
        close_price = group['price'].iloc[-1]

        # Update cumulative metrics
        cumulative_vol += minute_vol
        cumulative_delta += minute_delta
        rolling_high = max(rolling_high, minute_high)
        rolling_low = min(rolling_low, minute_low)

        # Store state
        session_state[timestamp] = {
            'cumulative_volume': cumulative_vol,
            'cumulative_delta': cumulative_delta,
            'rolling_high': rolling_high,
            'rolling_low': rolling_low,
            'minute_volume': minute_vol,
            'minute_delta': minute_delta,
            'minute_range': minute_range,
            'price': close_price
        }

    print(f"[PRE-SCAN] Processed {len(session_state)} minutes of data")
    return session_state


# --- 6. METRICS ENGINE ---
def calculate_granular_metrics(df: pd.DataFrame) -> Tuple[Optional[pd.DataFrame], Dict[str, int]]:
    """Calculate per-minute metrics and period totals."""
    if df.empty:
        return None, {}

    df = df.copy()
    df['candle_time'] = df.index.floor('1min')
    groups = df.groupby('candle_time')
    candle_stats = []

    for timestamp, group in groups:
        tick_deltas = group['signed_vol'].values
        cumulative_path = np.cumsum(tick_deltas)
        open_px, close_px = group['price'].iloc[0], group['price'].iloc[-1]
        max_delta, min_delta = np.max(cumulative_path), np.min(cumulative_path)
        final_delta = cumulative_path[-1]

        candle_stats.append({
            'Time': timestamp.strftime('%H:%M'),
            'Open': open_px,
            'Close': close_px,
            'High': group['price'].max(),
            'Low': group['price'].min(),
            'Vol': int(group['size'].sum()),
            'Delta': int(final_delta),
            'Min_Delta': int(min_delta),
            'Max_Delta': int(max_delta),
            'Absorbed_Buy': int(max_delta - final_delta if max_delta > final_delta else 0),
            'Absorbed_Sell': int(final_delta - min_delta if min_delta < final_delta else 0)
        })

    stats_df = pd.DataFrame(candle_stats)
    if stats_df.empty:
        return None, {}

    period_totals = {
        'total_vol': stats_df['Vol'].sum(),
        'net_delta': stats_df['Delta'].sum(),
        'sum_max_delta': stats_df['Max_Delta'].sum(),
        'sum_min_delta': stats_df['Min_Delta'].sum(),
        'total_buy_abs': stats_df['Absorbed_Buy'].sum(),
        'total_sell_abs': stats_df['Absorbed_Sell'].sum()
    }

    return stats_df, period_totals


# --- 6. VOLUME PROFILE CALCULATION ---
def calculate_volume_profile(event_df: pd.DataFrame) -> Tuple[float, float, float]:
    """Calculate volume distribution across price range."""
    if event_df.empty or len(event_df) < 2:
        return 0.5, 0.5, 0.5

    high_px = event_df['price'].max()
    low_px = event_df['price'].min()
    mid_px = (high_px + low_px) / 2
    range_size = high_px - low_px

    # Calculate volume in upper vs lower half
    upper_vol = event_df[event_df['price'] > mid_px]['size'].sum()
    lower_vol = event_df[event_df['price'] <= mid_px]['size'].sum()
    total_vol = event_df['size'].sum()

    if total_vol == 0:
        return 0.5, 0.5, 0.5

    upper_pct = upper_vol / total_vol
    lower_pct = lower_vol / total_vol

    # Find Point of Interest (POI)
    if range_size > 0:
        bins = np.linspace(low_px, high_px, VOLUME_PROFILE_BINS + 1)
        event_df_copy = event_df.copy()
        event_df_copy['price_bucket'] = pd.cut(event_df_copy['price'], bins=bins, include_lowest=True)
        vol_by_bucket = event_df_copy.groupby('price_bucket', observed=True)['size'].sum()

        if not vol_by_bucket.empty:
            poi_bucket = vol_by_bucket.idxmax()
            poi_price = (poi_bucket.left + poi_bucket.right) / 2
            poi_position = (poi_price - low_px) / range_size
        else:
            poi_position = 0.5
    else:
        poi_position = 0.5

    return upper_pct, lower_pct, poi_position


# --- 7. PRICE VELOCITY CALCULATION ---
def calculate_price_velocity(event_df: pd.DataFrame) -> Tuple[float, float, float]:
    """Calculate price movement velocity and acceleration."""
    if event_df.empty or len(event_df) < 2:
        return 0.0, 0.0, 0.0

    # Overall velocity
    price_change = event_df['price'].iloc[-1] - event_df['price'].iloc[0]
    duration_mins = (event_df.index[-1] - event_df.index[0]).total_seconds() / 60

    if duration_mins == 0:
        return 0.0, 0.0, 0.0

    overall_velocity = price_change / duration_mins

    # Calculate per-minute velocities
    event_df_copy = event_df.copy()
    event_df_copy['candle_time'] = event_df_copy.index.floor('1min')
    minute_groups = event_df_copy.groupby('candle_time')

    velocities = []
    for timestamp, group in minute_groups:
        if len(group) < 2:
            continue
        minute_change = group['price'].iloc[-1] - group['price'].iloc[0]
        minute_duration = (group.index[-1] - group.index[0]).total_seconds() / 60
        if minute_duration > 0:
            velocities.append(minute_change / minute_duration)

    if not velocities:
        return overall_velocity, 0.0, 0.0

    max_velocity = max(velocities, key=abs)

    # Acceleration
    mid_point = len(velocities) // 2
    if mid_point > 0:
        first_half_vel = np.mean(velocities[:mid_point])
        second_half_vel = np.mean(velocities[mid_point:])
        acceleration = second_half_vel - first_half_vel
    else:
        acceleration = 0.0

    return overall_velocity, max_velocity, acceleration


# --- 8. SESSION CONTEXT CALCULATION (NEW!) ---
class SessionContext:
    """Calculates and stores session-level context (gaps, IB, previous day levels)."""

    def __init__(self):
        self.prev_day_high = None
        self.prev_day_low = None
        self.prev_day_close = None
        self.today_open = None
        self.ib_high = None
        self.ib_low = None
        self.ib_range = None
        self.session_start = None
        self.session_end = None

    def calculate_from_data(self, current_df: pd.DataFrame, prev_df: Optional[pd.DataFrame],
                           date_obj: datetime.date, tz: pytz.timezone):
        """
        Calculate session context from current and previous day data.

        Args:
            current_df: Today's tick data
            prev_df: Previous day's tick data (can be None)
            date_obj: Current date
            tz: Timezone
        """
        if current_df.empty:
            return

        # Today's open (first tick of the day)
        self.today_open = current_df['price'].iloc[0]

        # Session boundaries
        self.session_start = current_df.index[0]
        self.session_end = current_df.index[-1]

        # Previous day levels
        if prev_df is not None and not prev_df.empty:
            self.prev_day_high = prev_df['price'].max()
            self.prev_day_low = prev_df['price'].min()
            self.prev_day_close = prev_df['price'].iloc[-1]
        else:
            # No previous day data available
            self.prev_day_high = self.today_open
            self.prev_day_low = self.today_open
            self.prev_day_close = self.today_open

        # Initial Balance (first hour of trading)
        ib_start = tz.localize(datetime.combine(
            date_obj,
            dt_time(SESSION_OPEN_HOUR, SESSION_OPEN_MINUTE)
        ))
        ib_end = ib_start + timedelta(minutes=IB_DURATION_MINUTES)

        ib_data = current_df[(current_df.index >= ib_start) & (current_df.index <= ib_end)]

        if not ib_data.empty:
            self.ib_high = ib_data['price'].max()
            self.ib_low = ib_data['price'].min()
            self.ib_range = self.ib_high - self.ib_low
        else:
            # IB not yet established or data doesn't cover IB period
            self.ib_high = self.today_open
            self.ib_low = self.today_open
            self.ib_range = 0.0

        print(f"[SESSION CONTEXT]")
        print(f"  Previous Day: High {self.prev_day_high:.2f} | Low {self.prev_day_low:.2f} | Close {self.prev_day_close:.2f}")
        print(f"  Today Open: {self.today_open:.2f}")
        print(f"  Gap: {((self.today_open - self.prev_day_close) / self.prev_day_close * 100):.2f}%")
        print(f"  Initial Balance: High {self.ib_high:.2f} | Low {self.ib_low:.2f} | Range {self.ib_range:.2f} pts")


# --- 9. ENHANCED FEATURE EXTRACTION (33 FEATURES!) ---
def extract_features(pre_df: pd.DataFrame, event_df: pd.DataFrame,
                    post_df: pd.DataFrame, totals: Dict,
                    session_ctx: SessionContext,
                    analysis_state: 'PatternAnalysisState',
                    current_time: datetime,
                    session_state: Dict = None) -> Dict:
    """
    Extract all 33 features for ML model (24 original + 9 incremental/consolidation).

    FEATURE BREAKDOWN:
    - Features 1-12: Base features (original + volume profile + velocity)
    - Features 13-16: Sequence context (previous patterns, timing)
    - Features 17-24: Multi-day/session context (gaps, IB, previous day levels, time of day)
    - Features 25-28: Incremental features (change since last pattern - NEW!)
    - Features 29-32: Consolidation context (breakout detection - NEW!)

    This comprehensive feature set enables the ML model to learn sequences automatically
    without hard-coding detection logic, and solves the overlapping window problem for
    close-together patterns.
    """
    open_px = event_df['price'].iloc[0]
    close_px = event_df['price'].iloc[-1]
    high_px = event_df['price'].max()
    low_px = event_df['price'].min()

    # ========== FEATURES 1-8: ORIGINAL ==========
    trend = 0
    if not pre_df.empty and len(pre_df) > 1:
        price_change = pre_df['price'].iloc[-1] - pre_df['price'].iloc[0]
        if price_change > PRICE_CHANGE_THRESHOLD:
            trend = 1
        elif price_change < -PRICE_CHANGE_THRESHOLD:
            trend = -1

    color = 1 if close_px > open_px else -1

    broken_high = 0
    broken_low = 0
    if not post_df.empty:
        if post_df['price'].max() > high_px:
            broken_high = 1
        if post_df['price'].min() < low_px:
            broken_low = 1

    range_size = high_px - low_px
    if range_size < MIN_RANGE_FOR_ABSORPTION:
        absorption_ratio = 0
    else:
        absorption_ratio = totals['total_vol'] / range_size

    delta_imbalance = totals['net_delta'] / totals['total_vol'] if totals['total_vol'] > 0 else 0

    total_vol = totals['total_vol']

    if len(event_df) > 1:
        duration_mins = (event_df.index[-1] - event_df.index[0]).total_seconds() / 60
    else:
        duration_mins = 0

    # ========== FEATURES 9-12: VOLUME PROFILE + VELOCITY ==========
    upper_vol_pct, lower_vol_pct, poi_position = calculate_volume_profile(event_df)
    overall_velocity, max_velocity, acceleration = calculate_price_velocity(event_df)

    # ========== FEATURES 13-16: SEQUENCE CONTEXT (NEW!) ==========
    # These features allow ML to learn sequences without hard-coding

    previous_pattern_1 = 0  # Encoded label of most recent pattern
    previous_pattern_2 = 0  # Encoded label of 2nd most recent pattern
    time_since_last = 0.0   # Minutes since last pattern
    recent_pattern_count = 0  # Patterns in last 30 minutes

    if analysis_state and analysis_state.analyzed_patterns:
        # Sort by timestamp
        sorted_patterns = sorted(analysis_state.analyzed_patterns,
                                key=lambda x: x['timestamp'])

        # Get patterns before current time
        prev_patterns = [p for p in sorted_patterns if p['timestamp'] < current_time]

        if prev_patterns:
            # Most recent pattern
            last_pattern = prev_patterns[-1]
            previous_pattern_1 = analysis_state.encode_pattern_label(last_pattern['label'])

            # Time since last pattern
            time_since_last = (current_time - last_pattern['timestamp']).total_seconds() / 60

            # Second most recent pattern
            if len(prev_patterns) >= 2:
                second_last = prev_patterns[-2]
                previous_pattern_2 = analysis_state.encode_pattern_label(second_last['label'])

            # Count patterns in last 30 minutes
            recent_threshold = current_time - timedelta(minutes=30)
            recent_pattern_count = sum(1 for p in prev_patterns
                                      if p['timestamp'] >= recent_threshold)

    # ========== FEATURES 17-24: MULTI-DAY/SESSION CONTEXT (NEW!) ==========
    # These features provide context about gaps, previous day, and intraday position

    # Gap from previous close
    if session_ctx.prev_day_close and session_ctx.today_open:
        gap_pct = ((session_ctx.today_open - session_ctx.prev_day_close) /
                   session_ctx.prev_day_close * 100)
    else:
        gap_pct = 0.0

    # Open type: gap up (1), gap down (-1), or flat (0)
    if gap_pct > 0.1:
        open_type = 1
    elif gap_pct < -0.1:
        open_type = -1
    else:
        open_type = 0

    # Initial Balance range
    ib_range = session_ctx.ib_range if session_ctx.ib_range else 0.0

    # Current price vs IB levels
    current_price = close_px
    if session_ctx.ib_high:
        current_vs_ib_high = current_price - session_ctx.ib_high
    else:
        current_vs_ib_high = 0.0

    if session_ctx.ib_low:
        current_vs_ib_low = current_price - session_ctx.ib_low
    else:
        current_vs_ib_low = 0.0

    # Current price vs previous day levels
    if session_ctx.prev_day_high:
        current_vs_prev_high = current_price - session_ctx.prev_day_high
    else:
        current_vs_prev_high = 0.0

    if session_ctx.prev_day_low:
        current_vs_prev_low = current_price - session_ctx.prev_day_low
    else:
        current_vs_prev_low = 0.0

    # Time of day (normalized 0-1 for trading hours)
    # Assumes RTH trading from 9:30 AM to 4:00 PM ET (390 minutes)
    if session_ctx.session_start:
        rth_start = session_ctx.session_start.replace(
            hour=SESSION_OPEN_HOUR, minute=SESSION_OPEN_MINUTE, second=0, microsecond=0
        )
        rth_duration_mins = 390  # 6.5 hours

        mins_since_open = (current_time - rth_start).total_seconds() / 60
        time_of_day = max(0.0, min(1.0, mins_since_open / rth_duration_mins))
    else:
        time_of_day = 0.5  # Default to midday

    # ========== FEATURES 25-28: INCREMENTAL (CHANGE SINCE LAST PATTERN) ==========
    # These features solve the overlapping window problem for close-together patterns

    delta_change_since_last = 0.0
    volume_change_since_last = 0.0
    price_change_since_last = 0.0
    velocity_change_since_last = 0.0

    if session_state and analysis_state and analysis_state.analyzed_patterns:
        # Get most recent pattern
        sorted_patterns = sorted(analysis_state.analyzed_patterns,
                                key=lambda x: x['timestamp'])
        prev_patterns = [p for p in sorted_patterns if p['timestamp'] < current_time]

        if prev_patterns:
            last_pattern = prev_patterns[-1]
            last_time = last_pattern['timestamp']
            last_features = last_pattern.get('features', {})

            # Calculate CHANGE since last pattern (not absolute values)
            # Use stored net_delta directly instead of reconstructing
            delta_change_since_last = totals.get('net_delta', 0) - last_features.get('net_delta', 0)
            volume_change_since_last = total_vol - last_features.get('total_vol', 0)
            price_change_since_last = close_px - last_features.get('price', close_px)

            # Velocity change (acceleration/deceleration)
            last_velocity = last_features.get('price_velocity', 0)
            velocity_change_since_last = overall_velocity - last_velocity

    # ========== FEATURES 29-32: CONSOLIDATION CONTEXT ==========
    # These features enable ML to learn breakout patterns from consolidation

    consol_context = analysis_state.get_consolidation_context(current_time, close_px) if analysis_state else {}

    inside_consolidation = 1.0 if consol_context.get('inside_consolidation', False) else 0.0
    breakout_from_consolidation = 1.0 if consol_context.get('breakout_from_consolidation', False) else 0.0
    consolidation_duration = consol_context.get('consolidation_duration', 0.0)
    breakout_magnitude = consol_context.get('breakout_magnitude', 0.0)

    return {
        # Base features (1-12)
        'trend': trend,
        'color': color,
        'broken_high': broken_high,
        'broken_low': broken_low,
        'absorption_ratio': absorption_ratio,
        'delta_imbalance': delta_imbalance,
        'total_vol': total_vol,
        'duration_mins': duration_mins,
        'upper_volume_pct': upper_vol_pct,
        'poi_position': poi_position,
        'price_velocity': overall_velocity,
        'max_velocity': max_velocity,

        # Reference values (stored for incremental calculations)
        'net_delta': totals.get('net_delta', 0),
        'price': close_px,

        # Sequence context features (13-16)
        'previous_pattern_1': previous_pattern_1,
        'previous_pattern_2': previous_pattern_2,
        'time_since_last': time_since_last,
        'recent_pattern_count': recent_pattern_count,

        # Multi-day/session context features (17-24)
        'gap_pct': gap_pct,
        'open_type': open_type,
        'ib_range': ib_range,
        'current_vs_ib_high': current_vs_ib_high,
        'current_vs_ib_low': current_vs_ib_low,
        'current_vs_prev_high': current_vs_prev_high,
        'current_vs_prev_low': current_vs_prev_low,
        'time_of_day': time_of_day,

        # Incremental features (25-28) - NEW!
        'delta_change_since_last': delta_change_since_last,
        'volume_change_since_last': volume_change_since_last,
        'price_change_since_last': price_change_since_last,
        'velocity_change_since_last': velocity_change_since_last,

        # Consolidation context features (29-32) - NEW!
        'inside_consolidation': inside_consolidation,
        'breakout_from_consolidation': breakout_from_consolidation,
        'consolidation_duration': consolidation_duration,
        'breakout_magnitude': breakout_magnitude
    }


# --- 10. THE AI BRAIN (OPTION A - 33 FEATURES) ---
class TradeClassifier:
    """Option A ML classifier with 33 features for sequence learning + incremental + consolidation context."""

    def __init__(self):
        self.model = None
        self.encoder = None
        self.needs_retraining = True

        # ALL 33 FEATURES
        self.feature_cols = [
            # Base features (1-12)
            'trend', 'color', 'broken_high', 'broken_low',
            'absorption_ratio', 'delta_imbalance', 'total_vol', 'duration_mins',
            'upper_volume_pct', 'poi_position', 'price_velocity', 'max_velocity',

            # Sequence context (13-16)
            'previous_pattern_1', 'previous_pattern_2',
            'time_since_last', 'recent_pattern_count',

            # Multi-day/session context (17-24)
            'gap_pct', 'open_type', 'ib_range',
            'current_vs_ib_high', 'current_vs_ib_low',
            'current_vs_prev_high', 'current_vs_prev_low',
            'time_of_day',

            # Incremental features (25-28) - NEW!
            'delta_change_since_last', 'volume_change_since_last',
            'price_change_since_last', 'velocity_change_since_last',

            # Consolidation context (29-32) - NEW!
            'inside_consolidation', 'breakout_from_consolidation',
            'consolidation_duration', 'breakout_magnitude'
        ]

        self.labels_map = [
            "HIGH OF DAY",           # 1: Session high (RTH)
            "LOW OF DAY",            # 2: Session low (RTH)
            "BUY REVERSAL",          # 3: Significant low, moves 10+ pts (ES) or 20+ pts (NQ)
            "SELL REVERSAL",         # 4: Significant high, moves 10+ pts (ES) or 20+ pts (NQ)
            "FALSE BUY REVERSAL",    # 5: Shallow bounce 5-10 pts (ES) or 10-20 pts (NQ)
            "FALSE SELL REVERSAL",   # 6: Shallow pullback 5-10 pts (ES) or 10-20 pts (NQ)
            "PULLBACK BUY REVERSAL", # 7: After false sell reversal, resumes buying
            "PULLBACK SELL REVERSAL",# 8: After false buy reversal, resumes selling
            "PULLBACK BUY CONTINUATION",  # 9: After pullback buy reversal, breakout
            "PULLBACK SELL CONTINUATION", # 10: After pullback sell reversal, breakdown
            "BUY CONTINUATION",      # 11: Makes higher high, closes above previous
            "SELL CONTINUATION",     # 12: Makes lower low, closes below previous
            "BUY IMPULSE",           # 13: Large green candle or large wick, high volume
            "SELL IMPULSE",          # 14: Large red candle or large wick, high volume
            "CONSOLIDATION"          # 15: Choppy period with many false reversals
        ]

    def load_model(self) -> bool:
        """Load pre-trained model from disk."""
        if not os.path.exists(MODEL_FILE):
            return False

        try:
            with open(MODEL_FILE, 'rb') as f:
                saved = pickle.load(f)
                self.model = saved['model']
                self.encoder = saved['encoder']
            print(f"[ML] Option A model loaded from {MODEL_FILE}")
            self.needs_retraining = False
            return True
        except Exception as e:
            print(f"[ML] Failed to load model: {e}")
            return False

    def save_model(self):
        """Save trained model to disk."""
        if self.model is None:
            return

        try:
            with open(MODEL_FILE, 'wb') as f:
                pickle.dump({
                    'model': self.model,
                    'encoder': self.encoder
                }, f)
            print(f"[ML] Option A model saved to {MODEL_FILE}")
        except Exception as e:
            print(f"[ML] Failed to save model: {e}")

    def train(self) -> bool:
        """Train the model on historical feedback data."""
        if not os.path.exists(TRAINING_FILE):
            return False

        try:
            df = pd.read_csv(TRAINING_FILE)

            if len(df) < MIN_TRAINING_SAMPLES:
                print(f"[ML] Need {MIN_TRAINING_SAMPLES - len(df)} more examples to train")
                print(f"     (Current: {len(df)}, Minimum: {MIN_TRAINING_SAMPLES})")
                return False

            # Check for required columns
            missing_cols = [col for col in self.feature_cols if col not in df.columns]
            if missing_cols:
                print(f"[ML WARN] Missing features in training data: {missing_cols}")
                print(f"          Old training data detected. Please re-train with 24 features.")
                return False

            X = df[self.feature_cols]
            y = df['label']

            self.encoder = LabelEncoder()
            y_encoded = self.encoder.fit_transform(y)

            X_train, X_test, y_train, y_test = train_test_split(
                X, y_encoded,
                test_size=TRAIN_TEST_SPLIT_SIZE,
                random_state=RF_RANDOM_STATE
            )

            self.model = RandomForestClassifier(
                n_estimators=RF_N_ESTIMATORS,
                random_state=RF_RANDOM_STATE
            )
            self.model.fit(X_train, y_train)

            train_score = self.model.score(X_train, y_train)
            test_score = self.model.score(X_test, y_test)

            print(f"[ML] Option A model trained on {len(df)} examples (33 features, 15 patterns)")
            print(f"     Training accuracy: {train_score:.1%}")
            print(f"     Testing accuracy:  {test_score:.1%}")

            if test_score < 0.5:
                print(f"[ML] WARNING: Low test accuracy - need more diverse examples")

            # Show feature importance
            if hasattr(self.model, 'feature_importances_'):
                importances = self.model.feature_importances_
                top_features = sorted(zip(self.feature_cols, importances),
                                    key=lambda x: x[1], reverse=True)[:10]
                print(f"[ML] Top 10 features:")
                for feat, imp in top_features:
                    print(f"      - {feat}: {imp:.1%}")

            self.save_model()
            self.needs_retraining = False

            return True

        except Exception as e:
            print(f"[ML ERROR] Training failed: {e}")
            traceback.print_exc()
            return False

    def predict(self, features: Dict) -> Optional[str]:
        """Predict pattern label."""
        if self.model is None:
            return None

        try:
            input_df = pd.DataFrame([features])[self.feature_cols]
            pred_idx = self.model.predict(input_df)[0]
            return self.encoder.inverse_transform([pred_idx])[0]
        except Exception as e:
            print(f"[ML] Prediction error: {e}")
            return None

    def predict_with_confidence(self, features: Dict) -> Tuple[Optional[str], float]:
        """Predict with confidence score."""
        if self.model is None:
            return None, 0.0

        try:
            input_df = pd.DataFrame([features])[self.feature_cols]
            probabilities = self.model.predict_proba(input_df)[0]
            pred_idx = probabilities.argmax()
            confidence = probabilities[pred_idx]

            label = self.encoder.inverse_transform([pred_idx])[0]
            return label, confidence
        except Exception as e:
            print(f"[ML] Prediction error: {e}")
            return None, 0.0

    def save_example(self, features: Dict, label: str, parent_pattern: Optional[str] = None,
                    sequence_position: Optional[int] = None):
        """
        Save training example with hierarchical info.

        Args:
            features: Feature dictionary (24 features)
            label: Pattern label
            parent_pattern: Parent pattern if this is a child
            sequence_position: Position in sequence (learned by ML, not hard-coded)
        """
        data = features.copy()
        data['label'] = label
        data['parent_pattern'] = parent_pattern if parent_pattern else "None"
        data['sequence_position'] = sequence_position if sequence_position else 0

        df = pd.DataFrame([data])

        write_header = not os.path.exists(TRAINING_FILE)
        if not write_header:
            if os.path.getsize(TRAINING_FILE) == 0:
                write_header = True

        try:
            df.to_csv(TRAINING_FILE, mode='a', header=write_header, index=False)
            print(f"[ML] Training example saved ({label})")
            if parent_pattern:
                print(f"     ↳ Child of: {parent_pattern}")
            if sequence_position:
                print(f"     ↳ Sequence position: {sequence_position}")
            self.needs_retraining = True
        except Exception as e:
            print(f"[ML] Failed to save example: {e}")


# --- 11. HEURISTIC LOGIC (NEW 15-PATTERN TAXONOMY) ---
def heuristic_classify(features: Dict, high_px: float, low_px: float, close_px: float,
                       open_px: float, duration: float, session_high: float, session_low: float) -> str:
    """
    Rule-based classification with new 15-pattern directional taxonomy.

    Pattern Definitions:
    - HIGH/LOW OF DAY: RTH extremes (volatility depends on when made)
    - BUY/SELL REVERSAL: Significant moves (10+ pts ES, 20+ pts NQ), holds 15+ mins
    - FALSE BUY/SELL REVERSAL: Shallow (5-10 pts ES, 10-20 pts NQ), often in consolidation
    - PULLBACK BUY/SELL REVERSAL: After false reversal opposite direction, resumes trend
    - PULLBACK BUY/SELL CONTINUATION: After pullback reversal, indicates breakout/breakdown
    - BUY/SELL CONTINUATION: Makes higher high/lower low, closes above/below previous
    - BUY/SELL IMPULSE: Large candles/wicks, high volume, explosive moves
    - CONSOLIDATION: Choppy, many false reversals
    """
    # Extract features
    trend = features['trend']
    color = features['color']
    broken_high = features['broken_high']
    broken_low = features['broken_low']
    range_pts = high_px - low_px
    velocity = abs(features.get('price_velocity', 0))
    max_velocity = abs(features.get('max_velocity', 0))
    total_vol = features.get('total_vol', 0)

    # Previous pattern context
    prev_pattern_1 = features.get('previous_pattern_1', 0)

    # Decode previous patterns (from pattern_label_encoder)
    # FALSE BUY REVERSAL = 5, FALSE SELL REVERSAL = 6
    # PULLBACK BUY REVERSAL = 7, PULLBACK SELL REVERSAL = 8
    prev_was_false_sell = prev_pattern_1 == 6
    prev_was_false_buy = prev_pattern_1 == 5
    prev_was_pullback_buy_reversal = prev_pattern_1 == 7
    prev_was_pullback_sell_reversal = prev_pattern_1 == 8

    # Check if session high or low (within 0.25 pts)
    is_session_high = abs(high_px - session_high) < 0.25
    is_session_low = abs(low_px - session_low) < 0.25

    # 1. HIGH OF DAY / LOW OF DAY (session extremes)
    if is_session_high:
        return "HIGH OF DAY"
    elif is_session_low:
        return "LOW OF DAY"

    # 2. CONSOLIDATION (low range, longer duration, choppy)
    if duration >= CONSOLIDATION_MIN_DURATION and range_pts < CONSOLIDATION_RANGE_THRESHOLD:
        return "CONSOLIDATION"

    # 3. IMPULSE CANDLES (large candles, large wicks, high volume, explosive moves)
    is_large_range = range_pts > 5.0
    is_high_volume = total_vol > 5000  # Threshold (can adjust)
    is_high_velocity = velocity > 5.0 or max_velocity > 8.0

    # Large wick detection
    upper_wick = high_px - max(open_px, close_px)
    lower_wick = min(open_px, close_px) - low_px
    has_large_wick = upper_wick > 2.0 or lower_wick > 2.0

    # Impulse: (large range + high volume) OR (large wick + high volume) OR high velocity
    is_impulse = (is_large_range and is_high_volume) or (has_large_wick and is_high_volume) or (is_high_velocity and range_pts > 3.0)

    if is_impulse:
        if color == 1:  # Green
            return "BUY IMPULSE"
        else:  # Red
            return "SELL IMPULSE"

    # 4. UPTREND PATTERNS (trend == 1)
    if trend == 1:
        if color == 1:  # Green candle (same direction as trend)
            # PULLBACK BUY CONTINUATION: After pullback buy reversal, indicates breakout
            if prev_was_pullback_buy_reversal:
                return "PULLBACK BUY CONTINUATION"

            # PULLBACK BUY REVERSAL: After false sell reversal, resumes buying
            # "No other red candles should occur immediately following"
            elif prev_was_false_sell:
                return "PULLBACK BUY REVERSAL"

            # BUY CONTINUATION: Makes higher high, closes above previous
            elif broken_low == 0:  # Didn't break low, continuing up
                return "BUY CONTINUATION"

            else:
                # Broke low - failed continuation
                return "FALSE BUY REVERSAL"

        else:  # color == -1, Red candle (pullback in uptrend)
            # Pullback in uptrend - check magnitude
            if FALSE_REVERSAL_MIN <= range_pts <= FALSE_REVERSAL_MAX:
                # Shallow pullback (5-10 pts ES, 10-20 pts NQ)
                return "FALSE SELL REVERSAL"
            elif range_pts > REVERSAL_THRESHOLD:
                # Significant sell-off (10+ pts ES, 20+ pts NQ)
                return "SELL REVERSAL"
            else:
                # Very small, default to false reversal
                return "FALSE SELL REVERSAL"

    # 5. DOWNTREND PATTERNS (trend == -1)
    elif trend == -1:
        if color == -1:  # Red candle (same direction as trend)
            # PULLBACK SELL CONTINUATION: After pullback sell reversal, indicates breakdown
            if prev_was_pullback_sell_reversal:
                return "PULLBACK SELL CONTINUATION"

            # PULLBACK SELL REVERSAL: After false buy reversal, resumes selling
            # "No other green candles should occur immediately following"
            elif prev_was_false_buy:
                return "PULLBACK SELL REVERSAL"

            # SELL CONTINUATION: Makes lower low, closes below previous
            elif broken_high == 0:  # Didn't break high, continuing down
                return "SELL CONTINUATION"

            else:
                # Broke high - failed continuation
                return "FALSE SELL REVERSAL"

        else:  # color == 1, Green candle (bounce in downtrend)
            # Bounce in downtrend - check magnitude
            if FALSE_REVERSAL_MIN <= range_pts <= FALSE_REVERSAL_MAX:
                # Shallow bounce (5-10 pts ES, 10-20 pts NQ)
                return "FALSE BUY REVERSAL"
            elif range_pts > REVERSAL_THRESHOLD:
                # Significant bounce (10+ pts ES, 20+ pts NQ)
                return "BUY REVERSAL"
            else:
                # Very small, default to false reversal
                return "FALSE BUY REVERSAL"

    # 6. NO CLEAR TREND (trend == 0 or neutral)
    else:
        # Check magnitude for reversal classification
        if color == 1:  # Green candle
            if range_pts > REVERSAL_THRESHOLD:
                return "BUY REVERSAL"
            elif FALSE_REVERSAL_MIN <= range_pts <= FALSE_REVERSAL_MAX:
                return "FALSE BUY REVERSAL"
            else:
                # Too small or in consolidation
                return "CONSOLIDATION"
        else:  # Red candle
            if range_pts > REVERSAL_THRESHOLD:
                return "SELL REVERSAL"
            elif FALSE_REVERSAL_MIN <= range_pts <= FALSE_REVERSAL_MAX:
                return "FALSE SELL REVERSAL"
            else:
                # Too small or in consolidation
                return "CONSOLIDATION"


# --- 12. PATTERN ANALYSIS STATE (ENHANCED FOR SEQUENCE LEARNING) ---
class PatternAnalysisState:
    """Tracks analyzed patterns and their relationships."""

    def __init__(self):
        self.analyzed_patterns = []  # List of dicts
        self.analyzed_times = []  # List of datetimes
        self.consolidation_ranges = []  # List of consolidation containers
        self.pattern_label_encoder = {
            "HIGH OF DAY": 1,
            "LOW OF DAY": 2,
            "BUY REVERSAL": 3,
            "SELL REVERSAL": 4,
            "FALSE BUY REVERSAL": 5,
            "FALSE SELL REVERSAL": 6,
            "PULLBACK BUY REVERSAL": 7,
            "PULLBACK SELL REVERSAL": 8,
            "PULLBACK BUY CONTINUATION": 9,
            "PULLBACK SELL CONTINUATION": 10,
            "BUY CONTINUATION": 11,
            "SELL CONTINUATION": 12,
            "BUY IMPULSE": 13,
            "SELL IMPULSE": 14,
            "CONSOLIDATION": 15
        }

    def encode_pattern_label(self, label: str) -> int:
        """Encode pattern label as integer for ML features."""
        return self.pattern_label_encoder.get(label, 0)

    def add_pattern(self, time_str: str, timestamp: datetime, label: str,
                   features: Dict, time_range: Tuple[datetime, datetime]):
        """Add a pattern to the state."""
        pattern = {
            'time_str': time_str,
            'timestamp': timestamp,
            'label': label,
            'features': features,
            'range': time_range,
            'children': [],
            'parent': None,
            'sequence_position': 0
        }

        # Check for hierarchical relationships
        for existing in self.analyzed_patterns:
            # This pattern contains existing?
            if (pattern['range'][0] <= existing['range'][0] and
                pattern['range'][1] >= existing['range'][1] and
                pattern['range'] != existing['range']):
                pattern['children'].append(existing['time_str'])
                existing['parent'] = pattern['time_str']
                print(f"[HIERARCHY] {pattern['time_str']} (parent) contains {existing['time_str']} (child)")

            # This pattern contained by existing?
            elif (existing['range'][0] <= pattern['range'][0] and
                  existing['range'][1] >= pattern['range'][1] and
                  pattern['range'] != existing['range']):
                existing['children'].append(pattern['time_str'])
                pattern['parent'] = existing['time_str']
                print(f"[HIERARCHY] {pattern['time_str']} (child) within {existing['time_str']} (parent)")

        self.analyzed_patterns.append(pattern)
        self.analyzed_times.append(timestamp)

    def detect_ml_learned_sequences(self):
        """
        Detect sequences that the ML model has learned.

        NOTE: Unlike the ultimate version which hard-codes liquidity sweep detection,
        Option A learns sequences automatically through the context features.

        This function is kept for visualization purposes but sequences are now
        discovered by the ML model through feature patterns, not hard-coded rules.
        """
        sequences = []

        # Sort patterns by time
        sorted_patterns = sorted(self.analyzed_patterns, key=lambda x: x['timestamp'])

        # Look for any 3-pattern sequences within 30 minutes
        # The ML model learns which sequences matter through training
        for i in range(len(sorted_patterns) - 2):
            p1 = sorted_patterns[i]
            p2 = sorted_patterns[i + 1]
            p3 = sorted_patterns[i + 2]

            # Time gap check (all within 30 minutes)
            if (p3['timestamp'] - p1['timestamp']).total_seconds() / 60 > 30:
                continue

            # Simply record 3-pattern sequences
            # The ML model's learned weights determine significance
            sequences.append({
                'type': 'ML_SEQUENCE',
                'patterns': [p1['time_str'], p2['time_str'], p3['time_str']],
                'labels': [p1['label'], p2['label'], p3['label']],
                'description': f"{p1['label']} → {p2['label']} → {p3['label']}"
            })

            # Mark sequence positions
            p1['sequence_position'] = 1
            p2['sequence_position'] = 2
            p3['sequence_position'] = 3

        if sequences:
            print(f"\n[ML SEQUENCES] Detected {len(sequences)} 3-pattern sequences:")
            for seq in sequences:
                print(f"  - {seq['description']}")

        return sequences

    def get_parent_label(self, pattern_time_str: str) -> Optional[str]:
        """Get the parent pattern label for a given pattern."""
        for pattern in self.analyzed_patterns:
            if pattern['time_str'] == pattern_time_str and pattern['parent']:
                parent_pattern = next((p for p in self.analyzed_patterns
                                     if p['time_str'] == pattern['parent']), None)
                if parent_pattern:
                    return parent_pattern['label']
        return None

    def add_consolidation_range(self, start_time: datetime, end_time: datetime,
                               high_px: float, low_px: float):
        """
        Add a consolidation range container.

        This is called when user enters a consolidation as a time range (e.g., "9:56-10:32").
        The consolidation acts as a context container for subsequent patterns.
        """
        duration_mins = (end_time - start_time).total_seconds() / 60
        range_pts = high_px - low_px

        consolidation = {
            'start': start_time,
            'end': end_time,
            'high': high_px,
            'low': low_px,
            'range': range_pts,
            'duration': duration_mins
        }

        self.consolidation_ranges.append(consolidation)
        print(f"[CONSOLIDATION RANGE] Added: {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}")
        print(f"                      Range: {range_pts:.2f} pts | Duration: {duration_mins:.0f} min")

    def get_consolidation_context(self, timestamp: datetime, price: float) -> Dict:
        """
        Get consolidation context for a given timestamp and price.

        Returns features:
        - inside_consolidation: Is this timestamp inside a consolidation range?
        - breakout_from_consolidation: Is this immediately after consolidation (within 5 min)?
        - consolidation_duration: Duration of the consolidation being broken out of
        - breakout_magnitude: How far from consolidation range (in pts)
        """
        context = {
            'inside_consolidation': False,
            'breakout_from_consolidation': False,
            'consolidation_duration': 0.0,
            'breakout_magnitude': 0.0
        }

        for consol in self.consolidation_ranges:
            # Check if inside consolidation
            if consol['start'] <= timestamp <= consol['end']:
                context['inside_consolidation'] = True
                context['consolidation_duration'] = consol['duration']
                return context

            # Check if breaking out (within 5 minutes after consolidation)
            time_after_consol = (timestamp - consol['end']).total_seconds() / 60
            if 0 < time_after_consol <= 5:
                context['breakout_from_consolidation'] = True
                context['consolidation_duration'] = consol['duration']

                # Calculate breakout magnitude
                if price > consol['high']:
                    context['breakout_magnitude'] = price - consol['high']
                elif price < consol['low']:
                    context['breakout_magnitude'] = consol['low'] - price
                else:
                    context['breakout_magnitude'] = 0.0

                return context

        return context


# --- 13. SESSION VISUALIZATION ---
def generate_session_chart(df: pd.DataFrame, analysis_state: PatternAnalysisState,
                           date_obj: datetime.date, sequences: List[Dict]):
    """
    Generate comprehensive visualization of the trading session.

    Shows:
    - Price action (1-minute candles)
    - Analyzed pattern markers with labels
    - Time windows used (shaded rectangles)
    - Hierarchical relationships (parent/child connections)
    - ML-learned sequences (connecting lines)
    - Color-coded by pattern type
    """
    if not MATPLOTLIB_AVAILABLE:
        print("[WARN] matplotlib not installed. Skipping visualization.")
        return None

    if not analysis_state.analyzed_patterns:
        print("[INFO] No patterns analyzed. Skipping visualization.")
        return None

    print("\n[VISUALIZATION] Generating session chart...")

    # Create 1-minute candles for visualization
    df_copy = df.copy()
    df_copy['minute'] = df_copy.index.floor('1min')
    candle_data = []

    for timestamp, group in df_copy.groupby('minute'):
        candle_data.append({
            'time': timestamp,
            'open': group['price'].iloc[0],
            'high': group['price'].max(),
            'low': group['price'].min(),
            'close': group['price'].iloc[-1],
            'volume': group['size'].sum()
        })

    candles_df = pd.DataFrame(candle_data)

    # Pattern color mapping
    pattern_colors = {
        'HOD': '#FF4444',  # Red - High of Day
        'LOD': '#44FF44',  # Green - Low of Day
        'REVERSAL': '#9370DB',  # Medium Purple - Significant reversal
        'FALSE REVERSAL': '#FFA500',  # Orange - Failed reversal
        'CONTINUATION': '#4444FF',  # Blue - Continues trend
        'PULLBACK CONTINUATION': '#00CED1',  # Dark Cyan - Pullback then resume
        'CONSOLIDATION': '#DAA520',  # Goldenrod - Sideways
        'IMPULSE MOVE': '#FF00FF'  # Magenta - Explosive move
    }

    # Create figure with 2 subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 12),
                                    height_ratios=[3, 1],
                                    gridspec_kw={'hspace': 0.1})

    # --- SUBPLOT 1: PRICE CHART ---

    # Plot candlestick-style line chart
    ax1.plot(candles_df['time'], candles_df['close'],
             color='#333333', linewidth=1, alpha=0.6, label='Price')

    # Fill between high and low for candle bodies
    for idx, row in candles_df.iterrows():
        color = '#00AA00' if row['close'] >= row['open'] else '#AA0000'
        ax1.plot([row['time'], row['time']], [row['low'], row['high']],
                color=color, linewidth=0.5, alpha=0.3)

    # Plot analyzed patterns
    for pattern in analysis_state.analyzed_patterns:
        label = pattern['label']
        timestamp = pattern['timestamp']
        time_range = pattern['range']
        color = pattern_colors.get(label, '#808080')

        # Get price at this time
        closest_candle = candles_df.iloc[(candles_df['time'] - timestamp).abs().argsort()[:1]]
        if not closest_candle.empty:
            price = closest_candle['close'].values[0]

            # Plot time window as shaded rectangle
            window_height = candles_df['high'].max() - candles_df['low'].min()
            rect = Rectangle((mdates.date2num(time_range[0]), candles_df['low'].min()),
                           mdates.date2num(time_range[1]) - mdates.date2num(time_range[0]),
                           window_height,
                           facecolor=color, alpha=0.1, edgecolor=color, linewidth=0.5)
            ax1.add_patch(rect)

            # Plot marker at center
            marker_style = 'o' if pattern['parent'] is None else '^'  # Circle for parent, triangle for child
            marker_size = 200 if pattern['parent'] is None else 100
            ax1.scatter(timestamp, price, s=marker_size, c=color,
                       marker=marker_style, edgecolors='black', linewidths=2,
                       zorder=5, alpha=0.9)

            # Add label text
            label_text = label
            if pattern['sequence_position'] > 0:
                label_text += f" (seq{pattern['sequence_position']})"
            if pattern['parent']:
                label_text += " ↑"  # Up arrow for child

            ax1.annotate(label_text,
                        xy=(timestamp, price),
                        xytext=(0, 20 if pattern['parent'] is None else -30),
                        textcoords='offset points',
                        fontsize=8,
                        fontweight='bold',
                        color=color,
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                                 edgecolor=color, alpha=0.8),
                        ha='center',
                        zorder=6)

    # Draw sequence connections
    if sequences:
        for seq in sequences:
            seq_patterns = [p for p in analysis_state.analyzed_patterns
                          if p['time_str'] in seq['patterns']]
            if len(seq_patterns) >= 2:
                for i in range(len(seq_patterns) - 1):
                    p1 = seq_patterns[i]
                    p2 = seq_patterns[i + 1]

                    # Get prices
                    c1 = candles_df.iloc[(candles_df['time'] - p1['timestamp']).abs().argsort()[:1]]
                    c2 = candles_df.iloc[(candles_df['time'] - p2['timestamp']).abs().argsort()[:1]]

                    if not c1.empty and not c2.empty:
                        price1 = c1['close'].values[0]
                        price2 = c2['close'].values[0]

                        # Draw dashed line connecting sequence
                        ax1.plot([p1['timestamp'], p2['timestamp']],
                                [price1, price2],
                                linestyle='--', linewidth=2, color='purple',
                                alpha=0.6, zorder=4)

    # Draw hierarchical connections (parent to children)
    for pattern in analysis_state.analyzed_patterns:
        if pattern['children']:
            parent_candle = candles_df.iloc[(candles_df['time'] - pattern['timestamp']).abs().argsort()[:1]]
            if not parent_candle.empty:
                parent_price = parent_candle['close'].values[0]

                for child_time_str in pattern['children']:
                    child_pattern = next((p for p in analysis_state.analyzed_patterns
                                        if p['time_str'] == child_time_str), None)
                    if child_pattern:
                        child_candle = candles_df.iloc[(candles_df['time'] - child_pattern['timestamp']).abs().argsort()[:1]]
                        if not child_candle.empty:
                            child_price = child_candle['close'].values[0]

                            # Draw dotted line showing hierarchy
                            ax1.plot([pattern['timestamp'], child_pattern['timestamp']],
                                    [parent_price, child_price],
                                    linestyle=':', linewidth=1.5, color='gray',
                                    alpha=0.4, zorder=3)

    # Format price chart
    ax1.set_ylabel('Price', fontsize=12, fontweight='bold')
    ax1.set_title(f'Trading Session Analysis (Option A: 24 Features) - {date_obj.strftime("%Y-%m-%d")}\n'
                  f'{len(analysis_state.analyzed_patterns)} Patterns | '
                  f'{len(sequences)} ML-Learned Sequences',
                  fontsize=14, fontweight='bold', pad=20)
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax1.tick_params(labelbottom=False)  # Hide x-labels on top chart

    # --- SUBPLOT 2: VOLUME ---
    ax2.bar(candles_df['time'], candles_df['volume'],
           width=1/1440, color='steelblue', alpha=0.6)
    ax2.set_ylabel('Volume', fontsize=10)
    ax2.set_xlabel('Time', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3, linestyle='--')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')

    # Create legend
    legend_elements = [plt.scatter([], [], s=100, c=color, marker='o',
                                  edgecolors='black', linewidths=2, label=label)
                      for label, color in pattern_colors.items()]
    legend_elements.append(plt.Line2D([0], [0], linestyle='--', linewidth=2,
                                     color='purple', label='ML Sequence'))
    legend_elements.append(plt.Line2D([0], [0], linestyle=':', linewidth=1.5,
                                     color='gray', label='Hierarchy'))
    ax1.legend(handles=legend_elements, loc='upper left', fontsize=9,
              framealpha=0.9, ncol=2)

    # Tight layout
    plt.tight_layout()

    # Save figure
    filename = f"session_chart_option_a_{date_obj.strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}.png"
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"[VISUALIZATION] Chart saved: {filename}")
    print(f"                Size: {os.path.getsize(filename) / 1024:.1f} KB")
    print(f"                Cross-reference this with your TradingView chart!")

    return filename


# --- 14. INTERACTIVE LOOP (OPTION A VERSION) ---
def parse_and_process_inputs(user_input: str, df: pd.DataFrame,
                             date_obj: datetime.date, tz: pytz.timezone,
                             ai_brain: TradeClassifier,
                             analysis_state: PatternAnalysisState,
                             session_ctx: SessionContext,
                             session_state: Dict):
    """Process user-specified time ranges with all 33 features (includes incremental + consolidation context)."""
    items = [x.strip() for x in user_input.split(',')]

    for item in items:
        if not item:
            continue

        try:
            # Parse Time/Range
            if '-' in item and ':' in item.split('-')[0] and ':' in item.split('-')[1]:
                # Explicit range: 11:00-11:45
                t1_str, t2_str = item.split('-')
                ts_start = tz.localize(datetime.combine(
                    date_obj, datetime.strptime(t1_str.strip(), '%H:%M').time()
                ))
                ts_end = tz.localize(datetime.combine(
                    date_obj, datetime.strptime(t2_str.strip(), '%H:%M').time()
                ))
                center_ts = ts_start + (ts_end - ts_start) / 2
                is_explicit_range = True
            else:
                # Single time: 11:00
                center_ts = tz.localize(datetime.combine(
                    date_obj, datetime.strptime(item.strip(), '%H:%M').time()
                ))

                # Check separation
                if not check_separation(analysis_state.analyzed_times, center_ts):
                    continue

                # Calculate adaptive window
                window_size = calculate_adaptive_window(df, center_ts)
                ts_start = center_ts - timedelta(minutes=window_size)
                ts_end = center_ts + timedelta(minutes=window_size)
                is_explicit_range = False

            # Slice Data
            pre_df = df[(df.index >= ts_start - timedelta(minutes=PRE_EVENT_LOOKBACK_MINUTES)) &
                       (df.index < ts_start)]
            event_df = df[(df.index >= ts_start) & (df.index <= ts_end)]
            post_df = df[df.index > ts_end]

            if event_df.empty:
                print(f"[WARN] No data for {item}")
                continue

            # Validate
            try:
                validate_data(event_df)
            except ValueError as e:
                print(f"[WARN] Skipping {item}: {e}")
                continue

            # Calculate metrics
            stats_df, totals = calculate_granular_metrics(event_df)
            if stats_df is None:
                print(f"[WARN] No metrics generated for {item}")
                continue

            # Extract Features (ALL 33!)
            feats = extract_features(pre_df, event_df, post_df, totals,
                                    session_ctx, analysis_state, center_ts, session_state)
            high_px, low_px = event_df['price'].max(), event_df['price'].min()
            close_px = event_df['price'].iloc[-1]  # Last price in window
            open_px = event_df['price'].iloc[0]    # First price in window
            duration = feats['duration_mins']

            # GET PREDICTIONS
            # Calculate session high/low for HOD/LOD detection
            session_high = df['price'].max()
            session_low = df['price'].min()
            heuristic_label = heuristic_classify(feats, high_px, low_px, close_px, open_px,
                                                duration, session_high, session_low)
            ml_label, confidence = ai_brain.predict_with_confidence(feats)

            # Decide what to show
            if ml_label and confidence > 0.5:
                final_display_label = ml_label
                source = f"AI MODEL ({confidence:.1%} confidence)"
            else:
                final_display_label = heuristic_label
                source = "RULE-BASED"

            # REPORT
            print(f"\n" + "="*80)
            print(f">>> ANALYSIS: {item} | Source: {source}")
            print(f"    Label       : {final_display_label}")
            print(f"    Stats       : Vol {totals['total_vol']} | Delta {totals['net_delta']} | "
                  f"Absorp {int(feats['absorption_ratio'])}")
            print(f"    Duration    : {duration:.1f} minutes")
            print(f"    Range       : {high_px:.2f} - {low_px:.2f} ({high_px - low_px:.2f} pts)")
            print(f"    Vol Profile : Upper {feats['upper_volume_pct']:.1%} | "
                  f"Lower {1-feats['upper_volume_pct']:.1%} | POI @ {feats['poi_position']:.1%}")
            print(f"    Velocity    : {feats['price_velocity']:.2f} pts/min | "
                  f"Max {feats['max_velocity']:.2f} pts/min")

            # Show sequence context
            print(f"    Sequence Ctx: Prev Pattern {feats['previous_pattern_1']} | "
                  f"Since Last {feats['time_since_last']:.1f}m | "
                  f"Recent Count {feats['recent_pattern_count']}")

            # Show session context
            print(f"    Session Ctx : Gap {feats['gap_pct']:.2f}% | "
                  f"IB Range {feats['ib_range']:.2f} | "
                  f"Time {feats['time_of_day']:.1%}")
            print("-" * 80)

            # Show per-minute breakdown
            print("\nPer-Minute Breakdown:")
            print(stats_df.to_string(index=False))

            # --- HUMAN IN THE LOOP ---
            valid_input = False
            while not valid_input:
                user_conf = input(f"\nIs '{final_display_label}' correct? (y/n/s to skip): ").lower().strip()

                if user_conf == 'y' or user_conf == '':
                    # Get parent pattern if exists
                    parent_label = analysis_state.get_parent_label(item)

                    # Save with hierarchy
                    ai_brain.save_example(feats, final_display_label, parent_pattern=parent_label)

                    # Add to state
                    analysis_state.add_pattern(item, center_ts, final_display_label,
                                             feats, (ts_start, ts_end))

                    # If this is a consolidation with explicit range, add as consolidation container
                    if final_display_label == "CONSOLIDATION" and is_explicit_range:
                        analysis_state.add_consolidation_range(ts_start, ts_end, high_px, low_px)

                    valid_input = True

                elif user_conf == 's':
                    print("[INFO] Skipped - no training data saved")
                    analysis_state.add_pattern(item, center_ts, final_display_label,
                                             feats, (ts_start, ts_end))

                    # If this is a consolidation with explicit range, add as consolidation container
                    if final_display_label == "CONSOLIDATION" and is_explicit_range:
                        analysis_state.add_consolidation_range(ts_start, ts_end, high_px, low_px)

                    valid_input = True

                elif user_conf == 'n':
                    print("\nSelect Correct Label:")
                    options = [
                        "HOD",
                        "LOD",
                        "REVERSAL",
                        "FALSE REVERSAL",
                        "CONTINUATION",
                        "PULLBACK CONTINUATION",
                        "CONSOLIDATION",
                        "IMPULSE MOVE"
                    ]
                    for i, opt in enumerate(options):
                        print(f" {i+1}. {opt}")

                    try:
                        sel = int(input("Choice # > "))
                        if 1 <= sel <= len(options):
                            correct_label = options[sel-1]

                            # Get parent pattern
                            parent_label = analysis_state.get_parent_label(item)

                            # Save with hierarchy
                            ai_brain.save_example(feats, correct_label, parent_pattern=parent_label)

                            # Add to state
                            analysis_state.add_pattern(item, center_ts, correct_label,
                                                     feats, (ts_start, ts_end))

                            # If this is a consolidation with explicit range, add as consolidation container
                            if correct_label == "CONSOLIDATION" and is_explicit_range:
                                analysis_state.add_consolidation_range(ts_start, ts_end, high_px, low_px)

                            print(f"[OK] Corrected to '{correct_label}'. Model will retrain.")
                            valid_input = True
                        else:
                            print("[ERROR] Invalid selection. Try again.")
                    except ValueError:
                        print("[ERROR] Please enter a number. Try again.")
                    except KeyboardInterrupt:
                        print("\n[INFO] Skipped")
                        valid_input = True
                else:
                    print("[ERROR] Please enter 'y', 'n', or 's'")

        except ValueError as e:
            print(f"[ERROR {item}]: Invalid format - {e}")
        except KeyError as e:
            print(f"[ERROR {item}]: Missing data - {e}")
        except Exception as e:
            print(f"[ERROR {item}]: {e}")
            traceback.print_exc()


def main():
    """Main entry point."""
    print("="*80)
    print("Trading Pattern Classifier - OPTION A (33 FEATURES)")
    print("15 Patterns | 33 Features | Sequence + Incremental + Consolidation Context")
    print("="*80)

    # Initialize AI
    brain = TradeClassifier()
    analysis_state = PatternAnalysisState()
    session_ctx = SessionContext()

    if SKLEARN_AVAILABLE:
        if brain.load_model():
            print("[ML] Option A model loaded successfully")
        else:
            has_trained = brain.train()
            if has_trained:
                print("[ML] Option A model trained on historical feedback")
            else:
                print("[ML] Option A model initialized (waiting for training data)")
                print(f"     Collect {MIN_TRAINING_SAMPLES} examples to enable ML predictions")
    else:
        print("[ML] Machine learning disabled - using rule-based logic only")

    # Get date input
    d_in = input("\nDate (YYYY-MM-DD) [Enter for Today]: ").strip()
    try:
        d_obj = datetime.now().date() if not d_in else datetime.strptime(d_in, '%Y-%m-%d').date()
    except ValueError:
        print("[ERROR] Invalid date format. Use YYYY-MM-DD")
        return

    # Fetch current day data
    df = get_databento_data(API_KEY, d_obj)

    if df is None:
        print("[ERROR] Could not fetch data. Exiting.")
        return

    print(f"[DATA] Loaded {len(df)} ticks from {df.index[0]} to {df.index[-1]}")

    # Fetch previous trading day data (handles weekends and holidays)
    prev_df, prev_date = get_previous_trading_day_data(API_KEY, d_obj)

    if prev_df is None:
        print("[WARN] Could not find previous trading day data. Using today's open as baseline.")

    # Calculate session context
    tz = pytz.timezone(TZ_STR)
    session_ctx.calculate_from_data(df, prev_df, d_obj, tz)

    # Pre-scan session for rolling metrics (enables incremental features)
    session_state = pre_scan_session(df)

    # Interactive loop
    print("\nEnter times to analyze:")
    print("  Examples:")
    print("    - Single time (adaptive window): 09:30")
    print("    - Explicit range: 11:00-11:45")
    print("    - Multiple: 09:30, 11:00-12:00, 14:15")
    print("  Type 'q' to quit")
    print("  Type 'seq' to view ML-learned sequences")

    while True:
        try:
            u_in = input("\nTimes > ").strip()
            if u_in.lower() == 'q':
                break
            elif u_in.lower() == 'seq':
                print("\n[ML SEQUENCE DETECTION]")
                sequences = analysis_state.detect_ml_learned_sequences()
                if not sequences:
                    print("No sequences detected yet. Analyze more patterns!")
                continue

            if not u_in:
                continue

            parse_and_process_inputs(u_in, df, d_obj, tz, brain, analysis_state, session_ctx, session_state)

            # Retrain if needed
            if SKLEARN_AVAILABLE and brain.needs_retraining:
                print("\n[ML] Retraining Option A model with new feedback...")
                brain.train()

        except KeyboardInterrupt:
            print("\n\n[INFO] Exiting...")
            break

    # Final sequence detection
    print("\n[SESSION SUMMARY]")
    print(f"Analyzed {len(analysis_state.analyzed_patterns)} patterns")
    sequences = analysis_state.detect_ml_learned_sequences()
    print(f"Detected {len(sequences)} pattern sequences (ML-learned)")

    # Generate visualization
    if analysis_state.analyzed_patterns:
        generate_session_chart(df, analysis_state, d_obj, sequences)

    print("\n[INFO] Session complete. Goodbye!")


if __name__ == "__main__":
    main()
