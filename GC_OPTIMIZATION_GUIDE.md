# GC (Gold Futures) Optimization Guide

## Complete Step-by-Step Process

This guide will help you run parameter optimization for gold futures, similar to the ES and NQ optimizations you've already completed.

## Prerequisites ✅

All scripts are ready:
- ✅ `generate_levels_ENHANCED_GC.py` - Level generator
- ✅ `trading_bot_GC_FIXED.py` - Trading bot
- ✅ `backtest_bot_GC_COMPLETE.py` - Backtester
- ✅ `optimize_parameters_GC.py` - Optimizer

## Step 1: Generate GC Levels (REQUIRED)

Before running optimization, you need to generate trading levels for gold:

```bash
python generate_levels_ENHANCED_GC.py
```

**When prompted:**
- Select option: `2` (Last 30 days - recommended to match NQ)
- Wait for data to be fetched (this may take 5-10 minutes)
- Output file: `critical_levels_master_enhanced_GC.csv`

**Then rename the file:**
```bash
mv critical_levels_master_enhanced_GC.csv critical_levels_GC_master.csv
```

OR if you prefer a different name:
```bash
cp critical_levels_master_enhanced_GC.csv critical_levels_GC_master.csv
```

## Step 2: Run Optimization

Once levels are generated, run the optimizer:

```bash
python optimize_parameters_GC.py
```

**The optimizer will test:**
- **Cooldown options:** [15, 30, 45, 60, 90, 120] minutes (6 options)
- **Target options:** [2.0, 3.0, 4.0, 5.0, 6.0, 8.0] points (6 options)
- **Stop options:** [1.0, 1.5, 2.0, 2.5, 3.0, 4.0] points (6 options)
- **Total combinations:** 216 tests

**Expected runtime:** 30-60 minutes (depending on date range)

## Step 3: Review Results

After optimization completes, you'll see:

```
====================================================================
TOP 10 CONFIGURATIONS
====================================================================

Rank 1:
  Cooldown: 60 minutes
  Target: 4.0 points
  Stop: 2.0 points
  Win Rate: 62.5%
  Total Trades: 180
  Winners: 112
  Losers: 68
  Expectancy: $75.50 per trade
  Total P&L: $13,590
  ...
```

Results are also saved to:
- `backtest_results_GC/optimization_results_YYYY-MM-DD.csv`
- `backtest_results_GC/optimization_summary_YYYY-MM-DD.json`

## Expected Results (Based on ES/NQ)

### Previous Optimizations:
| Instrument | Optimal Config | Win Rate | Expectancy | Daily P&L |
|------------|---------------|----------|------------|-----------|
| **ES** | 60min/3pt/2pt | 67.2% | $67.91 | $251 |
| **NQ** | 60min/15pt/4pt | 57.6% | $138.79 | $705 |
| **GC** | ??? | ???% | $??? | $??? |

### Expected GC Performance:
- **Win Rate:** 60-65% (between ES and NQ)
- **Expectancy:** $50-100/trade
- **Daily Range:** $10-30
- **Signals/Day:** 2-4 (shorter RTH: 5 hours vs 6.5)
- **Point Value:** $100/point (highest value)

**Why GC might perform well:**
- Higher point value ($100 vs ES $50, NQ $20)
- Lower volatility = more predictable
- Tighter levels due to smaller tick size (0.10)
- Institutional participation during pit hours

**Why GC might be challenging:**
- Lower volume than ES/NQ
- Shorter RTH (5 hours vs 6.5)
- Fewer signals per day
- Different market drivers (USD, bonds, geopolitical)

## Recommended Parameters to Test

Based on gold's characteristics:

### Conservative (Higher Win Rate):
```
Cooldown: 60 minutes
Target: 3.0 points ($300)
Stop: 1.5 points ($150)
Expected: 65-70% WR, $60-80 expectancy
```

### Balanced (Best R:R):
```
Cooldown: 60 minutes
Target: 4.0 points ($400)
Stop: 2.0 points ($200)
Expected: 60-65% WR, $70-90 expectancy
```

### Aggressive (Higher Profit):
```
Cooldown: 60 minutes
Target: 6.0 points ($600)
Stop: 2.5 points ($250)
Expected: 55-60% WR, $80-120 expectancy
```

## Troubleshooting

### Issue: "No GC levels file found"
**Solution:** Run Step 1 first to generate levels

### Issue: "No data returned" during level generation
**Solution:**
- Check API key is set correctly
- Try a shorter date range (5 days first)
- Verify you have Databento access to GLBX.MDP3 dataset

### Issue: Optimization running slowly
**Solution:**
- Normal for 216 combinations
- Each backtest needs to generate plans and replay data
- Expected: 8-15 seconds per combination = 30-60 minutes total

### Issue: Low signal count
**Solution:**
- Gold has shorter RTH (5 hours)
- Expect 2-4 signals/day vs ES 3-6
- This is normal for gold

## What to Look For in Results

### Good Signs:
- ✅ Win rate above 60%
- ✅ Expectancy above $50/trade
- ✅ MFE/MAE ratio above 1.5
- ✅ Consistent performance across zones
- ✅ Total P&L positive over test period

### Warning Signs:
- ⚠️ Win rate below 55%
- ⚠️ Expectancy below $30/trade
- ⚠️ Very few trades (<50 total)
- ⚠️ Zone 1 performance worse than Zone 2/3
- ⚠️ High MAE relative to MFE

## After Optimization

Once you find optimal parameters:

1. **Update trading bot default:**
```python
# In trading_bot_GC_FIXED.py
# Update based on optimization results
```

2. **Run validation backtest:**
```bash
python backtest_bot_GC_COMPLETE.py
# Use optimal parameters from optimization
```

3. **Paper trade before going live:**
```bash
python trading_bot_GC_FIXED.py
# Select option 2 (Live Signals)
# Monitor without trading real money first
```

## Quick Start (TL;DR)

```bash
# 1. Generate levels (5-10 minutes)
python generate_levels_ENHANCED_GC.py
# Select: 2 (30 days)

# 2. Rename file
mv critical_levels_master_enhanced_GC.csv critical_levels_GC_master.csv

# 3. Run optimization (30-60 minutes)
python optimize_parameters_GC.py

# 4. Review results
# Check backtest_results_GC/ folder
```

## Support

If you encounter issues:
1. Check that all 4 GC scripts exist
2. Verify GC levels file exists
3. Ensure Databento API key is set
4. Try a smaller date range first (7 days)
5. Check logs in `logs/` directory

---

**Expected Timeline:**
- Level generation: 5-10 minutes
- Optimization: 30-60 minutes
- Total: 35-70 minutes

**Good luck with your GC optimization!** 🏆
