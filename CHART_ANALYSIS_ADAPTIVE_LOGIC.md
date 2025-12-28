# Chart Analysis & Adaptive Time Window Logic

## 📊 Analysis of Your Charts

### Chart 1: Uptrend with Pullbacks

**Pattern Flow (Reading left to right):**

```
Circle Locations & Likely Patterns:

1. Bottom Left (~6,928) - REVERSAL (BOTTOM)
   - V-shape low
   - Start of uptrend
   - High volume spike visible

2. First Pullback (~6,935) - PULLBACK CONTINUATION
   - Uptrend established
   - Small red pullback
   - Continues higher

3. Mid-trend Pullback (~6,945) - PULLBACK CONTINUATION
   - Trend still strong (blue line)
   - Another healthy retracement
   - Resumes uptrend

4. Near Top (~6,955) - PULLBACK CONTINUATION or FALSE REVERSAL
   - Testing resistance (red line ~6,960)
   - Pulls back slightly
   - Final push higher

5. Top Resistance Test (~6,960-6,963) - CONSOLIDATION → REVERSAL (TOP)?
   - Multiple tests of resistance (red line)
   - Choppy consolidation (square area implied)
   - Yellow lines mark range
   - Eventually rejects?

6. Final High (~6,963) - REVERSAL (TOP)
   - Failed to break yellow resistance
   - Volume declining
   - Likely reversal point
```

**Key Observations:**
- **Clean uptrend** with multiple pullback continuation opportunities
- Pullbacks are **spaced reasonably** (probably 10-20 min apart)
- **Top area clusters** - multiple patterns within 5-10 minutes
  - Consolidation at 6,960
  - False breakout attempt at 6,963
  - Final reversal

---

### Chart 2: Range-Bound / Consolidation Day

**Pattern Flow:**

```
Circle Locations & Likely Patterns:

1. Bottom Left (~6,920) - REVERSAL (BOTTOM) or V-SHAPE
   - Sharp spike down
   - Quick recovery
   - High volume

2-3. Early Bounces (~6,922-6,924) - CONSOLIDATION
   - Multiple circles close together
   - Blue square marks consolidation zone
   - Choppy, no clear direction
   - **CLUSTERING ISSUE!** 3-4 circles within 10 minutes

4. Mid-range (~6,928) - FALSE REVERSAL
   - Breaks above consolidation
   - Fails to hold
   - Back into range

5-6. Top Tests (~6,933-6,936) - CONSOLIDATION / REVERSAL (TOP)
   - Multiple tests of resistance
   - Blue square marks consolidation
   - **CLUSTERING!** Several circles within 5-10 min

7. Large Circle (~6,930) - PULLBACK CONTINUATION
   - After failed top, sells off
   - Bounces at support
   - Continues back up

8. Late Resistance Test (~6,933) - FALSE REVERSAL
   - Another test of resistance
   - Fails again
   - Back down

9. Final Low (~6,921) - REVERSAL (BOTTOM)
   - Tests support again
   - Holds
   - Slight bounce into close
```

**Key Observations:**
- **Heavy clustering** in consolidation zones
- Multiple patterns within 5-minute windows
- **Low volume = tight clustering** (your point exactly!)
- Traditional ±10 min windows would overlap heavily

---

## 🚨 The Clustering Problem You Identified

### Example from Chart 2:

```
Timeline (approximated):
10:45 - False reversal at 6,933 (circle)
10:48 - Pullback continuation at 6,930 (circle, 3 min later!)
10:52 - Another test at 6,932 (circle, 4 min later!)

Using ±10 min windows:
10:45 analysis: 10:35-10:55 window
10:48 analysis: 10:38-10:58 window  ← 80% overlap!
10:52 analysis: 10:42-11:02 window  ← 80% overlap!

Post-event windows heavily overlap:
- Post-event of 10:45 includes events of 10:48 and 10:52
- Features will be highly correlated
- Model gets confusing training data
```

**Current Script Behavior:**
```python
# Fixed ±10 min window
ts_start = center_ts - timedelta(minutes=10)
ts_end = center_ts + timedelta(minutes=10)

# Problem: Doesn't adapt to market conditions!
```

---

## 💡 Proposed Solutions

### Solution 1: Adaptive Time Windows Based on Volatility (RECOMMENDED)

**Concept:** Adjust window size based on recent price movement.

```python
def calculate_adaptive_window(df, center_time, base_window_minutes=10):
    """
    Calculate adaptive time window based on recent volatility.

    Low volatility (consolidation) → Smaller windows
    High volatility (trending) → Larger windows
    """
    # Look at last 30 minutes before center_time
    lookback_start = center_time - timedelta(minutes=30)
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

    # Adaptive logic:
    # Low volatility (<1 pt/min) → Use smaller window (5 min)
    # Normal volatility (1-3 pts/min) → Use standard window (10 min)
    # High volatility (>3 pts/min) → Use larger window (15 min)

    if avg_range_per_min < 1.0:
        return 5  # Consolidation - use smaller window
    elif avg_range_per_min < 3.0:
        return 10  # Normal - standard window
    else:
        return 15  # Volatile - larger window
```

