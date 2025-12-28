# Pattern Definitions & Overlapping Time Windows

## 🚨 PART 1: Overlapping Time Windows Issue

### Your Concern: Does Overlap Skew Results?

**SHORT ANSWER: Yes, it can - but it's also realistic market behavior.**

---

### Example of the Problem

```
Timeline:
10:50 ────────────────────────────────────────────────────> 11:50
     │         │    │    │         │                │
     │         │    │    │         │                │
     │    Pre  │Event│Post│         │                │
     │   (15m) │(20m)│    │         │                │
     └─────────┴─────┴────┘         │                │
          Analysis #1: 11:00         │                │
          "FALSE REVERSAL"           │                │
                                     │                │
                 │         │    │    │    │           │
                 │    Pre  │Event│Post│               │
                 │   (15m) │(20m)│    │               │
                 └─────────┴─────┴────┘               │
                      Analysis #2: 11:05              │
                      "CONTINUATION"                  │
                                                      │
     │                              │                 │
     │                         Pre  │     Event       │  Post
     │                        (15m) │     (45m)       │
     └──────────────────────────────┴─────────────────┴───────
                      Analysis #3: 11:00-11:45
                      "CONSOLIDATION"
```

### The Issues:

**Issue 1: Post-Event of #1 Contains Event of #2**
- Analysis #1 (11:00): Post-event window extends to ~11:20
- Analysis #2 (11:05): Event window is 10:55-11:15
- **Problem:** The "post_df" of #1 includes the "event_df" of #2
- **Result:** Feature "broken_high" in #1 might be detecting the price action from #2

**Issue 2: Nested Timeframes**
- Small pattern (5-min continuation at 11:05)
- Medium pattern (20-min false reversal at 11:00)
- Large pattern (45-min consolidation 11:00-11:45)
- **All occurring in the same price action!**

**Issue 3: Contradictory Labels**
```
Example:
11:00-11:20 labeled as "FALSE REVERSAL" (because high broken at 11:15)
11:15-11:35 labeled as "CONTINUATION" (the actual breakout)

But they're describing THE SAME PRICE MOVE from different perspectives!
```

---

### Does This Skew the Model? YES and NO

#### ❌ **BAD SKEW (Confusing the Model)**

**Scenario: Contradictory Training Data**
```
Training Example #1:
Time: 11:00-11:20
Features: trend=1, color=-1, broken_high=1
Label: "FALSE REVERSAL"

Training Example #2:
Time: 11:00-11:20 (same exact period!)
Features: trend=1, color=-1, broken_high=1 (identical!)
Label: "REVERSAL (TOP)" (different label!)

Model sees: "Same features, different labels = ??? I'm confused"
Result: Lower accuracy, random predictions
```

**This happens when:**
- You analyze the same time window twice with different labels
- You're inconsistent about what constitutes a "reversal" vs "false reversal"

#### ✅ **GOOD OVERLAP (Realistic Multi-Timeframe Analysis)**

**Scenario: Different Timeframes, Different Perspectives**
```
Training Example #1:
Time: 11:00 (±10min window = 10:50-11:10)
Features: trend=1, color=-1, duration=5min, velocity=-15 pts/min
Label: "REVERSAL (TOP)" (5-minute timeframe)
Context: Sharp rejection at resistance

Training Example #2:
Time: 11:00-11:45 (explicit 45-minute window)
Features: trend=0, color=1, duration=45min, range=3pts, velocity=-0.5 pts/min
Label: "CONSOLIDATION" (45-minute timeframe)
Context: Larger consolidation containing the reversal

Model learns: "Short, sharp moves with high velocity = reversals"
              "Long, low-range periods with low velocity = consolidation"
Result: Model learns multi-timeframe context (GOOD!)
```

**This is realistic because:**
- Real trading happens on multiple timeframes simultaneously
- A 5-min chart reversal can occur within a 1-hour chart consolidation
- The features (velocity, duration, range) will be different enough for the model to distinguish

---

### Solutions & Best Practices

#### ✅ **Solution 1: Consistent Timeframe Definitions**

**Define your analysis windows clearly:**

```
MICRO PATTERNS (±5 min window):
- Use for: Quick reversals, V-shapes
- Example: 11:00 → analyzes 10:55-11:05

STANDARD PATTERNS (±10 min window - DEFAULT):
- Use for: Most patterns
- Example: 11:00 → analyzes 10:50-11:10

MACRO PATTERNS (explicit range):
- Use for: Consolidations, larger moves
- Example: 11:00-12:00 → analyzes exactly that period
```

