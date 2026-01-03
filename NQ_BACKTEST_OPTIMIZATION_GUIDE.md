# NQ Trading Bot - Backtest & Optimization Guide

## 🎯 Overview

This guide covers the complete NQ (Nasdaq futures) backtesting and optimization suite, adapted from the proven ES methodology but scaled for NQ's higher volatility.

---

## 📊 Key Differences: NQ vs ES

### Volatility & Scaling

| Metric | ES | NQ | Scaling Factor |
|--------|-----|-----|----------------|
| **Daily Range** | 40-60 pts | 150-250 pts | **4x** |
| **Point Value** | $50 | $20 | **0.4x** |
| **Dollar Volatility** | $2,000-$3,000 | $3,000-$5,000 | **~1.5x** |

### Parameter Ranges (Recommended)

| Parameter | ES | NQ |
|-----------|-----|-----|
| **Cooldown** | 30-60 min | 60-120 min |
| **Target** | 3-6 pts | 10-20 pts |
| **Stop** | 2-3 pts | 6-10 pts |
| **Scan Range** | 20 pts | 80 pts |
| **POC Thresholds** | 10-20-50 pts | 40-80-200 pts |

### Why NQ Needs Different Settings

1. **Higher Volatility**: NQ moves ~4x faster than ES
2. **More Noise**: Requires longer cooldowns to avoid signal spam
3. **Larger Targets**: 10pt NQ target ≈ 2.5pt ES target (in dollar terms)
4. **Wider Stops**: Must accommodate larger intraday swings

---

## 🚀 Part 1: Backtesting (backtest_bot_NQ_COMPLETE.py)

### What It Does

- Replays historical data tick-by-tick
- Tests your NQ levels with configurable parameters
- Tracks **MFE/MAE** for every trade
- Calculates win rate, P&L, expectancy
- Strict RTH filtering (9:30-16:00 ET only)
- Enforces signal cooldown to prevent spam

### Quick Start

```bash
python backtest_bot_NQ_COMPLETE.py
```

**Interactive Prompts:**
```
Select Option [1-4]: 2               # 30-day backtest
Enable POC Filter? [y/N]: N          # Start with POC off
Signal Cooldown (minutes) [60]: 60   # Default 60min (2x ES)
Target (points) [10.0]: 10           # Default 10pts (~4x ES)
Stop (points) [6.0]: 6               # Default 6pts (~3x ES)
```

### Expected Results (First Run)

**Healthy Backtest:**
```
Signals: 3-8 per day
Win Rate: 55-70%
MFE/MAE Ratio: >2.0
Expectancy: Positive
All signals: 9:30 AM - 4:00 PM ET
```

**Red Flags:**
```
❌ Signals: >15 per day → Increase cooldown
❌ Win Rate: <45% → Levels may not be working
❌ MFE/MAE: <1.0 → No edge
❌ After-hours signals → Report bug (shouldn't happen)
```

### Output Files

All saved to `backtest_results_NQ/`:

1. **`signals_[dates].csv`** - All entry signals with timestamps
2. **`trades_[dates].csv`** - Full trade analysis with MFE/MAE
3. **`summary_[dates].json`** - Key metrics and statistics
4. **`charts_[dates].png`** - 7-panel visualization

### Interpreting MFE/MAE for NQ

**Example Trade:**
```
Entry: 20,000.00 LONG @ 10:00
Target: 20,010.00 (+10 pts = $200)
Stop: 19,994.00 (-6 pts = $120)

Price Action:
10:05 - High: 20,008.50 (MFE: 8.50 pts)
10:20 - Low: 19,997.25 (MAE: 2.75 pts)
10:35 - High: 20,012.00 (TARGET HIT!)

Results:
✅ MFE: 12.00 pts (reached 20,012)
✅ MAE: 2.75 pts (worst drawdown)
✅ Outcome: WIN (target hit)
✅ P&L: +10 pts ($200)
✅ Efficiency: 83.3% (captured 10 of 12 available)
```

**What This Tells You:**
- **MFE > Target**: Could increase target to 12pts
- **MAE < Stop**: Stop placement is good
- **High Efficiency**: Exit timing is excellent

---

## ⚡ Part 2: Parameter Optimization (optimize_parameters_NQ.py)

### What It Does

- Tests **all combinations** of cooldown/target/stop
- Ranks by multiple criteria (expectancy, win rate, consistency)
- Finds optimal configuration automatically
- Saves full results to CSV for analysis

