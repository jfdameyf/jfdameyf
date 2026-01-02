# ES Trading Bot - Backtesting Guide

## 📋 Overview

The backtesting suite allows you to test your trading bot strategy on historical data to validate that the fixes work and identify optimal configuration settings.

### Files Included

1. **`backtest_bot.py`** - Core backtesting engine
2. **`backtest_compare.py`** - Configuration comparison tool
3. **`BACKTESTING_GUIDE.md`** - This guide

---

## 🚀 Quick Start

### Option 1: Quick 7-Day Backtest

Test if the bot would have generated signals in the last week:

```bash
python backtest_bot.py
# Select: 1 (Quick Backtest - Last 7 trading days)
# POC Filter: N
```

**What it does:**
- Generates daily plans for the last 7 trading days
- Replays historical price data
- Shows all signals that would have fired
- Creates charts and reports

**Expected time:** 2-5 minutes

---

### Option 2: Extended 30-Day Backtest

More comprehensive test covering the last month:

```bash
python backtest_bot.py
# Select: 2 (Quick Backtest - Last 30 trading days)
# POC Filter: N
```

**Expected time:** 5-10 minutes

---

### Option 3: Custom Date Range

Test a specific period:

```bash
python backtest_bot.py
# Select: 3 (Custom Date Range)
# Start Date: 2025-11-01
# End Date: 2025-12-31
# POC Filter: N
```

**Use this to:**
- Test specific market conditions
- Validate during known volatile periods
- Compare before/after code changes

---

## 📊 Understanding the Results

### Console Output

```
📈 OVERALL STATISTICS
   Period: 2025-12-01 to 2025-12-08
   Trading Days: 6
   Total Signals: 42
   Avg Signals/Day: 7.0

🎯 SIGNAL BREAKDOWN
   Responsive: 28
   Recapture: 14

   Long Signals: 23
   Short Signals: 19

📍 ZONE DISTRIBUTION
   Zone 1: 18 (42.9%)
   Zone 2: 12 (28.6%)
   Zone 3: 8 (19.0%)
   Zone 4: 4 (9.5%)
```

### What Each Metric Means

**Total Signals:**
- How many trade setups the bot identified
- Good range: 3-10 per day
- Too few (<2/day): Levels too conservative or filters too strict
- Too many (>15/day): May include noise

**Responsive vs Recapture:**
- **Responsive:** Zones 1 & 2 - immediate entries on touch
- **Recapture:** Zones 3 & 4 - entries after violation + reclaim
- Healthy ratio: ~60% responsive, 40% recapture

**Zone Distribution:**
- **Zone 1 (nearest):** Should have most signals (~40%)
- **Zone 2:** Second most (~30%)
- **Zone 3 & 4 (furthest):** Fewer signals (~20-30% combined)

**Long/Short Balance:**
- Ideal: ~50/50 split
- Heavy skew (>70/30) indicates:
  - Trending market (normal in strong trends)
  - Possible level bias (check critical_levels.csv)

---

## 📁 Output Files

All results saved to `backtest_results/` directory:

### 1. Signal Details CSV

**File:** `signals_2025-12-01_to_2025-12-08.csv`

Contains every signal with:
- Timestamp
- Entry type (RESPONSIVE/RECAPTURE)
- Direction (LONG/SHORT)
- Price
- Zone
- Size modifier
- Message

**Use for:**
- Detailed analysis
- Manual trade validation
- Excel/spreadsheet analysis

### 2. Summary JSON

**File:** `summary_2025-12-01_to_2025-12-08.json`

Structured data including:
- Overall statistics
- Zone distribution
- Top signal days
- Configuration settings

**Use for:**
- Programmatic analysis
- Building dashboards
- Comparing multiple backtests

### 3. Charts

**File:** `charts_2025-12-01_to_2025-12-08.png`

Visual charts showing:
- Signals per day (bar chart)
- Signal type distribution (pie chart)
- Zone distribution (bar chart)
- Long vs Short distribution (pie chart)

**Use for:**
- Quick visual assessment
- Presentations
- Identifying patterns

---

## 🔬 Configuration Comparison

### Why Compare Configurations?

The backtesting suite lets you test different settings to find what works best:

- **POC Filter ON vs OFF**
- Different threshold values
- Zone proximity settings

### Running Comparisons

```bash
python backtest_compare.py
# Select: 2 (Compare POC Filter - 30 days)
```

**What happens:**
1. Runs full backtest with POC Filter OFF
2. Runs full backtest with POC Filter ON
3. Compares results side-by-side
4. Recommends best configuration

**Output:**

