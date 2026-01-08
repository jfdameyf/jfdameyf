# Order Book FLIP Analysis Workflow
## Complete Step-by-Step Guide

This document outlines the complete workflow for implementing and running order book analysis on FLIP signals to validate trade quality using Level 2/3 market data.

---

## 📋 Prerequisites

### 1. Required Accounts & API Keys
- ✅ **Databento Account** - Sign up at databento.com
- ✅ **API Key** - Get from Databento dashboard
- ✅ **API Credits** - Estimate $50-200 for 30-90 days of Level 2 data

### 2. Python Dependencies
```bash
# Install required packages (if not already installed)
pip install databento pandas numpy matplotlib seaborn pytz
```

### 3. Current Repository State
- ✅ Backtest framework updated for FLIP signals
- ✅ OrderBookFlipAnalyzer skeleton complete
- ✅ Integration framework documented
- ⏳ Databento data fetching needs implementation
- ⏳ Order book calculations need implementation

---

## 🎯 Phase 1: Setup & Data Collection (Week 1)

### Step 1.1: Configure Databento API

**File:** Create `config.py` or add to existing config
```python
# config.py
DATABENTO_API_KEY = "your_api_key_here"  # Replace with actual key
SYMBOL = "ES.c.0"  # ES futures
DATASET = "GLBX.MDP3"  # CME Globex
```

**Test connection:**
```python
import databento as db

client = db.Historical(DATABENTO_API_KEY)

# Test basic fetch
from datetime import datetime
test_date = datetime(2024, 12, 15)

# Fetch 1 minute of data to test
test_data = client.timeseries.get_range(
    dataset="GLBX.MDP3",
    schema="ohlcv-1m",
    symbols=["ES.c.0"],
    stype_in="continuous",
    start=test_date.replace(hour=9, minute=30),
    end=test_date.replace(hour=9, minute=31)
)

print(f"✅ Databento connected! Got {len(test_data)} records")
```

### Step 1.2: Identify Sample FLIP Events

**Goal:** Find 5-10 recent FLIP signals to use for pilot testing

**Option A: From Live Bot Logs**
```bash
# Check your recent signal CSV logs
grep "FLIP" logs/es_signals_*.csv | head -10
```

**Option B: Run Quick Backtest**
```python
# Run 7-day backtest to find FLIPs
from backtest_compare import compare_poc_filter

comp = compare_poc_filter(days_back=7)

# Extract FLIP signals from results
import pandas as pd
for name, data in comp.results.items():
    df = pd.DataFrame(data['signals'])
    flips = df[df['type'] == 'FLIP']
    print(f"\n{name}: {len(flips)} FLIP signals")
    print(flips[['time', 'price', 'direction', 'zone']].head())
```

**Record Sample Events:**
```
Sample FLIP Events for Testing:
1. Date: 2024-12-15, Time: 10:23:15, Price: 5925.50, Type: RES→SUP
2. Date: 2024-12-15, Time: 14:45:32, Price: 5930.25, Type: SUP→RES
3. Date: 2024-12-16, Time: 11:12:45, Price: 5918.75, Type: RES→SUP
... (continue for 5-10 events)
```

### Step 1.3: Understand Databento MBP Schema

**Test fetching Level 2 data for one sample event:**
```python
import databento as db
from datetime import datetime, timedelta
import pytz

client = db.Historical(DATABENTO_API_KEY)
NY_TZ = pytz.timezone('America/New_York')

# Use one of your sample FLIP events
flip_time = NY_TZ.localize(datetime(2024, 12, 15, 10, 23, 15))

# Fetch 10 minutes before flip
start = flip_time - timedelta(minutes=10)
end = flip_time + timedelta(minutes=2)

# Fetch MBP-10 (market by price, 10 levels)
book_data = client.timeseries.get_range(
    dataset="GLBX.MDP3",
    schema="mbp-10",  # 10 levels of depth
    symbols=["ES.c.0"],
    stype_in="continuous",
    start=start,
    end=end
).to_df()

print(f"✅ Got {len(book_data)} order book snapshots")
print(f"\nColumns: {book_data.columns.tolist()}")
print(f"\nSample snapshot:")
print(book_data.head())
```

