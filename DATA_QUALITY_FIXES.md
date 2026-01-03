# Data Quality & Timezone Fixes

## Issues Fixed

### 1. Bad/Corrupt Data (CRITICAL)
**Problem:** The script was receiving corrupt data with impossible prices (e.g., open=55.90, high=6798.00)

**Root Causes:**
- Multiple symbols mixed in the same dataset
- Bad ticks from exchange
- Outlier data points

**Fixes:**
- Added `_validate_ohlcv_data()` method that:
  - Checks `high >= low` (basic sanity)
  - Validates `open` and `close` are within `[low, high]`
  - Detects extreme outliers using IQR method (3*IQR threshold)
  - Removes zero or negative prices
  - Reports all removed data with details

- Added symbol filtering:
  - Checks for multiple symbols in returned data
  - Filters to keep only the primary symbol
  - Warns if multiple symbols detected

### 2. Timezone Issues
**Problem:** Using US/Eastern timezone could cause ambiguity with date strings

**Example Issue:**
- Request: `start_date='2025-10-20'`
- With US/Eastern: Unclear if this means midnight Eastern or UTC
- Could miss data or get wrong date range

**Fixes:**
- **All data now stored in UTC** for clarity and safety
- RTH filtering still works correctly:
  - RTH hours defined in US/Eastern (9:30-16:00 for ES)
  - Temporarily converts to US/Eastern for filtering
  - Converts back to UTC after filtering
- Added `convert_timezone()` method for display if needed

**Why UTC is Better:**
- Unambiguous date/time interpretation
- No DST (daylight saving time) complications
- Standard for financial data
- Easier to work with multiple markets/timezones

### 3. Better Debugging & Validation
**Added:**
- Detailed column/datatype logging
- Price range validation before plotting
- Data quality checks (reports pass/fail)
- Sample data display
- Clear indication that timestamps = START of candle period

## How to Use the Fixed Version

### Basic Usage (UTC - Recommended)
```python
from market_data_analyzer import MarketDataAnalyzer

analyzer = MarketDataAnalyzer()

# Fetch data - times in UTC
df = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-10-20',
    end_date='2025-10-24',
    timeframe='5T',
    rth_only=True
)

# Data is in UTC - timestamps show UTC times
# RTH filtering still works (internally converts to US/Eastern)
```

### Convert to Local Timezone for Display
```python
# If you want to see times in US/Eastern
df_eastern = analyzer.convert_timezone(df, 'US/Eastern')

# Or any other timezone
df_london = analyzer.convert_timezone(df, 'Europe/London')
df_tokyo = analyzer.convert_timezone(df, 'Asia/Tokyo')
```

### Understanding the Output

The script now prints clear validation info:

```
Columns in data: ['open', 'high', 'low', 'close', 'volume', 'symbol']
Symbols in data: ['ESZ4']

WARNING: Found 4 extreme price outliers
  Price bounds: 6700.00 to 6900.00
  Sample outliers:
                              open   high    low  close  volume
2025-10-20 09:30:00+00:00    55.90  6798.00  55.90  6798.00  15715

Data validation: Removed 4 corrupt/outlier rows (0.3%)
Clean data: 1560 rows remaining

============================================================
DATA SUMMARY
============================================================
Symbol: ES.FUT
Request Range: 2025-10-20 to 2025-10-24
Timeframe: 5T
RTH Only: True
Total Candles: 312
Actual Range: 2025-10-20 13:30:00+00:00 to 2025-10-23 20:00:00+00:00
  (All times in UTC)
  (Each timestamp = START of candle period)
Price Range: $6741.75 - $6850.25
Avg Volume: 8432
============================================================
```

**Note the UTC timestamps:**
- `13:30:00+00:00` = 9:30 AM Eastern
- `20:00:00+00:00` = 4:00 PM Eastern

## Data Quality Checks

The script now validates:

1. **High >= Low**: Basic sanity check
2. **Open in [Low, High]**: Open price must be within the bar's range
3. **Close in [Low, High]**: Close price must be within the bar's range
4. **Outlier Detection**: Uses IQR method to detect extreme outliers
5. **Positive Prices**: Removes zero or negative prices
6. **Symbol Filtering**: Ensures only one symbol in the dataset

## Interpreting Timestamps

**Important:** All timestamps represent the **START** of each candle period.

For 1-minute candles:
- `2025-10-20 13:30:00+00:00` = candle from 13:30:00 to 13:30:59.999
- `2025-10-20 13:31:00+00:00` = candle from 13:31:00 to 13:31:59.999

For 5-minute candles:
- `2025-10-20 13:30:00+00:00` = candle from 13:30:00 to 13:34:59.999
- `2025-10-20 13:35:00+00:00` = candle from 13:35:00 to 13:39:59.999

## Troubleshooting

### "WARNING: Found X extreme price outliers"
This is normal! The script detected and removed bad data:
- Check the sample outliers shown
- These are automatically removed
- Clean data count is reported

### "WARNING: Multiple symbols found"
Databento sometimes returns data for multiple symbols:
- Script automatically filters to the primary symbol
- Check which symbol was kept
- If wrong symbol, try being more specific in your request

### Times Look Wrong
Remember: all times are in UTC!
- Add 4-5 hours for US/Eastern (depending on DST)
- RTH 9:30-16:00 Eastern = 13:30-20:00 UTC (EST) or 13:30-20:00 UTC (EDT)
- Use `convert_timezone()` to display in your local timezone

## Migration Guide

If you were using the old version:

### Old (US/Eastern)
```python
df = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-10-20',
    end_date='2025-10-24',
    timeframe='5T'
)
# Times were in US/Eastern
```

### New (UTC)
```python
df = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-10-20',  # Interpreted as UTC
    end_date='2025-10-24',
    timeframe='5T'
)
# Times are now in UTC

# Convert to Eastern if needed
df = analyzer.convert_timezone(df, 'US/Eastern')
```

## Benefits of These Fixes

1. **Clean Data**: No more corrupt/outlier prices in your charts
2. **Accurate Analysis**: Statistical analysis on clean data only
3. **Clear Timestamps**: No ambiguity about timezone
4. **Better Debugging**: See exactly what data was received and cleaned
5. **Safer**: UTC prevents DST and timezone interpretation issues

## Questions?

Run the diagnostic tool to see the full data pipeline:
```bash
python diagnostic.py
```

This will show you:
- Raw data from Databento
- Data validation steps
- Outlier detection
- Final clean data
- Sample chart