**In practice:**
```bash
# Micro (5-min)
Times > 11:00  # Use default ±10min

# Macro (explicit)
Times > 11:00-11:45  # Larger consolidation
```

#### ✅ **Solution 2: Hierarchical Labeling (Recommended)**

**Think of patterns as nested:**

```
11:00-11:45: CONSOLIDATION (parent pattern)
  ├─ 11:00-11:05: REVERSAL (TOP) (child - failed breakout attempt)
  ├─ 11:15-11:20: CONTINUATION (child - another probe)
  └─ 11:40-11:45: REVERSAL (BOTTOM) (child - final support test)
```

**Rule:**
- **Small timeframes (<15 min):** Analyze individual moves
- **Large timeframes (>30 min):** Analyze overall structure

**Training data should reflect this:**
```csv
# Micro moves
11:00, trend=1, color=-1, duration=5, velocity=-15, label="REVERSAL (TOP)"
11:05, trend=-1, color=1, duration=5, velocity=8, label="REVERSAL (BOTTOM)"

# Macro structure
11:00-11:45, trend=0, color=1, duration=45, velocity=-0.5, label="CONSOLIDATION"
```

The model will learn:
- Short duration + high velocity = specific reversal
- Long duration + low velocity + small range = consolidation

#### ✅ **Solution 3: Avoid Duplicate Time Windows**

**DON'T do this:**
```bash
Times > 11:00
[Analyze, label as "FALSE REVERSAL"]

# Later same session...
Times > 11:00
[Analyze again, label as "REVERSAL (TOP)"]

# ❌ Same time window, different label = BAD
```

**DO this:**
```bash
Times > 11:00
[Analyze, label as "FALSE REVERSAL"]

# Later, if you need to correct:
# 1. Delete the CSV row manually, OR
# 2. Use a different time (11:00-11:20 vs just 11:00)
```

#### ✅ **Solution 4: Feature Differentiation Will Help**

**Even with overlapping windows, features differ:**

```python
# 11:00 (5-min reversal)
{
    'duration_mins': 5.0,
    'price_velocity': -15.2,  # Fast drop
    'upper_volume_pct': 0.85,  # Volume at top
    'broken_high': 1
}
Label: "FALSE REVERSAL"

# 11:00-11:45 (consolidation containing the reversal)
{
    'duration_mins': 45.0,  # Much longer
    'price_velocity': -0.8,  # Slow drift
    'upper_volume_pct': 0.52,  # Balanced
    'broken_high': 0  # Range held
}
Label: "CONSOLIDATION"
```

**Model sees these as completely different patterns!**

---

### When Overlap is GOOD vs BAD

| Scenario | Good or Bad? | Why |
|----------|--------------|-----|
| Same time window, same features, different labels | ❌ **BAD** | Confuses model |
| Overlapping windows, different durations, different features | ✅ **GOOD** | Multi-timeframe learning |
| Post-event of #1 contains event of #2 | ⚠️ **NEUTRAL** | Realistic but be aware |
| Analyzing 11:00, 11:05, 11:10 separately (micro-scalping) | ❌ **BAD** | Too granular, high correlation |
| Analyzing 11:00 (5min), 11:00-12:00 (1hr), different labels | ✅ **GOOD** | Different timeframe perspectives |

---

### Recommended Data Collection Strategy

**1. Choose Primary Timeframe**
```
For day trading: ±10 min windows (default)
For swing trading: ±30 min windows
For scalping: ±5 min windows
```

**2. Separate Micro vs Macro**
```bash
# Micro analysis (specific moves)
Times > 09:30, 09:45, 10:15

# Macro analysis (larger structures)
Times > 09:30-10:30, 11:00-12:00
```

**3. Wait Between Overlapping Times**
```bash
# Good spacing (minimal overlap)
Times > 09:30, 10:00, 10:30, 11:00

# Bad spacing (high overlap)
Times > 09:30, 09:32, 09:35, 09:38  # Too close!
```

**4. Be Consistent With Labels**
Keep notes:
```
11:00 FALSE REVERSAL - rallied to 5010, broke through to 5012 at 11:15
11:15 CONTINUATION - breakout confirmed, held above 5010
11:00-11:45 CONSOLIDATION - overall range 5000-5012, choppy
```