**Expected columns:**
- `ts_event` - Timestamp
- `bid_px_00` to `bid_px_09` - Bid prices (10 levels)
- `ask_px_00` to `ask_px_09` - Ask prices (10 levels)
- `bid_sz_00` to `bid_sz_09` - Bid sizes (10 levels)
- `ask_sz_00` to `ask_sz_09` - Ask sizes (10 levels)

---

## 🔧 Phase 2: Implement Data Fetching (Week 1-2)

### Step 2.1: Implement `_fetch_orderbook_snapshot()`

**File:** `orderbook_flip_analyzer.py`

**Replace the placeholder method:**
```python
def _fetch_orderbook_snapshot(self, start_time, end_time, focus_time):
    """
    Fetch Level 2 order book data for a time window

    Args:
        start_time: Start of window
        end_time: End of window
        focus_time: The key moment we're analyzing

    Returns:
        DataFrame with order book data
    """
    logging.debug(f"Fetching order book: {start_time} to {end_time}")

    try:
        book_data = self.client.timeseries.get_range(
            dataset="GLBX.MDP3",
            schema="mbp-10",  # Market by price, 10 levels deep
            symbols=[self.symbol],
            stype_in="continuous",
            start=start_time,
            end=end_time
        ).to_df()

        if book_data.empty:
            logging.warning(f"No order book data for {start_time} to {end_time}")
            return pd.DataFrame()

        logging.info(f"✅ Fetched {len(book_data)} order book snapshots")
        return book_data

    except Exception as e:
        logging.error(f"Error fetching order book: {e}")
        return pd.DataFrame()
```

### Step 2.2: Test Data Fetching

**Create test script:** `test_databento_fetch.py`
```python
"""Test Databento order book fetching"""
from orderbook_flip_analyzer import create_analyzer_from_api_key
from datetime import datetime, timedelta
import pytz

# Your API key
DATABENTO_KEY = "your_key_here"

# Create analyzer
analyzer = create_analyzer_from_api_key(DATABENTO_KEY, "ES.c.0")

# Test fetch on sample event
NY_TZ = pytz.timezone('America/New_York')
test_time = NY_TZ.localize(datetime(2024, 12, 15, 10, 23, 15))

book = analyzer._fetch_orderbook_snapshot(
    start_time=test_time - timedelta(minutes=5),
    end_time=test_time + timedelta(minutes=2),
    focus_time=test_time
)

print(f"✅ Fetched {len(book)} snapshots")
print(f"Columns: {book.columns.tolist()}")
print(f"\nSample:")
print(book.head())
```

Run: `python test_databento_fetch.py`

---

## 🧮 Phase 3: Implement Calculations (Week 2)

### Step 3.1: Implement `_calculate_total_bid_size()`

```python
def _calculate_total_bid_size(self, book_data, level_price):
    """
    Calculate total bid size within proximity of level

    Sums all bid volume within self.tick_proximity ticks of level_price
    """
    if book_data.empty:
        return 0

    # Get the snapshot closest to our focus time (last snapshot)
    snapshot = book_data.iloc[-1]

    total_bid_size = 0
    proximity_range = self.tick_size * self.tick_proximity

    # Sum bid sizes for all 10 levels within range
    for i in range(10):
        bid_px = snapshot.get(f'bid_px_{i:02d}', None)
        bid_sz = snapshot.get(f'bid_sz_{i:02d}', 0)

        if bid_px and abs(bid_px - level_price) <= proximity_range:
            total_bid_size += bid_sz

    return total_bid_size
```

### Step 3.2: Implement `_calculate_total_ask_size()`

```python
def _calculate_total_ask_size(self, book_data, level_price):
    """
    Calculate total ask size within proximity of level
    """
    if book_data.empty:
        return 0

    snapshot = book_data.iloc[-1]
    total_ask_size = 0
    proximity_range = self.tick_size * self.tick_proximity

    for i in range(10):
        ask_px = snapshot.get(f'ask_px_{i:02d}', None)
        ask_sz = snapshot.get(f'ask_sz_{i:02d}', 0)

        if ask_px and abs(ask_px - level_price) <= proximity_range:
            total_ask_size += ask_sz

    return total_ask_size
```

