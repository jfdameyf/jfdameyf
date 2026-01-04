# GC Performance Crisis - Diagnosis & Fix

## 🚨 Critical Issues Found

### Issue #1: Missing/Outdated Levels File ❌

**Problem:** No GC levels file exists, or it's using old pit session hours (8:20-13:30)

**Evidence:**
- Level types showing as "UNKNOWN" for all trades
- Only 26 trades over 2 months (0.5 trades/day)
- This should be 1-2 trades/day minimum

**Fix Required:**
```bash
# Generate fresh GC levels with new RTH hours (9:30-16:15)
python3 generate_levels_ENHANCED_GC.py
```

---

### Issue #2: Extended Hours May Be Destroying Performance 📉

**The Data Shows:**

| Metric | Value | Status |
|--------|-------|--------|
| Best expectancy | -$1.16/trade | 🔴 LOSING |
| Best P&L | -$36 over 2 months | 🔴 LOSING |
| Best win rate | 29% | 🔴 TERRIBLE |
| Trades per day | 0.5-0.6 | 🔴 TOO LOW |

**Hypothesis:** Gold afternoon session (1:30-4:15 PM) has terrible liquidity/volatility

**Evidence:**
- Gold pit session is 8:20 AM - 1:30 PM for a reason
- European markets close at 11:30 AM ET
- Afternoon gold is notoriously choppy

---

### Issue #3: Zone 3 is THE ONLY WINNER 🤔

**Counterintuitive Finding:**

```
Z1: 4t WR=25% Exp=$-212    🔴 LOSING
Z2: 13t WR=23% Exp=$-160   🔴 LOSING
Z3: 5t WR=40% Exp=$80      ✅ WINNING (only 5 trades)
Z4: 4t WR=25% Exp=$-138    🔴 LOSING
```

**What This Means:**
- Zone 1 (strongest levels) is LOSING
- Zone 3 (weaker levels) is WINNING
- This suggests the strategy fundamentals are broken for these hours
- OR: Zone 3 captures recapture/trend trades better in choppy conditions

---

### Issue #4: SINGLE_PRINT Category is Toxic ☠️

```
SINGLE_PRINT: 21t WR=24% Exp=$-194   🔴 DISASTER
SUPER_WALL: 2t WR=50% Exp=$400       ✅ GOOD (but only 2 trades!)
MAGNET: 3t WR=33% Exp=$67            ✅ OK (but only 3 trades!)
```

**Analysis:**
- 80% of trades are single prints
- They're losing badly
- Super walls are rare but work
- The afternoon session probably creates tons of false single prints

---

## 🔧 Fix Strategy

### Option 1: Revert to Pit Session Hours (RECOMMENDED)

**Revert to 8:20 AM - 1:30 PM ET**

Why:
- Gold pit session has real institutional flow
- Electronic afternoon is low liquidity
- Original ES/NQ optimization used RTH because they have liquidity all day
- Gold is different

**How to revert:**

1. Edit `generate_levels_ENHANCED_GC.py` line 454:
```python
# REVERT THIS:
rth = df.between_time('09:30', '16:15').copy()

# BACK TO THIS:
rth = df.between_time('08:20', '13:30').copy()
```

2. Edit `backtest_bot_GC_COMPLETE.py` line 139:
```python
# REVERT THIS:
start_dt = NY_TZ.localize(datetime.combine(test_date, time(9, 30)))
end_dt = NY_TZ.localize(datetime.combine(test_date, time(16, 15)))

# BACK TO THIS:
start_dt = NY_TZ.localize(datetime.combine(test_date, time(8, 20)))
end_dt = NY_TZ.localize(datetime.combine(test_date, time(13, 30)))
```

3. Edit line 157:
```python
# REVERT THIS:
bars = bars.between_time('09:30', '16:15')

# BACK TO THIS:
bars = bars.between_time('08:20', '13:30')
```

4. Edit line 180:
```python
# REVERT THIS:
if not ((hour == 9 and minute >= 30) or (10 <= hour < 16) or (hour == 16 and minute <= 15)):

# BACK TO THIS:
if not ((hour == 8 and minute >= 20) or (9 <= hour < 13) or (hour == 13 and minute <= 30)):
```

5. Do the same for `trading_bot_GC_FIXED.py` (lines 408, 445)

