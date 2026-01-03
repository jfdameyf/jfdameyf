#!/usr/bin/env python3
"""
Example use cases for the Market Data Analyzer

This file demonstrates different ways to use the analyzer for various
market analysis scenarios.
"""

from market_data_analyzer import MarketDataAnalyzer
from datetime import time


def example_1_basic_usage():
    """Basic usage: Fetch and visualize 5-minute candles"""
    print("\n" + "="*60)
    print("EXAMPLE 1: Basic 5-minute candle analysis")
    print("="*60)

    analyzer = MarketDataAnalyzer()

    df = analyzer.analyze(
        symbol='ES.FUT',
        start_date='2025-10-20',
        end_date='2025-10-24',
        timeframe='5T',  # 5-minute candles
        rth_only=True,
        plot_type='plotly'
    )


def example_2_different_timeframes():
    """Compare different timeframes for the same period"""
    print("\n" + "="*60)
    print("EXAMPLE 2: Analyzing different timeframes")
    print("="*60)

    analyzer = MarketDataAnalyzer()

    timeframes = ['1T', '3T', '5T', '15T']

    for tf in timeframes:
        print(f"\nAnalyzing {tf} timeframe...")
        df = analyzer.analyze(
            symbol='NQ.FUT',  # NASDAQ E-mini
            start_date='2025-11-01',
            end_date='2025-11-05',
            timeframe=tf,
            rth_only=True,
            plot_type='plotly',
            save_chart=True
        )


def example_3_multiple_symbols():
    """Analyze multiple symbols for comparison"""
    print("\n" + "="*60)
    print("EXAMPLE 3: Multi-symbol analysis")
    print("="*60)

    analyzer = MarketDataAnalyzer()

    symbols = ['ES.FUT', 'NQ.FUT', 'YM.FUT', 'RTY.FUT']

    for symbol in symbols:
        print(f"\nAnalyzing {symbol}...")
        df = analyzer.analyze(
            symbol=symbol,
            start_date='2025-12-15',
            end_date='2025-12-16',
            timeframe='5T',
            rth_only=True,
            plot_type='plotly',
            save_chart=True
        )


def example_4_custom_hours():
    """Use custom trading hours instead of RTH defaults"""
    print("\n" + "="*60)
    print("EXAMPLE 4: Custom trading hours")
    print("="*60)

    analyzer = MarketDataAnalyzer()

    # Fetch full day data first
    df = analyzer.fetch_data(
        symbol='ES.FUT',
        start_date='2025-10-20',
        end_date='2025-10-21',
        dataset='GLBX.MDP3'
    )

    # Filter with custom hours (e.g., European session)
    df_custom = analyzer.filter_rth(
        df,
        custom_start=time(3, 0),   # 3:00 AM
        custom_end=time(11, 30)     # 11:30 AM
    )

    # Resample and visualize
    df_custom = analyzer.resample_candles(df_custom, '5T')
    analyzer.plot_candlestick_plotly(
        df_custom,
        title="ES.FUT - European Session (3:00-11:30)"
    )


def example_5_extended_hours():
    """Analyze extended trading hours (no RTH filter)"""
    print("\n" + "="*60)
    print("EXAMPLE 5: Extended hours analysis")
    print("="*60)

    analyzer = MarketDataAnalyzer()

    df = analyzer.analyze(
        symbol='ES.FUT',
        start_date='2025-10-20',
        end_date='2025-10-21',
        timeframe='5T',
        rth_only=False,  # Include all trading hours
        plot_type='plotly'
    )


def example_6_high_frequency():
    """High-frequency 1-minute analysis"""
    print("\n" + "="*60)
    print("EXAMPLE 6: High-frequency 1-minute candles")
    print("="*60)

    analyzer = MarketDataAnalyzer()

    df = analyzer.analyze(
        symbol='ES.FUT',
        start_date='2025-10-20 09:30',
        end_date='2025-10-20 16:00',
        timeframe='1T',  # 1-minute candles
        rth_only=True,
        plot_type='plotly',
        save_chart=True
    )


