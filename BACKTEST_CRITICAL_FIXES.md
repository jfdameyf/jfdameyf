# Backtest Critical Fixes - Signal Spam & Missing Zones

## 🚨 Problems Identified

### Results Before Fixes:
```
Total Signals: 9,261
Avg Signals/Day: 140.3
Signal Breakdown:
  - Responsive: 9,261 (100%)
  - Recapture: 0 (0%)
  - FLIP: 0 (0%)

Zone Distribution:
  - Zone 1: 4,994 (54%)
  - Zone 2: 4,267 (46%)
  - Zone 3: 0 (0%)  ← RED FLAG
  - Zone 4: 0 (0%)  ← RED FLAG

Worst Day: Oct 24 with 371 signals
```

### Root Causes:

**1. No Zone 3/4 Levels**
- Zones assigned by distance bins from current price
- If CSV levels only within ~12pts, all fall into Zone 1/2
- Zone 3/4 use recapture logic, Zone 1/2 use responsive
- Result: Recapture logic never runs, no recapture/FLIP signals

**2. Signal Spam (No Cross-Bar Deduplication)**
- Deduplication only prevents duplicates within single bar
- Resets every bar, so same level fires 100+ times
- Price hovering near level = signal every minute
- Result: 140+ signals/day instead of 5-20

**3. Proximity Threshold Too Loose**
- Zone 2 allows 4.0 pts proximity
- Price 4pts away is not "touching" level
- Should be tighter (1.0-1.5pts for Zone 2)
- Result: Premature signals far from actual level

---

## ✅ Fix 1: Ensure Zone 3/4 Levels Exist

### Problem:
```python
# Current: Creates bins based on predicted_range
bins = np.linspace(0, total_reach, num=5)
# If range=20, total_reach=24: bins=[0, 6, 12, 18, 24]
# Levels only within 12pts → Only Zone 1/2 populated
```

### Solution A: Use Fixed Distance Bins (Recommended)
```python
# Use absolute distance bins instead of range-based
def get_levels_hybrid(df, direction_label):
    if df.empty: return []

    # Fixed bins for ES (adjust for NQ/GC)
    # Zone 1: 0-5pts, Zone 2: 5-10pts, Zone 3: 10-20pts, Zone 4: 20+pts
    bins = [0, 5, 10, 20, 1000]  # Fixed bins ensure all zones can be populated
    labels = ['Zone 1', 'Zone 2', 'Zone 3', 'Zone 4']

    df['zone'] = pd.cut(df['dist'], bins=bins, labels=labels, include_lowest=True)

    # Rest of selection logic...
```

**Pros:**
- Guarantees Zone 3/4 exist if levels are farther out
- Consistent zone assignments across different days
- Levels at 15pts always Zone 3, not "depends on range"

**Cons:**
- Need instrument-specific bins (ES vs NQ vs GC)

### Solution B: Increase total_reach to Ensure Farther Levels
```python
# Increase buffer to pull in farther levels
BUFFER_PCT = 0.5  # 50% instead of 20%
total_reach = predicted_range * (1 + BUFFER_PCT)

# OR use minimum reach
MIN_REACH = 30.0  # Always look at least 30pts out
total_reach = max(predicted_range * (1 + BUFFER_PCT), MIN_REACH)
```

**Pros:**
- Simple change
- Pulls in levels farther from current price

**Cons:**
- Doesn't guarantee Zone 3/4 if CSV lacks far levels
- Still depends on range-based binning

### Solution C: Hybrid Approach (Best)
```python
# Use fixed bins but ensure we fetch enough levels
MIN_REACH = 30.0
total_reach = max(predicted_range * (1 + BUFFER_PCT), MIN_REACH)

# Fixed distance bins
bins = [0, 5, 10, 20, total_reach]
```

---

## ✅ Fix 2: Add Session-Wide Signal Deduplication

### Problem:
```python
# Current: Only prevents duplicates within same bar
fired_this_bar = set()  # Resets every bar!
```

### Solution: Add Session-Wide Tracking with Cooldown
```python
class BacktestEngine:
    def __init__(self, ...):
        # ...
        self.fired_signals_session = {}  # {signal_key: timestamp}
        self.SIGNAL_COOLDOWN_MINUTES = 15  # Don't repeat signal for 15 min

    def _evaluate_bar(self, plan, strategy, current_price, timestamp):
        signals = []
        scan_range = 20.0

        # Still track per-bar to prevent multiple signals at same level same bar
        fired_this_bar = set()

        for level in plan.get('levels', {}).get('raw_sup', []):
            if abs(current_price - level['price']) <= scan_range:
                level['type'] = 'SUP'

                strategy.detect_level_recapture(...)
                signal = self._check_signal(...)

                if signal:
                    signal_key = f"{signal['price']:.2f}_{signal['type']}_{signal['direction']}"

                    # Check per-bar dedup
                    if signal_key in fired_this_bar:
                        continue

                    # ✅ NEW: Check session-wide dedup with cooldown
                    if signal_key in self.fired_signals_session:
                        last_fired = self.fired_signals_session[signal_key]
                        time_since = (timestamp - last_fired).total_seconds() / 60

                        if time_since < self.SIGNAL_COOLDOWN_MINUTES:
                            continue  # Skip - too soon since last signal

                    # Signal passed all checks
                    signals.append(signal)
                    fired_this_bar.add(signal_key)
                    self.fired_signals_session[signal_key] = timestamp  # Update last fired

        # ... same for resistance levels
        return signals
```

**Benefits:**
- Same level can't fire multiple signals within 15 minutes
- Prevents spam from price hovering
- Still allows re-entry if price leaves and returns later

