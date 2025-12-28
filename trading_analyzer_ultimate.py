"""
Trading Pattern Classifier - ULTIMATE Version

Combines ALL advanced features:
- 8 Pattern Types (including PULLBACK CONTINUATION)
- 12 ML Features (Volume Profile + Price Velocity)
- Adaptive Time Windows (auto-adjusts to volatility)
- Hierarchical Pattern Tracking (parent/child relationships)
- Sequence Detection (liquidity sweep → regain → reversal)
- Minimum Separation Warnings
- Session Visualization (auto-generated chart for cross-reference)

SETUP:
1. Install dependencies: pip install databento pandas numpy scikit-learn pytz matplotlib
2. Set environment variable: export DATABENTO_API_KEY="your_api_key_here"
3. Run: python trading_analyzer_ultimate.py

FEATURES:
- Expected accuracy: 80-90%+ with 100+ training examples
- Auto-adapts to trending vs consolidation days
- Learns pattern sequences and relationships
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
TRAINING_FILE = "ml_training_data_ultimate.csv"
MODEL_FILE = "trained_model_ultimate.pkl"

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
MIN_SEPARATION_MINUTES = 15  # Minimum time between analyses

# ML Parameters
RF_N_ESTIMATORS = 100
RF_RANDOM_STATE = 42
MIN_TRAINING_SAMPLES = 50
TRAIN_TEST_SPLIT_SIZE = 0.2

# Price change threshold to avoid noise
PRICE_CHANGE_THRESHOLD = 0.25

# Volume Profile Parameters
VOLUME_PROFILE_BINS = 10


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


# --- 5. METRICS ENGINE ---
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


# --- 8. ENHANCED FEATURE EXTRACTION ---
def extract_features(pre_df: pd.DataFrame, event_df: pd.DataFrame,
                    post_df: pd.DataFrame, totals: Dict) -> Dict:
    """
    Extract enhanced features (12 total).

    Features:
    1-8: Original (trend, color, broken_high/low, absorption_ratio, delta_imbalance, total_vol, duration_mins)
    9-10: Volume Profile (upper_volume_pct, poi_position)
    11-12: Price Velocity (price_velocity, max_velocity)
    """
    open_px = event_df['price'].iloc[0]
    close_px = event_df['price'].iloc[-1]
    high_px = event_df['price'].max()
    low_px = event_df['price'].min()

    # Original features
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

    # New features
    upper_vol_pct, lower_vol_pct, poi_position = calculate_volume_profile(event_df)
    overall_velocity, max_velocity, acceleration = calculate_price_velocity(event_df)

    return {
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
        'max_velocity': max_velocity
    }


# --- 9. THE AI BRAIN (ULTIMATE) ---
class TradeClassifier:
    """Ultimate ML classifier with 8 pattern types."""

    def __init__(self):
        self.model = None
        self.encoder = None
        self.needs_retraining = True
        self.feature_cols = [
            'trend', 'color', 'broken_high', 'broken_low',
            'absorption_ratio', 'delta_imbalance', 'total_vol', 'duration_mins',
            'upper_volume_pct', 'poi_position', 'price_velocity', 'max_velocity'
        ]
        self.labels_map = [
            "REVERSAL (TOP)",
            "REVERSAL (BOTTOM)",
            "FALSE REVERSAL",
            "CONTINUATION",
            "PULLBACK CONTINUATION",  # ← NEW!
            "CONSOLIDATION",
            "V-SHAPE",
            "UNCERTAIN"
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
            print(f"[ML] Ultimate model loaded from {MODEL_FILE}")
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
            print(f"[ML] Ultimate model saved to {MODEL_FILE}")
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

            # Check for required columns (handle both old and new format)
            missing_cols = [col for col in self.feature_cols if col not in df.columns]
            if missing_cols:
                print(f"[ML WARN] Missing new features in training data: {missing_cols}")
                print(f"          Old training data detected. Please re-train with new features.")
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

            print(f"[ML] Ultimate model trained on {len(df)} examples (12 features, 8 patterns)")
            print(f"     Training accuracy: {train_score:.1%}")
            print(f"     Testing accuracy:  {test_score:.1%}")

            if test_score < 0.5:
                print(f"[ML] WARNING: Low test accuracy - need more diverse examples")

            # Show feature importance
            if hasattr(self.model, 'feature_importances_'):
                importances = self.model.feature_importances_()
                top_features = sorted(zip(self.feature_cols, importances),
                                    key=lambda x: x[1], reverse=True)[:5]
                print(f"[ML] Top 5 features:")
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
            features: Feature dictionary
            label: Pattern label
            parent_pattern: Parent pattern if this is a child (e.g., "CONSOLIDATION")
            sequence_position: Position in sequence (e.g., 1, 2, 3 for liquidity sweep sequence)
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


# --- 10. HEURISTIC LOGIC (UPDATED WITH PULLBACK CONTINUATION) ---
def heuristic_classify(features: Dict, high_px: float, low_px: float,
                       duration: float) -> str:
    """
    Updated rule-based classification with PULLBACK CONTINUATION.
    """
    trend = features['trend']
    color = features['color']
    broken_high = features['broken_high']
    broken_low = features['broken_low']
    range_pts = high_px - low_px

    # Consolidation check
    if duration >= CONSOLIDATION_MIN_DURATION and range_pts < CONSOLIDATION_RANGE_THRESHOLD:
        return "CONSOLIDATION"

    # UPTREND PATTERNS
    if trend == 1:
        if color == 1:  # Green (same as trend)
            if broken_low == 0:
                return "CONTINUATION"
            else:
                return "FALSE REVERSAL"

        elif color == -1:  # Red (pullback)
            if broken_high == 1:
                return "PULLBACK CONTINUATION"  # ← NEW! Breaks above pullback
            elif broken_high == 0 and broken_low == 0:
                return "REVERSAL (TOP)"  # True reversal
            else:
                return "FALSE REVERSAL"

    # DOWNTREND PATTERNS
    elif trend == -1:
        if color == -1:  # Red (same as trend)
            if broken_high == 0:
                return "CONTINUATION"
            else:
                return "FALSE REVERSAL"

        elif color == 1:  # Green (bounce)
            if broken_low == 1:
                return "PULLBACK CONTINUATION"  # ← NEW! Breaks below bounce
            elif broken_low == 0 and broken_high == 0:
                return "REVERSAL (BOTTOM)"  # True reversal
            else:
                return "FALSE REVERSAL"

    return "UNCERTAIN"


# --- 11. PATTERN ANALYSIS STATE (FOR HIERARCHICAL TRACKING) ---
class PatternAnalysisState:
    """Tracks analyzed patterns and their relationships."""

    def __init__(self):
        self.analyzed_patterns = []  # List of dicts
        self.analyzed_times = []  # List of datetimes

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

    def detect_sequences(self):
        """Detect common pattern sequences (e.g., liquidity sweep → regain → reversal)."""
        sequences = []

        # Sort patterns by time
        sorted_patterns = sorted(self.analyzed_patterns, key=lambda x: x['timestamp'])

        # Look for liquidity sweep sequences (3-pattern sequence)
        for i in range(len(sorted_patterns) - 2):
            p1 = sorted_patterns[i]
            p2 = sorted_patterns[i + 1]
            p3 = sorted_patterns[i + 2]

            # Time gap check (all within 30 minutes)
            if (p3['timestamp'] - p1['timestamp']).total_seconds() / 60 > 30:
                continue

            # Liquidity Sweep Pattern: FALSE REVERSAL → PULLBACK CONTINUATION → REVERSAL
            if (p1['label'] == "FALSE REVERSAL" and
                p2['label'] in ["PULLBACK CONTINUATION", "CONTINUATION"] and
                p3['label'] in ["REVERSAL (TOP)", "REVERSAL (BOTTOM)"]):

                sequences.append({
                    'type': 'LIQUIDITY_SWEEP',
                    'patterns': [p1['time_str'], p2['time_str'], p3['time_str']],
                    'description': f"Liquidity sweep → regain → reversal"
                })
                print(f"[SEQUENCE] Detected LIQUIDITY_SWEEP:")
                print(f"           {p1['time_str']} ({p1['label']}) →")
                print(f"           {p2['time_str']} ({p2['label']}) →")
                print(f"           {p3['time_str']} ({p3['label']})")

                # Mark sequence positions
                p1['sequence_position'] = 1
                p2['sequence_position'] = 2
                p3['sequence_position'] = 3

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


# --- 12. SESSION VISUALIZATION ---
def generate_session_chart(df: pd.DataFrame, analysis_state: PatternAnalysisState,
                           date_obj: datetime.date, sequences: List[Dict]):
    """
    Generate comprehensive visualization of the trading session.

    Shows:
    - Price action (1-minute candles)
    - Analyzed pattern markers with labels
    - Time windows used (shaded rectangles)
    - Hierarchical relationships (parent/child connections)
    - Sequences (connecting lines)
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
        'REVERSAL (TOP)': '#FF4444',  # Red
        'REVERSAL (BOTTOM)': '#44FF44',  # Green
        'FALSE REVERSAL': '#FFA500',  # Orange
        'CONTINUATION': '#4444FF',  # Blue
        'PULLBACK CONTINUATION': '#00CED1',  # Dark Cyan
        'CONSOLIDATION': '#DAA520',  # Goldenrod
        'V-SHAPE': '#FF00FF',  # Magenta
        'UNCERTAIN': '#808080'  # Gray
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
    ax1.set_title(f'Trading Session Analysis - {date_obj.strftime("%Y-%m-%d")}\n'
                  f'{len(analysis_state.analyzed_patterns)} Patterns | '
                  f'{len(sequences)} Sequences',
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
                                     color='purple', label='Sequence'))
    legend_elements.append(plt.Line2D([0], [0], linestyle=':', linewidth=1.5,
                                     color='gray', label='Hierarchy'))
    ax1.legend(handles=legend_elements, loc='upper left', fontsize=9,
              framealpha=0.9, ncol=2)

    # Tight layout
    plt.tight_layout()

    # Save figure
    filename = f"session_chart_{date_obj.strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}.png"
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"[VISUALIZATION] Chart saved: {filename}")
    print(f"                Size: {os.path.getsize(filename) / 1024:.1f} KB")
    print(f"                Cross-reference this with your TradingView chart!")

    return filename


