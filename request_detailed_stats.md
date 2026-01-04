# Request for Detailed GC Backtest Statistics

To fully understand the low win rate, we need to see the SCRATCH trade breakdown.

## What to run:

Add this to the end of your `optimize_parameters_GC.py` after a test completes:

```python
# After line 156, add:
scratches = df_trades[df_trades['outcome'] == 'SCRATCH']
print(f"   Scratches: {len(scratches)} ({len(scratches)/total_trades*100:.1f}%)")
if len(scratches) > 0:
    print(f"   Scratch avg P&L: ${scratches['pnl'].mean()*20:.2f}")
```

## Or run this one-time diagnostic:

```python
from backtest_bot_GC_COMPLETE import TradingBotBacktester
from datetime import datetime
import pandas as pd

backtester = TradingBotBacktester(
    start_date=datetime(2024, 11, 1),
    end_date=datetime(2024, 12, 31),
    signal_cooldown_minutes=60,
    target_points=25.0,
    stop_points=12.0
)

backtester.generate_historical_plans()
backtester.run_backtest()

df = pd.DataFrame(backtester.trades)

print("\nOUTCOME BREAKDOWN:")
print(df['outcome'].value_counts())
print("\nP&L BY OUTCOME:")
for outcome in ['WIN', 'LOSS', 'SCRATCH']:
    subset = df[df['outcome'] == outcome]
    if len(subset) > 0:
        print(f"{outcome}: {len(subset)} trades, Avg P&L: ${subset['pnl'].mean()*100:.2f}")
```

## What we're looking for:

1. How many SCRATCH trades?
2. What's the average P&L of scratches?
3. Are scratches contributing significantly to the $129 expectancy?

## Hypothesis:

Your "low" 22.7% WR is actually masking a more complex picture:
- 22.7% = Full 25pt target hits ($2,500 each)
- ~50% = Full 12pt stop losses (-$1,200 each)
- ~27% = SCRATCH trades (small positive P&L, maybe $200-500 average)

This would explain why you're profitable despite being "below break-even."