**Tuning:**
- 15 min cooldown: Moderate (prevents spam but allows re-entry)
- 30 min cooldown: Conservative (very few repeat signals)
- 5 min cooldown: Aggressive (more signals, less filtering)

---

## ✅ Fix 3: Tighten Proximity Thresholds

### Problem:
```python
proximity_threshold = 2.0 if zone == 1 else 4.0
```

Zone 2 with 4.0 pts is way too loose.

### Solution: Tighter Thresholds
```python
if zone in [1, 2]:
    # Tighten proximity thresholds
    proximity_threshold = 1.0 if zone == 1 else 1.5  # Much tighter

    if distance <= proximity_threshold:
        return "IMMEDIATE_ENTRY", ...
```

**Recommended Thresholds:**

| Zone | Old | New | Reasoning |
|------|-----|-----|-----------|
| Zone 1 | 2.0 | 1.0 | Closest levels, should be near-exact touch |
| Zone 2 | 4.0 | 1.5 | Still close, but slightly more room |

For ES at 0.25 tick:
- 1.0 pt = 4 ticks = very tight
- 1.5 pts = 6 ticks = reasonable proximity
- 4.0 pts = 16 ticks = way too loose

---

## ✅ Fix 4: Add Signal Rate Limiter (Optional)

**Problem:** Even with fixes, high volatility days might generate 50+ signals.

**Solution:** Max signals per day limit
```python
class BacktestEngine:
    def __init__(self, ...):
        self.MAX_SIGNALS_PER_DAY = 30  # Safety limit
        self.signals_today_count = 0
        self.current_backtest_date = None

    def _evaluate_bar(self, plan, strategy, current_price, timestamp):
        # Check if new day
        bar_date = timestamp.date()
        if bar_date != self.current_backtest_date:
            self.current_backtest_date = bar_date
            self.signals_today_count = 0
            self.fired_signals_session.clear()  # Clear session tracking on new day

        # Check rate limit
        if self.signals_today_count >= self.MAX_SIGNALS_PER_DAY:
            logging.debug(f"Hit max signals for day: {self.MAX_SIGNALS_PER_DAY}")
            return []

        signals = []
        # ... evaluate signals as normal

        # Increment count
        self.signals_today_count += len(signals)
        return signals
```

**Benefits:**
- Prevents extreme outlier days (371 signals → capped at 30)
- Forces quality over quantity
- Realistic for actual trading (can't take 100 trades/day)

---

## 📊 Expected Results After Fixes

### Before:
```
Total Signals: 9,261
Avg/Day: 140.3
Responsive: 100%
Recapture: 0%
FLIP: 0%
Zones: 54% Zone1, 46% Zone2, 0% Zone3/4
```

### After (Estimated):
```
Total Signals: ~800-1200
Avg/Day: 12-18
Responsive: 70-80%
Recapture: 15-25%
FLIP: 5-10%
Zones: 40% Zone1, 35% Zone2, 20% Zone3, 5% Zone4
```

**Improvements:**
- ✅ 10-15x fewer signals (realistic)
- ✅ Recapture signals appear
- ✅ FLIP signals appear
- ✅ All zones populated
- ✅ Quality over quantity

---

## 🔧 Implementation Priority

### Critical (Must Fix):
1. ✅ **Fix 1**: Ensure Zone 3/4 exist (fixed bins)
2. ✅ **Fix 2**: Add session-wide deduplication (cooldown)
3. ✅ **Fix 3**: Tighten proximity thresholds

### Optional (Nice to Have):
4. ⭐ **Fix 4**: Add daily signal rate limiter

---

## 🎯 Implementation Steps

1. Update `get_levels_hybrid()` in trading_bot_FIXED.py:
   - Use fixed bins: [0, 5, 10, 20, 1000]
   - Or minimum reach: max(range*1.5, 30)

2. Update `BacktestEngine.__init__()`:
   - Add `self.fired_signals_session = {}`
   - Add `self.SIGNAL_COOLDOWN_MINUTES = 15`

3. Update `BacktestEngine._evaluate_bar()`:
   - Check session-wide dedup before appending signal
   - Track last fired time per signal key

4. Update proximity thresholds in trading_bot_FIXED.py:
   - Zone 1: 1.0 pts
   - Zone 2: 1.5 pts

5. Optional: Add daily rate limiter
   - Track signals_today_count
   - Reset on new day
   - Cap at 30 signals/day

---

## 🧪 Testing After Fixes

Run backtest and check:

**Zone Distribution:**
```
Zone 1: 30-40%
Zone 2: 30-40%
Zone 3: 15-25%  ← Should now exist!
Zone 4: 5-10%   ← Should now exist!
```

**Signal Breakdown:**
```
Responsive: 70-80% (Zone 1/2)
Recapture: 15-25% (Zone 3/4)  ← Should now exist!
FLIP: 5-10% (Zone 3/4, after level fails)  ← Should now exist!
```

**Signal Rate:**
```
Avg Signals/Day: 10-20 (not 140!)
Max Day: < 40 signals (not 371!)
```

---

## 📝 Summary

**Root Causes:**
1. Only Zone 1/2 levels → No recapture logic
2. No cross-bar deduplication → Signal spam
3. Loose proximity (4pts) → Premature triggers

**Fixes:**
1. Use fixed distance bins for zones
2. Add 15-min cooldown between same signals
3. Tighten proximity to 1.0-1.5 pts
4. Optional: Cap at 30 signals/day

**Expected Outcome:**
- 90% fewer signals
- Recapture/FLIP signals appear
- All zones populated
- Realistic trading volume

Ready to implement? 🚀
