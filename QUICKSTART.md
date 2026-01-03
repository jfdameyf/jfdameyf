# Quick Start Guide

Get up and running with the Market Data Analyzer in 5 minutes!

**Latest Updates:**
- ✅ Data quality validation (removes corrupt/outlier prices)
- ✅ All timestamps now in UTC for clarity
- ✅ Better debugging and error messages
- ✅ See [DATA_QUALITY_FIXES.md](DATA_QUALITY_FIXES.md) for details

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 2: Configure API Key

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Edit `.env` and add your Databento API key:
```
DATABENTO_API_KEY=db-your-actual-key-here
```

Get your key from: https://databento.com/portal

## Step 3: Run Your First Analysis

Create a file called `my_analysis.py`:

```python
from market_data_analyzer import MarketDataAnalyzer

# Initialize
analyzer = MarketDataAnalyzer()

# Analyze ES futures for your desired date range
df = analyzer.analyze(
    symbol='ES.FUT',                # E-mini S&P 500
    start_date='2025-10-20',        # Start date
    end_date='2025-10-24',          # End date
    timeframe='5T',                 # 5-minute candles
    rth_only=True,                  # Regular Trading Hours only
    plot_type='plotly',             # Interactive chart
    save_chart=True                 # Save to HTML file
)

# Save data to CSV
df.to_csv('my_market_data.csv')
print("Analysis complete! Check the HTML and CSV files.")
```

Run it:
```bash
python my_analysis.py
```

**Note:** All timestamps are in UTC. For US markets:
- RTH 9:30 AM Eastern = 13:30 or 14:30 UTC (depending on DST)
- The script handles this automatically for RTH filtering
- See "Understanding Timestamps" section below

## Step 4: Explore Examples

Check out the 10 example use cases:

```bash
python examples.py
```

Edit `examples.py` and uncomment the example you want to run.

## Common Use Cases

### Analyze Different Timeframes

```python
# 1-minute candles for intraday analysis
df_1min = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-10-20',
    end_date='2025-10-20',
    timeframe='1T'
)

# 15-minute candles for swing trading
df_15min = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-10-20',
    end_date='2025-10-24',
    timeframe='15T'
)
```

### Compare Multiple Symbols

```python
symbols = ['ES.FUT', 'NQ.FUT', 'YM.FUT']

for symbol in symbols:
    df = analyzer.analyze(
        symbol=symbol,
        start_date='2025-10-20',
        end_date='2025-10-24',
        timeframe='5T',
        save_chart=True
    )
```

### Extended Hours Analysis

```python
# Include all trading hours (not just RTH)
df = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-10-20',
    end_date='2025-10-21',
    timeframe='5T',
    rth_only=False  # This is the key
)
```

## Timeframe Reference

| Code | Meaning |
|------|---------|
| `1T` | 1 minute |
| `3T` | 3 minutes |
| `5T` | 5 minutes |
| `15T` | 15 minutes |
| `30T` | 30 minutes |
| `1H` | 1 hour |
| `1D` | 1 day |

## Popular Symbols

| Symbol | Description |
|--------|-------------|
| `ES.FUT` | E-mini S&P 500 |
| `NQ.FUT` | E-mini NASDAQ-100 |
| `YM.FUT` | E-mini Dow Jones |
| `RTY.FUT` | E-mini Russell 2000 |
| `GC.FUT` | Gold Futures |
| `CL.FUT` | Crude Oil Futures |

## Understanding Timestamps

**All timestamps are in UTC (Coordinated Universal Time)**

### What This Means
- Each timestamp represents the **START** of a candle period
- For 1-minute candles: `13:30:00` = candle from 13:30:00 to 13:30:59
- For 5-minute candles: `13:30:00` = candle from 13:30:00 to 13:34:59

### UTC to US/Eastern Conversion
- **EST (winter):** UTC - 5 hours  → 13:30 UTC = 8:30 AM EST
- **EDT (summer):** UTC - 4 hours → 13:30 UTC = 9:30 AM EDT

### RTH (Regular Trading Hours)
The script automatically handles RTH filtering:
- RTH for ES: 9:30 AM - 4:00 PM Eastern
- In UTC: ~13:30-20:00 (EST) or ~13:30-20:00 (EDT)
- The script converts internally - you don't need to worry about it!

### Convert to Your Timezone
```python
# Convert to US/Eastern for display
df_eastern = analyzer.convert_timezone(df, 'US/Eastern')

# Convert to other timezones
df_london = analyzer.convert_timezone(df, 'Europe/London')
df_tokyo = analyzer.convert_timezone(df, 'Asia/Tokyo')
```

## Data Quality & Validation

The script automatically validates and cleans data:

✅ **Checks performed:**
- High >= Low
- Open and Close within [Low, High]
- Outlier detection (removes extreme prices)
- Filters out zero/negative prices
- Symbol filtering (single symbol only)

✅ **What you'll see:**
```
WARNING: Found 4 extreme price outliers
  Price bounds: 6700.00 to 6900.00
Data validation: Removed 4 corrupt rows (0.3%)
Clean data: 1560 rows remaining
```

This is normal and good! The script detected and removed bad data automatically.

## Troubleshooting

### Run the Diagnostic Tool

If you're having issues, run the diagnostic script first:

```bash
python diagnostic.py
```

This will test your setup and identify potential problems.

### Common Issues

**Problem: "No data returned"**
- Check your date range is within your Databento subscription
- Verify the symbol format (use `.FUT` suffix)
- Try a different date range
- Run `python diagnostic.py` to test your connection

**Problem: "API key not found"**
- Make sure you created the `.env` file
- Check that your key starts with `db-`
- Verify the key in your Databento portal

**Problem: "Chart looks weird/compressed"**
- This was fixed in the latest version
- Make sure you have the latest code
- The debug output will show what data was received
- Check that OHLCV columns are present in the output

**Problem: "Chart not displaying"**
- If using Plotly, it will open in your browser
- Check if an HTML file was created
- Try `plot_type='matplotlib'` instead

## Next Steps

1. Read the full [MARKET_DATA_README.md](MARKET_DATA_README.md)
2. Explore all examples in `examples.py`
3. Customize the RTH hours for your trading strategy
4. Build your own analysis workflows!

---

Happy trading! 📈