### Step 3.3: Implement `_calculate_absorption_at_level()`

```python
def _calculate_absorption_at_level(self, book_data, level_price, level_type):
    """
    Calculate volume absorbed exactly at the level

    For SUP: Sum bid size at level_price
    For RES: Sum ask size at level_price
    """
    if book_data.empty:
        return 0

    snapshot = book_data.iloc[-1]
    absorption = 0

    if level_type == 'SUP':
        # Look for bids at this price
        for i in range(10):
            bid_px = snapshot.get(f'bid_px_{i:02d}', None)
            bid_sz = snapshot.get(f'bid_sz_{i:02d}', 0)

            if bid_px and abs(bid_px - level_price) < self.tick_size / 2:
                absorption += bid_sz
    else:  # RES
        # Look for asks at this price
        for i in range(10):
            ask_px = snapshot.get(f'ask_px_{i:02d}', None)
            ask_sz = snapshot.get(f'ask_sz_{i:02d}', 0)

            if ask_px and abs(ask_px - level_price) < self.tick_size / 2:
                absorption += ask_sz

    return absorption
```

### Step 3.4: Implement `_calculate_imbalance()`

```python
def _calculate_imbalance(self, book_data, level_price):
    """
    Calculate order book imbalance near level

    Returns: -1.0 (ask dominated) to +1.0 (bid dominated)
    """
    total_bid = self._calculate_total_bid_size(book_data, level_price)
    total_ask = self._calculate_total_ask_size(book_data, level_price)

    total = total_bid + total_ask

    if total == 0:
        return 0.0

    # Normalize to -1 to +1
    imbalance = (total_bid - total_ask) / total
    return imbalance
```

### Step 3.5: Implement `_count_large_orders()`

```python
def _count_large_orders(self, book_data, level_price, side):
    """
    Count large orders near the level

    Args:
        side: 'bid' or 'ask'
    """
    if book_data.empty:
        return 0

    snapshot = book_data.iloc[-1]
    count = 0
    proximity_range = self.tick_size * self.tick_proximity

    if side == 'bid':
        for i in range(10):
            bid_px = snapshot.get(f'bid_px_{i:02d}', None)
            bid_sz = snapshot.get(f'bid_sz_{i:02d}', 0)

            if (bid_px and
                abs(bid_px - level_price) <= proximity_range and
                bid_sz >= self.large_order_threshold):
                count += 1
    else:  # ask
        for i in range(10):
            ask_px = snapshot.get(f'ask_px_{i:02d}', None)
            ask_sz = snapshot.get(f'ask_sz_{i:02d}', 0)

            if (ask_px and
                abs(ask_px - level_price) <= proximity_range and
                ask_sz >= self.large_order_threshold):
                count += 1

    return count
```

### Step 3.6: Implement `_assess_depth_quality()`

```python
def _assess_depth_quality(self, book_data, level_price, level_type):
    """
    Assess overall order book depth quality

    Returns: 'STRONG' | 'MODERATE' | 'WEAK' | 'VERY_WEAK'
    """
    if book_data.empty:
        return 'UNKNOWN'

    # Get metrics
    total_bid = self._calculate_total_bid_size(book_data, level_price)
    total_ask = self._calculate_total_ask_size(book_data, level_price)
    absorption = self._calculate_absorption_at_level(book_data, level_price, level_type)
    imbalance = abs(self._calculate_imbalance(book_data, level_price))
    large_bids = self._count_large_orders(book_data, level_price, 'bid')
    large_asks = self._count_large_orders(book_data, level_price, 'ask')

    total_liquidity = total_bid + total_ask
    total_large = large_bids + large_asks

    # Scoring criteria (for ES)
    # Adjust thresholds for NQ/GC

    # STRONG: Deep book, good absorption, low imbalance, multiple large orders
    if (total_liquidity > 2000 and
        absorption > 500 and
        imbalance < 0.3 and
        total_large >= 3):
        return 'STRONG'

    # MODERATE: Decent depth, reasonable absorption
    elif (total_liquidity > 1000 and
          absorption > 250 and
          imbalance < 0.5):
        return 'MODERATE'

    # WEAK: Thin book or poor metrics
    elif total_liquidity > 500:
        return 'WEAK'

    # VERY_WEAK: Extremely thin, risky
    else:
        return 'VERY_WEAK'
```