**Benefits:**
- **Consolidation days** (Chart 2): Auto-switches to 5-min windows
- **Trending days** (Chart 1): Uses 10-min windows
- **Reduces overlap** in choppy markets
- **Adapts automatically** to market conditions

**Usage:**
```python
# In parse_and_process_inputs():
window_size = calculate_adaptive_window(df, center_ts)
ts_start = center_ts - timedelta(minutes=window_size)
ts_end = center_ts + timedelta(minutes=window_size)
```

---

### Solution 2: Level-Based Analysis Instead of Time-Based

**Concept:** Analyze price LEVELS rather than TIME windows.

```python
def analyze_by_level(df, target_price, range_tolerance=2.0):
    """
    Analyze price action around a specific LEVEL instead of time.

    Args:
        df: Full day's data
        target_price: Price level of interest (e.g., 6,933)
        range_tolerance: +/- points around level (default 2.0)

    Returns:
        event_df: All data within the price range
        pre_df: Data before first touch of level
        post_df: Data after last touch of level
    """
    # Find all data within the price range
    in_range = df[
        (df['price'] >= target_price - range_tolerance) &
        (df['price'] <= target_price + range_tolerance)
    ]

    if in_range.empty:
        return None, None, None

    # First and last time price was in this range
    first_touch = in_range.index[0]
    last_touch = in_range.index[-1]

    # Pre-event: 15 min before first touch
    pre_start = first_touch - timedelta(minutes=15)
    pre_df = df[(df.index >= pre_start) & (df.index < first_touch)]

    # Event: All time spent in this price range
    event_df = in_range

    # Post-event: All data after last touch
    post_df = df[df.index > last_touch]

    return event_df, pre_df, post_df
```

**Benefits for Your Charts:**
- **Chart 1:** Analyzes 6,960-6,963 resistance zone as ONE pattern
- **Chart 2:** Analyzes 6,930-6,933 consolidation as ONE pattern
- **No artificial time windows** - follows actual price action
- **Natural deduplication** - same level = same analysis

**Usage:**
```bash
# Instead of time
Times > 11:30

# Use price levels
Levels > 6933, 6960, 6921
```

---

### Solution 3: Minimum Separation Enforcement (Simple)

**Concept:** Don't allow analysis of times too close together.

```python
def enforce_minimum_separation(analyzed_times, new_time, min_separation_minutes=15):
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
            print(f"       Minimum separation: {min_separation_minutes} min, actual: {time_diff:.1f} min")
            return False
    return True
```

**Usage:**
```python
# In main loop
analyzed_times = []

for item in items:
    # ... parse time ...

    if not enforce_minimum_separation(analyzed_times, center_ts, min_separation_minutes=15):
        print(f"[SKIP] {item} - too close to previous analysis")
        continue

    # ... proceed with analysis ...
    analyzed_times.append(center_ts)
```

**Benefits:**
- **Simple to implement**
- **Prevents overlapping windows**
- **User gets immediate feedback** ("too close, try 11:35 instead")

**Drawback:**
- Might miss legitimate patterns if they cluster naturally

---

### Solution 4: Hierarchical Analysis (Best for Your Use Case)

**Concept:** Analyze at multiple timeframes, mark relationships.

```python
def hierarchical_analysis(times_list, df, tz):
    """
    Identify which patterns are nested within others.

    Returns:
        patterns: List of pattern dicts with hierarchy info
    """
    patterns = []

    for time_str in times_list:
        # ... parse and analyze as normal ...

        pattern = {
            'time': time_str,
            'label': label,
            'features': features,
            'range': (ts_start, ts_end),
            'children': [],  # Patterns within this one
            'parent': None   # Larger pattern containing this
        }

        # Check if this pattern contains or is contained by others
        for existing in patterns:
            # This pattern contains existing?
            if (pattern['range'][0] <= existing['range'][0] and
                pattern['range'][1] >= existing['range'][1]):
                pattern['children'].append(existing['time'])
                existing['parent'] = pattern['time']

            # This pattern contained by existing?
            elif (existing['range'][0] <= pattern['range'][0] and
                  existing['range'][1] >= pattern['range'][1]):
                existing['children'].append(pattern['time'])
                pattern['parent'] = existing['time']

        patterns.append(pattern)

    return patterns
```

**Example Output:**
```
CONSOLIDATION (11:00-11:45) [PARENT]
  ├─ FALSE REVERSAL (11:05) [CHILD]
  ├─ PULLBACK CONTINUATION (11:08) [CHILD]
  └─ FALSE REVERSAL (11:30) [CHILD]

[ML] Saving with hierarchy tags:
  - CONSOLIDATION (macro, parent=None)
  - FALSE REVERSAL (micro, parent=11:00-11:45)
  - PULLBACK CONTINUATION (micro, parent=11:00-11:45)
```

