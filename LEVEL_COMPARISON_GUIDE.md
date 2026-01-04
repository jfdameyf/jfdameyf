# Comparing Old vs Enhanced Level Performance

## Overview

This guide shows how to generate levels with both scripts and compare their backtest performance to validate that the enhancements actually improve trading results.

---

## Step 1: Generate Levels with Both Scripts

### A. Generate with OLD script (baseline)

```bash
# First, backup your current levels
cp critical_levels_master_final.csv critical_levels_master_final.csv.backup

# Run your ORIGINAL level generator for the backtest period
python generate_levels.py
# When prompted, select the date range matching your backtest
# Example: Last 30 days to match your NQ optimization period

# Save these as baseline levels
cp critical_levels_master_final.csv critical_levels_BASELINE.csv
```

### B. Generate with ENHANCED script (comparison)

```bash
# Run the enhanced level generator for THE SAME period
python generate_levels_ENHANCED.py

# Select option 2 or 3:
# Option 1: Last 5 days (quick)
# Option 2: Last 30 days (backtest)  ← USE THIS
# Option 3: Last 90 days (comprehensive)
# Option 4: Custom date range

# Save these as enhanced levels
cp critical_levels_master_final.csv critical_levels_ENHANCED.csv
```

**CRITICAL:** Both must use the **exact same date range** for fair comparison!

---

## Step 2: Run Backtests with Each Level Set

### A. Backtest with BASELINE levels

```bash
# Copy baseline levels to active file
cp critical_levels_BASELINE.csv critical_levels_master_final.csv

# Run ES backtest
python backtest_bot_COMPLETE.py
# Select: 2 (30 days)
# POC Filter: N
# Cooldown: 60
# Target: 3
# Stop: 2

# Save results
mv backtest_results/trades_*.csv backtest_results/trades_BASELINE_ES.csv
mv backtest_results/signals_*.csv backtest_results/signals_BASELINE_ES.csv
mv backtest_results/summary_*.json backtest_results/summary_BASELINE_ES.json
```

### B. Backtest with ENHANCED levels

```bash
# Copy enhanced levels to active file
cp critical_levels_ENHANCED.csv critical_levels_master_final.csv

# Run ES backtest with SAME parameters
python backtest_bot_COMPLETE.py
# Select: 2 (30 days)
# POC Filter: N
# Cooldown: 60
# Target: 3
# Stop: 2

# Save results
mv backtest_results/trades_*.csv backtest_results/trades_ENHANCED_ES.csv
mv backtest_results/signals_*.csv backtest_results/signals_ENHANCED_ES.csv
mv backtest_results/summary_*.json backtest_results/summary_ENHANCED_ES.json
```

---

## Step 3: Compare Results

### Quick Comparison (Command Line)

```bash
echo "=== BASELINE LEVELS ==="
grep -A 10 "TRADE PERFORMANCE" backtest_results/summary_BASELINE_ES.json

echo "=== ENHANCED LEVELS ==="
grep -A 10 "TRADE PERFORMANCE" backtest_results/summary_ENHANCED_ES.json
```

### Detailed Comparison (Python)

Create `compare_levels.py`:

```python
import pandas as pd
import json

# Load summaries
with open('backtest_results/summary_BASELINE_ES.json', 'r') as f:
    baseline = json.load(f)

with open('backtest_results/summary_ENHANCED_ES.json', 'r') as f:
    enhanced = json.load(f)

# Extract key metrics
baseline_perf = baseline['performance']
enhanced_perf = enhanced['performance']

print("="*60)
print("BASELINE vs ENHANCED LEVEL COMPARISON")
print("="*60)

metrics = [
    ('Total Trades', 'total_trades'),
    ('Winners', 'winners'),
    ('Win Rate %', 'win_rate'),
    ('Expectancy $', 'expectancy_dollars'),
    ('Total P&L $', 'total_pnl_dollars')
]

for label, key in metrics:
    base_val = baseline_perf[key]
    enh_val = enhanced_perf[key]
    diff = enh_val - base_val
    pct_change = (diff / base_val * 100) if base_val != 0 else 0

    print(f"\n{label}:")
    print(f"  Baseline:  {base_val:>10}")
    print(f"  Enhanced:  {enh_val:>10}")
    print(f"  Change:    {diff:>10.1f} ({pct_change:+.1f}%)")

# MFE/MAE comparison
baseline_mfe = baseline['mfe_mae']
enhanced_mfe = enhanced['mfe_mae']

print("\n" + "="*60)
print("MFE/MAE ANALYSIS")
print("="*60)

print(f"\nAvg MFE (Max Favorable):")
print(f"  Baseline: {baseline_mfe['avg_mfe']:.2f} pts")
print(f"  Enhanced: {enhanced_mfe['avg_mfe']:.2f} pts")
print(f"  Change:   {enhanced_mfe['avg_mfe'] - baseline_mfe['avg_mfe']:+.2f} pts")

print(f"\nAvg MAE (Max Adverse):")
print(f"  Baseline: {baseline_mfe['avg_mae']:.2f} pts")
print(f"  Enhanced: {enhanced_mfe['avg_mae']:.2f} pts")
print(f"  Change:   {enhanced_mfe['avg_mae'] - baseline_mfe['avg_mae']:+.2f} pts")

print(f"\nCapture Efficiency:")
print(f"  Baseline: {baseline_mfe['avg_efficiency']:.1f}%")
print(f"  Enhanced: {enhanced_mfe['avg_efficiency']:.1f}%")
print(f"  Change:   {enhanced_mfe['avg_efficiency'] - baseline_mfe['avg_efficiency']:+.1f}%")

print("\n" + "="*60)
```

