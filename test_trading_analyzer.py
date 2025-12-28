"""
Unit tests for trading_analyzer_fixed.py

Run with: pytest test_trading_analyzer.py -v
Coverage: pytest test_trading_analyzer.py --cov=trading_analyzer_fixed --cov-report=html
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import os
import tempfile

# Import functions to test
# NOTE: Adjust import based on your module structure
# If running from same directory: from trading_analyzer_fixed import ...
# For now, we'll define imports assuming file is importable

# Mock imports for testing without actual module
# In real usage, uncomment these:
# from trading_analyzer_fixed import (
#     validate_data,
#     calculate_granular_metrics,
#     extract_features,
#     heuristic_classify,
#     TradeClassifier,
#     CONSOLIDATION_MIN_DURATION,
#     CONSOLIDATION_RANGE_THRESHOLD,
#     PRICE_CHANGE_THRESHOLD,
#     MIN_RANGE_FOR_ABSORPTION
# )


# ============================================================================
# FIXTURES - Reusable Test Data
# ============================================================================

@pytest.fixture
def valid_tick_data():
    """Valid tick data for testing."""
    timestamps = pd.date_range('2024-01-01 09:30:00', periods=100, freq='1s', tz='UTC')
    return pd.DataFrame({
        'price': np.random.uniform(5000, 5010, 100),
        'size': np.random.randint(1, 50, 100),
        'signed_vol': np.random.randint(-30, 30, 100)
    }, index=timestamps)


@pytest.fixture
def simple_tick_data():
    """Simple tick data with known values."""
    timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
    return pd.DataFrame({
        'price': [5000.0, 5000.25, 5000.5, 5000.25, 5000.0],
        'size': [10, 20, 30, 20, 10],
        'signed_vol': [10, 20, 30, -20, -10]  # Net: +30
    }, index=timestamps)


@pytest.fixture
def temp_training_file():
    """Temporary file for training data tests."""
    fd, path = tempfile.mkstemp(suffix='.csv')
    os.close(fd)
    yield path
    # Cleanup
    if os.path.exists(path):
        os.remove(path)


# ============================================================================
# TEST: validate_data
# ============================================================================

class TestValidateData:
    """Tests for data validation function."""

    def test_empty_dataframe(self):
        """Should raise ValueError for empty DataFrame."""
        df = pd.DataFrame()
        with pytest.raises(ValueError, match="DataFrame is empty"):
            validate_data(df)

    def test_single_data_point(self):
        """Should raise ValueError for single data point."""
        df = pd.DataFrame({
            'price': [5000.0],
            'size': [10]
        })
        with pytest.raises(ValueError, match="at least 2 data points"):
            validate_data(df)

    def test_missing_price_column(self):
        """Should raise ValueError when price column missing."""
        df = pd.DataFrame({
            'size': [10, 20, 30]
        })
        with pytest.raises(ValueError, match="Missing required columns"):
            validate_data(df)

    def test_missing_size_column(self):
        """Should raise ValueError when size column missing."""
        df = pd.DataFrame({
            'price': [5000.0, 5000.25, 5000.5]
        })
        with pytest.raises(ValueError, match="Missing required columns"):
            validate_data(df)

    def test_all_identical_prices(self):
        """Should raise ValueError when all prices are the same."""
        df = pd.DataFrame({
            'price': [5000.0, 5000.0, 5000.0],
            'size': [10, 20, 30]
        })
        with pytest.raises(ValueError, match="All prices are identical"):
            validate_data(df)

    def test_out_of_order_timestamps(self):
        """Should raise ValueError when timestamps not monotonic."""
        timestamps = [
            pd.Timestamp('2024-01-01 09:30:00'),
            pd.Timestamp('2024-01-01 09:30:05'),
            pd.Timestamp('2024-01-01 09:30:03')  # Out of order!
        ]
        df = pd.DataFrame({
            'price': [5000.0, 5000.25, 5000.5],
            'size': [10, 20, 30]
        }, index=timestamps)
        with pytest.raises(ValueError, match="not in chronological order"):
            validate_data(df)

    def test_valid_data(self, valid_tick_data):
        """Should return True for valid data."""
        result = validate_data(valid_tick_data)
        assert result is True


# ============================================================================
# TEST: calculate_granular_metrics
# ============================================================================

class TestCalculateGranularMetrics:
    """Tests for metrics calculation function."""

    def test_empty_dataframe(self):
        """Should return None and empty dict for empty DataFrame."""
        df = pd.DataFrame()
        stats_df, totals = calculate_granular_metrics(df)
        assert stats_df is None
        assert totals == {}

    def test_single_tick(self):
        """Should handle single tick correctly."""
        timestamps = pd.date_range('2024-01-01 09:30:00', periods=1, freq='1s', tz='UTC')
        df = pd.DataFrame({
            'price': [5000.0],
            'size': [10],
            'signed_vol': [10]
        }, index=timestamps)

        stats_df, totals = calculate_granular_metrics(df)

        assert stats_df is not None
        assert len(stats_df) == 1
        assert totals['total_vol'] == 10
        assert totals['net_delta'] == 10

    def test_all_buys(self):
        """All buy volume should result in positive delta equal to volume."""
        timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        df = pd.DataFrame({
            'price': [5000.0, 5000.25, 5000.5, 5000.75, 5001.0],
            'size': [10, 20, 30, 20, 10],
            'signed_vol': [10, 20, 30, 20, 10]  # All positive
        }, index=timestamps)

        stats_df, totals = calculate_granular_metrics(df)

        assert totals['total_vol'] == 90
        assert totals['net_delta'] == 90

    def test_all_sells(self):
        """All sell volume should result in negative delta equal to -volume."""
        timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        df = pd.DataFrame({
            'price': [5001.0, 5000.75, 5000.5, 5000.25, 5000.0],
            'size': [10, 20, 30, 20, 10],
            'signed_vol': [-10, -20, -30, -20, -10]  # All negative
        }, index=timestamps)

        stats_df, totals = calculate_granular_metrics(df)

        assert totals['total_vol'] == 90
        assert totals['net_delta'] == -90

    def test_absorption_calculation(self):
        """Should correctly track max/min delta for absorption."""
        timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        # Cumulative path: [20, 50, 10, 30, 10]
        # Max: 50, Min: 10, Final: 10
        # Absorbed Buy: 50 - 10 = 40
        df = pd.DataFrame({
            'price': [5000.0] * 5,
            'size': [20, 30, 40, 20, 20],
            'signed_vol': [20, 30, -40, 20, -20]
        }, index=timestamps)

        stats_df, totals = calculate_granular_metrics(df)

        # Check first candle
        candle = stats_df.iloc[0]
        assert candle['Max_Delta'] == 50
        assert candle['Min_Delta'] == 10
        assert candle['Delta'] == 10
        assert candle['Absorbed_Buy'] == 40  # Price tried to go higher but got absorbed

    def test_multiple_minutes(self):
        """Should create separate candles for different minutes."""
        # Create data spanning 3 minutes
        timestamps = pd.date_range('2024-01-01 09:30:00', '2024-01-01 09:32:59', freq='30s')
        df = pd.DataFrame({
            'price': np.random.uniform(5000, 5010, len(timestamps)),
            'size': [10] * len(timestamps),
            'signed_vol': [10] * len(timestamps)
        }, index=timestamps)

        stats_df, totals = calculate_granular_metrics(df)

        # Should have 3 candles (09:30, 09:31, 09:32)
        assert len(stats_df) == 3


# ============================================================================
# TEST: extract_features
# ============================================================================

class TestExtractFeatures:
    """Tests for feature extraction function."""

    def test_duration_uses_timestamps_not_tick_count(self):
        """CRITICAL: Duration should use actual time, not tick count."""
        # Create data spanning exactly 5 minutes with variable tick count
        timestamps = pd.date_range('2024-01-01 09:30:00', '2024-01-01 09:35:00',
                                   freq='10s', tz='UTC')  # 31 ticks
        event_df = pd.DataFrame({
            'price': [5000.0] * len(timestamps),
            'size': [10] * len(timestamps)
        }, index=timestamps)

        totals = {'total_vol': 310, 'net_delta': 100}
        features = extract_features(pd.DataFrame(), event_df, pd.DataFrame(), totals)

        # Should be 5.0 minutes, NOT 31/60 = 0.52
        assert abs(features['duration_mins'] - 5.0) < 0.01

    def test_uptrend_into_green(self):
        """Uptrend followed by green candle."""
        pre_timestamps = pd.date_range('2024-01-01 09:25:00', periods=10, freq='1min', tz='UTC')
        pre_df = pd.DataFrame({
            'price': np.linspace(4990, 5000, 10)  # Rising trend
        }, index=pre_timestamps)

        event_timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        event_df = pd.DataFrame({
            'price': [5000.0, 5000.5, 5001.0, 5001.5, 5002.0],  # Green candle (open < close)
            'size': [10] * 5
        }, index=event_timestamps)

        totals = {'total_vol': 50, 'net_delta': 30}
        features = extract_features(pre_df, event_df, pd.DataFrame(), totals)

        assert features['trend'] == 1  # Uptrend
        assert features['color'] == 1  # Green candle

    def test_uptrend_into_red_reversal(self):
        """Uptrend followed by red candle (potential reversal)."""
        pre_timestamps = pd.date_range('2024-01-01 09:25:00', periods=10, freq='1min', tz='UTC')
        pre_df = pd.DataFrame({
            'price': np.linspace(4990, 5000, 10)  # Rising trend
        }, index=pre_timestamps)

        event_timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        event_df = pd.DataFrame({
            'price': [5002.0, 5001.5, 5001.0, 5000.5, 5000.0],  # Red candle (open > close)
            'size': [10] * 5
        }, index=event_timestamps)

        totals = {'total_vol': 50, 'net_delta': -30}
        features = extract_features(pre_df, event_df, pd.DataFrame(), totals)

        assert features['trend'] == 1  # Uptrend
        assert features['color'] == -1  # Red candle

    def test_downtrend_into_green_reversal(self):
        """Downtrend followed by green candle (potential reversal)."""
        pre_timestamps = pd.date_range('2024-01-01 09:25:00', periods=10, freq='1min', tz='UTC')
        pre_df = pd.DataFrame({
            'price': np.linspace(5010, 5000, 10)  # Falling trend
        }, index=pre_timestamps)

        event_timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        event_df = pd.DataFrame({
            'price': [5000.0, 5000.5, 5001.0, 5001.5, 5002.0],  # Green candle
            'size': [10] * 5
        }, index=event_timestamps)

        totals = {'total_vol': 50, 'net_delta': 30}
        features = extract_features(pre_df, event_df, pd.DataFrame(), totals)

        assert features['trend'] == -1  # Downtrend
        assert features['color'] == 1  # Green candle

    def test_flat_trend(self):
        """Sideways price action should result in trend=0."""
        pre_timestamps = pd.date_range('2024-01-01 09:25:00', periods=10, freq='1min', tz='UTC')
        pre_df = pd.DataFrame({
            'price': [5000.0] * 10  # Flat
        }, index=pre_timestamps)

        event_timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        event_df = pd.DataFrame({
            'price': [5000.0, 5000.5, 5001.0, 5000.5, 5000.0],
            'size': [10] * 5
        }, index=event_timestamps)

        totals = {'total_vol': 50, 'net_delta': 0}
        features = extract_features(pre_df, event_df, pd.DataFrame(), totals)

        assert features['trend'] == 0  # Neutral

    def test_broken_high_detection(self):
        """Should detect when high is broken in future data."""
        event_timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        event_df = pd.DataFrame({
            'price': [5000.0, 5001.0, 5002.0, 5001.0, 5000.0],  # High: 5002
            'size': [10] * 5
        }, index=event_timestamps)

        post_timestamps = pd.date_range('2024-01-01 09:30:10', periods=5, freq='1s', tz='UTC')
        post_df = pd.DataFrame({
            'price': [5000.0, 5001.0, 5003.0, 5002.0, 5001.0],  # Breaks 5002!
        }, index=post_timestamps)

        totals = {'total_vol': 50, 'net_delta': 0}
        features = extract_features(pd.DataFrame(), event_df, post_df, totals)

        assert features['broken_high'] == 1

    def test_broken_low_detection(self):
        """Should detect when low is broken in future data."""
        event_timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        event_df = pd.DataFrame({
            'price': [5002.0, 5001.0, 5000.0, 5001.0, 5002.0],  # Low: 5000
            'size': [10] * 5
        }, index=event_timestamps)

        post_timestamps = pd.date_range('2024-01-01 09:30:10', periods=5, freq='1s', tz='UTC')
        post_df = pd.DataFrame({
            'price': [5002.0, 5001.0, 4999.0, 5000.0, 5001.0],  # Breaks 5000!
        }, index=post_timestamps)

        totals = {'total_vol': 50, 'net_delta': 0}
        features = extract_features(pd.DataFrame(), event_df, post_df, totals)

        assert features['broken_low'] == 1

    def test_absorption_ratio_normal_range(self):
        """Should calculate absorption ratio for normal ranges."""
        event_timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        event_df = pd.DataFrame({
            'price': [5000.0, 5001.0, 5002.0, 5001.0, 5000.0],  # Range: 2.0
            'size': [10] * 5
        }, index=event_timestamps)

        totals = {'total_vol': 1000, 'net_delta': 0}
        features = extract_features(pd.DataFrame(), event_df, pd.DataFrame(), totals)

        # 1000 / 2.0 = 500
        assert features['absorption_ratio'] == pytest.approx(500.0, rel=0.01)

    def test_absorption_ratio_tiny_range(self):
        """Should return 0 for tiny ranges (avoid huge numbers)."""
        event_timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        event_df = pd.DataFrame({
            'price': [5000.0, 5000.1, 5000.2, 5000.1, 5000.0],  # Range: 0.2 < 0.5
            'size': [10] * 5
        }, index=event_timestamps)

        totals = {'total_vol': 10000, 'net_delta': 0}
        features = extract_features(pd.DataFrame(), event_df, pd.DataFrame(), totals)

        # Range < MIN_RANGE_FOR_ABSORPTION, should be 0
        assert features['absorption_ratio'] == 0

    def test_delta_imbalance(self):
        """Should calculate delta imbalance correctly."""
        event_timestamps = pd.date_range('2024-01-01 09:30:00', periods=5, freq='1s', tz='UTC')
        event_df = pd.DataFrame({
            'price': [5000.0] * 5,
            'size': [10] * 5
        }, index=event_timestamps)

        # Net delta: 80, Total vol: 100 -> Imbalance: 0.8
        totals = {'total_vol': 100, 'net_delta': 80}
        features = extract_features(pd.DataFrame(), event_df, pd.DataFrame(), totals)

        assert features['delta_imbalance'] == pytest.approx(0.8, rel=0.01)


# ============================================================================
# TEST: heuristic_classify
# ============================================================================

class TestHeuristicClassify:
    """Tests for rule-based classification logic."""

    def test_reversal_top(self):
        """Uptrend + Red candle + No breakout = REVERSAL (TOP)."""
        features = {
            'trend': 1,
            'color': -1,
            'broken_high': 0,
            'broken_low': 0
        }
        result = heuristic_classify(features, 5010.0, 5005.0, 3.0)
        assert result == "REVERSAL (TOP)"

    def test_reversal_bottom(self):
        """Downtrend + Green candle + No breakdown = REVERSAL (BOTTOM)."""
        features = {
            'trend': -1,
            'color': 1,
            'broken_high': 0,
            'broken_low': 0
        }
        result = heuristic_classify(features, 5005.0, 5000.0, 3.0)
        assert result == "REVERSAL (BOTTOM)"

    def test_false_reversal_top(self):
        """Uptrend + Red candle + High broken = FALSE REVERSAL."""
        features = {
            'trend': 1,
            'color': -1,
            'broken_high': 1,  # Fakeout!
            'broken_low': 0
        }
        result = heuristic_classify(features, 5010.0, 5005.0, 3.0)
        assert result == "FALSE REVERSAL"

    def test_false_reversal_bottom(self):
        """Downtrend + Green candle + Low broken = FALSE REVERSAL."""
        features = {
            'trend': -1,
            'color': 1,
            'broken_high': 0,
            'broken_low': 1  # Fakeout!
        }
        result = heuristic_classify(features, 5005.0, 5000.0, 3.0)
        assert result == "FALSE REVERSAL"

    def test_continuation_up(self):
        """Uptrend + Green candle = CONTINUATION."""
        features = {
            'trend': 1,
            'color': 1,
            'broken_high': 0,
            'broken_low': 0
        }
        result = heuristic_classify(features, 5010.0, 5005.0, 3.0)
        assert result == "CONTINUATION"

    def test_continuation_down(self):
        """Downtrend + Red candle = CONTINUATION."""
        features = {
            'trend': -1,
            'color': -1,
            'broken_high': 0,
            'broken_low': 0
        }
        result = heuristic_classify(features, 5005.0, 5000.0, 3.0)
        assert result == "CONTINUATION"

    def test_consolidation(self):
        """Duration ≥5min + Small range = CONSOLIDATION."""
        features = {
            'trend': 0,
            'color': 1,
            'broken_high': 0,
            'broken_low': 0
        }
        # 8 minutes, 1.5 point range (< 4.0 threshold)
        result = heuristic_classify(features, 5001.5, 5000.0, 8.0)
        assert result == "CONSOLIDATION"

    def test_not_consolidation_short_duration(self):
        """Small range but short duration should not be consolidation."""
        features = {
            'trend': 1,
            'color': 1,
            'broken_high': 0,
            'broken_low': 0
        }
        # Only 2 minutes (< 5 min threshold)
        result = heuristic_classify(features, 5001.0, 5000.0, 2.0)
        assert result == "CONTINUATION"  # Falls through to continuation logic


# ============================================================================
# TEST: TradeClassifier
# ============================================================================

class TestTradeClassifier:
    """Tests for ML classifier class."""

    def test_init(self):
        """Should initialize with None model."""
        classifier = TradeClassifier()
        assert classifier.model is None
        assert classifier.encoder is None
        assert classifier.needs_retraining is True

    def test_train_insufficient_data(self, temp_training_file):
        """Should fail to train with < 50 samples."""
        # Create CSV with only 10 examples
        data = []
        for i in range(10):
            data.append({
                'trend': 1, 'color': 1, 'broken_high': 0, 'broken_low': 0,
                'absorption_ratio': 100, 'delta_imbalance': 0.5,
                'total_vol': 1000, 'duration_mins': 5.0,
                'label': 'CONTINUATION'
            })
        pd.DataFrame(data).to_csv(temp_training_file, index=False)

        classifier = TradeClassifier()
        # Mock TRAINING_FILE constant
        classifier.__class__.TRAINING_FILE = temp_training_file

        result = classifier.train()
        assert result is False
        assert classifier.model is None

    def test_train_sufficient_data(self, temp_training_file):
        """Should train successfully with ≥50 samples."""
        # Create CSV with 60 examples
        data = []
        labels = ['REVERSAL (TOP)', 'REVERSAL (BOTTOM)', 'CONTINUATION']
        for i in range(60):
            data.append({
                'trend': np.random.choice([-1, 0, 1]),
                'color': np.random.choice([-1, 1]),
                'broken_high': np.random.choice([0, 1]),
                'broken_low': np.random.choice([0, 1]),
                'absorption_ratio': np.random.uniform(0, 1000),
                'delta_imbalance': np.random.uniform(-1, 1),
                'total_vol': np.random.randint(100, 10000),
                'duration_mins': np.random.uniform(1, 10),
                'label': np.random.choice(labels)
            })
        pd.DataFrame(data).to_csv(temp_training_file, index=False)

        classifier = TradeClassifier()
        classifier.__class__.TRAINING_FILE = temp_training_file

        result = classifier.train()
        assert result is True
        assert classifier.model is not None
        assert classifier.encoder is not None
        assert classifier.needs_retraining is False

    def test_predict_without_training(self):
        """Should return None when model not trained."""
        classifier = TradeClassifier()
        features = {
            'trend': 1, 'color': -1, 'broken_high': 0, 'broken_low': 0,
            'absorption_ratio': 500, 'delta_imbalance': -0.3,
            'total_vol': 1000, 'duration_mins': 5.0
        }
        result = classifier.predict(features)
        assert result is None

    def test_predict_with_confidence(self, temp_training_file):
        """Should return label and confidence score."""
        # Create training data
        data = []
        for i in range(60):
            data.append({
                'trend': 1, 'color': -1, 'broken_high': 0, 'broken_low': 0,
                'absorption_ratio': 500, 'delta_imbalance': -0.3,
                'total_vol': 1000, 'duration_mins': 5.0,
                'label': 'REVERSAL (TOP)'
            })
        pd.DataFrame(data).to_csv(temp_training_file, index=False)

        classifier = TradeClassifier()
        classifier.__class__.TRAINING_FILE = temp_training_file
        classifier.train()

        features = {
            'trend': 1, 'color': -1, 'broken_high': 0, 'broken_low': 0,
            'absorption_ratio': 500, 'delta_imbalance': -0.3,
            'total_vol': 1000, 'duration_mins': 5.0
        }
        label, confidence = classifier.predict_with_confidence(features)

        assert label is not None
        assert 0.0 <= confidence <= 1.0

    def test_save_example_sets_retraining_flag(self, temp_training_file):
        """Saving example should set needs_retraining=True."""
        classifier = TradeClassifier()
        classifier.__class__.TRAINING_FILE = temp_training_file
        classifier.needs_retraining = False

        features = {
            'trend': 1, 'color': -1, 'broken_high': 0, 'broken_low': 0,
            'absorption_ratio': 500, 'delta_imbalance': -0.3,
            'total_vol': 1000, 'duration_mins': 5.0
        }
        classifier.save_example(features, 'REVERSAL (TOP)')

        assert classifier.needs_retraining is True

    def test_model_persistence(self, temp_training_file):
        """Should save and load model correctly."""
        # Train model
        data = []
        for i in range(60):
            data.append({
                'trend': 1, 'color': -1, 'broken_high': 0, 'broken_low': 0,
                'absorption_ratio': 500, 'delta_imbalance': -0.3,
                'total_vol': 1000, 'duration_mins': 5.0,
                'label': 'REVERSAL (TOP)'
            })
        pd.DataFrame(data).to_csv(temp_training_file, index=False)

        # Create temp model file
        model_fd, model_path = tempfile.mkstemp(suffix='.pkl')
        os.close(model_fd)

        classifier1 = TradeClassifier()
        classifier1.__class__.TRAINING_FILE = temp_training_file
        classifier1.__class__.MODEL_FILE = model_path
        classifier1.train()
        classifier1.save_model()

        # Load model in new instance
        classifier2 = TradeClassifier()
        classifier2.__class__.MODEL_FILE = model_path
        loaded = classifier2.load_model()

        assert loaded is True
        assert classifier2.model is not None

        # Predictions should match
        features = {
            'trend': 1, 'color': -1, 'broken_high': 0, 'broken_low': 0,
            'absorption_ratio': 500, 'delta_imbalance': -0.3,
            'total_vol': 1000, 'duration_mins': 5.0
        }
        pred1 = classifier1.predict(features)
        pred2 = classifier2.predict(features)
        assert pred1 == pred2

        # Cleanup
        os.remove(model_path)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for full pipeline."""

    def test_full_analysis_pipeline(self):
        """Test complete analysis flow: data → metrics → features → classification."""
        # Create realistic tick data
        timestamps = pd.date_range('2024-01-01 09:30:00', '2024-01-01 09:35:00',
                                   freq='5s', tz='UTC')
        event_df = pd.DataFrame({
            'price': np.concatenate([
                np.linspace(5000, 5005, 30),  # Rally
                np.linspace(5005, 5002, 31)   # Pullback
            ]),
            'size': np.random.randint(10, 50, 61),
        }, index=timestamps)
        event_df['signed_vol'] = np.where(
            event_df['price'].diff() > 0,
            event_df['size'],
            -event_df['size']
        )

        # Pre-event data (uptrend)
        pre_timestamps = pd.date_range('2024-01-01 09:20:00', '2024-01-01 09:29:59',
                                       freq='1min', tz='UTC')
        pre_df = pd.DataFrame({
            'price': np.linspace(4990, 5000, len(pre_timestamps))
        }, index=pre_timestamps)

        # Post-event data (no breakout)
        post_timestamps = pd.date_range('2024-01-01 09:35:01', '2024-01-01 09:40:00',
                                        freq='5s', tz='UTC')
        post_df = pd.DataFrame({
            'price': np.linspace(5002, 5001, len(post_timestamps))
        }, index=post_timestamps)

        # Step 1: Validate
        validate_data(event_df)

        # Step 2: Calculate metrics
        stats_df, totals = calculate_granular_metrics(event_df)
        assert stats_df is not None
        assert 'total_vol' in totals

        # Step 3: Extract features
        features = extract_features(pre_df, event_df, post_df, totals)
        assert 'trend' in features
        assert 'duration_mins' in features

        # Step 4: Classify
        high_px = event_df['price'].max()
        low_px = event_df['price'].min()
        duration = features['duration_mins']
        label = heuristic_classify(features, high_px, low_px, duration)

        assert label in ['REVERSAL (TOP)', 'REVERSAL (BOTTOM)', 'FALSE REVERSAL',
                        'CONTINUATION', 'CONSOLIDATION', 'V-SHAPE', 'UNCERTAIN']


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