6. **Regenerate levels:**
```bash
python3 generate_levels_ENHANCED_GC.py
```

7. **Re-run optimization:**
```bash
python3 optimize_parameters_GC.py
```

---

### Option 2: Test Hybrid Approach (9:30 AM - 1:30 PM)

**Compromise: Start at NY open, end at pit close**

- Captures US morning volatility
- Avoids dead afternoon
- Still gives 4 hours of trading

**How to implement:**

Change all RTH hours to:
```python
rth = df.between_time('09:30', '13:30').copy()
```

---

### Option 3: Keep Extended Hours but Filter Out Afternoon

**Keep 9:30-4:15 but don't trade after 1:30 PM**

Add to `backtest_bot_GC_COMPLETE.py` around line 182:

```python
# Skip afternoon trades
if hour >= 13 and minute >= 30:
    continue  # Don't trade after pit close
```

This lets you generate levels from full day but only trade the pit session.

---

## 🔬 Diagnostic: What Hour Destroyed You?

Create this script to see performance by hour:

```python
# Save as analyze_gc_by_hour.py
import pandas as pd
from backtest_bot_GC_COMPLETE import TradingBotBacktester
from datetime import datetime

backtester = TradingBotBacktester(
    start_date=datetime(2024, 11, 1),
    end_date=datetime(2024, 12, 31),
    signal_cooldown_minutes=15,
    target_points=8.0,
    stop_points=4.0
)

# Run backtest
backtester.generate_historical_plans()
backtester.run_backtest()

# Analyze by hour
df = pd.DataFrame(backtester.trades)

if len(df) > 0:
    df['entry_hour'] = pd.to_datetime(df['entry_time']).dt.hour

    print("\nPERFORMANCE BY HOUR:")
    print("="*60)

    for hour in sorted(df['entry_hour'].unique()):
        hour_trades = df[df['entry_hour'] == hour]
        wr = len(hour_trades[hour_trades['outcome'] == 'WIN']) / len(hour_trades) * 100
        exp = hour_trades['pnl'].mean() * 100

        print(f"Hour {hour:02d}:00 - {len(hour_trades):2d} trades | WR: {wr:5.1f}% | Exp: ${exp:6.0f}")
```

This will show you EXACTLY which hours are killing you.

---

## 💡 My Recommendation

**STEP 1: Revert to pit session (8:20-1:30)**

The extended hours experiment failed. Gold isn't ES/NQ - it's a different beast with different liquidity patterns.

**STEP 2: Regenerate levels with pit hours**

```bash
python3 generate_levels_ENHANCED_GC.py
```

**STEP 3: Re-run optimization**

```bash
python3 optimize_parameters_GC.py
```

**STEP 4: Compare to your earlier partial results**

You showed earlier results with 60min/25pt/12pt = 22.7% WR, $129 exp

If reverting to pit session gets you back to positive expectancy, we know the extended hours were the problem.

---

## 🎯 Expected Results After Revert

If this works, you should see:

- **2-3 trades per day** (instead of 0.5)
- **Positive expectancy** on at least some configs
- **Zone 1 > Zone 3** (normal hierarchy restored)
- **Level types populated** (not UNKNOWN)

If you STILL get terrible results after reverting:

- The levels generator might have a bug
- The signal logic might need adjustment
- Gold might just be harder to trade than ES/NQ
- The sample size (Nov-Dec 2024) might have been particularly bad for gold

---

## 🚫 What NOT to Do

**Don't try to "fix" the strategy while using extended hours**

The extended hours are masking what actually works. Revert first, then optimize.

**Don't trust the Zone 3 result**

It's only 5 trades with $80 expectancy. Could easily be luck.

**Don't trade this live**

Every single configuration is losing money. This needs to be fixed before any live trading.

---

## Next Steps

1. **Revert RTH hours** to 8:20-1:30 (pit session)
2. **Regenerate levels**
3. **Re-run optimizer**
4. **Report back** with new results

If the revert doesn't help, we'll dig deeper into:
- Level generation parameters (maybe thresholds too loose for GC)
- Signal logic (maybe proximity thresholds wrong)
- Time period (maybe Nov-Dec 2024 was just bad for gold)

But first, let's eliminate the obvious culprit: extended hours on a pit-traded instrument.
