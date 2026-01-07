"""
Futures Level Analyzer - Enhanced Version
Analyzes support/resistance levels from daily JSON context files
and provides actionable insights for next-day trading.
"""

import pandas as pd
import numpy as np
import databento as db
import json
import os
import pickle
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from functools import wraps
from dataclasses import dataclass, field
from collections import defaultdict

import pytz
import warnings

warnings.filterwarnings('ignore')

# ==============================================================================
# ⚙️ CONFIGURATION
# ==============================================================================

# Use environment variable for API key (export DATABENTO_API_KEY=your_key)
API_KEY = os.environ.get("DATABENTO_API_KEY", "")

# Cache settings
CACHE_DIR = Path(".cache/market_data")
CACHE_ENABLED = True

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Define all instruments and their specific settings
INSTRUMENT_CONFIG = {
    "ES": {
        "file": "daily_context_v2.json",
        "symbol": "ES.c.0",
        "timezone": "America/New_York",
        "tick_size": 0.25,
        # Volatility Settings (Points)
        "touch_buffer": 2.0,
        "break_threshold": 4.5,
        "hold_min_move": 6.0,
        # NEW: Time-based confirmation settings
        "break_confirm_bars": 3,      # Bars price must stay through level to confirm break (3 bars = 15min on 5m)
        "reaction_window_bars": 6,    # Bars to assess immediate reaction (6 bars = 30min on 5m)
        "consolidation_threshold": 3, # Crosses back and forth = consolidation, not multiple breaks
        # Price clustering for heatmap
        "cluster_size": 2.0,
    },
    "NQ": {
        "file": "nq_daily_context.json",
        "symbol": "NQ.c.0",
        "timezone": "America/New_York",
        "tick_size": 0.25,
        # NQ is ~4x more volatile than ES
        "touch_buffer": 8.0,
        "break_threshold": 18.0,
        "hold_min_move": 25.0,
        # NEW: Time-based confirmation settings
        "break_confirm_bars": 3,
        "reaction_window_bars": 6,
        "consolidation_threshold": 3,
        "cluster_size": 10.0,
    }
}

DATASET_ID = "GLBX.MDP3"


# ==============================================================================
# 🛠️ UTILITIES
# ==============================================================================

class NonRetryableError(Exception):
    """Exception that should not be retried (client errors like 422)."""
    pass


