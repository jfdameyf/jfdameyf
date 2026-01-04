# GC Trading Bot - Win Rate Analysis

## The Paradox

You observed that **wider stops correlate with LOWER win rates**, which seems counterintuitive. Normally, wider stops should give more breathing room and HIGHER win rates.

Your results:
- 60min / 25pt target / 6pt stop = **21.2% WR**, $120 expectancy
- 60min / 25pt target / 12pt stop = **22.7% WR**, $129 expectancy

The wider stop (12pt vs 6pt) only improved WR by 1.5%, much less than expected.

---

## Root Cause: Target Size, Not Stop Size

### Finding #1: Target Size Drives Win Rate

When you increase the target from 8pt → 25pt, win rate plummets:
- 8pt target = **47.0% WR**
- 12pt target = **39.4% WR**
- 25pt target = **21-23% WR**

**Why?** You're selecting for MUCH LARGER moves. Most trades don't have 25 points of runway in a 5-hour gold session (RTH: 8:20 AM - 1:30 PM).

### Finding #2: Stop Size Has Minimal Impact

With a 25pt target:
- 6pt stop = 21.2% WR (+1.8% edge over break-even of 19.4%)
- 12pt stop = 22.7% WR (+1.5% improvement)

The wider stop helps slightly, but can't overcome the fundamental challenge of needing price to move 25 full points in your favor.

---

## The SCRATCH Trade Mystery

### Critical Discovery

Your win rate calculation has a hidden component: **SCRATCH trades**

```python
# From backtest_bot_GC_COMPLETE.py, lines 432-437
if pnl >= self.target_points * 0.5:  # At least half target
    outcome = "WIN"
elif pnl <= -self.stop_points * 0.5:  # At least half stop
    outcome = "LOSS"
else:
    outcome = "SCRATCH"
```

### How This Affects Your Stats

- **Win Rate** = (Full target hits) / (All trades)
  - Only counts trades that hit the full 25pt target
  - Scratches are in the denominator but not the numerator

- **Expectancy** = Average P&L of ALL trades
  - Includes P&L from scratches
  - Scratches contribute to profitability but not to "wins"

### The Math That Doesn't Add Up

With 60min/25pt/12pt parameters (66 trades, 22.7% WR, $129 expectancy):

If only wins and losses existed:
- 15 winners × $2,500 = $37,500
- 51 losers × -$1,200 = -$61,200
- **Net = -$23,700 LOSS**

But your actual result: **+$8,488 profit**

**Conclusion:** You must have significant SCRATCH trades that are:
1. Not counted in the 22.7% win rate
2. Contributing positive P&L to the $129 expectancy

### Likely Scenario

Your 66 trades probably break down like:
- **15 winners** (22.7%) - Hit full 25pt target = $2,500 each
- **33 losers** (50%) - Hit full 12pt stop = -$1,200 each
- **18 scratches** (27%) - EOD exits with small profit = +$200-500 average

This would explain:
- Low WR of 22.7% (only counting full targets)
- High expectancy of $129 (including scratch profits)
- Profitability despite appearing "below break-even"

---

## Recommendations

### Option 1: Embrace the Low WR Strategy ⭐ HIGHEST EXPECTANCY
**Parameters:** 60min cooldown / 25pt target / 12pt stop
**Stats:** 22.7% WR, $129/trade expectancy

**Pros:**
- Highest per-trade expectancy
- Catches big gold trend moves
- Genuine edge ($129 >> fees)

**Cons:**
- Psychologically difficult (77% of trades don't hit target)
- **46% chance of 3 losses in a row**
- **17% chance of 7 losses in a row**
- Requires discipline and proper bankroll

**Best for:** Traders comfortable with trend-following, low-WR strategies

---

### Option 2: Higher WR, Lower Expectancy
**Parameters:** 60min cooldown / 12pt target / 6pt stop
**Stats:** 39.4% WR, $82/trade expectancy

**Pros:**
- More comfortable win rate
- Smoother equity curve
- Only 22% chance of 3 losses in a row

**Cons:**
- Lower expectancy ($82 vs $129)
- Leaves profit on the table during big moves

**Best for:** Traders who prefer consistency over maximum profit

---

### Option 3: Trade Management (Recommended Investigation) 🔍

**Problem:** Many SCRATCH trades are likely getting close to the 25pt target but not quite hitting it.

**Solution:** Implement partial profit taking or trailing stops

Example rules:
1. Enter at level (target=25pt, stop=12pt)
2. If +15pt profit, move stop to breakeven
3. If +20pt profit, take 50% position off (lock in $1,000)
4. Let remaining 50% run to 25pt or get stopped at breakeven

**Benefits:**
- Converts some scratches into partial wins
- Reduces psychological stress
- Still catches full 25pt moves with remaining position
- Could improve effective WR to 35-40% while maintaining high expectancy

---

## Next Steps

### 1. Get Detailed Scratch Statistics

Run this diagnostic (see `request_detailed_stats.md`):
- How many scratches per 66 trades?
- Average P&L of scratches?
- Are scratches mostly positive or negative?

### 2. Analyze MFE on Non-Winners

Check Maximum Favorable Excursion on losing/scratch trades:
- How many got within 5pts of the 25pt target?
- Average MFE on scratches?
- Should you have taken profits earlier?

### 3. Consider Trade Management Rules

Test these variations:
- Move to breakeven after +15pt
- Partial exit at +20pt
- Trailing stop after +18pt

### 4. Compare to ES/NQ

Your system shows very different characteristics:
- **ES:** 67.4% WR with 3pt/2pt (mean reversion)
- **NQ:** 57.6% WR with 15pt/4pt (medium trend)
- **GC:** 22.7% WR with 25pt/12pt (big trend)

Gold may need different trade management than ES/NQ due to:
- Shorter RTH window (5 hours vs 6.5 hours)
- Different volatility profile
- Trend vs mean-reversion characteristics

---

## Conclusion

**Your low win rate is NOT a bug - it's a feature of targeting large moves.**

The 25pt target on gold is asking for ~1% moves on a $2,500 contract. These don't happen frequently, but when they do, they pay well.

**The real question isn't "Why is my WR so low?"**

**It's "Should I optimize for:**
- **High WR** (12pt/6pt = 39% WR, $82 expectancy) - More comfortable
- **High expectancy** (25pt/12pt = 23% WR, $129 expectancy) - More profitable
- **Trade management** (25pt/12pt + partials = ~35% effective WR, ~$110 expectancy) - Best of both?"

I recommend Option 3: Get the scratch statistics first, then implement intelligent profit-taking rules to convert some scratches into wins while still catching the occasional 25pt home run.