**Benefits:**
- **Preserves all patterns** (doesn't skip any)
- **Model learns context** ("false reversals often happen in consolidations")
- **Prevents confusion** (knows they're related, not independent)

**Training Data:**
```csv
time,label,duration,velocity,parent_pattern
11:00-11:45,CONSOLIDATION,45,0.5,None
11:05,FALSE REVERSAL,5,-8.2,CONSOLIDATION
11:08,PULLBACK CONTINUATION,3,5.1,CONSOLIDATION
```

---

## 🎯 My Recommendation for Your Charts

### For Chart 1 (Clean Trend):
**Use:** Solution 1 (Adaptive Windows) or current default (±10 min)
- Patterns are well-spaced
- No clustering issues
- Standard approach works fine

### For Chart 2 (Consolidation Day):
**Use:** Combination of Solutions 1 + 4
1. **Adaptive windows** (auto-reduces to 5 min in consolidation)
2. **Hierarchical analysis** for clustered patterns

**Example Workflow for Chart 2:**
```bash
# First, identify the macro structure
Times > 10:30-11:00  # Consolidation zone
Label: CONSOLIDATION

# Then, analyze micro patterns within it
Times > 10:45  # False reversal (adaptive window = 5 min)
Label: FALSE REVERSAL (within consolidation)

Times > 10:48  # Pullback (adaptive window = 5 min)
Label: PULLBACK CONTINUATION (within consolidation)
```

---

## 📊 Specific Pattern Analysis for Your Charts

### Chart 1 Recommendations:

```bash
# Space these out (they're probably 15-20 min apart anyway)
Times > 09:30, 09:50, 10:15, 10:40, 11:00

Labels:
09:30 → REVERSAL (BOTTOM) (V-shape low)
09:50 → PULLBACK CONTINUATION (first pullback)
10:15 → PULLBACK CONTINUATION (mid-trend)
10:40 → PULLBACK CONTINUATION (near top)
11:00-11:15 → CONSOLIDATION (top resistance)
11:15 → REVERSAL (TOP) (final rejection)
```

### Chart 2 Recommendations:

```bash
# Use explicit ranges for consolidations
Times > 09:30-10:00, 10:30-11:00

# Use adaptive windows for micro moves
Times > 09:25, 10:45, 11:15, 11:45

Labels:
09:30-10:00 → CONSOLIDATION (bottom range)
09:25 → REVERSAL (BOTTOM) or V-SHAPE (spike low)
10:30-11:00 → CONSOLIDATION (mid-range chop)
10:45 → FALSE REVERSAL (within consolidation)
11:15 → FALSE REVERSAL (top test failure)
11:45 → REVERSAL (BOTTOM) (final support hold)
```

---

## 🔧 Implementation Priority

### Phase 1: Quick Fix (This Week)
1. ✅ Add PULLBACK CONTINUATION as 8th pattern
2. ✅ Add minimum separation warning (Solution 3)
3. ✅ Use explicit ranges for consolidations

### Phase 2: Adaptive Logic (Next Week)
1. Implement adaptive time windows (Solution 1)
2. Add volatility detection
3. Auto-adjust window sizes

### Phase 3: Advanced (Optional)
1. Level-based analysis (Solution 2)
2. Hierarchical pattern tracking (Solution 4)
3. Visual pattern overlay on charts

---

## ✅ Immediate Action Items

**For you right now:**
1. **Space out your analyses** on consolidation days
   - Minimum 15 minutes apart for micro patterns
   - Use explicit ranges for macro structures

2. **Mark hierarchy in notes:**
   ```
   10:30-11:00 CONSOLIDATION (parent)
     ├─ 10:45 FALSE REVERSAL (child)
     └─ 10:48 PULLBACK CONTINUATION (child)
   ```

3. **Use this decision tree:**
   ```
   Is this a consolidation day (range <10 pts, choppy)?
     YES → Analyze 1-2 macro ranges + 3-4 key reversals
     NO → Analyze individual pullbacks/continuations
   ```

**For me to implement:**
1. Create script with PULLBACK CONTINUATION
2. Add adaptive time windows
3. Add minimum separation check

---

## 📝 Summary

**Your Charts Show:**
- **Chart 1:** Clean trend, well-spaced patterns ✅
- **Chart 2:** Consolidation, clustered patterns ⚠️

**The Clustering Issue:**
- Real and needs addressing
- Worse on low-volume/consolidation days
- Current ±10 min fixed windows don't adapt

**Best Solution:**
- **Short term:** Manual spacing + explicit ranges
- **Long term:** Adaptive windows + hierarchical tracking

**Would you like me to:**
1. Create the enhanced script with PULLBACK CONTINUATION + adaptive windows?
2. Or start with just adding PULLBACK CONTINUATION first and add adaptive logic later?

Let me know and I'll implement it!