---

## 📖 PART 2: Explicit Pattern Definitions

### Pattern #1: REVERSAL (TOP)

**Definition:**
An uptrend into a red candle that DOES NOT get broken later (high holds).

**Market Context:**
- Price has been rising (uptrend)
- Buyers push to new high
- Sellers step in aggressively
- Price reverses down
- The high is NOT exceeded afterward (if it were, it would be FALSE REVERSAL)

**Visual:**
```
Price
 ↑
5010 ─────●  ← High (holds - not broken later)
          │╲
          │ ╲
5005      │  ╲  ← Red candle forms
          │   ●
          │
5000 ─────●  ← Start of move (uptrend)
       ───────────> Time
       Pre  Event Post
```

**Script Identification:**
```python
if trend == 1 and color == -1 and broken_high == 0:
    return "REVERSAL (TOP)"
```

**Features:**
- `trend`: 1 (uptrend going in)
- `color`: -1 (red candle)
- `broken_high`: 0 (high NOT broken later)
- `upper_volume_pct`: Usually high (0.7+) - volume at resistance
- `price_velocity`: Negative (turning down)

**Trading Implication:**
- ✅ **Short entry** at the high
- ✅ **Stop loss** just above the high
- ✅ **Target** below at support
- **Confidence:** High if volume profile shows 70%+ at top

**Example:**
```
Time: 09:30
Pre: 5000 → 5010 (uptrend)
Event: 5010 → 5005 (red candle)
Post: Stays below 5010 (high holds)
Label: REVERSAL (TOP) ✓
```

---

### Pattern #2: REVERSAL (BOTTOM)

**Definition:**
A downtrend into a green candle that DOES NOT get broken later (low holds).

**Market Context:**
- Price has been falling (downtrend)
- Sellers push to new low
- Buyers step in aggressively
- Price reverses up
- The low is NOT broken afterward (if it were, it would be FALSE REVERSAL)

**Visual:**
```
Price
 ↑
5010 ─────●  ← End (uptrend begins)
          │
          │╱
5005      │╱  ← Green candle forms
          ●╱
          │
5000 ─────●  ← Low (holds - not broken later)
       ───────────> Time
       Pre  Event Post
```

**Script Identification:**
```python
if trend == -1 and color == 1 and broken_low == 0:
    return "REVERSAL (BOTTOM)"
```

**Features:**
- `trend`: -1 (downtrend going in)
- `color`: 1 (green candle)
- `broken_low`: 0 (low NOT broken later)
- `lower_volume_pct`: Usually high (0.7+) - volume at support
- `price_velocity`: Positive (turning up)

**Trading Implication:**
- ✅ **Long entry** at the low
- ✅ **Stop loss** just below the low
- ✅ **Target** above at resistance
- **Confidence:** High if volume profile shows 70%+ at bottom

**Example:**
```
Time: 14:15
Pre: 5010 → 5000 (downtrend)
Event: 5000 → 5005 (green candle)
Post: Stays above 5000 (low holds)
Label: REVERSAL (BOTTOM) ✓
```

---

### Pattern #3: FALSE REVERSAL

**Definition:**
Looks like a reversal (uptrend→red or downtrend→green) but the high/low gets broken afterward.

**Market Context:**
- Appears to be reversing
- Traps traders into reversal trades
- Then breaks through in original direction
- Classic "fakeout" or "stop hunt"

**Visual (False Top):**
```
Price
 ↑
5015 ─────────●  ← Breaks through! (false reversal confirmed)
              │╱
5010 ─────●  ●  ← Initial "reversal" high
          │╲ │
          │ ╲│
5005      │  ●  ← Looked like reversal...
          │
5000 ─────●
       ───────────> Time
       Pre  Event Post
```

**Script Identification:**
```python
# False top
if trend == 1 and color == -1 and broken_high == 1:
    return "FALSE REVERSAL"

# False bottom
if trend == -1 and color == 1 and broken_low == 1:
    return "FALSE REVERSAL"
```

**Features:**
- `trend`: 1 or -1 (directional)
- `color`: Opposite of trend (-1 or 1)
- `broken_high`: 1 (for false top) OR `broken_low`: 1 (for false bottom)
- `price_velocity`: Often lower than true reversals (weak rejection)
- `upper_volume_pct`: For false tops, often NOT heavily concentrated at top