---

## 🧪 Phase 4: Pilot Testing (Week 2)

### Step 4.1: Test on Single FLIP Event

**Create:** `test_single_flip.py`
```python
"""Test order book analysis on a single FLIP event"""
from orderbook_flip_analyzer import create_analyzer_from_api_key
from datetime import datetime, timedelta
import pytz

# Setup
DATABENTO_KEY = "your_key"
analyzer = create_analyzer_from_api_key(DATABENTO_KEY, "ES.c.0")

# Use one of your sample FLIP events
NY_TZ = pytz.timezone('America/New_York')

# Example: RES failed at 10:15, flipped to SUP at 10:45
fail_time = NY_TZ.localize(datetime(2024, 12, 15, 10, 15, 0))
flip_time = NY_TZ.localize(datetime(2024, 12, 15, 10, 45, 0))
level_price = 5925.50

# Run analysis
result = analyzer.analyze_flip_level(
    level_price=level_price,
    fail_time=fail_time,
    flip_time=flip_time,
    original_type='RES',
    flip_type='SUP'
)

# Review results
if result:
    print("\n" + "="*60)
    print("FLIP ANALYSIS RESULT")
    print("="*60)
    print(f"\nLevel: {result['level_price']:.2f}")
    print(f"Type: {result['original_type']} → {result['flip_type']}")
    print(f"Time between: {result['time_between']:.1f} minutes")

    print(f"\n📊 FAILURE PHASE:")
    fail = result['failure_phase']
    print(f"   Total liquidity: {fail['total_liquidity']:,} contracts")
    print(f"   Absorption: {fail['absorption_at_level']:,} contracts")
    print(f"   Depth quality: {fail['depth_quality']}")
    print(f"   Large orders: {fail['total_large_orders']}")

    print(f"\n📊 FLIP PHASE:")
    flip = result['flip_phase']
    print(f"   Total liquidity: {flip['total_liquidity']:,} contracts")
    print(f"   Absorption: {flip['absorption_at_level']:,} contracts")
    print(f"   Depth quality: {flip['depth_quality']}")
    print(f"   Large orders: {flip['total_large_orders']}")

    print(f"\n📈 COMPARISON:")
    print(f"   Liquidity shift: {result['liquidity_shift']:+,} contracts")
    print(f"   Absorption delta: {result['absorption_delta']:+,} contracts")
    print(f"   Imbalance improvement: {result['imbalance_improvement']:+.2f}")

    print(f"\n⭐ QUALITY ASSESSMENT:")
    print(f"   Score: {result['quality_score']:.1f}/100")
    print(f"   Rating: {result['quality_rating']}")
    print(f"   Confidence: {result['confidence']}")
    print(f"   Recommendation: {result['recommendation']}")
else:
    print("❌ Analysis failed")
```

Run: `python test_single_flip.py`

**Validate results make sense:**
- Are liquidity numbers reasonable? (ES typically 500-3000 contracts in proximity)
- Does the quality rating align with your intuition?
- Did the flip phase show improvement over failure?

### Step 4.2: Test on 5-10 FLIP Events

