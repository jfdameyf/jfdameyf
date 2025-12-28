# Unit Testing Strategy for Trading Analyzer

## Overview

Unit tests ensure each component of the trading analyzer works correctly in isolation. This prevents bugs, documents expected behavior, and enables safe refactoring.

---

## 🎯 What to Test

### 1. Data Validation (`validate_data`)

**Why:** Critical safety function that prevents bad data from corrupting analysis

**Test Cases:**
- ✅ **Empty DataFrame** - Should raise ValueError
- ✅ **Single data point** - Should raise ValueError (need ≥2)
- ✅ **Missing columns** - Should raise ValueError
- ✅ **All identical prices** - Should raise ValueError
- ✅ **Out-of-order timestamps** - Should raise ValueError
- ✅ **Valid data** - Should return True

**Example Scenarios:**
```python
# Bad: Empty DataFrame
df = pd.DataFrame()
# Expected: ValueError("DataFrame is empty")

# Bad: All same price
df = pd.DataFrame({
    'price': [5000.0, 5000.0, 5000.0],
    'size': [10, 20, 15]
})
# Expected: ValueError("All prices are identical")

# Good: Normal data
df = pd.DataFrame({
    'price': [5000.0, 5000.25, 5000.5],
    'size': [10, 20, 15]
})
# Expected: True
```

---

### 2. Metrics Calculation (`calculate_granular_metrics`)

**Why:** Core calculation engine - errors here corrupt all downstream analysis

**Test Cases:**
- ✅ **Empty DataFrame** - Should return (None, {})
- ✅ **Single tick** - Should calculate correctly
- ✅ **Single minute of data** - Should create 1 candle
- ✅ **Multiple minutes** - Should create multiple candles
- ✅ **All buys (positive delta)** - Delta should equal volume
- ✅ **All sells (negative delta)** - Delta should equal -volume
- ✅ **Mixed buys/sells** - Delta should be net difference
- ✅ **Absorption calculation** - Max/Min delta should track cumulative path

**Example Scenarios:**
```python
# Test: All buys
df = pd.DataFrame({
    'price': [5000.0, 5000.25, 5000.5],
    'size': [10, 20, 30],
    'signed_vol': [10, 20, 30]  # All positive (buys)
})
stats_df, totals = calculate_granular_metrics(df)
# Expected: totals['net_delta'] = 60, totals['total_vol'] = 60

# Test: Absorption (icebergs)
# Price rallies to +50 delta, but gets absorbed back to +10
df = pd.DataFrame({
    'signed_vol': [20, 30, -40]  # Cumulative: [20, 50, 10]
})
# Expected: Max_Delta = 50, Final_Delta = 10, Absorbed_Buy = 40
```

---

### 3. Feature Extraction (`extract_features`)

**Why:** Features feed the ML model - wrong features = wrong predictions

**Test Cases:**
- ✅ **Uptrend into green candle** - trend=1, color=1
- ✅ **Uptrend into red candle** - trend=1, color=-1 (reversal pattern)
- ✅ **Downtrend into green** - trend=-1, color=1 (reversal pattern)
- ✅ **Flat trend** - trend=0
- ✅ **Duration calculation** - Should use actual time, not tick count
- ✅ **Absorption ratio with tiny range** - Should return 0
- ✅ **Absorption ratio with normal range** - Should calculate correctly
- ✅ **Broken high detection** - Should flag if post_df exceeds high
- ✅ **Broken low detection** - Should flag if post_df breaks low
- ✅ **Delta imbalance** - Should be in [-1, 1] range

**Critical Test - Duration Bug Fix:**
```python
# Create data spanning exactly 5 minutes
timestamps = pd.date_range('2024-01-01 09:30:00', '2024-01-01 09:35:00', freq='10s')
df = pd.DataFrame({
    'price': np.random.uniform(5000, 5010, len(timestamps)),
    'size': [10] * len(timestamps)
}, index=timestamps)

features = extract_features(pd.DataFrame(), df, pd.DataFrame(), {'total_vol': 310})

# Expected: duration_mins = 5.0
# NOT: len(df) / 60 = 31 / 60 = 0.52 ❌
assert abs(features['duration_mins'] - 5.0) < 0.01
```

---

### 4. Heuristic Classification (`heuristic_classify`)

**Why:** Fallback logic must be correct when ML unavailable