**Trading Implication:**
- ❌ **Reversal trade FAILS**
- ✅ **Breakout trade succeeds** (trade the break)
- **Stop hunters target** these patterns
- **Wait for confirmation** before trading reversals

**Example:**
```
Time: 11:00
Pre: 5000 → 5010 (uptrend)
Event: 5010 → 5008 (red candle, looks like reversal)
Post: Breaks through to 5012 (false reversal!)
Label: FALSE REVERSAL ✓
```

---

### Pattern #4: CONTINUATION

**Definition:**
Trend continues in the same direction (uptrend→green or downtrend→red).

**Market Context:**
- Strong trend already in place
- Momentum continues
- No reversal attempt
- Trend traders adding to positions

**Visual (Up Continuation):**
```
Price
 ↑
5015 ─────────●  ← Continues higher
              │╱
5010 ─────●  ●
          │╱
5005      ●  ← Green candle
          │
5000 ─────●  ← Start of uptrend
       ───────────> Time
       Pre  Event Post
```

**Script Identification:**
```python
# Bullish continuation
if trend == 1 and color == 1 and broken_low == 0:
    return "CONTINUATION"

# Bearish continuation
if trend == -1 and color == -1 and broken_high == 0:
    return "CONTINUATION"
```

**Features:**
- `trend`: 1 or -1 (directional)
- `color`: Same as trend (1 or -1)
- `broken_high/low`: 0 (trend intact)
- `price_velocity`: High (strong momentum)
- `delta_imbalance`: Strong (>0.5 or <-0.5)

**Trading Implication:**
- ✅ **Trade with the trend**
- ✅ **Add to existing positions**
- ✅ **Avoid counter-trend**
- **High win rate** when velocity is strong

**Example:**
```
Time: 10:30
Pre: 5000 → 5010 (uptrend)
Event: 5010 → 5015 (green candle)
Post: Continues to 5020
Label: CONTINUATION ✓
```

---

### Pattern #5: CONSOLIDATION

**Definition:**
Sideways price action with small range relative to time (duration ≥5min AND range <4pts).

**Market Context:**
- No clear direction
- Buyers and sellers balanced
- Low volatility
- Often precedes big move (coiling)

**Visual:**
```
Price
 ↑
5003 ─ ● ─ ● ─ ● ─ ● ─ ● ─  ← Oscillating
      ╱ ╲ ╱ ╲ ╱ ╲ ╱ ╲ ╱
5001 ● ─ ● ─ ● ─ ● ─ ● ─ ●
      ╲ ╱ ╲ ╱ ╲ ╱ ╲ ╱ ╲ ╱
5000 ─ ● ─ ● ─ ● ─ ● ─ ●  ← Small range
    ───────────────────────> Time
        (Long duration)
```

**Script Identification:**
```python
if duration >= 5 and range_pts < 4.0:
    return "CONSOLIDATION"
```

**Features:**
- `trend`: Usually 0 (neutral)
- `duration_mins`: ≥5 minutes
- Range (high - low): <4 points
- `price_velocity`: Low (<2 pts/min)
- `upper_volume_pct`: ~0.5 (balanced)
- `delta_imbalance`: Near 0 (balanced)

**Trading Implication:**
- ⚠️ **Avoid trading** inside the range (choppy)
- ✅ **Wait for breakout**
- ✅ **Trade the break** of high/low
- **Tighten stops** (low volatility)

**Example:**
```
Time: 11:00-11:45
Pre: Various
Event: Oscillates 5000-5003 for 45 minutes
Post: Eventually breaks
Label: CONSOLIDATION ✓
```

---

### Pattern #6: V-SHAPE

**Definition:**
Sharp reversal with minimal consolidation (down then immediately up, or vice versa).

**Market Context:**
- Panic spike/drop
- Immediate reversal
- No consolidation phase
- High volatility
- Often on news

**Visual:**
```
Price
 ↑
5010 ─────●                    ● ← Rapid recovery
          │╲                  ╱│
          │ ╲                ╱ │
5005      │  ╲              ╱  │
          │   ╲            ╱   │
5000 ─────●    ╲          ╱    │
               ╲        ╱
5995            ╲      ╱
                 ╲    ╱
4990              ●──●  ← V-bottom (spike low)
              ───────────> Time
              (Very short duration)
```

**Script Identification:**
```python
# Currently uses heuristic rules or user labels
# Characteristics:
# - High max_velocity (>10 pts/min)
# - Short duration (<3 min)
# - Large range relative to duration
```