**Create:** `test_multiple_flips.py`
```python
"""Test on multiple FLIP events"""
from orderbook_flip_analyzer import create_analyzer_from_api_key
from datetime import datetime
import pytz

DATABENTO_KEY = "your_key"
analyzer = create_analyzer_from_api_key(DATABENTO_KEY, "ES.c.0")
NY_TZ = pytz.timezone('America/New_York')

# Your sample FLIP events
sample_flips = [
    {
        'level': 5925.50,
        'fail_time': NY_TZ.localize(datetime(2024, 12, 15, 10, 15)),
        'flip_time': NY_TZ.localize(datetime(2024, 12, 15, 10, 45)),
        'original': 'RES',
        'flip': 'SUP'
    },
    {
        'level': 5930.25,
        'fail_time': NY_TZ.localize(datetime(2024, 12, 15, 14, 20)),
        'flip_time': NY_TZ.localize(datetime(2024, 12, 15, 14, 50)),
        'original': 'SUP',
        'flip': 'RES'
    },
    # ... add more
]

# Analyze each
for i, flip in enumerate(sample_flips, 1):
    print(f"\n{'='*60}")
    print(f"Testing FLIP {i}/{len(sample_flips)}")
    print(f"{'='*60}")

    result = analyzer.analyze_flip_level(
        level_price=flip['level'],
        fail_time=flip['fail_time'],
        flip_time=flip['flip_time'],
        original_type=flip['original'],
        flip_type=flip['flip']
    )

    if result:
        print(f"✅ {result['quality_rating']} (Score: {result['quality_score']:.1f})")
        print(f"   Recommendation: {result['recommendation']}")
    else:
        print(f"❌ Analysis failed")

# Generate summary
print("\n" + "="*60)
print("SUMMARY REPORT")
print("="*60)
analyzer.generate_summary_report()

# Export
analyzer.export_to_csv('pilot_flip_analysis.csv')
analyzer.plot_quality_distribution('pilot_quality_chart.png')

print("\n✅ Pilot test complete!")
print("   Results: pilot_flip_analysis.csv")
print("   Chart: pilot_quality_chart.png")
```

Run: `python test_multiple_flips.py`

**Review:**
- Check `pilot_flip_analysis.csv` for detailed metrics
- View `pilot_quality_chart.png` for quality distribution
- Validate that quality scores correlate with your trading intuition

### Step 4.3: Tune Quality Scoring Weights (Optional)

If the quality scores don't align with your expectations, adjust weights in `_assess_flip_quality()`:

```python
# Current weights:
score = (signal_score * 0.5) +      # Liquidity (50%)
        (zone_diversity * 0.3) +     # Zone diversity (30%)
        (balance_score * 0.2)        # Long/short balance (20%)

# Adjust based on pilot results
# Example: Prioritize absorption over liquidity
score = (absorption_score * 0.4) +   # Absorption (40%)
        (liquidity_score * 0.3) +    # Liquidity (30%)
        (depth_quality * 0.2) +      # Depth (20%)
        (imbalance * 0.1)            # Imbalance (10%)
```

---

## 🔗 Phase 5: Integration with Backtest (Week 3)

### Step 5.1: Add Integration Points to `backtest_bot.py`

**Reference:** `backtest_with_orderbook_example.py` has all the code

**Point 1: Add to `__init__`:**
```python
def __init__(self, start_date, end_date, enable_poc_filter=False,
             analyze_orderbook=False, databento_api_key=None):
    # ... existing code ...

    # ✅ NEW: Order book analysis
    self.analyze_orderbook = analyze_orderbook
    self.ob_analyzer = None

    if analyze_orderbook:
        if databento_api_key:
            from orderbook_flip_analyzer import create_analyzer_from_api_key
            self.ob_analyzer = create_analyzer_from_api_key(databento_api_key, SYMBOL)
            print("✅ Order book analysis enabled")
        else:
            print("⚠️  Order book enabled but no API key")
            self.analyze_orderbook = False
```

**Point 2: Track failures in `_check_signal` or signal processing:**
```python
# When you detect a level has FAILED
# (This happens in the strategy's detect_level_recapture method)
if self.analyze_orderbook and self.ob_analyzer:
    self.ob_analyzer.track_level_failure(
        level_price=level['price'],
        fail_time=timestamp,
        original_type=level['type']
    )
```

**Point 3: Process FLIPs in `_check_signal`:**
```python
elif action == "FLIP_ENTRY":
    signal = {
        'time': timestamp,
        'type': 'FLIP',
        'direction': 'LONG' if level['type'] == 'SUP' else 'SHORT',
        'price': current_price,
        'zone': strategy.get_zone_number(level),
        'size_mod': modifier,
        'message': message
    }

    # ✅ NEW: Order book analysis
    if self.analyze_orderbook and self.ob_analyzer:
        ob_result = self.ob_analyzer.process_flip_signal(signal, timestamp)
        if ob_result:
            signal['orderbook'] = ob_result

            # Optional: Filter by quality
            if ob_result['recommendation'] == 'SKIP':
                logging.info(f"   ⚠️  Low quality FLIP (score: {ob_result['quality_score']:.1f}) - skipping")
                return None  # Skip this signal

    return signal
```