### Quick Start

```bash
python optimize_parameters_NQ.py
```

**Choose Profile:**

#### 1. Quick Optimize (~10 minutes, 48 combinations)
```
Cooldowns: 30, 45, 60, 90 min
Targets: 10, 12, 15, 20 pts
Stops: 6, 8, 10 pts
```

**Use when:** Want fast results on 30-day period

#### 2. Comprehensive Optimize (~30 minutes, 150+ combinations)
```
Cooldowns: 15, 30, 45, 60, 90, 120 min
Targets: 8, 10, 12, 15, 20, 25 pts
Stops: 4, 6, 8, 10, 12 pts
```

**Use when:** Want thorough analysis, willing to wait

#### 3. Custom Optimize
```
Enter your own ranges:
Cooldowns: 60,90,120
Targets: 10,12,15
Stops: 6,8,10
```

**Use when:** Testing specific hypotheses

### Understanding the Results

The optimizer ranks by 5 criteria:

1. **Expectancy** (35% weight) - Most important
   - Average profit per trade in dollars
   - Must be positive to be profitable

2. **Win Rate** (25% weight)
   - Percentage of winning trades
   - Higher is better, but not everything

3. **MFE/MAE Ratio** (20% weight) - Edge quality
   - How much bigger favorable moves are vs adverse
   - >2.0 = good edge, >3.0 = strong edge

4. **Sharpe Score** (20% weight) - Consistency
   - Measures return vs volatility
   - Higher = more consistent profits

5. **Composite Score** (combines all above)
   - Weighted average of normalized metrics
   - **This determines the recommended config**

### Example Output

```
🏆 RECOMMENDED NQ CONFIGURATION
=====================================
   Cooldown: 60 minutes
   Target: 12 points
   Stop: 8 points
   Risk/Reward: 1.5:1

   EXPECTED PERFORMANCE:
   Signals/Day: 5.2
   Win Rate: 64.3%
   Expectancy: $89.50/trade
   Total P&L: $11,240 over 30 days
   MFE/MAE Ratio: 3.15
   Sharpe Score: 1.82
   Max Drawdown: 42.5 pts
```

### Comparing to ES Results

**Your ES Optimization Found:**
- Cooldown: 60 min
- Target: 3 pts ($150)
- Stop: 2 pts ($100)
- Win Rate: 67.2%
- Expectancy: $67.91/trade

**Expected NQ Equivalent (4x volatility):**
- Cooldown: 60-90 min (same time)
- Target: 10-12 pts ($200-$240)
- Stop: 6-8 pts ($120-$160)
- Win Rate: 60-65% (slightly lower due to noise)
- Expectancy: $80-$120/trade

---

## 📋 Step-by-Step Workflow

### Step 1: Initial Backtest (Validate Setup)

```bash
python backtest_bot_NQ_COMPLETE.py
# Select: 2 (30 days)
# POC: N
# Cooldown: 60
# Target: 10
# Stop: 6
```

**Check:**
- ✅ Signals: 3-8/day?
- ✅ Win rate: >50%?
- ✅ All signals within RTH?
- ✅ No obvious errors?

**If any issues, STOP and debug before optimizing!**

---

### Step 2: Run Optimization (Find Best Settings)

```bash
python optimize_parameters_NQ.py
# Select: 2 (Comprehensive)
# POC: N
# Wait 20-30 minutes...
```

**Review Results:**
- Check top 10 by expectancy
- Verify MFE/MAE ratios are healthy (>2.0)
- Note the recommended configuration
- Look for patterns (e.g., does 60min always beat 30min?)

---

### Step 3: Validate Best Config (Confirm Results)

Use the recommended settings from Step 2 for a fresh backtest:

```bash
python backtest_bot_NQ_COMPLETE.py
# Select: 4 (90 days - longer validation)
# Use recommended settings from optimizer
```

**Expected:** Results should match optimization predictions within 10-15%

**Example:**
```
Optimizer predicted: 64% WR, $89/trade
90-day validation: 62% WR, $85/trade
✅ GOOD - Within expected variance
```

---

### Step 4: Analyze Trade Details

Open `backtest_results_NQ/trades_[dates].csv` and sort by:

1. **MFE (descending)** - Find best opportunities
   - Are you exiting too early?
   - Should target be higher?

2. **MAE (ascending)** - Find worst drawdowns
   - Is stop too tight?
   - Which zones have worst MAE?

