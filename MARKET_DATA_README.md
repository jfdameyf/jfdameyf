# Market Data Analyzer

A Python tool for fetching, analyzing, and visualizing historical market data from Databento. This tool allows you to bypass TradingView's 1-month limitation on 1-minute data and analyze historical market behavior during different volatility regimes and market conditions.

## Features

- **Fetch Historical Data**: Retrieve market data for any date range using Databento API
- **Custom Timeframes**: Rebuild candles at any timeframe (1min, 3min, 5min, 15min, etc.)
- **RTH Filtering**: Filter for Regular Trading Hours (RTH) with pre-configured hours for major futures
- **Interactive Visualizations**: Create candlestick charts using both Matplotlib and Plotly
- **Multi-Symbol Support**: Analyze equity indices, commodities, bonds, and more
- **Data Export**: Save processed data to CSV or Excel for further analysis
- **Volatility Analysis**: Compare market behavior across different time periods

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd jfdameyf
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

3. Set up your Databento API key:
```bash
cp .env.example .env
# Edit .env and add your Databento API key
```

Get your API key from [Databento Portal](https://databento.com/portal)

## Quick Start

### Basic Usage

```python
from market_data_analyzer import MarketDataAnalyzer

# Initialize analyzer
analyzer = MarketDataAnalyzer()

# Fetch and visualize 5-minute candles for ES futures
df = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-10-20',
    end_date='2025-10-24',
    timeframe='5T',      # 5-minute candles
    rth_only=True,       # Regular Trading Hours only
    plot_type='plotly'   # Interactive chart
)

# Save the data
df.to_csv('es_data.csv')
```

### Running Examples

The `examples.py` file contains 10 different use cases. Edit the file and uncomment the example you want to run:

```bash
python examples.py
```

## Supported Timeframes

Use pandas time offset strings:
- `'1T'` - 1 minute
- `'3T'` - 3 minutes
- `'5T'` - 5 minutes
- `'15T'` - 15 minutes
- `'30T'` - 30 minutes
- `'1H'` - 1 hour
- `'1D'` - 1 day

## Supported Symbols

The analyzer works with any symbol available in your Databento dataset. Common symbols:

### Equity Index Futures
- `ES.FUT` - E-mini S&P 500
- `NQ.FUT` - E-mini NASDAQ-100
- `YM.FUT` - E-mini Dow Jones
- `RTY.FUT` - E-mini Russell 2000

### Commodities
- `GC.FUT` - Gold
- `SI.FUT` - Silver
- `CL.FUT` - Crude Oil
- `NG.FUT` - Natural Gas

### Bonds
- `ZB.FUT` - 30-Year Treasury Bond
- `ZN.FUT` - 10-Year Treasury Note

## Regular Trading Hours (RTH)

Pre-configured RTH for major markets:

| Symbol | RTH Start | RTH End   |
|--------|-----------|-----------|
| ES, NQ, YM, RTY | 9:30 AM | 4:00 PM |
| GC     | 8:20 AM   | 1:30 PM   |
| CL     | 9:00 AM   | 2:30 PM   |
| ZB     | 8:20 AM   | 3:00 PM   |

You can also specify custom hours:

```python
from datetime import time

df = analyzer.filter_rth(
    df,
    custom_start=time(3, 0),   # 3:00 AM
    custom_end=time(11, 30)     # 11:30 AM
)
```

## Advanced Usage

### Compare Different Timeframes

```python
analyzer = MarketDataAnalyzer()

for timeframe in ['1T', '3T', '5T', '15T']:
    df = analyzer.analyze(
        symbol='ES.FUT',
        start_date='2025-10-20',
        end_date='2025-10-24',
        timeframe=timeframe,
        save_chart=True
    )
```

### Analyze Volatility Regimes

```python
# Low volatility period
df_low = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-07-01',
    end_date='2025-07-05',
    timeframe='5T'
)

# High volatility period
df_high = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-08-05',
    end_date='2025-08-09',
    timeframe='5T'
)

# Compare average ranges
low_vol_range = (df_low['high'] - df_low['low']).mean()
high_vol_range = (df_high['high'] - df_high['low']).mean()
print(f"Low vol avg range: {low_vol_range:.2f}")
print(f"High vol avg range: {high_vol_range:.2f}")
```

### Extended Hours Analysis

```python
# Include all trading hours (not just RTH)
df = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-10-20',
    end_date='2025-10-21',
    timeframe='5T',
    rth_only=False  # Include extended hours
)
```

### Intraday Analysis

```python
# Analyze just the opening hour
df = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-10-20 09:30',
    end_date='2025-10-20 10:30',
    timeframe='1T'
)
```

## API Reference

### MarketDataAnalyzer Class

#### `__init__(api_key: Optional[str] = None)`
Initialize the analyzer with your Databento API key.

#### `fetch_data(symbol, start_date, end_date, dataset='GLBX.MDP3', schema='ohlcv-1m')`
Fetch raw data from Databento.

**Parameters:**
- `symbol` (str): Trading symbol (e.g., 'ES.FUT')
- `start_date` (str): Start date ('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM')
- `end_date` (str): End date ('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM')
- `dataset` (str): Databento dataset (default: 'GLBX.MDP3')
- `schema` (str): Data schema (default: 'ohlcv-1m')

**Returns:** DataFrame with OHLCV data

#### `filter_rth(df, symbol_prefix=None, custom_start=None, custom_end=None)`
Filter DataFrame to Regular Trading Hours.

**Parameters:**
- `df` (DataFrame): DataFrame with datetime index
- `symbol_prefix` (str): Symbol prefix for RTH lookup
- `custom_start` (time): Custom RTH start time
- `custom_end` (time): Custom RTH end time

**Returns:** Filtered DataFrame

#### `resample_candles(df, timeframe='5T')`
Resample OHLCV data to different timeframe.

**Parameters:**
- `df` (DataFrame): DataFrame with OHLCV data
- `timeframe` (str): Target timeframe (e.g., '1T', '5T', '15T')

**Returns:** Resampled DataFrame

#### `plot_candlestick_matplotlib(df, title, figsize=(16,8), save_path=None)`
Create static candlestick chart with Matplotlib.

#### `plot_candlestick_plotly(df, title, save_path=None)`
Create interactive candlestick chart with Plotly.

#### `analyze(symbol, start_date, end_date, timeframe='5T', rth_only=True, plot_type='plotly', save_chart=False)`
Complete workflow: fetch, process, and visualize.

**Parameters:**
- `symbol` (str): Trading symbol
- `start_date` (str): Start date
- `end_date` (str): End date
- `timeframe` (str): Target timeframe
- `rth_only` (bool): Filter for RTH only
- `plot_type` (str): 'matplotlib', 'plotly', or 'both'
- `save_chart` (bool): Save chart to file

**Returns:** Processed DataFrame

## Databento Datasets

Common datasets:
- `GLBX.MDP3` - CME Globex MDP 3.0 (equity index futures, rates, FX)
- `XNAS.ITCH` - Nasdaq TotalView-ITCH
- `XNYS.TRADES` - NYSE Trades
- `DBEQ.BASIC` - Databento Equities Basic

See [Databento Datasets](https://databento.com/docs/knowledge-base/new-users/datasets) for full list.

## Troubleshooting

### API Key Issues
- Ensure your `.env` file has `DATABENTO_API_KEY=db-your-key`
- Verify your key at https://databento.com/portal
- Check that the key starts with `db-`

### No Data Returned
- Verify the symbol format (use '.FUT' suffix for futures)
- Check that dates are within your Databento subscription
- Ensure the dataset contains your symbol
- Try without RTH filtering first

### Visualization Not Showing
- For Plotly: Check if running in Jupyter notebook or script
- For Matplotlib: Ensure `plt.show()` is called
- Try saving to file with `save_chart=True`

## Example Workflows

### Workflow 1: Daily Market Analysis

```python
analyzer = MarketDataAnalyzer()

# Analyze today's trading
from datetime import datetime, timedelta

today = datetime.now().strftime('%Y-%m-%d')
df = analyzer.analyze(
    symbol='ES.FUT',
    start_date=today,
    end_date=today,
    timeframe='5T',
    plot_type='plotly'
)
```

### Workflow 2: Historical Pattern Study

```python
# Study how ES.FUT behaved during a specific event
df = analyzer.analyze(
    symbol='ES.FUT',
    start_date='2025-08-05',  # Volatile period
    end_date='2025-08-09',
    timeframe='3T',
    save_chart=True
)

# Calculate key metrics
daily_range = df.groupby(df.index.date).apply(
    lambda x: x['high'].max() - x['low'].min()
)
print(f"Daily ranges:\n{daily_range}")
```

### Workflow 3: Multi-Timeframe Analysis

```python
analyzer = MarketDataAnalyzer()
date_range = ('2025-10-20', '2025-10-24')

# Create analysis at multiple timeframes
for tf in ['1T', '5T', '15T', '1H']:
    print(f"\n{tf} Analysis:")
    df = analyzer.analyze(
        symbol='NQ.FUT',
        start_date=date_range[0],
        end_date=date_range[1],
        timeframe=tf,
        save_chart=True
    )

    # Print statistics
    print(f"Candles: {len(df)}")
    print(f"Avg volume: {df['volume'].mean():.0f}")
    print(f"Range: {df['high'].max() - df['low'].min():.2f}")
```

## Performance Tips

1. **Use appropriate timeframes**: Don't request 1-minute data for months of history
2. **Filter early**: Apply RTH filtering before resampling for faster processing
3. **Batch requests**: Fetch multiple symbols separately rather than in one large request
4. **Cache results**: Save DataFrames to CSV for reuse

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This project is provided as-is for educational and research purposes.

## Resources

- [Databento Documentation](https://databento.com/docs)
- [Databento Python Library](https://github.com/databento/databento-python)
- [Databento Examples](https://databento.com/docs/examples)

## Support

For issues with:
- **This tool**: Open an issue in this repository
- **Databento API**: Contact [Databento Support](https://databento.com/support)
- **Data questions**: Check [Databento Knowledge Base](https://databento.com/docs/knowledge-base)

---

**Happy analyzing!** Use this tool to gain insights into market behavior across different volatility regimes and time periods.