**Point 4: Add to `generate_report`:**
```python
def generate_report(self):
    # ... existing report code ...

    # ✅ NEW: Order book report
    if self.analyze_orderbook and self.ob_analyzer:
        print("\n" + "="*60)
        print("📊 ORDER BOOK FLIP ANALYSIS")
        print("="*60)

        df_ob = self.ob_analyzer.generate_summary_report()

        if not df_ob.empty:
            # Export
            self.ob_analyzer.export_to_csv(
                f'{BACKTEST_OUTPUT}/flip_orderbook_{self.start_date}_to_{self.end_date}.csv'
            )

            # Chart
            self.ob_analyzer.plot_quality_distribution(
                f'{BACKTEST_OUTPUT}/flip_quality_{self.start_date}_to_{self.end_date}.png'
            )
```

### Step 5.2: Run Full Backtest with Order Book

**Create:** `run_backtest_with_orderbook.py`
```python
"""Run backtest with order book analysis enabled"""
from backtest_bot import TradingBotBacktester  # Your modified version
from datetime import datetime, timedelta
import pytz

NY_TZ = pytz.timezone('America/New_York')

# Configure period
end_date = datetime.now(NY_TZ).date() - timedelta(days=1)
start_date = end_date - timedelta(days=7)  # Start with 1 week

# Your Databento API key
DATABENTO_KEY = "your_key_here"

print("="*60)
print("BACKTEST WITH ORDER BOOK ANALYSIS")
print("="*60)
print(f"\nPeriod: {start_date} to {end_date}")
print(f"Order Book Analysis: ENABLED")

# Create backtester
backtester = TradingBotBacktester(
    start_date=start_date,
    end_date=end_date,
    enable_poc_filter=False,
    analyze_orderbook=True,  # 🔥 Enable order book
    databento_api_key=DATABENTO_KEY
)

# Run backtest
print("\n📅 Generating plans...")
backtester.generate_historical_plans()

print("\n🔄 Running backtest...")
backtester.run_backtest()

print("\n📊 Generating reports...")
backtester.generate_report()

print("\n✅ Backtest complete!")
print("\nCheck backtest_results/ for:")
print("  - flip_orderbook_*.csv (detailed metrics)")
print("  - flip_quality_*.png (quality distribution chart)")
```

Run: `python run_backtest_with_orderbook.py`

**Expected Output:**
```
📊 ORDER BOOK FLIP ANALYSIS
============================================================

📈 OVERALL STATISTICS
   Total FLIPs Analyzed: 15
   Average Quality Score: 58.3/100

⭐ QUALITY DISTRIBUTION
   EXCELLENT    :   2 ( 13.3%)
   GOOD         :   6 ( 40.0%)
   FAIR         :   4 ( 26.7%)
   POOR         :   3 ( 20.0%)

💡 RECOMMENDATIONS
   TAKE       :   8 ( 53.3%)
   CONSIDER   :   4 ( 26.7%)
   SKIP       :   3 ( 20.0%)

💰 LIQUIDITY INSIGHTS
   Avg Liquidity Shift: +285 contracts
   Avg Absorption Delta: +142 contracts
```

---

## 📊 Phase 6: Analysis & Optimization (Week 3-4)

### Step 6.1: Analyze Quality vs Performance Correlation

**Create:** `analyze_flip_performance.py`
```python
"""Correlate FLIP quality with actual performance"""
import pandas as pd
import matplotlib.pyplot as plt

# Load backtest results
signals = pd.read_csv('backtest_results/signals_*.csv')
ob_analysis = pd.read_csv('backtest_results/flip_orderbook_*.csv')

# Merge on price and time
flips_with_ob = signals[signals['type']=='FLIP'].merge(
    ob_analysis,
    left_on='price',
    right_on='level_price'
)

# Group by quality rating
perf_by_quality = flips_with_ob.groupby('quality_rating').agg({
    'mfe': 'mean',  # If you track MFE
    'mae': 'mean',  # If you track MAE
    'quality_score': 'mean'
})

print("\n📊 PERFORMANCE BY QUALITY RATING")
print(perf_by_quality)

# Plot correlation
fig, ax = plt.subplots(figsize=(10, 6))
ax.scatter(flips_with_ob['quality_score'], flips_with_ob['mfe'])
ax.set_xlabel('Order Book Quality Score')
ax.set_ylabel('Max Favorable Excursion (points)')
ax.set_title('FLIP Quality vs Performance')
ax.grid(alpha=0.3)
plt.savefig('quality_vs_performance.png', dpi=150)
print("\n✅ Saved quality_vs_performance.png")
```

