# GC Level Category & Type Performance Guide

## Major Change: Extended Trading Hours 🕒

**OLD:** 8:20 AM - 1:30 PM ET (5 hours - gold pit session)
**NEW:** 9:30 AM - 4:15 PM ET (6.75 hours - matching ES/NQ)

### Impact of Expanded Hours

**Positive:**
- 35% more trading time (+1.75 hours)
- More signal opportunities
- Catches afternoon gold moves

**Negative:**
- Lower afternoon volatility (European close at 11:30 AM ET)
- Afternoon may have different characteristics than morning
- Results from pit session (8:20-1:30) may not hold for extended hours

**What to Watch:**
- Compare morning vs afternoon win rates
- Check if level types perform differently by time of day
- May need time-of-day filters

---

## Level Category Definitions

### 📁 CATEGORIES (What the level represents)

#### SINGLE_PRINT
- **Definition:** TPO single prints (tails and gaps)
- **Theory:** Market rejected these prices quickly
- **Trading:** Reversal entries when price returns
- **Subtypes:** Buying tail, selling tail, gap zone
- **Expectation:** Moderate win rate, good for mean reversion

#### WALL
- **Definition:** High volume at edge of range
- **Theory:** Significant absorption at session high/low
- **Trading:** Strong support/resistance
- **Subtypes:** Bid absorption (lows), Ask absorption (highs)
- **Expectation:** Higher win rate, strong levels

#### SUPER_WALL
- **Definition:** Extreme volume at edge of range
- **Theory:** Major institutional defense level
- **Trading:** Strongest support/resistance
- **Subtypes:** Bid/Ask absorption with massive volume
- **Expectation:** Highest win rate, most reliable

#### MAGNET / MAGNET_ZONE
- **Definition:** High volume in middle of range with choppy price
- **Theory:** Attraction point, not rejection
- **Trading:** TARGET exit, not entry
- **Strategy:** Use as profit-taking level
- **Expectation:** Low win rate if used for entries

#### LIQUIDITY
- **Definition:** Resting limit orders (bid/ask walls from book)
- **Theory:** Large resting orders create temporary support/resistance
- **Trading:** Reversal at wall
- **Subtypes:** BID_WALL, ASK_WALL
- **Expectation:** Short-term holds, quick reactions

#### DELTA_EXHAUSTION
- **Definition:** Extreme delta imbalance detected
- **Theory:** One-sided flow exhausted
- **Trading:** Reversal when exhaustion detected
- **Expectation:** Good for catching reversals after strong moves

---

## Level Type Definitions

### 🏷️ LEVEL TYPES (How the level formed)

#### BUYING_TAIL
- **Formation:** Single print at session low
- **Meaning:** Buyers defended aggressively
- **Direction:** LONG at support
- **Strength:** Strong if high volume
- **Gold Specific:** Morning buying tails often mark daily low

#### SELLING_TAIL
- **Formation:** Single print at session high
- **Meaning:** Sellers defended aggressively
- **Direction:** SHORT at resistance
- **Strength:** Strong if high volume
- **Gold Specific:** Often forms at European session highs

#### GAP_ZONE
- **Formation:** Single print in middle of range
- **Meaning:** Fast move through price, no acceptance
- **Direction:** Both LONG and SHORT (depends on approach direction)
- **Strength:** Moderate, acts as magnet
- **Gold Specific:** Common during news events

#### BID_ABSORPTION / ASK_ABSORPTION
- **Formation:** High volume absorption at edge
- **Meaning:** Large orders defended the level
- **Direction:** BID = LONG, ASK = SHORT
- **Strength:** Very strong if SUPER_WALL
- **Gold Specific:** Often at psychological levels ($2700, $2750, etc.)

#### BID_WALL / ASK_WALL
- **Formation:** Resting limit orders in the book
- **Meaning:** Passive liquidity waiting
- **Direction:** BID = LONG support, ASK = SHORT resistance
- **Strength:** Temporary, can disappear
- **Gold Specific:** Less reliable than absorption walls

#### MAGNET
- **Formation:** High volume in chop zone
- **Meaning:** Price keeps returning but not rejecting
- **Direction:** Neither - use as target
- **Strength:** Don't trade entries here
- **Gold Specific:** Often forms at previous day's POC

---

## Interpreting Optimizer Output

### Example Output:

```
[66/150] Testing: Cooldown=60min, Target=25.0pts, Stop=12.0pts
   ✅ Trades: 66, WR: 22.7%, P&L: $8488, Exp: $129
   📍 ZONES:
      Z1: 35t WR=30% Exp=$150 P&L=$5250
      Z2: 20t WR=15% Exp=$100 P&L=$2000
      Z3: 11t WR=10% Exp=$80 P&L=$880
   📊 TYPES:
      RESPONSIVE: 50t WR=25% Exp=$140
      RECAPTURE: 16t WR=15% Exp=$90
   💫 SCRATCH: 18t Avg=$200 | 8 near target
   📁 CATEGORIES:
      SINGLE_PRINT: 30t WR=18% Exp=$90
      WALL: 20t WR=30% Exp=$180
      SUPER_WALL: 10t WR=40% Exp=$250
      MAGNET: 6t WR=5% Exp=$-50
   🏷️  LEVEL TYPES:
      BUYING_TAIL: 15t WR=25% Exp=$140
      SELLING_TAIL: 12t WR=22% Exp=$130
      GAP_ZONE: 10t WR=15% Exp=$80
      BID_ABSORPTION: 12t WR=35% Exp=$200
      ASK_ABSORPTION: 10t WR=32% Exp=$190
      MAGNET: 7t WR=8% Exp=$-20
```

---

## Decision Matrix by Category

### Scenario 1: SUPER_WALL Dominates

```
SUPER_WALL: 15t WR=45% Exp=$220
WALL: 20t WR=28% Exp=$140
SINGLE_PRINT: 25t WR=18% Exp=$80
MAGNET: 6t WR=0% Exp=$-100
```

**Analysis:**
- Super walls are clearly superior
- Single prints dragging down performance
- Magnets are toxic

**Action:**
```python
# In trading_bot_GC_FIXED.py, filter by category
if level.get('category') not in ['SUPER_WALL', 'WALL']:
    return "NO_ENTRY", 1.0, "Category filter"
```

**Expected Impact:**
- Fewer trades (15+20=35 vs 66)
- Higher WR (combined ~35% vs 22.7%)
- Higher expectancy (combined ~$170 vs $129)

---

### Scenario 2: Tail Types Outperform

```
BUYING_TAIL: 18t WR=35% Exp=$180
SELLING_TAIL: 16t WR=32% Exp=$170
GAP_ZONE: 20t WR=12% Exp=$50
BID_ABSORPTION: 12t WR=25% Exp=$120
```

**Analysis:**
- Tails (single prints at extremes) work best
- Gap zones (middle single prints) don't work
- This suggests gold respects range edges more than gaps

**Action:**
```python
# Filter to only tail types
if level.get('level_type') not in ['BUYING_TAIL', 'SELLING_TAIL']:
    return "NO_ENTRY", 1.0, "Level type filter"
```

**Expected Impact:**
- Trade only edge rejections (34 trades)
- WR improves to ~33%
- Expectancy improves to ~$175

---

### Scenario 3: MAGNET Category Appears

```
MAGNET: 15t WR=8% Exp=$-80
SINGLE_PRINT: 25t WR=22% Exp=$110
WALL: 20t WR=30% Exp=$160
```

**Analysis:**
- MAGNET levels are being traded for entries (WRONG strategy)
- These should be targets, not entries
- Big drag on overall performance

**Action:**
```python
# Skip MAGNET category entirely (or use as target only)
if level.get('category') in ['MAGNET', 'MAGNET_ZONE']:
    return "NO_ENTRY", 1.0, "Magnet = target not entry"
```

**Expected Impact:**
- Remove 15 losing trades
- WR jumps from 22.7% to ~27%
- Expectancy improves significantly

---

## Gold-Specific Patterns to Look For

### Pattern 1: Morning vs Afternoon

With extended hours, check if performance differs by time:
- **8:20-10:00 AM:** European active, high volatility
- **10:00-11:30 AM:** Peak gold volatility
- **11:30 AM-1:30 PM:** European close, volatility drops
- **1:30-4:15 PM:** US afternoon, lower volatility

**What to check:**
- Do BUYING_TAILs work better in morning?
- Do levels formed in afternoon hold less well?
- Should you stop trading after 1:30 PM?

**How to implement:**
```python
# In trading bot, add time filter
if timestamp.hour >= 13 and timestamp.minute >= 30:
    return "NO_ENTRY", 1.0, "After pit close"
```

---

### Pattern 2: Absorption vs Tails

Gold is institutional-heavy. Check if:
- **BID/ASK_ABSORPTION** (institutional defense) > **TAILS** (retail panic)
- If absorption outperforms, gold is in institutional control
- If tails outperform, gold is more reactive/retail-driven

**If absorption wins:**
```python
# Only trade institutional levels
if level.get('level_type') not in ['BID_ABSORPTION', 'ASK_ABSORPTION']:
    return "NO_ENTRY", 1.0, "Institutional only"
```

---