3. **Zone** - Performance by distance
   - Should you only trade Zone 1?
   - Are Zones 3-4 losing money?

---

### Step 5: Apply to Live Bot

Update `trading_bot_NQ_FIXED.py` with optimized settings:

```python
# Around line 656 in alert_signal()
# Cooldown (from optimization)
if (current_time - last_fired).seconds < 3600:  # 60 minutes
    return

# Update these based on your optimization results:
# - For actual trading, you'll set target/stop in your execution logic
# - The backtester shows what WOULD have happened
```

---

## 🔍 Advanced Analysis

### Comparing Multiple Optimizations

Run optimization on different periods:

```bash
# Period 1: Last 30 days
python optimize_parameters_NQ.py
# Save results as: optimization_2024-11_to_2024-12.csv

# Period 2: 30 days before that
# Manually adjust dates in script or use custom mode
# Save results as: optimization_2024-10_to_2024-11.csv
```

**Compare:**
- Are optimal settings stable across periods?
- Does one period have much better results?
- Market regime changes?

### Testing POC Filter Impact

Run two optimizations:

1. **Without POC filter:**
```bash
python optimize_parameters_NQ.py
# POC Filter: N
# Note: Best expectancy = $89/trade
```

2. **With POC filter:**
```bash
python optimize_parameters_NQ.py
# POC Filter: Y
# Note: Best expectancy = $102/trade
```

**If POC improves expectancy by >15%, enable it in live bot!**

### Zone-Specific Analysis

After backtest, check zone performance in report:

```
🎯 PERFORMANCE BY ZONE
   Zone 1: 85 trades, 72% WR, +125.5 pts
   Zone 2: 48 trades, 65% WR, +62.8 pts
   Zone 3: 22 trades, 45% WR, -15.2 pts
   Zone 4: 12 trades, 41% WR, -8.5 pts
```

**Action:** Only trade Zones 1 & 2!

Update `trading_bot_NQ_FIXED.py`:
```python
# In evaluate_market() around line 624
zone = self.strategy.get_zone_number(level)
if zone > 2:
    continue  # Skip zones 3-4
```

---

## 🎓 Troubleshooting

### Issue 1: Too Many Signals (>15/day)

**Solutions:**
1. Increase cooldown (try 90 or 120 min)
2. Only trade Zone 1 & 2
3. Enable POC filter
4. Check if levels are too clustered

### Issue 2: Low Win Rate (<45%)

**Causes:**
1. Levels aren't at quality support/resistance
2. Target too aggressive
3. Market conditions changed
4. Stop too tight

**Solutions:**
1. Review `critical_levels_NQ_master.csv` quality
2. Reduce target (try 8pts instead of 12pts)
3. Test different time period
4. Widen stop (try 8pts instead of 6pts)

### Issue 3: Negative Expectancy

**Red flag:** Strategy is losing money!

**Debug:**
1. Check MFE/MAE ratio
   - If <1.0: No edge, levels don't work
2. Check win rate vs avg win/loss
   - 40% WR with 3:1 R/R can still be profitable
3. Review trades CSV for patterns
   - Do losses cluster at certain times?
   - Specific zones always lose?

### Issue 4: Results Don't Match Optimization

**Example:**
```
Optimizer said: 65% WR, $90/trade
Validation got: 48% WR, $22/trade
```

**Likely causes:**
1. **Overfitting** - Optimization found random luck
   - Solution: Test on longer period (90+ days)
2. **Market regime change** - Conditions shifted
   - Solution: Use recent data for optimization
3. **Implementation error** - Bug in code
   - Solution: Check parameter settings match exactly

### Issue 5: Optimization Takes Too Long

**Speed it up:**
1. Use "Quick Optimize" instead of "Comprehensive"
2. Reduce date range (15 days instead of 30)
3. Test fewer combinations:
   ```python
   cooldowns=[60, 90]      # Just 2 options
   targets=[10, 12, 15]    # Just 3 options
   stops=[6, 8]            # Just 2 options
   # Total: 2 × 3 × 2 = 12 combinations
   ```

---

## 💡 Pro Tips

### 1. Start Conservative

First live trades should use:
- **Smaller target** than optimal (e.g., if optimizer says 12pts, use 10pts)
- **Wider stop** than optimal (e.g., if optimizer says 6pts, use 8pts)
- **Only Zone 1 trades** initially
- **Smaller size** (1 contract)