### Step 6.2: Find Optimal Quality Threshold

**Test different quality thresholds:**
```python
"""Find optimal quality filter threshold"""
import pandas as pd

# Load data
df = pd.read_csv('backtest_results/flip_orderbook_*.csv')

# Test thresholds
thresholds = [30, 40, 50, 60, 70]

print("\n📊 QUALITY THRESHOLD ANALYSIS")
print("="*60)

for threshold in thresholds:
    passing = df[df['quality_score'] >= threshold]
    pct = len(passing) / len(df) * 100

    print(f"\nThreshold: {threshold}")
    print(f"  Signals passing: {len(passing)}/{len(df)} ({pct:.1f}%)")
    print(f"  Avg quality: {passing['quality_score'].mean():.1f}")

    # If you have performance data
    # print(f"  Avg MFE: {passing['mfe'].mean():.2f}")
    # print(f"  Win rate: {passing['win_rate'].mean():.1%}")
```

### Step 6.3: Compare Filtered vs Unfiltered Strategy

**Run two backtests:**
```python
# Backtest 1: All FLIPs (no filter)
signals_all = run_backtest(filter_quality=False)

# Backtest 2: Only GOOD+ FLIPs (filtered)
signals_filtered = run_backtest(filter_quality=True, min_quality=60)

# Compare
print("\n📊 STRATEGY COMPARISON")
print("="*60)
print(f"\nAll FLIPs:")
print(f"  Total signals: {len(signals_all)}")
print(f"  Avg quality: {signals_all['quality_score'].mean():.1f}")

print(f"\nFiltered (60+):")
print(f"  Total signals: {len(signals_filtered)}")
print(f"  Avg quality: {signals_filtered['quality_score'].mean():.1f}")
print(f"  Reduction: {(1 - len(signals_filtered)/len(signals_all))*100:.1f}%")
```

---

## 🚀 Phase 7: Production Deployment (Week 4+)

### Step 7.1: Integrate with Live Bots

**Modify:** `trading_bot_FIXED.py`, `trading_bot_NQ_FIXED.py`, `trading_bot_GC_FIXED.py`

**Add order book analysis to live signal processing:**
```python
# In alert_signal() method
def alert_signal(self, price, signal_type, direction, size_mod, details):
    # ... existing alert code ...

    # Optional: Live order book analysis
    # NOTE: Requires real-time market data subscription
    # For now, you might skip this and rely on backtest validation

    # Log signal
    self.log_signal_to_csv(timestamp, direction, signal_type, price, size_mod, details)
```

### Step 7.2: Configure Quality-Based Sizing

**Use quality scores to adjust position sizes:**
```python
def calculate_position_size(self, signal, base_size=1):
    """
    Adjust position size based on FLIP quality
    """
    if signal['type'] != 'FLIP' or 'orderbook' not in signal:
        return base_size * signal['size_mod']

    quality = signal['orderbook']['quality_score']

    # Scale size by quality
    if quality >= 75:  # EXCELLENT
        quality_mult = 1.5
    elif quality >= 60:  # GOOD
        quality_mult = 1.2
    elif quality >= 45:  # FAIR
        quality_mult = 1.0
    else:  # POOR
        quality_mult = 0.5  # Reduce size or skip

    return base_size * signal['size_mod'] * quality_mult
```

### Step 7.3: Set Up Monitoring

