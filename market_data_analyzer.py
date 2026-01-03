#!/usr/bin/env python3
"""
Market Data Analyzer - Fetch and visualize historical market data from Databento

This script allows you to:
- Fetch historical market data for any date range
- Rebuild candles at custom timeframes (1min, 3min, 5min, etc.)
- Filter for Regular Trading Hours (RTH)
- Visualize candlestick charts for analysis

Author: Market Data Analysis Tool
Date: 2026-01-03
"""

import os
import sys
from datetime import datetime, time
from typing import Optional, Literal
import pandas as pd
import numpy as np
import databento as db
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import plotly.graph_objects as go
from plotly.subplots import make_subplots


class MarketDataAnalyzer:
    """Fetches and analyzes market data from Databento"""

    # Regular Trading Hours (RTH) definitions for major markets
    RTH_HOURS = {
        'ES': {'start': time(9, 30), 'end': time(16, 0)},  # E-mini S&P 500
        'NQ': {'start': time(9, 30), 'end': time(16, 0)},  # E-mini NASDAQ
        'YM': {'start': time(9, 30), 'end': time(16, 0)},  # E-mini Dow
        'RTY': {'start': time(9, 30), 'end': time(16, 0)}, # E-mini Russell 2000
        'GC': {'start': time(8, 20), 'end': time(13, 30)}, # Gold Futures
        'CL': {'start': time(9, 0), 'end': time(14, 30)},  # Crude Oil
        'ZB': {'start': time(8, 20), 'end': time(15, 0)},  # 30-Year Treasury Bond
        'default': {'start': time(9, 30), 'end': time(16, 0)}
    }

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Market Data Analyzer

        Args:
            api_key: Databento API key. If None, will look for DATABENTO_API_KEY env variable
        """
        # Load environment variables from .env file if it exists
        load_dotenv()

        # Get API key from parameter or environment
        self.api_key = api_key or os.getenv('DATABENTO_API_KEY')

        if not self.api_key:
            raise ValueError(
                "Databento API key not found. Either pass it as a parameter or "
                "set the DATABENTO_API_KEY environment variable"
            )

        # Initialize Databento client
        self.client = db.Historical(self.api_key)

    def _validate_ohlcv_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validate and clean OHLCV data to remove corrupt/outlier records

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Cleaned DataFrame
        """
        if df.empty:
            return df

        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            print("WARNING: Cannot validate - missing OHLCV columns")
            return df

        initial_len = len(df)

        # Rule 1: high >= low (basic sanity check)
        invalid_high_low = df['high'] < df['low']
        if invalid_high_low.any():
            print(f"WARNING: Found {invalid_high_low.sum()} rows where high < low")
            df = df[~invalid_high_low]

        # Rule 2: open and close should be between low and high
        invalid_open = (df['open'] < df['low']) | (df['open'] > df['high'])
        invalid_close = (df['close'] < df['low']) | (df['close'] > df['high'])

        if invalid_open.any():
            print(f"WARNING: Found {invalid_open.sum()} rows where open is outside [low, high]")
            df = df[~invalid_open]

        if invalid_close.any():
            print(f"WARNING: Found {invalid_close.sum()} rows where close is outside [low, high]")
            df = df[~invalid_close]

        # Rule 3: Detect extreme outliers using IQR method on close prices
        if len(df) > 10:  # Need sufficient data for statistical analysis
            Q1 = df['close'].quantile(0.25)
            Q3 = df['close'].quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 3 * IQR  # Use 3*IQR for extreme outliers
            upper_bound = Q3 + 3 * IQR

            outliers = (df['close'] < lower_bound) | (df['close'] > upper_bound)
            if outliers.any():
                print(f"WARNING: Found {outliers.sum()} extreme price outliers")
                print(f"  Price bounds: {lower_bound:.2f} to {upper_bound:.2f}")
                outlier_rows = df[outliers][['open', 'high', 'low', 'close', 'volume']].head()
                print("  Sample outliers:")
                print(outlier_rows)
                df = df[~outliers]

        # Rule 4: Check for zero or negative prices
        zero_prices = (df[['open', 'high', 'low', 'close']] <= 0).any(axis=1)
        if zero_prices.any():
            print(f"WARNING: Found {zero_prices.sum()} rows with zero or negative prices")
            df = df[~zero_prices]

        removed = initial_len - len(df)
        if removed > 0:
            print(f"Data validation: Removed {removed} corrupt/outlier rows ({removed/initial_len*100:.1f}%)")
            print(f"Clean data: {len(df)} rows remaining")

        return df

    def fetch_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        dataset: str = 'GLBX.MDP3',
        schema: str = 'ohlcv-1m',
        stype_in: str = 'parent'
    ) -> pd.DataFrame:
        """
        Fetch historical market data from Databento

        Args:
            symbol: Trading symbol (e.g., 'ES.FUT', 'NQ.FUT')
            start_date: Start date in format 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'
            end_date: End date in format 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'
            dataset: Databento dataset (default: 'GLBX.MDP3' for CME Globex)
            schema: Data schema (default: 'ohlcv-1m' for 1-minute OHLCV)
            stype_in: Symbol input type (default: 'parent' for continuous contracts)

        Returns:
            DataFrame with OHLCV data
        """
        print(f"Fetching data for {symbol} from {start_date} to {end_date}...")

        try:
            # Fetch data from Databento
            data = self.client.timeseries.get_range(
                dataset=dataset,
                symbols=symbol,
                stype_in=stype_in,
                schema=schema,
                start=start_date,
                end=end_date,
            )

            # Convert to DataFrame
            df = data.to_df()

            if df.empty:
                print("Warning: No data returned from Databento")
                return df

            print(f"Fetched {len(df)} records")

            # Debug: Print column names and data types
            print(f"\nColumns in data: {df.columns.tolist()}")
            print(f"Index name: {df.index.name}")
            print(f"Data types:\n{df.dtypes}")

            # Print first few rows to see the data structure
            print(f"\nFirst few rows of data:")
            print(df.head())

            # Check if we have the expected columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            missing_cols = [col for col in required_cols if col not in df.columns]

            if missing_cols:
                print(f"WARNING: Missing expected columns: {missing_cols}")
                print(f"Available columns: {df.columns.tolist()}")

            # Ensure proper datetime index
            if not isinstance(df.index, pd.DatetimeIndex):
                if 'ts_event' in df.columns:
                    df.index = pd.to_datetime(df['ts_event'])
                    df.drop('ts_event', axis=1, inplace=True, errors='ignore')
                else:
                    print("WARNING: Could not find datetime column for index")

            # Keep timezone in UTC for safety and clarity
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC')
            elif df.index.tz != 'UTC':
                df.index = df.index.tz_convert('UTC')

            print(f"Index range: {df.index.min()} to {df.index.max()}")

            # Filter to only the requested symbol if 'symbol' column exists
            if 'symbol' in df.columns:
                unique_symbols = df['symbol'].unique()
                print(f"Symbols in data: {unique_symbols}")

                # Keep only the primary symbol (first one)
                if len(unique_symbols) > 1:
                    primary_symbol = unique_symbols[0]
                    print(f"WARNING: Multiple symbols found. Filtering to: {primary_symbol}")
                    df = df[df['symbol'] == primary_symbol]
                    print(f"Filtered to {len(df)} records")

            # Validate and clean data
            df = self._validate_ohlcv_data(df)

            return df

        except Exception as e:
            print(f"Error fetching data: {e}")
            import traceback
            traceback.print_exc()
            raise

    def filter_rth(
        self,
        df: pd.DataFrame,
        symbol_prefix: Optional[str] = None,
        custom_start: Optional[time] = None,
        custom_end: Optional[time] = None
    ) -> pd.DataFrame:
        """
        Filter DataFrame to only include Regular Trading Hours (RTH)

        Note: RTH hours are defined in US/Eastern time. This method will
        temporarily convert UTC timestamps to US/Eastern for filtering,
        then convert back to UTC.

        Args:
            df: DataFrame with datetime index (should be in UTC)
            symbol_prefix: Symbol prefix (e.g., 'ES', 'NQ') to determine RTH hours
            custom_start: Custom RTH start time (overrides default)
            custom_end: Custom RTH end time (overrides default)

        Returns:
            Filtered DataFrame with only RTH data (in UTC)
        """
        if df.empty:
            return df

        # Determine RTH hours (these are in US/Eastern time)
        if custom_start and custom_end:
            rth_start = custom_start
            rth_end = custom_end
        elif symbol_prefix and symbol_prefix in self.RTH_HOURS:
            rth_start = self.RTH_HOURS[symbol_prefix]['start']
            rth_end = self.RTH_HOURS[symbol_prefix]['end']
        else:
            rth_start = self.RTH_HOURS['default']['start']
            rth_end = self.RTH_HOURS['default']['end']

        print(f"Filtering for RTH (US/Eastern): {rth_start} to {rth_end}")

        # Convert to US/Eastern for filtering
        df_eastern = df.copy()
        df_eastern.index = df_eastern.index.tz_convert('US/Eastern')

        # Filter by time
        df_rth = df_eastern.between_time(rth_start, rth_end)

        # Convert back to UTC
        df_rth.index = df_rth.index.tz_convert('UTC')

        print(f"RTH records: {len(df_rth)} (filtered from {len(df)})")

        return df_rth

    def resample_candles(
        self,
        df: pd.DataFrame,
        timeframe: str = '5T'
    ) -> pd.DataFrame:
        """
        Resample OHLCV data to a different timeframe

        Args:
            df: DataFrame with OHLCV data
            timeframe: Pandas timeframe string (e.g., '1T', '3T', '5T', '15T', '1H')
                      T = minutes, H = hours, D = days

        Returns:
            Resampled DataFrame with OHLCV data
        """
        if df.empty:
            return df

        print(f"Resampling to {timeframe} timeframe...")

        # Define aggregation rules
        ohlcv_dict = {
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }

        # Resample
        df_resampled = df.resample(timeframe).agg(ohlcv_dict)

        # Drop rows with NaN (gaps in data)
        df_resampled.dropna(inplace=True)

        print(f"Resampled to {len(df_resampled)} candles")

        return df_resampled

    def convert_timezone(
        self,
        df: pd.DataFrame,
        target_tz: str = 'US/Eastern'
    ) -> pd.DataFrame:
        """
        Convert DataFrame index to a different timezone

        Args:
            df: DataFrame with timezone-aware datetime index
            target_tz: Target timezone (e.g., 'US/Eastern', 'Europe/London', 'Asia/Tokyo')

        Returns:
            DataFrame with index converted to target timezone
        """
        if df.empty:
            return df

        if not isinstance(df.index, pd.DatetimeIndex):
            print("WARNING: Index is not a DatetimeIndex, cannot convert timezone")
            return df

        if df.index.tz is None:
            print("WARNING: Index is not timezone-aware, cannot convert")
            return df

        print(f"Converting from {df.index.tz} to {target_tz}")
        df_converted = df.copy()
        df_converted.index = df_converted.index.tz_convert(target_tz)

        return df_converted

    def plot_candlestick_matplotlib(
        self,
        df: pd.DataFrame,
        title: str = "Candlestick Chart",
        figsize: tuple = (16, 8),
        save_path: Optional[str] = None
    ):
        """
        Create a candlestick chart using matplotlib

        Args:
            df: DataFrame with OHLCV data
            title: Chart title
            figsize: Figure size (width, height)
            save_path: Optional path to save the chart
        """
        if df.empty:
            print("No data to plot")
            return

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize,
                                        gridspec_kw={'height_ratios': [3, 1]})

        # Convert timestamps for matplotlib
        timestamps = mdates.date2num(df.index.to_pydatetime())

        # Calculate appropriate width for candles based on time differences
        if len(timestamps) > 1:
            # Use median time difference to handle gaps
            time_diffs = np.diff(timestamps)
            median_diff = np.median(time_diffs)
            candle_width = median_diff * 0.6  # 60% of the time interval
        else:
            candle_width = 0.0003  # Default fallback

        # Plot candlesticks
        for i, (idx, row) in enumerate(df.iterrows()):
            timestamp = timestamps[i]

            # Determine color
            color = 'green' if row['close'] >= row['open'] else 'red'

            # Draw candle body
            body_height = abs(row['close'] - row['open'])
            body_bottom = min(row['open'], row['close'])

            # If body height is 0 (open == close), make it minimally visible
            if body_height == 0:
                body_height = (row['high'] - row['low']) * 0.01 if row['high'] != row['low'] else 0.1

            rect = Rectangle(
                (timestamp - candle_width/2, body_bottom),
                candle_width,
                body_height,
                facecolor=color,
                edgecolor='black',
                linewidth=0.5,
                alpha=0.8
            )
            ax1.add_patch(rect)

            # Draw wicks
            ax1.plot([timestamp, timestamp],
                    [row['low'], row['high']],
                    color='black', linewidth=1.0)

        # Format x-axis with adaptive date formatting
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))

        # Adaptive tick locator based on data span
        time_span = timestamps[-1] - timestamps[0]
        if time_span < 1:  # Less than 1 day
            ax1.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        elif time_span < 7:  # Less than a week
            ax1.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        else:
            ax1.xaxis.set_major_locator(mdates.DayLocator())

        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')

        ax1.set_ylabel('Price')
        ax1.set_title(title)
        ax1.grid(True, alpha=0.3)
        ax1.autoscale_view()

        # Plot volume
        volume_colors = ['green' if row['close'] >= row['open'] else 'red'
                        for _, row in df.iterrows()]
        ax2.bar(timestamps, df['volume'], color=volume_colors, width=candle_width, alpha=0.8)
        ax2.set_ylabel('Volume')
        ax2.set_xlabel('Time')
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))

        if time_span < 1:
            ax2.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        elif time_span < 7:
            ax2.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        else:
            ax2.xaxis.set_major_locator(mdates.DayLocator())

        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Chart saved to {save_path}")

        plt.show()

    def plot_candlestick_plotly(
        self,
        df: pd.DataFrame,
        title: str = "Candlestick Chart",
        save_path: Optional[str] = None
    ):
        """
        Create an interactive candlestick chart using Plotly

        Args:
            df: DataFrame with OHLCV data
            title: Chart title
            save_path: Optional path to save the chart as HTML
        """
        if df.empty:
            print("No data to plot")
            return

        # Validate required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            print(f"ERROR: Missing required columns for plotting: {missing_cols}")
            print(f"Available columns: {df.columns.tolist()}")
            return

        # Debug: Print data summary
        print(f"\n{'='*60}")
        print(f"PLOTTING {len(df)} CANDLES")
        print(f"{'='*60}")
        print(f"Date range: {df.index.min()} to {df.index.max()}")
        print(f"  (timestamps represent START of each candle period)")
        print(f"Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
        print(f"\nFirst 5 candles:")
        print(df[['open', 'high', 'low', 'close', 'volume']].head())
        print(f"\nData quality check:")
        print(f"  All prices > 0: {(df[['open', 'high', 'low', 'close']] > 0).all().all()}")
        print(f"  High >= Low: {(df['high'] >= df['low']).all()}")
        print(f"  Open in [Low, High]: {((df['open'] >= df['low']) & (df['open'] <= df['high'])).all()}")
        print(f"  Close in [Low, High]: {((df['close'] >= df['low']) & (df['close'] <= df['high'])).all()}")
        print(f"{'='*60}\n")

        # Create subplots
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            subplot_titles=(title, 'Volume'),
            row_heights=[0.7, 0.3]
        )

        # Add candlestick chart
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df['open'],
                high=df['high'],
                low=df['low'],
                close=df['close'],
                name='OHLC',
                increasing_line_color='green',
                decreasing_line_color='red'
            ),
            row=1, col=1
        )

        # Add volume bars
        colors = ['green' if row['close'] >= row['open'] else 'red'
                 for _, row in df.iterrows()]

        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df['volume'],
                marker_color=colors,
                name='Volume',
                showlegend=False
            ),
            row=2, col=1
        )

        # Update layout
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            height=800,
            showlegend=True,
            hovermode='x unified',
            template='plotly_white'
        )

        fig.update_xaxes(title_text="Time", row=2, col=1)
        fig.update_yaxes(title_text="Price", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)

        if save_path:
            fig.write_html(save_path)
            print(f"Interactive chart saved to {save_path}")

        fig.show()

    def analyze(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = '5T',
        rth_only: bool = True,
        dataset: str = 'GLBX.MDP3',
        plot_type: Literal['matplotlib', 'plotly', 'both'] = 'plotly',
        save_chart: bool = False
    ) -> pd.DataFrame:
        """
        Complete analysis workflow: fetch, process, and visualize market data

        Args:
            symbol: Trading symbol (e.g., 'ES.FUT', 'NQ.FUT')
            start_date: Start date in format 'YYYY-MM-DD'
            end_date: End date in format 'YYYY-MM-DD'
            timeframe: Target timeframe (e.g., '1T', '3T', '5T', '15T')
            rth_only: Filter for Regular Trading Hours only
            dataset: Databento dataset
            plot_type: Type of plot ('matplotlib', 'plotly', or 'both')
            save_chart: Whether to save the chart to file

        Returns:
            Processed DataFrame with OHLCV data
        """
        # Fetch data
        df = self.fetch_data(symbol, start_date, end_date, dataset=dataset)

        if df.empty:
            print("No data available for analysis")
            return df

        # Filter for RTH if requested
        if rth_only:
            symbol_prefix = symbol.split('.')[0]  # Extract symbol prefix
            df = self.filter_rth(df, symbol_prefix)

        # Resample to target timeframe
        df = self.resample_candles(df, timeframe)

        # Print summary statistics
        print("\n" + "="*70)
        print("DATA SUMMARY")
        print("="*70)
        print(f"Symbol: {symbol}")
        print(f"Request Range: {start_date} to {end_date}")
        print(f"Timeframe: {timeframe}")
        print(f"RTH Only: {rth_only}")
        print(f"Total Candles: {len(df)}")
        if not df.empty:
            print(f"Actual Range: {df.index.min()} to {df.index.max()}")
            print(f"  (All times in UTC)")
            print(f"  (Each timestamp = START of candle period)")
            print(f"Price Range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
            print(f"Avg Volume: {df['volume'].mean():.0f}")
        print("="*70 + "\n")

        # Create visualizations
        chart_title = f"{symbol} - {timeframe} Candles ({start_date} to {end_date})"

        if plot_type in ['matplotlib', 'both']:
            save_path = f"{symbol}_{timeframe}_matplotlib.png" if save_chart else None
            self.plot_candlestick_matplotlib(df, title=chart_title, save_path=save_path)

        if plot_type in ['plotly', 'both']:
            save_path = f"{symbol}_{timeframe}_plotly.html" if save_chart else None
            self.plot_candlestick_plotly(df, title=chart_title, save_path=save_path)

        return df


def main():
    """Example usage of the Market Data Analyzer"""

    # Example configuration
    analyzer = MarketDataAnalyzer()

    # Analyze E-mini S&P 500 for a specific date range
    df = analyzer.analyze(
        symbol='ES.FUT',
        start_date='2025-10-20',
        end_date='2025-10-24',
        timeframe='5T',  # 5-minute candles
        rth_only=True,
        plot_type='plotly',
        save_chart=True
    )

    # You can also save the data to CSV
    if not df.empty:
        output_file = 'market_data_output.csv'
        df.to_csv(output_file)
        print(f"Data saved to {output_file}")


if __name__ == "__main__":
    main()