**Why:** Backtest is theoretical, live trading is real!

### 2. NQ-Specific Considerations

- **News events:** NQ is very sensitive to tech earnings
- **Time of day:** First 30 min often choppy
- **Correlation:** NQ follows QQQ/tech stocks closely
- **Liquidity:** Excellent in RTH, poor overnight

### 3. Expectancy Targets

**Realistic NQ expectations:**
- **Good:** $50-$80/trade expectancy
- **Great:** $80-$120/trade expectancy
- **Exceptional:** $120+/trade expectancy

**Compare to costs:**
- NQ commissions: ~$2-5/round turn
- Slippage: ~0.25-1.0 pts ($5-$20)
- Total cost: ~$10-25/trade

**Minimum viable expectancy: $30-40/trade**

### 4. Risk Management

Even with 65% win rate and positive expectancy:
- **Max 2-3 trades/day** initially
- **Stop trading after 2 consecutive losses**
- **Never risk more than 1-2% account per trade**
- **Track daily P&L limits** ($500 max loss/day)

### 5. When to Re-Optimize

Run new optimization when:
- ✅ Every 30 days (monthly)
- ✅ After major market regime change
- ✅ If live win rate drops >15% below backtest
- ✅ If new levels added to master CSV

---

## 📈 Success Metrics

### After 30 Trades Live

**Compare to backtest predictions:**

| Metric | Backtest | Live | Variance |
|--------|----------|------|----------|
| Win Rate | 64% | 58% | -6% ✅ OK |
| Avg Winner | 10.2 pts | 9.8 pts | -4% ✅ OK |
| Avg Loser | -6.1 pts | -6.5 pts | +6% ✅ OK |
| Expectancy | $89 | $72 | -19% ⚠️ Watch |

**Green flags (✅):**
- Win rate within 10% of backtest
- Avg winner/loser within 15% of backtest
- Expectancy still positive
- No recurring execution errors

**Red flags (❌):**
- Win rate >20% below backtest
- Avg loser >30% worse than backtest
- Negative expectancy after 30+ trades
- Frequently missing fills

### After 100 Trades Live

**Should see:**
- Cumulative P&L curve trending up
- Win rate stabilized near backtest
- Drawdowns within expected range
- Confidence to increase size

---

## 🎯 Summary

### Complete Optimization Workflow

1. ✅ **Backtest 30 days** - Validate setup works
2. ✅ **Optimize parameters** - Find best settings
3. ✅ **Validate 90 days** - Confirm optimization
4. ✅ **Analyze zones** - Filter to best zones
5. ✅ **Test POC filter** - See if it improves results
6. ✅ **Paper trade 2 weeks** - Real-time validation
7. ✅ **Start small live** - 1 contract, conservative settings
8. ✅ **Track results** - Compare to backtest
9. ✅ **Re-optimize monthly** - Stay current

### Key Differences: NQ vs ES

- **4x volatility** → 4x targets/stops/thresholds
- **Same cooldowns** → Time-based, not point-based
- **Lower win rate** → More noise, expect 60-65% vs ES 67%
- **Higher expectancy** → Larger targets compensate

### Files You Have Now

1. ✅ `trading_bot_NQ_FIXED.py` - Live trading bot
2. ✅ `backtest_bot_NQ_COMPLETE.py` - Backtester with MFE/MAE
3. ✅ `optimize_parameters_NQ.py` - Parameter optimizer
4. ✅ `critical_levels_NQ_master.csv` - Your levels (you create this)
5. ✅ This guide

---

## 🚀 Next Steps

**Immediate (Today):**
1. Create `critical_levels_NQ_master.csv` with your NQ levels
2. Run 30-day backtest to validate setup
3. Review results and check for obvious issues

**Short-term (This Week):**
1. Run comprehensive optimization
2. Validate best config on 90-day period
3. Analyze zone performance
4. Test POC filter impact

**Medium-term (Next 2 Weeks):**
1. Paper trade with optimal settings
2. Track results vs backtest predictions
3. Fine-tune if needed
4. Build confidence before going live

**Long-term (Monthly):**
1. Re-run optimization with latest data
2. Update trading parameters if needed
3. Review and improve level selection
4. Scale up size as results prove out

---

**Good luck with your NQ trading! 🚀**

Remember: The ES bot optimization found a 3x improvement (34% → 67% win rate). The same methodology should work for NQ, but expect slightly lower win rates due to higher volatility.