```
📊 CONFIGURATION COMPARISON
================================================================================
Configuration    POC Filter  Total Signals  Avg/Day  Responsive  Recapture  Zone 1  Zone 2  Zone 3  Zone 4
POC Filter OFF   OFF         142            7.1      88          54         58      42      28      14
POC Filter ON    ON          89             4.5      62          27         42      28      14      5

🏆 BEST CONFIGURATION ANALYSIS
================================================================================

POC Filter OFF:
   Signals/Day: 7.1
   Zone Diversity: 100%
   Long/Short Balance: 95%
   OVERALL SCORE: 92.3/100

POC Filter ON:
   Signals/Day: 4.5
   Zone Diversity: 100%
   Long/Short Balance: 88%
   OVERALL SCORE: 78.5/100

🏆 WINNER: POC Filter OFF
   Score: 92.3/100
```

### Interpreting Comparison Results

**More signals ≠ Better**
- Quality matters more than quantity
- Look for good zone diversity
- Check long/short balance

**When POC Filter ON is better:**
- During strong trends (reduces counter-trend trades)
- When signal quality > signal quantity
- If you trade larger size (fewer, higher quality setups)

**When POC Filter OFF is better:**
- Balanced/choppy markets
- When you want more opportunities
- If you trade smaller size (more setups)

---

## 📈 Example Backtest Workflow

### Goal: Validate the bot works after fixes

**Step 1:** Quick 7-day test
```bash
python backtest_bot.py
# Select: 1
# POC Filter: N
```

**Expected:** Should see 20-50 signals total (3-7 per day)

**If you see 0 signals:**
- Check that `critical_levels_master_final.csv` exists and has data
- Verify Databento API key is set
- Check date range includes trading days (not all weekends)

---

**Step 2:** Review signal quality

Open: `backtest_results/signals_[date_range].csv`

**Check for:**
- Signals at reasonable prices (near support/resistance)
- Good mix of zones
- Timestamps make sense (within market hours)

**Red flags:**
- All signals from one zone (check level distribution)
- Prices clustered at same level (possible duplicate issue)
- Signals outside market hours (timezone problem)

---

**Step 3:** Extended 30-day validation

```bash
python backtest_bot.py
# Select: 2
# POC Filter: N
```

**Look for:**
- Consistent signal generation across days
- Avg 3-10 signals per day
- Some days with 0-2 (normal on low volatility)
- Some days with 10-15 (normal on high volatility)

---

**Step 4:** Configuration optimization

```bash
python backtest_compare.py
# Select: 2 (30-day POC comparison)
```

**Use the winner** in your live bot!

---

## 🎯 Troubleshooting

### Problem: "No signals generated during backtest period!"

**Causes:**
1. No levels in `critical_levels_master_final.csv`
2. Levels too far from market price
3. Date range has no trading days
4. Databento API issue

**Solutions:**
```bash
# Check levels file exists
ls -la critical_levels_master_final.csv

# Verify date range
# Make sure it's not all weekends/holidays

# Test with different date range
python backtest_bot.py
# Select: 3
# Use dates you KNOW had market data
```

---

### Problem: "Error loading context" or "Plan missing required fields"

**Cause:** Market planner failed to generate valid plans

**Solution:**
Check the console output during plan generation phase:

```
📅 Generating Historical Plans...
================================================================================

📊 Processing: 2025-12-01
   ⚠️ DEBUG: No history found before 2025-12-01  <- PROBLEM
```

**Fix:**
- Start date might be too early (no historical data)
- Try more recent dates
- Check Databento API has data for that period

---

### Problem: Very few signals (< 2 per day)

**Possible causes:**

1. **Levels too far from price action**
   - Check `predicted_range` in daily plans
   - Levels might be outside the BUFFER_PCT range

2. **Proximity thresholds too tight**
   - Zone 1 requires within 2 points
   - Zone 2 requires within 4 points
   - If levels are sparse, might miss opportunities

3. **POC filter too restrictive**
   - Try comparing with POC OFF
   - Market might be trending (>50pts from POC)

**Solutions:**
```bash
# Test without POC filter
python backtest_bot.py
# POC Filter: N

# Compare configurations
python backtest_compare.py
```

---

### Problem: Too many signals (> 15 per day)

**Possible causes:**

1. **Levels too close together**
   - MIN_LEVEL_SEPARATION might be too low
   - Check `critical_levels_master_final.csv` for clusters

2. **Proximity thresholds too loose**
   - Might be firing too early/late

3. **Signal deduplication not working**
   - Check for duplicate signals at same price/time

**Solutions:**
- Review signals CSV for duplicates
- Increase MIN_LEVEL_SEPARATION in config
- Check level quality in critical_levels file

---

## 💡 Best Practices

### 1. Test Recent Data First

Start with last 7 days:
- Validates current market structure
- Faster iteration
- Easier to manually verify