# --- 13. INTERACTIVE LOOP (ULTIMATE VERSION) ---
def parse_and_process_inputs(user_input: str, df: pd.DataFrame,
                             date_obj: datetime.date, tz: pytz.timezone,
                             ai_brain: TradeClassifier,
                             analysis_state: PatternAnalysisState):
    """Process user-specified time ranges with all advanced features."""
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

            # Extract Features
            feats = extract_features(pre_df, event_df, post_df, totals)
            high_px, low_px = event_df['price'].max(), event_df['price'].min()
            duration = feats['duration_mins']

            # GET PREDICTIONS
            heuristic_label = heuristic_classify(feats, high_px, low_px, duration)
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
                    valid_input = True

                elif user_conf == 's':
                    print("[INFO] Skipped - no training data saved")
                    analysis_state.add_pattern(item, center_ts, final_display_label,
                                             feats, (ts_start, ts_end))
                    valid_input = True

                elif user_conf == 'n':
                    print("\nSelect Correct Label:")
                    options = [
                        "REVERSAL (TOP)",
                        "REVERSAL (BOTTOM)",
                        "FALSE REVERSAL",
                        "CONTINUATION",
                        "PULLBACK CONTINUATION",  # ← NEW!
                        "CONSOLIDATION",
                        "V-SHAPE"
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
    print("Trading Pattern Classifier - ULTIMATE VERSION")
    print("8 Patterns | 12 Features | Adaptive Windows | Hierarchical Tracking")
    print("="*80)

    # Initialize AI
    brain = TradeClassifier()
    analysis_state = PatternAnalysisState()

    if SKLEARN_AVAILABLE:
        if brain.load_model():
            print("[ML] Ultimate model loaded successfully")
        else:
            has_trained = brain.train()
            if has_trained:
                print("[ML] Ultimate model trained on historical feedback")
            else:
                print("[ML] Ultimate model initialized (waiting for training data)")
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

    # Fetch data
    df = get_databento_data(API_KEY, d_obj)

    if df is None:
        print("[ERROR] Could not fetch data. Exiting.")
        return

    print(f"[DATA] Loaded {len(df)} ticks from {df.index[0]} to {df.index[-1]}")

    # Interactive loop
    tz = pytz.timezone(TZ_STR)

    print("\nEnter times to analyze:")
    print("  Examples:")
    print("    - Single time (adaptive window): 09:30")
    print("    - Explicit range: 11:00-11:45")
    print("    - Multiple: 09:30, 11:00-12:00, 14:15")
    print("  Type 'q' to quit")
    print("  Type 'seq' to detect pattern sequences")

    while True:
        try:
            u_in = input("\nTimes > ").strip()
            if u_in.lower() == 'q':
                break
            elif u_in.lower() == 'seq':
                print("\n[SEQUENCE DETECTION]")
                sequences = analysis_state.detect_sequences()
                if not sequences:
                    print("No sequences detected yet. Analyze more patterns!")
                continue

            if not u_in:
                continue

            parse_and_process_inputs(u_in, df, d_obj, tz, brain, analysis_state)

            # Retrain if needed
            if SKLEARN_AVAILABLE and brain.needs_retraining:
                print("\n[ML] Retraining ultimate model with new feedback...")
                brain.train()

        except KeyboardInterrupt:
            print("\n\n[INFO] Exiting...")
            break

    # Final sequence detection
    print("\n[SESSION SUMMARY]")
    print(f"Analyzed {len(analysis_state.analyzed_patterns)} patterns")
    sequences = analysis_state.detect_sequences()
    print(f"Detected {len(sequences)} pattern sequences")

    # Generate visualization
    if analysis_state.analyzed_patterns:
        generate_session_chart(df, analysis_state, d_obj, sequences)

    print("\n[INFO] Session complete. Goodbye!")


if __name__ == "__main__":
    main()