**Create dashboard to track FLIP quality over time:**
```python
"""Monitor FLIP quality trends"""
import pandas as pd
from datetime import datetime, timedelta

# Load recent analyses
df = pd.read_csv('flip_orderbook_*.csv')

# Recent trends
last_week = df[df['fail_time'] > datetime.now() - timedelta(days=7)]

print(f"\n📊 LAST 7 DAYS - FLIP QUALITY TRENDS")
print(f"Average quality: {last_week['quality_score'].mean():.1f}")
print(f"TAKE signals: {(last_week['recommendation']=='TAKE').sum()}")
print(f"SKIP signals: {(last_week['recommendation']=='SKIP').sum()}")

# Alert if quality deteriorating
if last_week['quality_score'].mean() < 50:
    print("\n⚠️  WARNING: FLIP quality declining - review recent levels")
```

---

## 📝 Ongoing Workflow (Daily/Weekly)

### Daily Routine:
1. **Review FLIP signals** from live bots
2. **Check quality scores** in CSV logs
3. **Monitor recommendations** (TAKE vs SKIP ratio)

### Weekly Analysis:
1. **Run backtest** on past week with order book analysis
2. **Review quality distribution**
3. **Analyze performance** by quality rating
4. **Adjust thresholds** if needed

### Monthly Optimization:
1. **Full month backtest** with order book
2. **Correlate quality with P&L**
3. **Tune quality scoring weights**
4. **Update quality thresholds**

---

## 🎯 Success Metrics

Track these KPIs to measure success of order book integration:

1. **Quality Score Accuracy**
   - Do higher quality scores correlate with better performance?
   - Target: +0.6 correlation or higher

2. **Signal Filtering Effectiveness**
   - How much does filtering improve win rate?
   - Target: 10-20% improvement when filtering SKIP signals

3. **Liquidity Validation**
   - Are FLIP levels with better liquidity more reliable?
   - Target: STRONG depth quality = 70%+ success rate

4. **Institutional Positioning**
   - Do large orders predict successful FLIPs?
   - Target: 3+ large orders = 65%+ success rate

---

## ⚠️ Common Issues & Solutions

### Issue 1: Databento API Rate Limits
**Solution:** Implement caching, batch requests, use smaller time windows

### Issue 2: Missing Order Book Data
**Solution:** Handle empty DataFrames gracefully, return UNKNOWN quality

### Issue 3: Quality Scores Too High/Low
**Solution:** Tune thresholds in `_assess_depth_quality()` based on instrument

### Issue 4: Slow Backtest Performance
**Solution:**
- Cache order book data
- Parallelize FLIP analysis
- Reduce proximity window if needed

### Issue 5: Conflicting Signals
**Solution:** Prioritize order book quality over other filters when in doubt

---

## 📚 Additional Resources

- **Databento Documentation:** https://docs.databento.com
- **MBP Schema Reference:** https://docs.databento.com/schemas/mbp
- **Design Document:** `orderbook_analysis_design.md`
- **Integration Examples:** `backtest_with_orderbook_example.py`

---

## ✅ Completion Checklist

Phase 1: Setup
- [ ] Databento account created
- [ ] API key obtained
- [ ] Python dependencies installed
- [ ] Sample FLIP events identified

Phase 2: Data Fetching
- [ ] `_fetch_orderbook_snapshot()` implemented
- [ ] Data fetching tested successfully
- [ ] MBP schema understood

Phase 3: Calculations
- [ ] All calculation methods implemented
- [ ] Quality assessment logic complete
- [ ] Unit tests passing

Phase 4: Pilot Testing
- [ ] Single FLIP test successful
- [ ] 5-10 FLIPs analyzed
- [ ] Quality scores validated
- [ ] Weights tuned (if needed)

Phase 5: Integration
- [ ] Integration points added to backtest
- [ ] Full backtest with OB runs successfully
- [ ] Reports generated correctly

Phase 6: Analysis
- [ ] Quality-performance correlation analyzed
- [ ] Optimal threshold identified
- [ ] Filtered vs unfiltered compared

Phase 7: Production
- [ ] Live bot integration (optional)
- [ ] Monitoring dashboard set up
- [ ] Documentation complete

---

**Estimated Timeline:** 3-4 weeks from start to production-ready
**Estimated Cost:** $50-200 for Databento data (depending on period length)
**Expected Outcome:** 10-20% improvement in FLIP signal quality through filtering