Then expand to 30+ days for statistical significance.

---

### 2. Compare Multiple Configurations

Don't assume default settings are best:

```bash
# Test POC filter impact
python backtest_compare.py
# Select: 2

# Results tell you which works better for YOUR levels
```

---

### 3. Validate Against Known Events

Pick a date you remember:
- Big trend day
- Choppy consolidation
- Gap up/down open

Run backtest for that day and verify signals make sense.

---

### 4. Check Signal Distribution

Healthy distribution:
- **Zone 1:** ~40-50% (most signals)
- **Zone 2:** ~25-35%
- **Zone 3:** ~15-25%
- **Zone 4:** ~5-15% (least signals)

If Zone 4 > Zone 1, something's wrong with level selection.

---

### 5. Balance Quality vs Quantity

**Too few signals (< 2/day):**
- Missing opportunities
- Levels might be too conservative
- Consider loosening filters

**Too many signals (> 15/day):**
- Likely includes noise
- May lead to overtrading
- Consider tightening filters

**Sweet spot: 3-10 signals/day**

---

## 🔄 Iterative Improvement Workflow

### Week 1: Baseline

```bash
python backtest_bot.py  # 30 days, POC OFF
```

Record baseline metrics:
- Total signals
- Zone distribution
- Quality assessment

---

### Week 2: Optimize Configuration

```bash
python backtest_compare.py  # POC comparison
```

Apply winner to live bot.

---

### Week 3: Validate Changes

```bash
python backtest_bot.py  # Same date range
```

Compare to baseline:
- More signals?
- Better distribution?
- Improved quality?

---

### Week 4: Expand Time Range

```bash
python backtest_bot.py  # 90 days
```

Test across different market conditions:
- Trending markets
- Choppy/balanced
- High/low volatility

---

## 📝 Advanced Usage

### Custom Analysis Script

Create your own analysis using the backtest data:

```python
import pandas as pd
import json

# Load backtest results
df = pd.read_csv('backtest_results/signals_2025-11-01_to_2025-12-01.csv')

# Calculate win rate (example: using fixed 4pt target, 2pt stop)
df['pnl'] = 0  # Add your P&L calculation logic here

# Analyze by zone
for zone in [1, 2, 3, 4]:
    zone_signals = df[df['zone'] == zone]
    print(f"Zone {zone}: {len(zone_signals)} signals")
    # Add your metrics
```

---

### Comparing Before/After Code Changes

**Before making changes:**
```bash
python backtest_bot.py  # Save results
mv backtest_results/signals_*.csv backtest_results/signals_BEFORE.csv
```

**After making changes:**
```bash
python backtest_bot.py  # Same date range
# Compare signals_BEFORE.csv vs new signals_*.csv
```

---

## 🎓 Key Takeaways

1. **Always backtest before going live** with configuration changes
2. **Compare configurations** to find what works for your levels
3. **3-10 signals/day** is a healthy target
4. **Zone distribution matters** - most signals should be Zones 1 & 2
5. **More ≠ Better** - quality over quantity
6. **Use recent data** (last 30 days) for most reliable results
7. **Validate fixes** - the backtest should show the bot WOULD have traded

---

## 🚨 Red Flags

Watch out for these warning signs:

❌ **0 signals over 30 days**
- Bot logic broken or levels are completely wrong

❌ **All signals from one zone**
- Level distribution problem

❌ **100% long or 100% short**
- Severe level bias or market in extreme trend

❌ **Signals cluster at exact same price**
- Deduplication not working

❌ **Signals outside market hours**
- Timezone issue

❌ **>20 signals per day consistently**
- Likely including noise, over-trading

---

## ✅ Next Steps After Backtesting

Once you've validated the strategy:

1. **Apply optimal configuration to live bot**
   ```python
   # In trading_bot_FIXED.py
   ENABLE_POC_FILTER = True  # or False based on backtest
   ```

2. **Paper trade for 1 week**
   - Run live bot but don't execute
   - Manually verify signals make sense
   - Compare to backtest expectations

3. **Start with small size**
   - Validate in real market conditions
   - Build confidence gradually

4. **Monitor and iterate**
   - Run weekly backtests
   - Compare live results vs backtest predictions
   - Refine levels and configuration

---

## 📚 Additional Resources

- **Trading Bot Analysis:** See `TRADING_BOT_ANALYSIS.md` for detailed explanation of fixes
- **Quick Reference:** See `FIXES_SUMMARY.md` for testing checklist
- **Live Bot Usage:** See trading_bot_FIXED.py comments

---

**Happy backtesting! 🚀**

If you discover your bot WOULD have generated many signals during the "silent weeks," that confirms the fixes work and the original bugs were the problem!