def example_7_volatility_regime_comparison():
    """Compare market behavior during different volatility regimes"""
    print("\n" + "="*60)
    print("EXAMPLE 7: Volatility regime comparison")
    print("="*60)

    analyzer = MarketDataAnalyzer()

    # Low volatility period
    print("\nAnalyzing low volatility period...")
    df_low_vol = analyzer.analyze(
        symbol='ES.FUT',
        start_date='2025-07-01',
        end_date='2025-07-05',
        timeframe='5T',
        rth_only=True,
        plot_type='plotly',
        save_chart=True
    )

    # High volatility period
    print("\nAnalyzing high volatility period...")
    df_high_vol = analyzer.analyze(
        symbol='ES.FUT',
        start_date='2025-08-05',
        end_date='2025-08-09',
        timeframe='5T',
        rth_only=True,
        plot_type='plotly',
        save_chart=True
    )

    # Compare statistics
    print("\nVolatility Comparison:")
    print(f"Low Vol Period - Avg Range: {(df_low_vol['high'] - df_low_vol['low']).mean():.2f}")
    print(f"High Vol Period - Avg Range: {(df_high_vol['high'] - df_high_vol['low']).mean():.2f}")


def example_8_save_data_for_analysis():
    """Fetch data and save it for further analysis"""
    print("\n" + "="*60)
    print("EXAMPLE 8: Export data for external analysis")
    print("="*60)

    analyzer = MarketDataAnalyzer()

    df = analyzer.analyze(
        symbol='ES.FUT',
        start_date='2025-10-01',
        end_date='2025-10-31',
        timeframe='5T',
        rth_only=True,
        plot_type='plotly'
    )

    # Save to CSV
    df.to_csv('es_october_2025_5min.csv')
    print("Data saved to es_october_2025_5min.csv")

    # Save to Excel (requires openpyxl: pip install openpyxl)
    try:
        df.to_excel('es_october_2025_5min.xlsx')
        print("Data saved to es_october_2025_5min.xlsx")
    except ImportError:
        print("Install openpyxl to save as Excel: pip install openpyxl")


def example_9_intraday_analysis():
    """Analyze specific intraday patterns"""
    print("\n" + "="*60)
    print("EXAMPLE 9: Intraday pattern analysis")
    print("="*60)

    analyzer = MarketDataAnalyzer()

    # Analyze just the opening hour
    df = analyzer.analyze(
        symbol='ES.FUT',
        start_date='2025-10-20 09:30',
        end_date='2025-10-20 10:30',
        timeframe='1T',
        rth_only=True,
        plot_type='plotly'
    )


def example_10_commodities():
    """Analyze commodities with different RTH"""
    print("\n" + "="*60)
    print("EXAMPLE 10: Commodity futures analysis")
    print("="*60)

    analyzer = MarketDataAnalyzer()

    # Gold futures
    df_gold = analyzer.analyze(
        symbol='GC.FUT',
        start_date='2025-10-20',
        end_date='2025-10-24',
        timeframe='5T',
        rth_only=True,
        plot_type='plotly',
        save_chart=True
    )

    # Crude Oil futures
    df_oil = analyzer.analyze(
        symbol='CL.FUT',
        start_date='2025-10-20',
        end_date='2025-10-24',
        timeframe='5T',
        rth_only=True,
        plot_type='plotly',
        save_chart=True
    )


if __name__ == "__main__":
    print("Market Data Analyzer - Example Usage")
    print("Select an example to run:\n")

    examples = [
        ("Basic 5-minute candle analysis", example_1_basic_usage),
        ("Different timeframes comparison", example_2_different_timeframes),
        ("Multi-symbol analysis", example_3_multiple_symbols),
        ("Custom trading hours", example_4_custom_hours),
        ("Extended hours analysis", example_5_extended_hours),
        ("High-frequency 1-minute candles", example_6_high_frequency),
        ("Volatility regime comparison", example_7_volatility_regime_comparison),
        ("Export data for external analysis", example_8_save_data_for_analysis),
        ("Intraday pattern analysis", example_9_intraday_analysis),
        ("Commodity futures analysis", example_10_commodities),
    ]

    for i, (desc, _) in enumerate(examples, 1):
        print(f"{i}. {desc}")

    print("\nUncomment the example you want to run in the code, or run all:")

    # Uncomment the example you want to run:
    # example_1_basic_usage()
    # example_2_different_timeframes()
    # example_3_multiple_symbols()
    # example_4_custom_hours()
    # example_5_extended_hours()
    # example_6_high_frequency()
    # example_7_volatility_regime_comparison()
    # example_8_save_data_for_analysis()
    # example_9_intraday_analysis()
    # example_10_commodities()

    print("\nEdit examples.py to uncomment the example you want to run!")