Run it:
```bash
python compare_levels.py
```

---

## Step 4: Analyze Level Differences

### Compare level counts and categories

```bash
# Count levels by category
echo "BASELINE:"
grep -o '"category":"[^"]*"' critical_levels_BASELINE.csv | sort | uniq -c

echo "ENHANCED:"
grep -o '"category":"[^"]*"' critical_levels_ENHANCED.csv | sort | uniq -c
```

### Find new delta exhaustion levels

```bash
# These should only exist in enhanced version
grep "DELTA_EXHAUSTION" critical_levels_ENHANCED.csv | wc -l
```

### Check for proven/persistent levels

```bash
# Count proven levels (5+ hits)
grep "PROVEN" critical_levels_ENHANCED.csv | wc -l

# Count persistent levels (multi-day)
grep "Appeared" critical_levels_ENHANCED.csv | wc -l
```

---

## Expected Results

### If Enhancements Work (Expected):

```
Win Rate: +3-6% improvement
Baseline: 67.2%
Enhanced: 70.1%
Change:   +2.9% (+4.3%)

Expectancy: +$10-20 improvement
Baseline: $67.91
Enhanced: $78.45
Change:   +$10.54 (+15.5%)

Total P&L: +15-25% improvement
Baseline: $16,838
Enhanced: $19,420
Change:   +$2,582 (+15.3%)

MFE/MAE Ratio: Improved
Baseline: 2.1
Enhanced: 2.3
Change:   +0.2 (better edge quality)
```

**Why:** Enhanced levels have:
- Strong tails prioritized (better entries)
- Proven levels boosted (higher probability)
- Weak levels deprioritized (fewer false signals)
- Delta exhaustion zones (additional high-edge setups)

### If No Improvement (Investigate):

Possible reasons:
1. **Sample size too small** - Need 60+ days for statistical significance
2. **Market regime changed** - Recent data different from historical
3. **Parameters need adjustment** - Thresholds might need tuning
4. **Level quality already high** - Original script already captured best levels

---

## Step 5: Detailed Trade Analysis

### Compare individual trades

```python
import pandas as pd

baseline_trades = pd.read_csv('backtest_results/trades_BASELINE_ES.csv')
enhanced_trades = pd.read_csv('backtest_results/trades_ENHANCED_ES.csv')

# Compare by zone
print("\nBASELINE Zone Performance:")
print(baseline_trades.groupby('zone')['pnl'].agg(['count', 'mean', 'sum']))

print("\nENHANCED Zone Performance:")
print(enhanced_trades.groupby('zone')['pnl'].agg(['count', 'mean', 'sum']))

# Find zones that improved
baseline_zone_pnl = baseline_trades.groupby('zone')['pnl'].mean()
enhanced_zone_pnl = enhanced_trades.groupby('zone')['pnl'].mean()

improvement = enhanced_zone_pnl - baseline_zone_pnl
print("\nZone Improvement:")
print(improvement.sort_values(ascending=False))

# Compare outcomes
print("\nBASELINE Outcomes:")
print(baseline_trades['outcome'].value_counts(normalize=True) * 100)

print("\nENHANCED Outcomes:")
print(enhanced_trades['outcome'].value_counts(normalize=True) * 100)
```

---

## Step 6: Visual Comparison

### Cumulative P&L curves

```python
import matplotlib.pyplot as plt

baseline_trades = pd.read_csv('backtest_results/trades_BASELINE_ES.csv')
enhanced_trades = pd.read_csv('backtest_results/trades_ENHANCED_ES.csv')

baseline_trades = baseline_trades.sort_values('entry_time')
enhanced_trades = enhanced_trades.sort_values('entry_time')

baseline_cum = baseline_trades['pnl'].cumsum()
enhanced_cum = enhanced_trades['pnl'].cumsum()

plt.figure(figsize=(14, 6))
plt.plot(baseline_cum.values, label='Baseline Levels', linewidth=2)
plt.plot(enhanced_cum.values, label='Enhanced Levels', linewidth=2)
plt.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
plt.xlabel('Trade Number')
plt.ylabel('Cumulative P&L (points)')
plt.title('Baseline vs Enhanced Level Performance')
plt.legend()
plt.grid(alpha=0.3)
plt.savefig('backtest_results/comparison.png', dpi=150)
print("Chart saved to: backtest_results/comparison.png")
```

---

## Repeat for NQ

Follow the same process but:

1. Use NQ level generator scripts
2. Use NQ backtest script
3. Use optimized NQ parameters:
   - Cooldown: 60 min
   - Target: 15 pts
   - Stop: 4 pts

```bash
# Generate NQ levels (baseline)
python generate_levels_NQ.py
cp critical_levels_NQ_master.csv critical_levels_NQ_BASELINE.csv

# Generate NQ levels (enhanced)
python generate_levels_NQ_ENHANCED.py
cp critical_levels_NQ_master.csv critical_levels_NQ_ENHANCED.csv

# Backtest both
cp critical_levels_NQ_BASELINE.csv critical_levels_NQ_master.csv
python backtest_bot_NQ_COMPLETE.py  # 60min/15pts/4pts

cp critical_levels_NQ_ENHANCED.csv critical_levels_NQ_master.csv
python backtest_bot_NQ_COMPLETE.py  # 60min/15pts/4pts

# Compare results
python compare_levels_NQ.py
```

---

## Key Metrics to Watch

### Primary Metrics (Most Important):
1. **Win Rate** - Should improve 3-6%
2. **Expectancy** - Should improve $10-20/trade (ES)
3. **Total P&L** - Should improve 15-25%

### Secondary Metrics (Quality Indicators):
4. **MFE/MAE Ratio** - Should improve (better edge)
5. **Avg Signals/Day** - Might decrease slightly (fewer weak signals)
6. **Zone 1 Win Rate** - Should be highest with enhanced levels

### Red Flags:
- Win rate **decreases** - Enhancement may have made levels worse
- Signal count **drops >50%** - May be filtering too aggressively
- Zone 1 performance **worse** - Core level quality degraded

---

## Decision Matrix

| Result | Action |
|--------|--------|
| Win rate +3-6%, Expectancy +$15+ | ✅ **Use enhanced levels permanently** |
| Win rate +1-3%, Expectancy +$5-15 | ⚠️ **Test on larger sample (90 days)** |
| Win rate unchanged ±1% | ⚠️ **Investigate - may need tuning** |
| Win rate decreases >2% | ❌ **Revert to baseline, review enhancements** |

---

## Sample Size Requirements

**Minimum viable test:**
- 30 days (20 trading days)
- 100+ trades
- Both tests use identical date range

**Statistically significant:**
- 90 days (65 trading days)
- 300+ trades
- Confidence: 95%

**Gold standard:**
- 180 days (130 trading days)
- 500+ trades
- Confidence: 99%

---

## Troubleshooting

### Issue: Enhanced has fewer trades than baseline

**Check:**
```bash
# Count levels per day
grep "level_date" critical_levels_BASELINE.csv | sort | uniq -c
grep "level_date" critical_levels_ENHANCED.csv | sort | uniq -c
```

**Likely cause:** Enhanced filtering too aggressive (weak levels removed)

**Solution:** Adjust `STRONG_TAIL_VOLUME_THRESHOLD` or `PERFORMANCE_BOOST_THRESHOLD`

### Issue: Enhanced levels not showing improvements

**Check:**
```bash
# Check if proven/persistent levels exist
grep -c "PROVEN" critical_levels_ENHANCED.csv
grep -c "Appeared" critical_levels_ENHANCED.csv
```

**If zero:** Not enough historical data for performance weighting

**Solution:** Run on longer period (90+ days) to build history

### Issue: Results are identical

**Likely cause:** Date ranges don't overlap, or enhancements not applied

**Check:** Verify delta exhaustion zones exist in enhanced version

---

## Quick Validation Checklist

Before running full backtest comparison:

```bash
# 1. Check enhanced version has new features
grep -c "DELTA_EXHAUSTION" critical_levels_ENHANCED.csv
# Should be > 0

# 2. Check for strength classification
grep -c "STRONG\|MODERATE\|WEAK" critical_levels_ENHANCED.csv
# Should be > 0

# 3. Check for performance tags
grep -c "PROVEN\|TESTED" critical_levels_ENHANCED.csv
# Should be > 0 (after 10+ days of history)

# 4. Check for persistence tags
grep -c "Appeared" critical_levels_ENHANCED.csv
# Should be > 0 (after 10+ days)

# 5. Verify date ranges match
head -1 critical_levels_BASELINE.csv
head -1 critical_levels_ENHANCED.csv
# Should have same earliest date
```

---

## Expected Timeline

**Quick comparison (30 days):**
- Generate levels: ~10 minutes each
- Run backtests: ~5 minutes each
- Analysis: ~10 minutes
- **Total: ~40 minutes**

**Comprehensive (90 days):**
- Generate levels: ~30 minutes each
- Run backtests: ~15 minutes each
- Analysis: ~15 minutes
- **Total: ~2 hours**

---

## Summary

1. Generate baseline levels for target period
2. Generate enhanced levels for **same period**
3. Backtest both with **identical parameters**
4. Compare win rate, expectancy, total P&L
5. Analyze level quality differences
6. Decide: Use enhanced permanently or tune parameters

**Success criteria:** +3-6% win rate, +$15+ expectancy (ES), +15-25% total P&L

If successful, enhanced levels become your new standard! 🚀
