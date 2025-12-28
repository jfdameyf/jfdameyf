"""
Trading Pattern Classifier - Fixed Version
Analyzes tick data and classifies trading patterns using ML + heuristics.

SETUP:
1. Install dependencies: pip install databento pandas numpy scikit-learn pytz
2. Set environment variable: export DATABENTO_API_KEY="your_api_key_here"
3. Run: python trading_analyzer_fixed.py
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
from typing import Tuple, Dict, Optional

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
TRAINING_FILE = "ml_training_data.csv"
MODEL_FILE = "trained_model.pkl"

# Analysis Parameters
PRICE_SCALE_FACTOR = 1e9
CONSOLIDATION_RANGE_THRESHOLD = 4.0  # Points
CONSOLIDATION_MIN_DURATION = 5  # Minutes
ANALYSIS_WINDOW_MINUTES = 10
PRE_EVENT_LOOKBACK_MINUTES = 15
MIN_RANGE_FOR_ABSORPTION = 0.5  # Minimum range to calculate absorption

# ML Parameters
RF_N_ESTIMATORS = 100
RF_RANDOM_STATE = 42
MIN_TRAINING_SAMPLES = 50  # Increased from 5
TRAIN_TEST_SPLIT_SIZE = 0.2

# Price change threshold to avoid noise
PRICE_CHANGE_THRESHOLD = 0.25


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


# --- 2. DATA FETCHING ---
def get_databento_data(api_key: str, date_obj: datetime.date) -> Optional[pd.DataFrame]:
    """
    Fetch tick data from Databento API.

    Args:
        api_key: Databento API key
        date_obj: Date to fetch data for

    Returns:
        DataFrame with tick data or None if error/no data
    """
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


# --- 3. METRICS ENGINE ---
def calculate_granular_metrics(df: pd.DataFrame) -> Tuple[Optional[pd.DataFrame], Dict[str, int]]:
    """
    Calculate per-minute metrics and period totals.

    Args:
        df: DataFrame with tick data including 'price', 'size', 'signed_vol'

    Returns:
        Tuple of (candle stats DataFrame, period totals dict)
    """
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


# --- 4. ML FEATURE EXTRACTION ---
def extract_features(pre_df: pd.DataFrame, event_df: pd.DataFrame,
                    post_df: pd.DataFrame, totals: Dict) -> Dict:
    """
    Extract features from price action for ML model.

    Args:
        pre_df: Data before the event window
        event_df: Data during the event window
        post_df: Data after the event window
        totals: Aggregated metrics for the event window

    Returns:
        Dictionary of features
    """
    open_px = event_df['price'].iloc[0]
    close_px = event_df['price'].iloc[-1]
    high_px = event_df['price'].max()
    low_px = event_df['price'].min()

    # Feature 1: Incoming Trend (-1 Down, 0 Neutral, 1 Up)
    trend = 0
    if not pre_df.empty and len(pre_df) > 1:
        price_change = pre_df['price'].iloc[-1] - pre_df['price'].iloc[0]
        if price_change > PRICE_CHANGE_THRESHOLD:
            trend = 1
        elif price_change < -PRICE_CHANGE_THRESHOLD:
            trend = -1

    # Feature 2: Candle Color (-1 Red, 1 Green)
    color = 1 if close_px > open_px else -1

    # Feature 3: Did it break high/low later?
    broken_high = 0
    broken_low = 0
    if not post_df.empty:
        if post_df['price'].max() > high_px:
            broken_high = 1
        if post_df['price'].min() < low_px:
            broken_low = 1

    # Feature 4: Absorption Ratio (FIXED: handle small ranges)
    range_size = high_px - low_px
    if range_size < MIN_RANGE_FOR_ABSORPTION:
        absorption_ratio = 0  # Too small to be meaningful
    else:
        absorption_ratio = totals['total_vol'] / range_size

    # Feature 5: Delta Imbalance
    delta_imbalance = totals['net_delta'] / totals['total_vol'] if totals['total_vol'] > 0 else 0

    # Feature 6: Duration in minutes (FIXED: use actual time, not tick count)
    if len(event_df) > 1:
        duration_mins = (event_df.index[-1] - event_df.index[0]).total_seconds() / 60
    else:
        duration_mins = 0

    return {
        'trend': trend,
        'color': color,
        'broken_high': broken_high,
        'broken_low': broken_low,
        'absorption_ratio': absorption_ratio,
        'delta_imbalance': delta_imbalance,
        'total_vol': totals['total_vol'],
        'duration_mins': duration_mins
    }


# --- 5. THE AI BRAIN ---
class TradeClassifier:
    """Machine learning classifier for trading patterns with persistence."""

    def __init__(self):
        self.model = None
        self.encoder = None
        self.needs_retraining = True
        self.feature_cols = [
            'trend', 'color', 'broken_high', 'broken_low',
            'absorption_ratio', 'delta_imbalance', 'total_vol', 'duration_mins'
        ]
        self.labels_map = [
            "REVERSAL (TOP)", "REVERSAL (BOTTOM)", "FALSE REVERSAL",
            "CONTINUATION", "CONSOLIDATION", "V-SHAPE"
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
            print(f"[ML] Model loaded from {MODEL_FILE}")
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
            print(f"[ML] Model saved to {MODEL_FILE}")
        except Exception as e:
            print(f"[ML] Failed to save model: {e}")

    def train(self) -> bool:
        """Train the model on historical feedback data."""
        if not os.path.exists(TRAINING_FILE):
            return False

        try:
            df = pd.read_csv(TRAINING_FILE)

            # FIXED: Require minimum samples
            if len(df) < MIN_TRAINING_SAMPLES:
                print(f"[ML] Need {MIN_TRAINING_SAMPLES - len(df)} more examples to train")
                print(f"     (Current: {len(df)}, Minimum: {MIN_TRAINING_SAMPLES})")
                return False

            X = df[self.feature_cols]
            y = df['label']

            # Encode labels
            self.encoder = LabelEncoder()
            y_encoded = self.encoder.fit_transform(y)

            # Train/test split for validation
            X_train, X_test, y_train, y_test = train_test_split(
                X, y_encoded,
                test_size=TRAIN_TEST_SPLIT_SIZE,
                random_state=RF_RANDOM_STATE
            )

            # Train model
            self.model = RandomForestClassifier(
                n_estimators=RF_N_ESTIMATORS,
                random_state=RF_RANDOM_STATE
            )
            self.model.fit(X_train, y_train)

            # Validate
            train_score = self.model.score(X_train, y_train)
            test_score = self.model.score(X_test, y_test)

            print(f"[ML] Model trained on {len(df)} examples")
            print(f"     Training accuracy: {train_score:.1%}")
            print(f"     Testing accuracy:  {test_score:.1%}")

            if test_score < 0.5:
                print(f"[ML] WARNING: Low test accuracy - model may not be reliable yet")

            # Save model
            self.save_model()
            self.needs_retraining = False

            return True

        except Exception as e:
            print(f"[ML ERROR] Training failed: {e}")
            traceback.print_exc()
            return False

    def predict(self, features: Dict) -> Optional[str]:
        """Predict pattern label for given features."""
        if self.model is None:
            return None

        try:
            # Convert single feature dict to DataFrame
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

            # Get probabilities
            probabilities = self.model.predict_proba(input_df)[0]
            pred_idx = probabilities.argmax()
            confidence = probabilities[pred_idx]

            label = self.encoder.inverse_transform([pred_idx])[0]
            return label, confidence
        except Exception as e:
            print(f"[ML] Prediction error: {e}")
            return None, 0.0

    def save_example(self, features: Dict, label: str):
        """Save training example to CSV."""
        data = features.copy()
        data['label'] = label
        df = pd.DataFrame([data])

        # Write header only if file doesn't exist or is empty
        write_header = not os.path.exists(TRAINING_FILE)
        if not write_header:
            # Check if file is empty
            if os.path.getsize(TRAINING_FILE) == 0:
                write_header = True

        try:
            df.to_csv(TRAINING_FILE, mode='a', header=write_header, index=False)
            print(f"[ML] Training example saved ({label})")
            self.needs_retraining = True
        except Exception as e:
            print(f"[ML] Failed to save example: {e}")


# --- 6. HEURISTIC LOGIC (The Fallback) ---
def heuristic_classify(features: Dict, high_px: float, low_px: float,
                       duration: float) -> str:
    """
    Rule-based classification fallback when ML model unavailable.

    Args:
        features: Feature dictionary
        high_px: Highest price in window
        low_px: Lowest price in window
        duration: Duration in minutes

    Returns:
        Pattern label string
    """
    # Unpack for readability
    trend = features['trend']
    color = features['color']
    broken_high = features['broken_high']
    broken_low = features['broken_low']
    range_pts = high_px - low_px

    # Consolidation check
    if duration >= CONSOLIDATION_MIN_DURATION and range_pts < CONSOLIDATION_RANGE_THRESHOLD:
        return "CONSOLIDATION"

    # Reversal patterns
    if trend == 1 and color == -1:  # Up into Red
        return "REVERSAL (TOP)" if not broken_high else "FALSE REVERSAL"
    elif trend == -1 and color == 1:  # Down into Green
        return "REVERSAL (BOTTOM)" if not broken_low else "FALSE REVERSAL"

    # Continuation patterns
    elif trend == 1 and color == 1:  # Up into Green
        return "CONTINUATION" if not broken_low else "FALSE REVERSAL"
    elif trend == -1 and color == -1:  # Down into Red
        return "CONTINUATION" if not broken_high else "FALSE REVERSAL"

    return "UNCERTAIN"


# --- 7. INTERACTIVE LOOP ---
def parse_and_process_inputs(user_input: str, df: pd.DataFrame,
                             date_obj: datetime.date, tz: pytz.timezone,
                             ai_brain: TradeClassifier):
    """Process user-specified time ranges for analysis."""
    items = [x.strip() for x in user_input.split(',')]

    for item in items:
        if not item:
            continue

        try:
            # Parse Time/Range
            if '-' in item:
                t1_str, t2_str = item.split('-')
                ts_start = tz.localize(datetime.combine(
                    date_obj, datetime.strptime(t1_str.strip(), '%H:%M').time()
                ))
                ts_end = tz.localize(datetime.combine(
                    date_obj, datetime.strptime(t2_str.strip(), '%H:%M').time()
                ))
            else:
                center_ts = tz.localize(datetime.combine(
                    date_obj, datetime.strptime(item.strip(), '%H:%M').time()
                ))
                ts_start = center_ts - timedelta(minutes=ANALYSIS_WINDOW_MINUTES)
                ts_end = center_ts + timedelta(minutes=ANALYSIS_WINDOW_MINUTES)

            # Slice Data
            pre_df = df[(df.index >= ts_start - timedelta(minutes=PRE_EVENT_LOOKBACK_MINUTES)) &
                       (df.index < ts_start)]
            event_df = df[(df.index >= ts_start) & (df.index <= ts_end)]
            post_df = df[df.index > ts_end]

            if event_df.empty:
                print(f"[WARN] No data for {item}")
                continue

            # Validate event data
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
            if ml_label and confidence > 0.5:  # Use ML if confident
                final_display_label = ml_label
                source = f"AI MODEL ({confidence:.1%} confidence)"
            else:
                final_display_label = heuristic_label
                source = "RULE-BASED"

            # REPORT
            print(f"\n" + "="*75)
            print(f">>> ANALYSIS: {item} | Source: {source}")
            print(f"    Label    : {final_display_label}")
            print(f"    Stats    : Vol {totals['total_vol']} | Delta {totals['net_delta']} | "
                  f"Absorp {int(feats['absorption_ratio'])}")
            print(f"    Duration : {duration:.1f} minutes")
            print(f"    Range    : {high_px:.2f} - {low_px:.2f} ({high_px - low_px:.2f} pts)")
            print("-" * 75)

            # Show per-minute breakdown
            print("\nPer-Minute Breakdown:")
            print(stats_df.to_string(index=False))

            # --- HUMAN IN THE LOOP ---
            valid_input = False
            while not valid_input:
                user_conf = input(f"\nIs '{final_display_label}' correct? (y/n/s to skip): ").lower().strip()

                if user_conf == 'y' or user_conf == '':
                    ai_brain.save_example(feats, final_display_label)
                    valid_input = True
                elif user_conf == 's':
                    print("[INFO] Skipped - no training data saved")
                    valid_input = True
                elif user_conf == 'n':
                    print("\nSelect Correct Label:")
                    options = [
                        "REVERSAL (TOP)", "REVERSAL (BOTTOM)", "FALSE REVERSAL",
                        "CONTINUATION", "CONSOLIDATION", "V-SHAPE"
                    ]
                    for i, opt in enumerate(options):
                        print(f" {i+1}. {opt}")

                    try:
                        sel = int(input("Choice # > "))
                        if 1 <= sel <= len(options):
                            correct_label = options[sel-1]
                            ai_brain.save_example(feats, correct_label)
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
            print(f"[ERROR {item}]: Invalid time format - {e}")
        except KeyError as e:
            print(f"[ERROR {item}]: Missing data - {e}")
        except Exception as e:
            print(f"[ERROR {item}]: {e}")
            traceback.print_exc()


def main():
    """Main entry point."""
    print("="*75)
    print("Trading Pattern Classifier - Fixed Version")
    print("="*75)

    # Initialize AI
    brain = TradeClassifier()

    if SKLEARN_AVAILABLE:
        # Try to load existing model
        if brain.load_model():
            print("[ML] Pre-trained model loaded successfully")
        else:
            # Try to train from scratch
            has_trained = brain.train()
            if has_trained:
                print("[ML] Model trained on historical feedback")
            else:
                print("[ML] Model initialized (waiting for training data)")
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
    print("    - Single time with ±10min window: 09:30")
    print("    - Specific range: 11:00-12:00")
    print("    - Multiple: 09:30, 11:00-12:00, 14:15")
    print("  Type 'q' to quit")

    while True:
        try:
            u_in = input("\nTimes > ").strip()
            if u_in.lower() == 'q':
                break

            if not u_in:
                continue

            parse_and_process_inputs(u_in, df, d_obj, tz, brain)

            # FIXED: Only retrain if needed and enough data
            if SKLEARN_AVAILABLE and brain.needs_retraining:
                print("\n[ML] Retraining model with new feedback...")
                brain.train()

        except KeyboardInterrupt:
            print("\n\n[INFO] Exiting...")
            break

    print("\n[INFO] Session complete. Goodbye!")


if __name__ == "__main__":
    main()