**Test Cases:**
- ✅ **Reversal (Top)**: Uptrend + Red candle + No breakout = REVERSAL (TOP)
- ✅ **Reversal (Bottom)**: Downtrend + Green candle + No breakdown = REVERSAL (BOTTOM)
- ✅ **False Reversal (Top)**: Uptrend + Red candle + High broken later = FALSE REVERSAL
- ✅ **False Reversal (Bottom)**: Downtrend + Green + Low broken later = FALSE REVERSAL
- ✅ **Continuation (Up)**: Uptrend + Green = CONTINUATION
- ✅ **Continuation (Down)**: Downtrend + Red = CONTINUATION
- ✅ **Consolidation**: Duration ≥5min + Range <4pts = CONSOLIDATION

**Example Scenarios:**
```python
# Test: Classic reversal pattern
features = {
    'trend': 1,  # Uptrend
    'color': -1,  # Red candle
    'broken_high': 0,  # High NOT broken
    'broken_low': 0
}
result = heuristic_classify(features, 5010.0, 5005.0, 3.0)
# Expected: "REVERSAL (TOP)"

# Test: False reversal (fakeout)
features = {
    'trend': 1,  # Uptrend
    'color': -1,  # Red candle
    'broken_high': 1,  # High WAS broken later (fakeout!)
    'broken_low': 0
}
result = heuristic_classify(features, 5010.0, 5005.0, 3.0)
# Expected: "FALSE REVERSAL"

# Test: Consolidation
features = {'trend': 0, 'color': 1, 'broken_high': 0, 'broken_low': 0}
result = heuristic_classify(features, 5001.5, 5000.0, 8.0)
# Expected: "CONSOLIDATION" (8 mins, 1.5 pt range)
```

---

### 5. TradeClassifier Class

**Why:** ML pipeline must work correctly and handle edge cases

**Test Cases:**

#### 5a. Model Training
- ✅ **Insufficient data (<50 samples)** - Should fail gracefully
- ✅ **Exactly 50 samples** - Should train successfully
- ✅ **100+ samples** - Should train with good accuracy
- ✅ **Train/test split** - Should report both accuracies
- ✅ **Feature columns match** - Should use all 8 features

#### 5b. Model Persistence
- ✅ **Save model** - Should create .pkl file
- ✅ **Load model** - Should restore model correctly
- ✅ **Load non-existent model** - Should return False
- ✅ **Predictions match** - Loaded model should predict same as original

#### 5c. Predictions
- ✅ **Predict without training** - Should return None
- ✅ **Predict with confidence** - Should return label + score
- ✅ **Confidence in [0, 1]** - Should be valid probability

#### 5d. Save Example
- ✅ **First example** - Should create file with header
- ✅ **Subsequent examples** - Should append without extra headers
- ✅ **Set retraining flag** - needs_retraining should be True

**Example Scenarios:**
```python
# Test: Insufficient training data
classifier = TradeClassifier()
# Create CSV with only 10 examples
result = classifier.train()
# Expected: False, message "Need 40 more examples"

# Test: Model persistence
classifier.train()  # Train model
classifier.save_model()  # Save
classifier2 = TradeClassifier()
classifier2.load_model()  # Load

features = {'trend': 1, 'color': -1, ...}
pred1 = classifier.predict(features)
pred2 = classifier2.predict(features)
# Expected: pred1 == pred2 (same predictions)
```

---

### 6. Integration Tests

**Why:** Components must work together correctly

**Test Cases:**
- ✅ **Full pipeline**: Fetch → Validate → Metrics → Features → Classify
- ✅ **Time range parsing**: "09:30", "11:00-12:00"
- ✅ **Timezone handling**: UTC → Local conversion
- ✅ **Error recovery**: Bad time window should skip, not crash

---

## 📊 Test Coverage Goals

| Component | Target Coverage |
|-----------|----------------|
| `validate_data` | 100% |
| `calculate_granular_metrics` | 95% |
| `extract_features` | 95% |
| `heuristic_classify` | 100% |
| `TradeClassifier` | 90% |
| Overall | 90%+ |

---

## 🛠️ Testing Tools

### Recommended Stack:
```bash
pip install pytest pytest-cov pandas numpy
```

### Running Tests:
```bash
# Run all tests
pytest test_trading_analyzer.py -v

# With coverage report
pytest test_trading_analyzer.py --cov=trading_analyzer_fixed --cov-report=html

# Run specific test
pytest test_trading_analyzer.py::test_validate_data_empty -v
```

---

## 🎓 Testing Best Practices