### Pattern 3: Single Print vs Wall Categories

This reveals gold's personality:

**If SINGLE_PRINT outperforms:**
- Gold is mean-reverting
- Quick rejections work
- Smaller targets may be better

**If WALL/SUPER_WALL outperforms:**
- Gold is respecting major levels
- Larger targets make sense
- Institutional defense is strong

---

## Combining Filters

### Example: Best Category + Best Type + Best Zone

```
# Results show:
CATEGORIES: SUPER_WALL (40% WR, $200 exp) >> others
LEVEL_TYPES: BID_ABSORPTION (38% WR, $210 exp) >> others
ZONES: Zone 1 (35% WR, $180 exp) >> others
```

**Multi-filter strategy:**
```python
# In check_entry_signal()
zone = self.get_zone_number(level)

# Zone filter
if zone not in [1]:
    return "NO_ENTRY", 1.0, "Zone filter"

# Category filter
if level.get('category') not in ['SUPER_WALL', 'WALL']:
    return "NO_ENTRY", 1.0, "Category filter"

# Type filter
if level.get('level_type') not in ['BID_ABSORPTION', 'ASK_ABSORPTION']:
    return "NO_ENTRY", 1.0, "Type filter"
```

**Expected result:**
- Very few trades (maybe 8-12 per 66 original)
- Very high win rate (50-60%)
- High expectancy ($250-300)
- But: Sample size risk! Need longer backtest to validate

---

## Red Flags to Watch For

### 🚩 Red Flag 1: MAGNETs Being Traded
If you see MAGNET category with >10% of trades, that's wrong
- MAGNETs should be targets, not entries
- Filter them out immediately

### 🚩 Red Flag 2: All Categories Perform Similarly
If every category has ~22% WR and ~$130 exp:
- Level classification isn't working
- System is not discriminating between level quality
- May need to regenerate levels with stricter thresholds

### 🚩 Red Flag 3: GAP_ZONEs Outperform Tails
This would be unusual:
- Tails (edges) should be stronger than gaps (middle)
- If gaps win, may indicate choppy/ranging market
- Consider if gold is in low-volatility regime

### 🚩 Red Flag 4: Afternoon Performance Tanks
If trades after 1:30 PM have <15% WR:
- Extended hours aren't helping
- Revert to pit session only (9:30-1:30 or even 8:20-1:30)
- Afternoon gold is different beast

---

## Recommended Analysis Workflow

### Step 1: Run Full Optimization
```bash
python3 optimize_parameters_GC.py
```

### Step 2: Focus on Best Parameters
Look at 60min/25pt/12pt results specifically:
- Note overall WR and expectancy
- **Copy the category breakdown**
- **Copy the level type breakdown**
- **Note scratch near-target count**

### Step 3: Identify Dominant Category
Which category has:
- Most trades AND high WR? → Trade only that
- Highest expectancy? → Consider emphasizing
- Negative expectancy? → Filter out immediately

### Step 4: Identify Dominant Level Type
Same analysis as categories

### Step 5: Create Filter Combination
Start conservative:
- Filter out negative categories/types
- Keep successful ones

Then get aggressive:
- Trade ONLY best category + best type + best zone
- See if high WR compensates for fewer trades

### Step 6: Re-run with Filters
Implement filters in `trading_bot_GC_FIXED.py`
Re-run optimizer to validate filtered strategy

### Step 7: Consider Time Filters
If you have the data:
- Split results by morning (9:30-12:00) vs afternoon (12:00-4:15)
- Check if stopping at 1:30 PM improves results

---

## Expected Insights

Based on ES/NQ patterns, I predict:

**Hypothesis 1: SUPER_WALL >> WALL >> SINGLE_PRINT**
- Stronger levels should have higher WR
- But single prints may have better expectancy (bigger moves when they work)

**Hypothesis 2: Absorption Types > Tail Types**
- Gold is institutional
- Absorption (volume defense) should outperform tails (panic prints)

**Hypothesis 3: MAGNETs Will Hurt Performance**
- If system trades magnet entries, they'll lose
- Should see negative expectancy on MAGNET category

**Hypothesis 4: Extended Hours May Underperform**
- 1:30-4:15 PM session may have worse results than pit hours
- May need to revert or apply time filter

---

## Next Steps

1. **Run the enhanced optimizer**
2. **Review output for 60min/25pt/12pt**
3. **Share with me:**
   - Category breakdown
   - Level type breakdown
   - Any surprising patterns

4. **Implement filters based on data**
5. **Re-run optimization with filters**
6. **Compare:**
   - Filtered vs unfiltered
   - Extended hours vs pit-only

This will tell you exactly which level types are worth trading on gold!