**Features:**
- `price_velocity`: Very high (>10 pts/min)
- `max_velocity`: Extreme
- `acceleration`: High (velocity increasing)
- `duration_mins`: Usually <3 minutes
- Sharp reversal in post-event data

**Trading Implication:**
- ⚠️ **Very difficult to trade** (too fast)
- ❌ **Avoid chasing**
- ✅ **Wait for retest** of spike level
- **High slippage** risk

**Example:**
```
Time: 14:15
Pre: Steady at 5000
Event: Drops to 4990 in 1 minute, immediately recovers to 5000
Post: Continues higher
Label: V-SHAPE ✓
```

---

### Pattern #7: UNCERTAIN

**Definition:**
Doesn't fit any clear pattern (fallback label).

**When This Happens:**
- Mixed signals
- No clear trend going in (trend=0)
- Conflicting features
- Transitional phase

**Script Identification:**
```python
# Fallback when no other rules match
return "UNCERTAIN"
```

**Trading Implication:**
- ❌ **Do not trade**
- ⚠️ **Wait for clarity**
- ✅ **Re-analyze later** with more context

---

## 📊 Pattern Comparison Matrix

| Pattern | Trend | Color | Broken High/Low | Velocity | Duration | Range | Volume Profile |
|---------|-------|-------|-----------------|----------|----------|-------|----------------|
| **REVERSAL (TOP)** | Up (+1) | Red (-1) | High holds (0) | Negative | Any | Any | Top-heavy (>70%) |
| **REVERSAL (BOTTOM)** | Down (-1) | Green (+1) | Low holds (0) | Positive | Any | Any | Bottom-heavy (>70%) |
| **FALSE REVERSAL** | +1 or -1 | Opposite | Broken (1) | Low | Any | Any | Not concentrated |
| **CONTINUATION** | +1 or -1 | Same | Holds (0) | High | Any | Large | Directional |
| **CONSOLIDATION** | Neutral (0) | Any | Holds (0) | Low (<2) | Long (>5min) | Small (<4pts) | Balanced (~50%) |
| **V-SHAPE** | Any | Reverses | Any | Very high (>10) | Short (<3min) | Large | Varies |
| **UNCERTAIN** | Any | Any | Any | Any | Any | Any | Any |

---

## 🎯 Decision Tree for Classification

```
START
  │
  ├─ Duration >5min AND Range <4pts?
  │  └─ YES → CONSOLIDATION
  │  └─ NO → Continue
  │
  ├─ Trend = UP (1)?
  │  │
  │  ├─ Candle = RED (-1)?
  │  │  │
  │  │  ├─ High broken later?
  │  │  │  └─ YES → FALSE REVERSAL
  │  │  │  └─ NO → REVERSAL (TOP)
  │  │
  │  └─ Candle = GREEN (1)?
  │     └─ CONTINUATION
  │
  ├─ Trend = DOWN (-1)?
  │  │
  │  ├─ Candle = GREEN (1)?
  │  │  │
  │  │  ├─ Low broken later?
  │  │  │  └─ YES → FALSE REVERSAL
  │  │  │  └─ NO → REVERSAL (BOTTOM)
  │  │
  │  └─ Candle = RED (-1)?
  │     └─ CONTINUATION
  │
  ├─ Velocity >10 pts/min + Short duration?
  │  └─ YES → V-SHAPE
  │
  └─ Everything else
     └─ UNCERTAIN
```

---

## ✅ Summary: Avoiding Confusion

### Best Practices Checklist

- [ ] Define your primary timeframe (±5min, ±10min, or custom)
- [ ] Space out analysis times (at least 15-20 min apart for micro, 1+ hour for macro)
- [ ] Use explicit ranges for consolidations (11:00-11:45, not just 11:00)
- [ ] Be consistent with labels (keep notes!)
- [ ] Don't analyze the same time window twice with different labels
- [ ] Understand that overlap is OK if features differ (multi-timeframe)
- [ ] Review your CSV periodically for duplicates

### When in Doubt

**ASK YOURSELF:**
1. "What timeframe am I analyzing?" (5min vs 1hour)
2. "What would I trade based on this pattern?"
3. "Is this the main move or part of a larger structure?"
4. "Am I being consistent with previous similar setups?"

---

All files committed and pushed! Would you like me to create a visual pattern recognition guide with actual price charts?