### 1. Use Fixtures for Test Data
```python
@pytest.fixture
def sample_tick_data():
    """Reusable test data."""
    return pd.DataFrame({
        'price': [5000.0, 5000.25, 5000.5],
        'size': [10, 20, 30],
        'signed_vol': [10, -20, 30]
    })
```

### 2. Test Edge Cases First
- Empty data
- Single data point
- Extreme values
- Boundary conditions

### 3. Use Descriptive Test Names
```python
def test_validate_data_raises_error_when_all_prices_identical():
    # Clear what's being tested
```

### 4. One Assertion Per Test (Usually)
```python
# Good: Focused test
def test_duration_calculation_uses_timestamps():
    features = extract_features(...)
    assert abs(features['duration_mins'] - 5.0) < 0.01

# Avoid: Testing multiple things
def test_all_features():
    features = extract_features(...)
    assert features['duration_mins'] == 5.0
    assert features['trend'] == 1
    assert features['color'] == -1
    # ... 10 more assertions
```

### 5. Mock External Dependencies
```python
from unittest.mock import Mock, patch

def test_get_databento_data():
    with patch('databento.Historical') as mock_client:
        mock_client.return_value.timeseries.get_range.return_value.to_df.return_value = mock_df
        result = get_databento_data("fake_key", datetime.now().date())
        # Test without hitting real API
```

---

## 🐛 Common Testing Pitfalls

### ❌ Pitfall 1: Floating Point Comparisons
```python
# Bad: Will fail due to floating point precision
assert features['duration_mins'] == 5.0

# Good: Use tolerance
assert abs(features['duration_mins'] - 5.0) < 0.01
```

### ❌ Pitfall 2: Timezone-Naive Timestamps
```python
# Bad: Timezone-naive datetimes can cause bugs
df.index = pd.date_range('2024-01-01', periods=10)

# Good: Specify timezone
df.index = pd.date_range('2024-01-01', periods=10, tz='America/New_York')
```

### ❌ Pitfall 3: File Dependencies
```python
# Bad: Test depends on existing file
def test_load_model():
    classifier = TradeClassifier()
    result = classifier.load_model()  # Fails if file doesn't exist

# Good: Create file in test
def test_load_model(tmp_path):
    # tmp_path is pytest fixture for temp directory
    model_file = tmp_path / "trained_model.pkl"
    # ... create test model file ...
```

---

## 📈 Example Test Run Output

```
============================= test session starts ==============================
test_trading_analyzer.py::test_validate_data_empty PASSED                [ 10%]
test_trading_analyzer.py::test_validate_data_single_point PASSED          [ 20%]
test_trading_analyzer.py::test_validate_data_missing_columns PASSED       [ 30%]
test_trading_analyzer.py::test_validate_data_identical_prices PASSED      [ 40%]
test_trading_analyzer.py::test_calculate_metrics_all_buys PASSED          [ 50%]
test_trading_analyzer.py::test_extract_features_duration_correct PASSED   [ 60%]
test_trading_analyzer.py::test_heuristic_reversal_top PASSED              [ 70%]
test_trading_analyzer.py::test_heuristic_false_reversal PASSED            [ 80%]
test_trading_analyzer.py::test_classifier_insufficient_data PASSED        [ 90%]
test_trading_analyzer.py::test_model_persistence PASSED                   [100%]

========================== 10 passed in 2.34s ===============================

----------- coverage: platform linux, python 3.10.12 -----------
Name                          Stmts   Miss  Cover
-------------------------------------------------
trading_analyzer_fixed.py      287     12    96%
-------------------------------------------------
TOTAL                          287     12    96%
```

---

## 🎯 Priority Testing Order

1. **Critical Path** (Must test first):
   - ✅ `validate_data` - Prevents bad data
   - ✅ `extract_features` - Especially duration bug fix
   - ✅ `calculate_granular_metrics` - Core calculations

2. **High Value** (Test second):
   - ✅ `heuristic_classify` - Fallback logic
   - ✅ `TradeClassifier.train()` - ML pipeline
   - ✅ Model persistence - Save/load

3. **Nice to Have** (Test third):
   - ✅ Error handling paths
   - ✅ Edge cases in UI functions
   - ✅ Integration tests

---

## 📚 Next Steps

1. Implement tests in `test_trading_analyzer.py`
2. Run tests and achieve 90%+ coverage
3. Add tests to CI/CD pipeline (GitHub Actions)
4. Update tests when adding new features

See `test_trading_analyzer.py` for full implementation of these tests.