def retry_on_failure(max_retries: int = 3, backoff_factor: float = 2.0):
    """
    Decorator for retrying failed operations with exponential backoff.
    Only retries on transient errors (network, 5xx). Does NOT retry on client errors (4xx).
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except NonRetryableError:
                    # Don't retry client errors - re-raise immediately
                    raise
                except Exception as e:
                    error_str = str(e)
                    # Check if this is a client error (4xx) that shouldn't be retried
                    if any(code in error_str for code in ['400', '401', '403', '404', '422']):
                        raise NonRetryableError(str(e)) from e

                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_factor ** attempt
                        logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
            logger.error(f"All {max_retries} attempts failed")
            raise last_exception
        return wrapper
    return decorator


@dataclass
class LevelResult:
    """Structured result for a single level evaluation."""
    date: str
    price: float
    level_type: str  # 'RES' or 'SUP'
    zone: str
    category: str
    outcome: str  # 'UNTOUCHED', 'HELD', 'BROKEN', 'CHOP', 'CONSOLIDATION'
    mae: float  # Maximum Adverse Excursion (full day)
    mfe: float  # Maximum Favorable Excursion (full day)
    touch_time: Optional[str] = None
    hold_duration_bars: int = 0
    # NEW: First touch specific metrics
    first_touch_outcome: str = 'UNKNOWN'  # What happened on FIRST test
    first_touch_mae: float = 0.0  # MAE within reaction window
    first_touch_mfe: float = 0.0  # MFE within reaction window
    # NEW: Break quality metrics
    was_stop_hunt: bool = False  # Broke but immediately reversed
    break_sustained: bool = False  # Break held for confirmation bars
    num_tests: int = 1  # How many times level was tested
    bars_to_break: int = 0  # How many bars after touch until break (0 = didn't break)

    def to_dict(self) -> Dict:
        return {
            'date': self.date,
            'price': self.price,
            'type': self.level_type,
            'zone': self.zone,
            'category': self.category,
            'outcome': self.outcome,
            'mae': self.mae,
            'mfe': self.mfe,
            'touch_time': self.touch_time,
            'hold_duration': self.hold_duration_bars,
            # New fields
            'first_touch_outcome': self.first_touch_outcome,
            'first_touch_mae': self.first_touch_mae,
            'first_touch_mfe': self.first_touch_mfe,
            'was_stop_hunt': self.was_stop_hunt,
            'break_sustained': self.break_sustained,
            'num_tests': self.num_tests,
            'bars_to_break': self.bars_to_break
        }


@dataclass
class LevelStats:
    """Aggregated statistics for a level category/zone combination."""
    total: int = 0
    touched: int = 0
    held: int = 0
    broken: int = 0
    chop: int = 0
    avg_mae: float = 0.0
    avg_mfe: float = 0.0

    @property
    def hold_rate(self) -> float:
        return (self.held / self.touched * 100) if self.touched > 0 else 0.0

    @property
    def touch_rate(self) -> float:
        return (self.touched / self.total * 100) if self.total > 0 else 0.0


# ==============================================================================
# 📊 ANALYZER ENGINE
# ==============================================================================

class LevelAnalyzer:
    """
    Analyzes support/resistance levels against historical market data.
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.ny_tz = pytz.timezone(config['timezone'])
        self.context_data = self._load_context()
        self.market_data_cache: Dict[str, pd.DataFrame] = {}
        self.results_cache: List[LevelResult] = []

        # Initialize Databento client
        if not API_KEY:
            logger.error("DATABENTO_API_KEY environment variable not set")
            self.db_client = None
        else:
            self.db_client = db.Historical(API_KEY)

    def _load_context(self) -> Dict[str, Any]:
        """Load and validate the trading context JSON file."""
        file_path = self.config['file']

        if not os.path.exists(file_path):
            logger.error(f"Context file not found: {file_path}")
            return {}

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            # Validate structure
            valid_dates = {}
            for date_key, day_data in data.items():
                if 'levels' not in day_data:
                    logger.warning(f"Missing 'levels' key for {date_key}")
                    continue

                levels = day_data['levels']
                if not levels.get('raw_res') and not levels.get('raw_sup'):
                    logger.warning(f"No raw_res/raw_sup for {date_key}")
                    continue

                valid_dates[date_key] = day_data

            logger.info(f"Loaded {len(valid_dates)} valid dates from {file_path}")
            return dict(sorted(valid_dates.items()))

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {file_path}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return {}

    def _get_cache_path(self, date_str: str) -> Path:
        """Get the cache file path for a specific date."""
        cache_dir = CACHE_DIR / self.name
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{date_str}.pkl"

    def _load_from_cache(self, date_str: str) -> Optional[pd.DataFrame]:
        """Load market data from disk cache if available."""
        if not CACHE_ENABLED:
            return None

        cache_path = self._get_cache_path(date_str)
        if cache_path.exists():
            try:
                with open(cache_path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.warning(f"Cache read error for {date_str}: {e}")
        return None

    def _save_to_cache(self, date_str: str, df: pd.DataFrame) -> None:
        """Save market data to disk cache."""
        if not CACHE_ENABLED:
            return

        cache_path = self._get_cache_path(date_str)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(df, f)
        except Exception as e:
            logger.warning(f"Cache write error for {date_str}: {e}")

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    def fetch_market_data(self, date_str: str) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data from Databento with caching and retry logic.
        Returns 5-minute bars for the specified date.
        """
        if self.db_client is None:
            return None

        # Check memory cache first
        if date_str in self.market_data_cache:
            return self.market_data_cache[date_str]

        # Check disk cache
        cached = self._load_from_cache(date_str)
        if cached is not None:
            self.market_data_cache[date_str] = cached
            return cached

        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            now_utc = datetime.now(pytz.UTC)

            # Time range: 6 hours buffer on each side of NY trading day
            ny_start = self.ny_tz.localize(
                datetime.combine(target_date, datetime.min.time())
            ) - timedelta(hours=6)

            ny_end = self.ny_tz.localize(
                datetime.combine(target_date + timedelta(days=1), datetime.min.time())
            ) + timedelta(hours=6)

            # Cap end time to current time minus buffer (data may lag by ~30 min)
            # This prevents 422 errors for recent dates
            max_end = now_utc - timedelta(minutes=30)
            ny_end_utc = ny_end.astimezone(pytz.UTC)
            ny_start_utc = ny_start.astimezone(pytz.UTC)

            if ny_start_utc > max_end:
                # Entire date is in the future or too recent
                logger.warning(f"Skipping {date_str}: data not yet available (date is too recent)")
                return None

            if ny_end_utc > max_end:
                ny_end_utc = max_end
                logger.debug(f"Capped end time to {max_end} for recent date {date_str}")

            start_iso = ny_start_utc.isoformat()
            end_iso = ny_end_utc.isoformat()

            logger.info(f"[{self.name}] Fetching data for {date_str}...")

            data = self.db_client.timeseries.get_range(
                dataset=DATASET_ID,
                schema="ohlcv-1m",
                stype_in="continuous",
                symbols=[self.config['symbol']],
                start=start_iso,
                end=end_iso
            )

            df = data.to_df()

            if df.empty:
                logger.warning(f"No data returned for {date_str}")
                return None

            # Convert to NY timezone and filter to target date
            df.index = df.index.tz_convert(self.ny_tz)
            df = df[df.index.date == target_date].copy()

            if df.empty:
                logger.warning(f"No data for {date_str} after timezone filter")
                return None

            # Resample 1m -> 5m
            df_5m = df.resample('5min').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()

            df_5m.rename(columns={
                'open': 'Open', 'high': 'High',
                'low': 'Low', 'close': 'Close', 'volume': 'Volume'
            }, inplace=True)

            # Cache results
            self.market_data_cache[date_str] = df_5m
            self._save_to_cache(date_str, df_5m)

            return df_5m

        except Exception as e:
            logger.error(f"Failed to fetch data for {date_str}: {e}")
            raise

    def evaluate_levels(self, date_str: str, plan: Dict) -> List[LevelResult]:
        """
        Evaluate all levels for a given date against actual market data.
        Uses time-based confirmation to distinguish real breaks from stop hunts.
        Returns structured results for each level.
        """
        df = self.fetch_market_data(date_str)
        if df is None or df.empty:
            return []

        results = []

        # Load thresholds from config
        TOUCH = self.config['touch_buffer']
        BREAK = self.config['break_threshold']
        HOLD = self.config['hold_min_move']
        CONFIRM_BARS = self.config.get('break_confirm_bars', 3)
        REACTION_BARS = self.config.get('reaction_window_bars', 6)
        CONSOL_THRESHOLD = self.config.get('consolidation_threshold', 3)

        # Extract levels from plan
        levels_to_check = []
        if 'levels' in plan:
            for lvl in plan['levels'].get('raw_res', []):
                lvl['level_type'] = 'RES'
                levels_to_check.append(lvl)
            for lvl in plan['levels'].get('raw_sup', []):
                lvl['level_type'] = 'SUP'
                levels_to_check.append(lvl)

        if not levels_to_check:
            return []

        day_high = df['High'].max()
        day_low = df['Low'].min()

        for lvl in levels_to_check:
            price = lvl['price']
            l_type = lvl['level_type']
            zone = lvl.get('zone', 'Unknown')
            category = lvl.get('category', 'Unknown')

            # Broad filter: was level anywhere near day's range?
            if not (day_low - TOUCH <= price <= day_high + TOUCH):
                results.append(LevelResult(
                    date=date_str, price=price, level_type=l_type,
                    zone=zone, category=category,
                    outcome='UNTOUCHED', mae=0.0, mfe=0.0,
                    first_touch_outcome='UNTOUCHED'
                ))
                continue

            # Find bars that touched the level
            if l_type == 'RES':
                touch_mask = df['High'] >= (price - TOUCH)
            else:
                touch_mask = df['Low'] <= (price + TOUCH)

            if not touch_mask.any():
                results.append(LevelResult(
                    date=date_str, price=price, level_type=l_type,
                    zone=zone, category=category,
                    outcome='UNTOUCHED', mae=0.0, mfe=0.0,
                    first_touch_outcome='UNTOUCHED'
                ))
                continue

            # Get first touch
            first_touch_idx = df[touch_mask].index[0]
            first_touch_time = first_touch_idx.strftime('%H:%M')
            first_touch_pos = df.index.get_loc(first_touch_idx)

            # ============================================================
            # FIRST TOUCH ANALYSIS (Reaction Window)
            # ============================================================
            reaction_end_pos = min(first_touch_pos + REACTION_BARS, len(df))
            reaction_df = df.iloc[first_touch_pos:reaction_end_pos]

            if l_type == 'RES':
                ft_mae = max(0.0, reaction_df['High'].max() - price)
                ft_mfe = max(0.0, price - reaction_df['Low'].min())
            else:
                ft_mae = max(0.0, price - reaction_df['Low'].min())
                ft_mfe = max(0.0, reaction_df['High'].max() - price)

            # ============================================================
            # CHECK FOR SUSTAINED BREAK vs STOP HUNT
            # ============================================================
            was_stop_hunt = False
            break_sustained = False
            bars_to_break = 0

            # Find if/when price broke through
            if l_type == 'RES':
                break_mask = df['High'] > (price + BREAK)
            else:
                break_mask = df['Low'] < (price - BREAK)

            broke_through = break_mask.any()

            if broke_through:
                # Find first break bar
                first_break_idx = df[break_mask].index[0]
                first_break_pos = df.index.get_loc(first_break_idx)
                bars_to_break = first_break_pos - first_touch_pos

                # Check if break was sustained (stayed through for CONFIRM_BARS)
                confirm_end_pos = min(first_break_pos + CONFIRM_BARS, len(df))
                confirm_df = df.iloc[first_break_pos:confirm_end_pos]

                if len(confirm_df) >= CONFIRM_BARS:
                    if l_type == 'RES':
                        # For resistance break, check if lows stayed above level
                        break_sustained = confirm_df['Low'].min() > price
                    else:
                        # For support break, check if highs stayed below level
                        break_sustained = confirm_df['High'].max() < price

                # Stop hunt: broke through but immediately reversed back
                if not break_sustained and len(confirm_df) >= 2:
                    if l_type == 'RES':
                        # Reversed back below level quickly
                        was_stop_hunt = confirm_df['Close'].iloc[-1] < price
                    else:
                        was_stop_hunt = confirm_df['Close'].iloc[-1] > price

            # ============================================================
            # COUNT NUMBER OF TESTS (for consolidation detection)
            # ============================================================
            # A "test" is when price comes back to the level after moving away
            num_tests = 1
            touch_indices = df[touch_mask].index.tolist()

            # Group touches that are within 2 bars of each other as same test
            if len(touch_indices) > 1:
                current_test_start = touch_indices[0]
                for idx in touch_indices[1:]:
                    pos_diff = df.index.get_loc(idx) - df.index.get_loc(current_test_start)
                    if pos_diff > 2:  # Gap of more than 2 bars = new test
                        num_tests += 1
                        current_test_start = idx

            # ============================================================
            # FULL DAY MAE/MFE
            # ============================================================
            post_touch_df = df[df.index >= first_touch_idx]

            if l_type == 'RES':
                mae = max(0.0, post_touch_df['High'].max() - price)
                mfe = max(0.0, price - post_touch_df['Low'].min())
            else:
                mae = max(0.0, price - post_touch_df['Low'].min())
                mfe = max(0.0, post_touch_df['High'].max() - price)

            # ============================================================
            # DETERMINE OUTCOMES
            # ============================================================
            # First touch outcome (what a trader would experience on first test)
            if ft_mae > BREAK and not was_stop_hunt:
                first_touch_outcome = 'BROKEN'
            elif ft_mfe > HOLD:
                first_touch_outcome = 'HELD'
            elif was_stop_hunt:
                first_touch_outcome = 'STOP_HUNT'
            else:
                first_touch_outcome = 'CHOP'

            # Overall outcome (considering full day and nuances)
            if num_tests >= CONSOL_THRESHOLD and not break_sustained:
                outcome = 'CONSOLIDATION'
            elif mae > BREAK and break_sustained:
                outcome = 'BROKEN'
            elif mae > BREAK and was_stop_hunt:
                outcome = 'STOP_HUNT'
            elif mfe > HOLD:
                outcome = 'HELD'
            elif mae > BREAK:
                # Broke but not sustained - treat as eventual break
                outcome = 'BROKEN_WEAK'
            else:
                outcome = 'CHOP'

            results.append(LevelResult(
                date=date_str, price=price, level_type=l_type,
                zone=zone, category=category,
                outcome=outcome, mae=round(mae, 2), mfe=round(mfe, 2),
                touch_time=first_touch_time,
                hold_duration_bars=len(post_touch_df),
                first_touch_outcome=first_touch_outcome,
                first_touch_mae=round(ft_mae, 2),
                first_touch_mfe=round(ft_mfe, 2),
                was_stop_hunt=was_stop_hunt,
                break_sustained=break_sustained,
                num_tests=num_tests,
                bars_to_break=bars_to_break
            ))

        return results

    def get_timeframe_dates(self, mode: str = 'current_week') -> List[str]:
        """Get list of dates for a specific timeframe."""
        if not self.context_data:
            return []

        last_date_str = list(self.context_data.keys())[-1]
        anchor_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
        all_dates = sorted([
            datetime.strptime(d, "%Y-%m-%d").date()
            for d in self.context_data.keys()
        ])

        if mode == 'all':
            return [d.strftime("%Y-%m-%d") for d in all_dates]
        elif mode == 'current_week':
            start = anchor_date - timedelta(days=anchor_date.weekday())
            return [d.strftime("%Y-%m-%d") for d in all_dates if d >= start]
        elif mode == 'previous_week':
            end_prev = (anchor_date - timedelta(days=anchor_date.weekday())) - timedelta(days=1)
            start_prev = end_prev - timedelta(days=6)
            return [d.strftime("%Y-%m-%d") for d in all_dates if start_prev <= d <= end_prev]
        elif mode == 'current_month':
            return [
                d.strftime("%Y-%m-%d") for d in all_dates
                if d.month == anchor_date.month and d.year == anchor_date.year
            ]
        elif mode == 'last_n_days':
            # Last 10 trading days
            return [d.strftime("%Y-%m-%d") for d in all_dates[-10:]]
        return []

    def run_full_analysis(self) -> pd.DataFrame:
        """
        Run analysis on all available dates and cache results.
        Returns DataFrame with all results.
        Gracefully handles errors for individual dates.
        """
        all_dates = self.get_timeframe_dates('all')

        if not all_dates:
            logger.error("No dates found in context file")
            return pd.DataFrame()

        logger.info(f"Processing {len(all_dates)} days for {self.name}...")

        all_results = []
        skipped_dates = []

        for date_str in all_dates:
            if date_str not in self.context_data:
                continue

            try:
                results = self.evaluate_levels(date_str, self.context_data[date_str])
                all_results.extend(results)
            except NonRetryableError as e:
                # Client error (e.g., data not available yet) - skip this date
                logger.warning(f"Skipping {date_str}: {e}")
                skipped_dates.append(date_str)
            except Exception as e:
                # Unexpected error - log and continue
                logger.error(f"Error processing {date_str}: {e}")
                skipped_dates.append(date_str)

        if skipped_dates:
            logger.info(f"Skipped {len(skipped_dates)} dates due to errors: {skipped_dates}")

        self.results_cache = all_results

        if not all_results:
            return pd.DataFrame()

        return pd.DataFrame([r.to_dict() for r in all_results])


# ==============================================================================
# 📈 ENHANCED REPORTING & NEXT-DAY INSIGHTS
# ==============================================================================

class TradingInsights:
    """
    Generates actionable trading insights from level analysis results.
    """

    def __init__(self, analyzer: LevelAnalyzer, results_df: pd.DataFrame):
        self.analyzer = analyzer
        self.df = results_df
        self.config = analyzer.config
        self.name = analyzer.name

    def get_category_performance(self) -> pd.DataFrame:
        """Analyze performance by level category (MAGNET, WALL, SUPER_WALL)."""
        if self.df.empty:
            return pd.DataFrame()

        touched = self.df[self.df['outcome'] != 'UNTOUCHED'].copy()
        if touched.empty:
            return pd.DataFrame()

        stats = touched.groupby('category').agg({
            'outcome': [
                'count',
                lambda x: (x == 'HELD').sum(),
                lambda x: (x.isin(['BROKEN', 'BROKEN_WEAK'])).sum(),
                lambda x: (x == 'STOP_HUNT').sum(),
                lambda x: (x == 'CONSOLIDATION').sum()
            ],
            'mae': 'mean',
            'mfe': 'mean'
        }).round(2)

        stats.columns = ['Total', 'Held', 'Broken', 'StopHunt', 'Consol', 'Avg_MAE', 'Avg_MFE']
        stats['Hold_Rate%'] = (stats['Held'] / stats['Total'] * 100).round(1)
        stats['Edge'] = (stats['Avg_MFE'] - stats['Avg_MAE']).round(2)

        return stats.sort_values('Hold_Rate%', ascending=False)

    def get_first_touch_performance(self) -> pd.DataFrame:
        """
        Analyze FIRST TOUCH performance - most relevant for actual trading.
        This shows what would happen if you traded the first test of each level.
        """
        if self.df.empty:
            return pd.DataFrame()

        touched = self.df[self.df['first_touch_outcome'] != 'UNTOUCHED'].copy()
        if touched.empty:
            return pd.DataFrame()

        stats = touched.groupby('category').agg({
            'first_touch_outcome': [
                'count',
                lambda x: (x == 'HELD').sum(),
                lambda x: (x == 'BROKEN').sum(),
                lambda x: (x == 'STOP_HUNT').sum()
            ],
            'first_touch_mae': 'mean',
            'first_touch_mfe': 'mean'
        }).round(2)

        stats.columns = ['Total', 'Held', 'Broken', 'StopHunt', 'Avg_MAE', 'Avg_MFE']
        # For first touch, "Win" = Held OR StopHunt (both are tradeable wins)
        stats['Win_Rate%'] = ((stats['Held'] + stats['StopHunt']) / stats['Total'] * 100).round(1)
        stats['Edge'] = (stats['Avg_MFE'] - stats['Avg_MAE']).round(2)

        return stats.sort_values('Win_Rate%', ascending=False)

    def get_stop_hunt_analysis(self) -> Dict:
        """Analyze stop hunt frequency and characteristics."""
        if self.df.empty:
            return {}

        touched = self.df[self.df['outcome'] != 'UNTOUCHED']
        if touched.empty:
            return {}

        total = len(touched)
        stop_hunts = len(touched[touched['was_stop_hunt'] == True])
        sustained_breaks = len(touched[touched['break_sustained'] == True])
        consolidations = len(touched[touched['outcome'] == 'CONSOLIDATION'])

        return {
            'total_tested': total,
            'stop_hunts': stop_hunts,
            'stop_hunt_rate': round(stop_hunts / total * 100, 1) if total > 0 else 0,
            'sustained_breaks': sustained_breaks,
            'sustained_break_rate': round(sustained_breaks / total * 100, 1) if total > 0 else 0,
            'consolidations': consolidations,
            'avg_tests_per_level': round(touched['num_tests'].mean(), 1)
        }

    def get_zone_performance(self) -> pd.DataFrame:
        """Analyze performance by zone (Zone 1, Zone 2, etc.)."""
        if self.df.empty:
            return pd.DataFrame()

        touched = self.df[self.df['outcome'] != 'UNTOUCHED'].copy()
        if touched.empty:
            return pd.DataFrame()

        stats = touched.groupby('zone').agg({
            'outcome': [
                'count',
                lambda x: (x == 'HELD').sum(),
                lambda x: (x == 'BROKEN').sum()
            ],
            'mae': 'mean',
            'mfe': 'mean'
        }).round(2)

        stats.columns = ['Total', 'Held', 'Broken', 'Avg_MAE', 'Avg_MFE']
        stats['Hold_Rate%'] = (stats['Held'] / stats['Total'] * 100).round(1)

        return stats.sort_index()

    def get_time_of_day_analysis(self) -> pd.DataFrame:
        """Analyze when levels typically get tested."""
        if self.df.empty or 'touch_time' not in self.df.columns:
            return pd.DataFrame()

        touched = self.df[
            (self.df['outcome'] != 'UNTOUCHED') &
            (self.df['touch_time'].notna())
        ].copy()

        if touched.empty:
            return pd.DataFrame()

        # Extract hour from touch time
        touched['hour'] = touched['touch_time'].apply(
            lambda x: int(x.split(':')[0]) if pd.notna(x) else None
        )

        hourly = touched.groupby('hour').agg({
            'outcome': [
                'count',
                lambda x: (x == 'HELD').sum()
            ]
        })
        hourly.columns = ['Tests', 'Held']
        hourly['Hold_Rate%'] = (hourly['Held'] / hourly['Tests'] * 100).round(1)

        return hourly

    def get_level_confluence(self, levels: List[Dict], cluster_size: float = None) -> List[Dict]:
        """
        Identify price zones where multiple levels cluster together.
        Confluence zones are typically stronger.
        """
        if not levels:
            return []

        if cluster_size is None:
            cluster_size = self.config.get('cluster_size', 5.0)

        # Sort levels by price
        sorted_levels = sorted(levels, key=lambda x: x['price'])

        clusters = []
        current_cluster = [sorted_levels[0]]

        for lvl in sorted_levels[1:]:
            if lvl['price'] - current_cluster[-1]['price'] <= cluster_size:
                current_cluster.append(lvl)
            else:
                if len(current_cluster) >= 2:
                    clusters.append({
                        'price_low': current_cluster[0]['price'],
                        'price_high': current_cluster[-1]['price'],
                        'midpoint': np.mean([l['price'] for l in current_cluster]),
                        'count': len(current_cluster),
                        'categories': [l.get('category', 'Unknown') for l in current_cluster],
                        'has_super_wall': any(l.get('category') == 'SUPER_WALL' for l in current_cluster)
                    })
                current_cluster = [lvl]

        # Don't forget last cluster
        if len(current_cluster) >= 2:
            clusters.append({
                'price_low': current_cluster[0]['price'],
                'price_high': current_cluster[-1]['price'],
                'midpoint': np.mean([l['price'] for l in current_cluster]),
                'count': len(current_cluster),
                'categories': [l.get('category', 'Unknown') for l in current_cluster],
                'has_super_wall': any(l.get('category') == 'SUPER_WALL' for l in current_cluster)
            })

        return sorted(clusters, key=lambda x: x['count'], reverse=True)

    def get_recurring_levels(self, timeframe_dates: List[str], min_occurrences: int = 2) -> pd.DataFrame:
        """Find levels that appear multiple times with their historical performance."""
        if self.df.empty:
            return pd.DataFrame()

        tf_df = self.df[self.df['date'].isin(timeframe_dates)].copy()
        if tf_df.empty:
            return pd.DataFrame()

        # Round prices for clustering
        cluster_size = self.config.get('cluster_size', 2.0)
        tf_df['price_cluster'] = (tf_df['price'] / cluster_size).round() * cluster_size

        grouped = tf_df.groupby('price_cluster').agg({
            'date': 'count',
            'outcome': lambda x: list(x),
            'type': 'first',
            'category': lambda x: list(x)
        })

        grouped.columns = ['Occurrences', 'Outcomes', 'Type', 'Categories']
        grouped['Held'] = grouped['Outcomes'].apply(lambda x: x.count('HELD'))
        grouped['Broken'] = grouped['Outcomes'].apply(lambda x: x.count('BROKEN'))
        grouped['Touched'] = grouped['Occurrences'] - grouped['Outcomes'].apply(lambda x: x.count('UNTOUCHED'))
        grouped['Hold_Rate%'] = grouped.apply(
            lambda r: round(r['Held'] / r['Touched'] * 100, 1) if r['Touched'] > 0 else 0, axis=1
        )

        recurring = grouped[grouped['Occurrences'] >= min_occurrences].sort_values(
            ['Occurrences', 'Hold_Rate%'], ascending=[False, False]
        )

        return recurring[['Occurrences', 'Touched', 'Held', 'Broken', 'Hold_Rate%', 'Type']]

    def score_level_for_tomorrow(self, level: Dict, historical_stats: Dict) -> Dict:
        """
        Score a level for next-day trading based on historical performance.
        Returns level with added scoring metrics.
        """
        category = level.get('category', 'Unknown')
        zone = level.get('zone', 'Unknown')

        # Base scores from historical performance
        cat_stats = historical_stats.get('category', {}).get(category, {})
        zone_stats = historical_stats.get('zone', {}).get(zone, {})

        cat_hold_rate = cat_stats.get('hold_rate', 50)
        zone_hold_rate = zone_stats.get('hold_rate', 50)

        # Composite score (0-100)
        base_score = (cat_hold_rate * 0.6 + zone_hold_rate * 0.4)

        # Bonus for SUPER_WALL
        if category == 'SUPER_WALL':
            base_score += 10

        # Bonus for Zone 1 (closest to price)
        if zone == 'Zone 1':
            base_score += 5

        level['score_composite'] = min(100, round(base_score, 1))
        level['historical_hold_rate'] = round(cat_hold_rate, 1)

        return level

    def generate_next_day_levels(self, next_day_plan: Dict) -> Dict:
        """
        Generate scored and ranked levels for next-day trading.
        """
        if not next_day_plan or 'levels' not in next_day_plan:
            return {}

        # Calculate historical stats
        touched = self.df[self.df['outcome'] != 'UNTOUCHED']

        historical_stats = {
            'category': {},
            'zone': {}
        }

        for cat in touched['category'].unique():
            cat_df = touched[touched['category'] == cat]
            historical_stats['category'][cat] = {
                'hold_rate': (cat_df['outcome'] == 'HELD').mean() * 100,
                'avg_mfe': cat_df['mfe'].mean()
            }

        for zone in touched['zone'].unique():
            zone_df = touched[touched['zone'] == zone]
            historical_stats['zone'][zone] = {
                'hold_rate': (zone_df['outcome'] == 'HELD').mean() * 100
            }

        # Score resistance levels
        res_levels = []
        for lvl in next_day_plan['levels'].get('raw_res', []):
            scored = self.score_level_for_tomorrow(lvl.copy(), historical_stats)
            res_levels.append(scored)

        # Score support levels
        sup_levels = []
        for lvl in next_day_plan['levels'].get('raw_sup', []):
            scored = self.score_level_for_tomorrow(lvl.copy(), historical_stats)
            sup_levels.append(scored)

        # Find confluence zones
        all_levels = res_levels + sup_levels
        confluence = self.get_confluence_zones(all_levels)

        # Sort by composite score
        res_levels.sort(key=lambda x: x.get('score_composite', 0), reverse=True)
        sup_levels.sort(key=lambda x: x.get('score_composite', 0), reverse=True)

        return {
            'current_price': next_day_plan.get('current_price'),
            'predicted_range': next_day_plan.get('predicted_range'),
            'resistance': res_levels,
            'support': sup_levels,
            'confluence_zones': confluence,
            'top_resistance': res_levels[:3] if res_levels else [],
            'top_support': sup_levels[:3] if sup_levels else []
        }

    def get_confluence_zones(self, levels: List[Dict]) -> List[Dict]:
        """Wrapper for confluence detection."""
        return self.get_level_confluence(levels)

    def get_volatility_accuracy(self) -> pd.DataFrame:
        """Compare predicted vs actual daily ranges."""
        if not self.analyzer.context_data:
            return pd.DataFrame()

        records = []
        for date_str, plan in self.analyzer.context_data.items():
            predicted = plan.get('predicted_range')
            if predicted is None:
                continue

            df = self.analyzer.fetch_market_data(date_str)
            if df is None or df.empty:
                continue

            actual_range = df['High'].max() - df['Low'].min()

            records.append({
                'date': date_str,
                'predicted': round(predicted, 2),
                'actual': round(actual_range, 2),
                'error': round(actual_range - predicted, 2),
                'error_pct': round((actual_range - predicted) / predicted * 100, 1)
            })

        return pd.DataFrame(records)


# ==============================================================================
# 📋 REPORT GENERATOR
# ==============================================================================

class ReportGenerator:
    """Generates formatted reports for trading insights."""

    def __init__(self, analyzer: LevelAnalyzer, insights: TradingInsights):
        self.analyzer = analyzer
        self.insights = insights
        self.name = analyzer.name
        self._lines: List[str] = []

    def _add(self, text: str = ""):
        """Add a line to the report buffer."""
        self._lines.append(text)

    def _header(self, title: str, char: str = '=', width: int = 70):
        """Add a header section."""
        self._add("")
        self._add(char * width)
        self._add(f"  {title}")
        self._add(char * width)

    def _section(self, title: str):
        """Add a section divider."""
        self._add("")
        self._add("─" * 50)
        self._add(f"  {title}")
        self._add("─" * 50)

    def _get_report(self) -> str:
        """Get the full report as a string."""
        return "\n".join(self._lines)

    def _clear(self):
        """Clear the report buffer."""
        self._lines = []

    def _output(self, output_file: str = None) -> str:
        """Print to console and optionally save to file. Returns report text."""
        report_text = self._get_report()
        print(report_text)

        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report_text)
            logger.info(f"Report saved to {output_file}")

        return report_text

    def generate_full_report(self, results_df: pd.DataFrame, output_file: str = None) -> str:
        """Generate comprehensive analysis report. Returns report text."""
        self._clear()

        self._header(f"LEVEL ANALYSIS REPORT: {self.name}")

        self._add(f"\nConfig: Touch={self.analyzer.config['touch_buffer']}, "
                  f"Break={self.analyzer.config['break_threshold']}, "
                  f"Hold={self.analyzer.config['hold_min_move']}")

        # Overall Statistics
        self._section("OVERALL STATISTICS")
        total = len(results_df)
        touched_df = results_df[results_df['outcome'] != 'UNTOUCHED']
        touched = len(touched_df)

        self._add(f"  Total Levels: {total}")
        self._add(f"  Touched: {touched} ({touched/total*100:.1f}%)")

        if touched > 0:
            held = len(touched_df[touched_df['outcome'] == 'HELD'])
            broken = len(touched_df[touched_df['outcome'].isin(['BROKEN', 'BROKEN_WEAK'])])
            stop_hunts = len(touched_df[touched_df['outcome'] == 'STOP_HUNT'])
            consol = len(touched_df[touched_df['outcome'] == 'CONSOLIDATION'])

            self._add(f"  Held: {held} ({held/touched*100:.1f}%)")
            self._add(f"  Broken (sustained): {broken} ({broken/touched*100:.1f}%)")
            self._add(f"  Stop Hunts (fake breaks): {stop_hunts} ({stop_hunts/touched*100:.1f}%)")
            self._add(f"  Consolidation: {consol} ({consol/touched*100:.1f}%)")

        # Stop Hunt Analysis
        self._section("BREAK QUALITY ANALYSIS")
        sh_stats = self.insights.get_stop_hunt_analysis()
        if sh_stats:
            self._add(f"  Avg tests per level: {sh_stats['avg_tests_per_level']}")
            self._add(f"  Stop hunt rate: {sh_stats['stop_hunt_rate']}% (broke but reversed quickly)")
            self._add(f"  Sustained break rate: {sh_stats['sustained_break_rate']}% (broke and held through)")

        # FIRST TOUCH Performance (Most Important for Trading!)
        self._section("FIRST TOUCH PERFORMANCE (Trading Relevant)")
        self._add("  [Shows outcome if you traded the FIRST test of each level]")
        ft_perf = self.insights.get_first_touch_performance()
        if not ft_perf.empty:
            self._add(ft_perf.to_string())
        else:
            self._add("  No data available")

        # Category Performance (Full Day)
        self._section("FULL DAY PERFORMANCE BY CATEGORY")
        cat_perf = self.insights.get_category_performance()
        if not cat_perf.empty:
            self._add(cat_perf.to_string())
        else:
            self._add("  No data available")

        # Zone Performance
        self._section("PERFORMANCE BY ZONE")
        zone_perf = self.insights.get_zone_performance()
        if not zone_perf.empty:
            self._add(zone_perf.to_string())
        else:
            self._add("  No data available")

        # Time of Day Analysis
        self._section("TIME OF DAY ANALYSIS (Hour of First Touch)")
        tod = self.insights.get_time_of_day_analysis()
        if not tod.empty:
            self._add(tod.to_string())
        else:
            self._add("  No data available")

        # Timeframe breakdowns
        for tf in ['current_week', 'previous_week', 'last_n_days']:
            dates = self.analyzer.get_timeframe_dates(tf)
            if not dates:
                continue

            tf_label = tf.upper().replace('_', ' ')
            self._section(f"{tf_label} ({len(dates)} days: {dates[0]} to {dates[-1]})")

            tf_df = results_df[results_df['date'].isin(dates)]
            if tf_df.empty:
                self._add("  No data")
                continue

            touched_tf = tf_df[tf_df['outcome'] != 'UNTOUCHED']
            if len(touched_tf) > 0:
                held = len(touched_tf[touched_tf['outcome'] == 'HELD'])
                broken = len(touched_tf[touched_tf['outcome'].isin(['BROKEN', 'BROKEN_WEAK'])])
                stop_hunts = len(touched_tf[touched_tf['outcome'] == 'STOP_HUNT'])
                self._add(f"  Tested: {len(touched_tf)} | Held: {held} | Broken: {broken} | StopHunts: {stop_hunts}")

                # First touch stats for this timeframe
                ft_held = len(touched_tf[touched_tf['first_touch_outcome'] == 'HELD'])
                ft_broken = len(touched_tf[touched_tf['first_touch_outcome'] == 'BROKEN'])
                ft_sh = len(touched_tf[touched_tf['first_touch_outcome'] == 'STOP_HUNT'])
                ft_wins = ft_held + ft_sh
                self._add(f"  First Touch: {ft_wins}/{len(touched_tf)} wins ({ft_wins/len(touched_tf)*100:.0f}%) [Held:{ft_held} StopHunt:{ft_sh} Broken:{ft_broken}]")

            # Recurring levels
            recurring = self.insights.get_recurring_levels(dates)
            if not recurring.empty:
                self._add("\n  Recurring Levels (2+ occurrences):")
                self._add(recurring.head(5).to_string())

        return self._output(output_file)

    def generate_next_day_report(self, next_day_date: str = None, output_file: str = None) -> str:
        """Generate actionable report for next trading day. Returns report text."""
        self._clear()

        self._header(f"NEXT DAY TRADING LEVELS: {self.name}", char='*')

        # Find next day's plan
        if next_day_date is None:
            dates = list(self.analyzer.context_data.keys())
            if not dates:
                self._add("No context data available")
                return self._output(output_file)
            next_day_date = dates[-1]

        if next_day_date not in self.analyzer.context_data:
            self._add(f"No plan found for {next_day_date}")
            return self._output(output_file)

        plan = self.analyzer.context_data[next_day_date]
        scored = self.insights.generate_next_day_levels(plan)

        self._add(f"\n  Date: {next_day_date}")
        self._add(f"  Current Price: {scored.get('current_price', 'N/A')}")
        pred_range = scored.get('predicted_range')
        self._add(f"  Predicted Range: {pred_range:.1f} pts" if pred_range else "  Predicted Range: N/A")

        # Top Resistance Levels
        self._section("TOP RESISTANCE LEVELS (Ranked by Historical Performance)")
        for i, lvl in enumerate(scored.get('top_resistance', []), 1):
            self._add(f"  {i}. {lvl['price']:.2f} | {lvl['category']} | {lvl['zone']} | "
                      f"Score: {lvl.get('score_composite', 0):.0f} | "
                      f"Hist Hold: {lvl.get('historical_hold_rate', 0):.0f}%")

        # Top Support Levels
        self._section("TOP SUPPORT LEVELS (Ranked by Historical Performance)")
        for i, lvl in enumerate(scored.get('top_support', []), 1):
            self._add(f"  {i}. {lvl['price']:.2f} | {lvl['category']} | {lvl['zone']} | "
                      f"Score: {lvl.get('score_composite', 0):.0f} | "
                      f"Hist Hold: {lvl.get('historical_hold_rate', 0):.0f}%")

        # Confluence Zones
        confluence = scored.get('confluence_zones', [])
        if confluence:
            self._section("CONFLUENCE ZONES (Multiple Levels Clustered)")
            for i, zone in enumerate(confluence[:3], 1):
                sw_flag = " [SUPER_WALL]" if zone['has_super_wall'] else ""
                self._add(f"  {i}. {zone['price_low']:.2f} - {zone['price_high']:.2f} | "
                          f"{zone['count']} levels{sw_flag}")

        # Trading Notes
        self._section("TRADING NOTES")

        # Identify best category historically
        cat_perf = self.insights.get_category_performance()
        if not cat_perf.empty and 'Hold_Rate%' in cat_perf.columns:
            best_cat = cat_perf['Hold_Rate%'].idxmax()
            best_rate = cat_perf.loc[best_cat, 'Hold_Rate%']
            self._add(f"  - Best performing category: {best_cat} ({best_rate:.0f}% hold rate)")

        # Zone 1 alert
        zone_perf = self.insights.get_zone_performance()
        if not zone_perf.empty and 'Zone 1' in zone_perf.index:
            z1_rate = zone_perf.loc['Zone 1', 'Hold_Rate%']
            self._add(f"  - Zone 1 historical hold rate: {z1_rate:.0f}%")

        self._add(f"\n  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return self._output(output_file)


# ==============================================================================
# 📤 EXPORT FUNCTIONS
# ==============================================================================

def export_to_json(analyzer: LevelAnalyzer, insights: TradingInsights,
                   output_file: str = None) -> str:
    """Export next-day levels and insights to JSON for external use."""

    dates = list(analyzer.context_data.keys())
    if not dates:
        return ""

    next_day = dates[-1]
    plan = analyzer.context_data[next_day]
    scored = insights.generate_next_day_levels(plan)

    # Add metadata
    export_data = {
        'instrument': analyzer.name,
        'generated_at': datetime.now().isoformat(),
        'target_date': next_day,
        'levels': scored,
        'category_performance': insights.get_category_performance().to_dict() if not insights.get_category_performance().empty else {},
        'zone_performance': insights.get_zone_performance().to_dict() if not insights.get_zone_performance().empty else {}
    }

    if output_file is None:
        output_file = f"{analyzer.name.lower()}_next_day_levels.json"

    with open(output_file, 'w') as f:
        json.dump(export_data, f, indent=2, default=str)

    logger.info(f"Exported to {output_file}")
    return output_file


def export_to_csv(results_df: pd.DataFrame, output_file: str) -> str:
    """Export full results to CSV for further analysis."""
    results_df.to_csv(output_file, index=False)
    logger.info(f"Exported to {output_file}")
    return output_file


# ==============================================================================
# 🚀 MAIN ENTRY POINT
# ==============================================================================

def main():
    """Main entry point for the analysis."""

    print("\n" + "=" * 70)
    print("  FUTURES LEVEL ANALYZER - Enhanced Edition")
    print("=" * 70)

    if not API_KEY:
        print("\n⚠️  WARNING: DATABENTO_API_KEY not set.")
        print("   Export it with: export DATABENTO_API_KEY=your_key")
        print("   Analysis will skip market data fetching.\n")

    for instrument_name, config in INSTRUMENT_CONFIG.items():
        # Check if config file exists
        if not os.path.exists(config['file']):
            logger.warning(f"Skipping {instrument_name}: {config['file']} not found")
            continue

        # Initialize analyzer
        analyzer = LevelAnalyzer(instrument_name, config)

        # Run full analysis
        results_df = analyzer.run_full_analysis()

        if results_df.empty:
            logger.warning(f"No results for {instrument_name}")
            continue

        # Generate insights
        insights = TradingInsights(analyzer, results_df)

        # Generate reports (print to console and save to files)
        reporter = ReportGenerator(analyzer, insights)
        reporter.generate_full_report(
            results_df,
            output_file=f"{instrument_name.lower()}_analysis_report.txt"
        )
        reporter.generate_next_day_report(
            output_file=f"{instrument_name.lower()}_next_day_report.txt"
        )

        # Export data files
        export_to_json(analyzer, insights)
        export_to_csv(results_df, f"{instrument_name.lower()}_level_results.csv")

    print("\n" + "=" * 70)
    print("  Analysis Complete")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
