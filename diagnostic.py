#!/usr/bin/env python3
"""
Diagnostic script to test Databento connection and data retrieval

This script helps diagnose issues with the market data analyzer by:
1. Testing Databento API connection
2. Fetching a small sample of data
3. Displaying data structure and format
4. Identifying potential issues
"""

from market_data_analyzer import MarketDataAnalyzer
import pandas as pd


def test_connection():
    """Test basic connection to Databento"""
    print("="*60)
    print("DIAGNOSTIC TEST - Databento Connection")
    print("="*60)

    try:
        analyzer = MarketDataAnalyzer()
        print("✓ Successfully initialized analyzer with API key")
        return analyzer
    except ValueError as e:
        print(f"✗ Failed to initialize: {e}")
        print("\nPlease check:")
        print("1. You have created a .env file (copy from .env.example)")
        print("2. Your DATABENTO_API_KEY is set in the .env file")
        print("3. Your API key starts with 'db-'")
        return None
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return None


def test_data_fetch(analyzer):
    """Test fetching a small amount of data"""
    print("\n" + "="*60)
    print("DIAGNOSTIC TEST - Data Fetch")
    print("="*60)

    # Fetch just one day of data to test
    print("\nFetching one day of ES.FUT data (2024-12-02)...")

    try:
        df = analyzer.fetch_data(
            symbol='ES.FUT',
            start_date='2024-12-02',
            end_date='2024-12-03',
            dataset='GLBX.MDP3',
            schema='ohlcv-1m'
        )

        if df.empty:
            print("✗ No data returned")
            print("\nPossible issues:")
            print("1. Your Databento subscription doesn't include this dataset")
            print("2. The date range is outside your subscription period")
            print("3. The symbol format is incorrect")
            return None

        print(f"\n✓ Successfully fetched {len(df)} records")
        return df

    except Exception as e:
        print(f"✗ Error fetching data: {e}")
        print("\nPossible issues:")
        print("1. Invalid API key")
        print("2. No subscription to GLBX.MDP3 dataset")
        print("3. Network connectivity issues")
        return None


def test_data_structure(df):
    """Analyze the data structure"""
    print("\n" + "="*60)
    print("DIAGNOSTIC TEST - Data Structure")
    print("="*60)

    print(f"\nDataFrame shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    print(f"Index type: {type(df.index)}")
    print(f"Index name: {df.index.name}")

    print("\nData types:")
    print(df.dtypes)

    print("\nFirst 5 rows:")
    print(df.head())

    print("\nLast 5 rows:")
    print(df.tail())

    print("\nBasic statistics:")
    print(df[['open', 'high', 'low', 'close', 'volume']].describe())

    # Check for required columns
    required = ['open', 'high', 'low', 'close', 'volume']
    missing = [col for col in required if col not in df.columns]

    if missing:
        print(f"\n✗ WARNING: Missing required columns: {missing}")
    else:
        print(f"\n✓ All required columns present")

    # Check for NaN values
    nan_counts = df.isna().sum()
    if nan_counts.any():
        print(f"\n✗ WARNING: Found NaN values:")
        print(nan_counts[nan_counts > 0])
    else:
        print(f"\n✓ No NaN values found")

    # Check timezone
    if df.index.tz:
        print(f"\n✓ Index is timezone-aware: {df.index.tz}")
    else:
        print(f"\n✗ WARNING: Index is not timezone-aware")


def test_resample(analyzer, df):
    """Test resampling to different timeframe"""
    print("\n" + "="*60)
    print("DIAGNOSTIC TEST - Resampling")
    print("="*60)

    try:
        print("\nResampling to 5-minute candles...")
        df_5min = analyzer.resample_candles(df, '5T')

        print(f"\n✓ Successfully resampled to {len(df_5min)} candles")
        print(f"Original: {len(df)} 1-minute candles")
        print(f"Resampled: {len(df_5min)} 5-minute candles")

        print("\nFirst 5 resampled candles:")
        print(df_5min.head())

        return df_5min

    except Exception as e:
        print(f"✗ Error resampling: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_plot(analyzer, df):
    """Test plotting"""
    print("\n" + "="*60)
    print("DIAGNOSTIC TEST - Plotting")
    print("="*60)

    try:
        print("\nAttempting to create chart...")
        print("(Chart window should open - close it to continue)")

        analyzer.plot_candlestick_plotly(
            df,
            title="Diagnostic Test Chart",
            save_path="diagnostic_test_chart.html"
        )

        print("\n✓ Chart created successfully")
        print("Check diagnostic_test_chart.html in your browser")

    except Exception as e:
        print(f"✗ Error creating chart: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all diagnostic tests"""
    print("\n" + "="*70)
    print("MARKET DATA ANALYZER - DIAGNOSTIC TOOL")
    print("="*70)
    print("\nThis tool will help diagnose issues with your setup.\n")

    # Test 1: Connection
    analyzer = test_connection()
    if not analyzer:
        print("\n" + "="*70)
        print("DIAGNOSTIC FAILED - Cannot connect to Databento")
        print("="*70)
        return

    # Test 2: Data fetch
    df = test_data_fetch(analyzer)
    if df is None:
        print("\n" + "="*70)
        print("DIAGNOSTIC FAILED - Cannot fetch data")
        print("="*70)
        print("\nTroubleshooting steps:")
        print("1. Verify your Databento subscription includes GLBX.MDP3 dataset")
        print("2. Try a different date within your subscription period")
        print("3. Check your API key permissions at https://databento.com/portal")
        return

    # Test 3: Data structure
    test_data_structure(df)

    # Test 4: Resampling
    df_resampled = test_resample(analyzer, df)

    # Test 5: Plotting
    if df_resampled is not None and not df_resampled.empty:
        test_plot(analyzer, df_resampled)

    print("\n" + "="*70)
    print("DIAGNOSTIC COMPLETE")
    print("="*70)
    print("\nIf all tests passed, your setup is working correctly.")
    print("If you're still having issues, please share the output above.")


if __name__ == "__main__":
    main()
