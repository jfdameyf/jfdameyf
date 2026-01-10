"""
ES Trading Bot Backtester
Replays historical data to validate strategy performance

✅ NOW INCLUDES: Order Book FLIP Analysis Integration
"""

import pandas as pd
import numpy as np
import databento as db
import yfinance as yf
import joblib
import json
import os
import sys
from datetime import datetime, time, timedelta
import pytz
import warnings
from collections import defaultdict
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings('ignore')

# Import from main bot
from trading_bot_FIXED import StrategyManager, MarketPlanner

# Configuration
API_KEY = # will place your databento API key here
SYMBOL = "ES.c.0"
NY_TZ = pytz.timezone('America/New_York')

CRITICAL_LEVELS_FILE = "critical_levels_master_final.csv"
BACKTEST_OUTPUT = "backtest_results"
os.makedirs(BACKTEST_OUTPUT, exist_ok=True)

# ==============================================================================
# BACKTESTER WITH ORDER BOOK INTEGRATION
# ==============================================================================
class TradingBotBacktester:
    def __init__(self, start_date, end_date, enable_poc_filter=False,
                 analyze_orderbook=False, databento_api_key=None,
                 use_delta_filter=True, delta_mode="static", static_delta_threshold=400):
        """
        Initialize backtester

        Args:
            start_date: datetime.date - First day to test
            end_date: datetime.date - Last day to test
            enable_poc_filter: bool - Enable POC distance filtering
            analyze_orderbook: bool - Enable order book FLIP analysis (NEW)
            databento_api_key: str - Databento API key for order book data (NEW)
            use_delta_filter: bool - Enable delta filtering (NEW)
            delta_mode: str - "static" or "dynamic" (NEW)
            static_delta_threshold: int - Fixed delta threshold (NEW, default: 400)
        """
        self.start_date = start_date
        self.end_date = end_date
        self.enable_poc_filter = enable_poc_filter
        self.use_delta_filter = use_delta_filter
        self.delta_mode = delta_mode
        self.static_delta_threshold = static_delta_threshold

        if "YOUR_DATABENTO" in API_KEY:
            print("❌ ERROR: Please set your Databento API Key")
            sys.exit(1)

        self.client = db.Historical(API_KEY)
        self.planner = MarketPlanner()

        # Results tracking
        self.daily_plans = {}
        self.signals = []
        self.daily_stats = {}

        # ✅ NEW: Trade tracking with MAE/MFE
        self.trades = []  # All completed trades
        self.open_position = None  # Current open trade
        self.TARGET_PROFIT = 4.0  # 4 points target for ES (adjusted from 5.0 based on MAE/MFE)
        self.STOP_LOSS = 3.0  # 3 points stop for ES (adjusted from 2.0 based on MAE/MFE)

        # ✅ FIX 2: Session-wide signal deduplication
        self.fired_signals_session = {}  # {signal_key: timestamp}
        self.SIGNAL_COOLDOWN_MINUTES = 15  # Don't repeat same signal within 15 min

        # ✅ NEW: Dynamic SUP/RES tracking
        self.previous_close = None  # Track previous bar's close to determine approach direction
        self.level_last_signal = {}  # {level_price: {'direction': 'LONG/SHORT', 'timestamp': dt, 'price': float}}
        self.WHIPSAW_PREVENTION_DISTANCE = 3.0  # Don't fire opposite signal within 3 points

        # ✅ INTEGRATION POINT 1: Order Book Analysis Setup
        self.analyze_orderbook = analyze_orderbook
        self.ob_analyzer = None

        if analyze_orderbook:
            if databento_api_key:
                try:
                    from orderbook_flip_analyzer import create_analyzer_from_api_key
                    self.ob_analyzer = create_analyzer_from_api_key(
                        databento_api_key,
                        symbol=SYMBOL
                    )
                    print("✅ Order book analysis ENABLED")
                except ImportError as e:
                    print(f"⚠️  Could not import OrderBookFlipAnalyzer: {e}")
                    print("   Order book analysis will be DISABLED")
                    self.analyze_orderbook = False
            else:
                print("⚠️  Order book analysis requested but no API key provided")
                print("   Pass databento_api_key parameter to enable")
                self.analyze_orderbook = False

        print(f"🔬 BACKTESTER INITIALIZED")
        print(f"   Period: {start_date} to {end_date}")
        print(f"   POC Filter: {enable_poc_filter}")
        print(f"   Delta Filter: {use_delta_filter} ({delta_mode.upper()} mode)")
        if use_delta_filter and delta_mode == "static":
            print(f"   Delta Threshold: {static_delta_threshold}")
        print(f"   Order Book Analysis: {self.analyze_orderbook}")
        print(f"   Symbol: {SYMBOL}\n")

    def generate_historical_plans(self):
        """Generate daily trading plans for each day in backtest period"""
        print("📅 Generating Historical Plans...")
        print("="*60)

        current = self.start_date
        while current <= self.end_date:
            # Skip weekends
            if current.weekday() >= 5:  # Saturday=5, Sunday=6
                current += timedelta(days=1)
                continue

            try:
                print(f"\n📊 Processing: {current.strftime('%Y-%m-%d')}")
                self.planner.generate_plan_for_date(current)

                # Load the generated plan
                plan_key = current.strftime('%Y-%m-%d')
                with open('daily_context_v2.json', 'r') as f:
                    data = json.load(f)
                    if plan_key in data:
                        self.daily_plans[plan_key] = data[plan_key]

                        # Print summary
                        levels = data[plan_key].get('levels', {})
                        sup_count = len(levels.get('raw_sup', []))
                        res_count = len(levels.get('raw_res', []))
                        print(f"   ✅ Levels: {sup_count} SUP, {res_count} RES")
                    else:
                        print(f"   ⚠️ No plan generated (holiday?)")

            except Exception as e:
                print(f"   ❌ Error: {e}")

            current += timedelta(days=1)

        print("\n" + "="*60)
        print(f"✅ Generated {len(self.daily_plans)} daily plans\n")

    def run_backtest(self):
        """Main backtesting loop - replays historical data"""
        print("🔄 Running Backtest...")
        print("="*60 + "\n")

        for date_str, plan in self.daily_plans.items():
            print(f"📈 Backtesting: {date_str}")

            # Parse date
            test_date = datetime.strptime(date_str, '%Y-%m-%d').date()

            # Get trade data for this day (RTH only: 9:30 - 16:00 ET)
            start_dt = NY_TZ.localize(datetime.combine(test_date, time(9, 30)))
            end_dt = NY_TZ.localize(datetime.combine(test_date, time(16, 0)))

            try:
                # Fetch minute bars (more efficient than ticks for backtest)
                bars = self.client.timeseries.get_range(
                    dataset="GLBX.MDP3",
                    schema="ohlcv-1m",
                    symbols=[SYMBOL],
                    stype_in="continuous",
                    start=start_dt,
                    end=end_dt
                ).to_df()

                if bars.empty:
                    print(f"   ⚠️ No data (holiday/weekend)")
                    continue

                # Initialize strategy for this day
                strategy = self._create_strategy_for_day(plan)

                # ✅ NEW: Reset tracking variables for new day
                self.previous_close = None  # Reset for new session
                self.level_last_signal = {}  # Clear previous day's signals

                # Track day stats
                day_signals = []
                tick_count = 0

                # Replay each bar
                for timestamp, bar in bars.iterrows():
                    tick_count += 1
                    current_price = bar['close']
                    bar_high = bar['high']
                    bar_low = bar['low']
                    bar_open = bar['open']
                    bar_volume = bar.get('volume', 1000)  # Default if missing

                    # ✅ NEW: Estimate candle delta from bar data (heuristic)
                    # Real delta requires trade-by-trade data, so we estimate:
                    # - Positive if close > open (buying pressure)
                    # - Negative if close < open (selling pressure)
                    # - Magnitude based on volume and price move percentage
                    price_change = current_price - bar_open
                    price_range = bar_high - bar_low
                    if price_range > 0:
                        directional_strength = abs(price_change) / price_range
                    else:
                        directional_strength = 0.5

                    estimated_delta = price_change * bar_volume * directional_strength * 0.01
                    # Note: This is a rough estimate. Real delta would be calculated from trades.

                    # ✅ NEW: Update open position MAE/MFE
                    if self.open_position:
                        self._update_trade_metrics(bar_high, bar_low, current_price, timestamp)

                    # Check all levels (pass estimated delta)
                    signals_this_bar = self._evaluate_bar(
                        strategy, current_price, timestamp, plan, candle_delta=estimated_delta
                    )

                    day_signals.extend(signals_this_bar)

                    # ✅ NEW: Process signals as trade entries
                    for signal in signals_this_bar:
                        self._process_signal_as_trade(signal, current_price, timestamp)

                # ✅ NEW: Close any open position at end of day
                if self.open_position:
                    self._close_trade(bars['close'].iloc[-1], bars.index[-1], reason="EOD")

                # Store results
                self.signals.extend(day_signals)
                self.daily_stats[date_str] = {
                    'signals': len(day_signals),
                    'ticks': tick_count,
                    'high': bars['high'].max(),
                    'low': bars['low'].min(),
                    'close': bars['close'].iloc[-1],
                    'range': bars['high'].max() - bars['low'].min()
                }

                print(f"   ✅ {len(day_signals)} signals | Range: {self.daily_stats[date_str]['range']:.2f}pts")

                # Print signal details
                for sig in day_signals:
                    sig_type = sig['type']
                    # Add quality indicator for FLIP signals
                    quality_str = ""
                    if sig_type == 'FLIP' and 'orderbook' in sig:
                        ob = sig['orderbook']
                        quality_str = f" | Quality: {ob['quality_rating']} ({ob['quality_score']:.0f})"

                    print(f"      🔔 {sig['time'].strftime('%H:%M')} | {sig_type} @ {sig['price']:.2f} | Zone {sig['zone']}{quality_str}")

            except Exception as e:
                print(f"   ❌ Error: {e}")

        print("\n" + "="*60)
        print(f"✅ Backtest Complete: {len(self.signals)} total signals")

    def _create_strategy_for_day(self, plan):
        """Create a StrategyManager instance pre-loaded with a specific day's plan"""
        strategy = StrategyManager.__new__(StrategyManager)
        strategy.context = plan
        strategy.pd_poc = plan.get('pd_profile', {}).get('POC', None)
        strategy.use_poc_filter = self.enable_poc_filter
        strategy.active_monitors = {}

        # Thresholds
        strategy.POC_SWEET_SPOT_MIN = 10.0
        strategy.POC_SWEET_SPOT_MAX = 20.0
        strategy.POC_DANGER_THRESHOLD = 50.0

        # ✅ NEW: Delta filter configuration
        strategy.use_delta_filter = self.use_delta_filter
        strategy.delta_mode = self.delta_mode
        strategy.static_delta_threshold = self.static_delta_threshold
        strategy.dynamic_delta_threshold = None
        strategy.dynamic_volume_threshold = None

        # Calculate dynamic thresholds if needed (using previous day's data)
        if self.use_delta_filter and self.delta_mode == "dynamic":
            # For backtest, calculate from data BEFORE the test day
            # This ensures we're not looking into the future
            strategy.dynamic_delta_threshold = self._calculate_dynamic_threshold_for_day(plan)

        return strategy

    def _calculate_dynamic_threshold_for_day(self, plan):
        """
        Calculate dynamic delta threshold from previous day's data

        ✅ Simplified version using heuristic based on market range
        In production, this would fetch actual trade data from previous day

        Args:
            plan: Current day's plan (contains market context)

        Returns:
            float: Calculated delta threshold or static fallback
        """
        try:
            # Get predicted range from plan
            predicted_range = plan.get('predicted_range', 40.0)

            # Heuristic: Higher volatility days need higher delta threshold
            # Base: 400 for avg 40pt range
            # Scale linearly with range
            dynamic_threshold = 400.0 * (predicted_range / 40.0)

            # Clamp to reasonable bounds (200-800)
            dynamic_threshold = max(200, min(800, dynamic_threshold))

            return dynamic_threshold

        except Exception as e:
            logging.error(f"Error calculating dynamic threshold: {e}")
            return self.static_delta_threshold  # Fallback

    def _evaluate_bar(self, strategy, current_price, timestamp, plan, candle_delta=None):
        """
        Evaluate a single price bar for signals

        ✅ NEW APPROACH: Dynamic SUP/RES designation based on approach direction
        - Levels are treated fluidly - type determined by price approach direction
        - If approaching from below → level acts as RESISTANCE (sell)
        - If approaching from above → level acts as SUPPORT (buy)
        - Whipsaw prevention: don't fire opposite signals in close proximity

        ✅ NEW: Delta filtering support
        - Accepts estimated candle delta for filtering
        - Passes to check_signal for entry validation
        """
        signals = []
        scan_range = 20.0  # Only check levels within 20 points

        # Track fired signals to prevent duplicates within same bar
        fired_this_bar = set()

        # ✅ NEW: Combine all levels (SUP + RES) into one array
        # We'll dynamically assign type based on approach direction
        all_levels = []

        # Get support levels
        for level in plan.get('levels', {}).get('raw_sup', []):
            all_levels.append({
                'price': level['price'],
                'zone': level.get('zone', 0),
                'original_type': 'SUP'  # Track original designation for reference
            })

        # Get resistance levels
        for level in plan.get('levels', {}).get('raw_res', []):
            all_levels.append({
                'price': level['price'],
                'zone': level.get('zone', 0),
                'original_type': 'RES'  # Track original designation for reference
            })

        # Check each level
        for level in all_levels:
            level_price = level['price']

            # Only check levels within scan range
            if abs(current_price - level_price) > scan_range:
                continue

            # ✅ DYNAMIC SUP/RES DESIGNATION
            # Determine approach direction using previous bar's price
            if self.previous_close is not None:
                # Determine if we're approaching from above or below
                prev_distance = abs(self.previous_close - level_price)
                curr_distance = abs(current_price - level_price)

                # Are we getting closer to the level?
                approaching = curr_distance < prev_distance

                if approaching:
                    # Price is approaching - determine from which direction
                    if current_price < level_price:
                        # Approaching from below → level acts as RESISTANCE (sell)
                        level['type'] = 'RES'
                        expected_direction = 'SHORT'
                    else:
                        # Approaching from above → level acts as SUPPORT (buy)
                        level['type'] = 'SUP'
                        expected_direction = 'LONG'
                else:
                    # Not approaching - use position relative to level
                    if current_price < level_price:
                        # Below level → it acts as RESISTANCE (sell when we touch it)
                        level['type'] = 'RES'
                        expected_direction = 'SHORT'
                    else:
                        # Above level → it acts as SUPPORT (buy when we touch it)
                        level['type'] = 'SUP'
                        expected_direction = 'LONG'
            else:
                # First bar - use simple position-based logic
                if current_price < level_price:
                    level['type'] = 'RES'
                    expected_direction = 'SHORT'
                else:
                    level['type'] = 'SUP'
                    expected_direction = 'LONG'

            # ✅ WHIPSAW PREVENTION
            # Don't fire opposite signal if we just fired the other direction at this level
            level_key = f"{level_price:.2f}"
            if level_key in self.level_last_signal:
                last_sig = self.level_last_signal[level_key]
                last_direction = last_sig['direction']
                last_price = last_sig['price']

                # Check if we're trying to fire opposite direction
                if expected_direction != last_direction:
                    # Check if we're still in whipsaw zone
                    if abs(current_price - last_price) <= self.WHIPSAW_PREVENTION_DISTANCE:
                        # Skip - too close to opposite signal
                        continue

            # Check for entry signal (pass delta for filtering)
            signal = self._check_signal(strategy, current_price, level, timestamp, candle_delta=candle_delta)

            if signal:
                signal_key = f"{signal['price']:.2f}_{signal['type']}_{signal['direction']}"

                # Check per-bar deduplication
                if signal_key in fired_this_bar:
                    continue

                # ✅ FIX 2: Check session-wide deduplication with cooldown
                if signal_key in self.fired_signals_session:
                    last_fired = self.fired_signals_session[signal_key]
                    time_since_minutes = (timestamp - last_fired).total_seconds() / 60

                    if time_since_minutes < self.SIGNAL_COOLDOWN_MINUTES:
                        continue  # Skip - too soon since last signal

                # Signal passed all checks
                signals.append(signal)
                fired_this_bar.add(signal_key)
                self.fired_signals_session[signal_key] = timestamp

                # Track this signal for whipsaw prevention
                self.level_last_signal[level_key] = {
                    'direction': signal['direction'],
                    'timestamp': timestamp,
                    'price': current_price
                }

        # Update previous close for next bar
        self.previous_close = current_price

        return signals

    def _check_signal(self, strategy, current_price, level, timestamp, candle_delta=None):
        """
        Check if a level generates a signal

        ✅ INTEGRATION POINT 3: Process FLIP signals with order book analysis
        ✅ NEW: Pass delta for entry filtering
        """
        action, modifier, message = strategy.check_entry_signal(current_price, level,
                                                                 candle_delta=candle_delta,
                                                                 session_delta=None)

        if action == "IMMEDIATE_ENTRY":
            return {
                'time': timestamp,
                'type': 'RESPONSIVE',
                'direction': 'LONG' if level['type'] == 'SUP' else 'SHORT',
                'price': level['price'],
                'zone': strategy.get_zone_number(level),
                'size_mod': modifier,
                'message': message
            }

        elif action == "RECAPTURE_ENTRY":
            return {
                'time': timestamp,
                'type': 'RECAPTURE',
                'direction': 'LONG' if level['type'] == 'SUP' else 'SHORT',
                'price': current_price,
                'zone': strategy.get_zone_number(level),
                'size_mod': modifier,
                'message': message
            }

        elif action == "FLIP_ENTRY":
            signal = {
                'time': timestamp,
                'type': 'FLIP',
                'direction': 'LONG' if level['type'] == 'SUP' else 'SHORT',
                'price': current_price,
                'zone': strategy.get_zone_number(level),
                'size_mod': modifier,
                'message': message
            }

            # ✅ NEW: Order Book Analysis for FLIP signals
            if self.analyze_orderbook and self.ob_analyzer:
                try:
                    # Process this FLIP signal through order book analyzer
                    # NOTE: This requires that the level failure was tracked earlier
                    # For now, we'll attempt analysis but it may return None if
                    # the failure wasn't tracked (which requires deeper integration)

                    ob_result = self.ob_analyzer.process_flip_signal(signal, timestamp)

                    if ob_result:
                        # Attach order book analysis to signal
                        signal['orderbook'] = ob_result

                        # Optional: Filter by quality
                        # Uncomment to skip low-quality FLIPs:
                        # if ob_result['recommendation'] == 'SKIP':
                        #     print(f"      ⚠️  Low quality FLIP @ {current_price:.2f} (score: {ob_result['quality_score']:.1f}) - SKIPPED")
                        #     return None

                        # Log quality for debugging
                        quality_rating = ob_result['quality_rating']
                        quality_score = ob_result['quality_score']
                        recommendation = ob_result['recommendation']

                        if recommendation == 'SKIP':
                            print(f"      ⚠️  FLIP quality: {quality_rating} ({quality_score:.1f}) - {recommendation}")
                        else:
                            print(f"      ✅ FLIP quality: {quality_rating} ({quality_score:.1f}) - {recommendation}")

                except Exception as e:
                    # Don't fail the backtest if order book analysis fails
                    print(f"      ⚠️  Order book analysis error: {e}")

            return signal

        return None

    def generate_report(self):
        """
        Generate comprehensive backtest report

        ✅ INTEGRATION POINT 4: Add order book analysis report
        """
        print("\n" + "="*60)
        print("📊 BACKTEST REPORT")
        print("="*60)

        # Convert signals to DataFrame
        if not self.signals:
            print("❌ No signals generated during backtest period!")
            return

        df = pd.DataFrame(self.signals)

        # Overall stats
        print(f"\n📈 OVERALL STATISTICS")
        print(f"   Period: {self.start_date} to {self.end_date}")
        print(f"   Trading Days: {len(self.daily_stats)}")
        print(f"   Total Signals: {len(df)}")
        print(f"   Avg Signals/Day: {len(df) / max(len(self.daily_stats), 1):.1f}")

        # Signal breakdown
        print(f"\n🎯 SIGNAL BREAKDOWN")
        print(f"   Responsive: {len(df[df['type']=='RESPONSIVE'])}")
        print(f"   Recapture: {len(df[df['type']=='RECAPTURE'])}")
        print(f"   Flip: {len(df[df['type']=='FLIP'])}")
        print(f"\n   Long Signals: {len(df[df['direction']=='LONG'])}")
        print(f"   Short Signals: {len(df[df['direction']=='SHORT'])}")

        # Zone distribution
        print(f"\n📍 ZONE DISTRIBUTION")
        for zone in sorted(df['zone'].unique()):
            count = len(df[df['zone']==zone])
            pct = (count / len(df)) * 100
            print(f"   Zone {zone}: {count} ({pct:.1f}%)")

        # Daily breakdown
        print(f"\n📅 TOP SIGNAL DAYS")
        daily_counts = defaultdict(int)
        for sig in self.signals:
            date_key = sig['time'].strftime('%Y-%m-%d')
            daily_counts[date_key] += 1

        top_days = sorted(daily_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        for date, count in top_days:
            day_range = self.daily_stats.get(date, {}).get('range', 0)
            print(f"   {date}: {count} signals (range: {day_range:.1f}pts)")

        # Size modifier stats
        print(f"\n⚖️ SIZE MODIFIER STATS")
        print(f"   Min: {df['size_mod'].min():.2f}x")
        print(f"   Max: {df['size_mod'].max():.2f}x")
        print(f"   Avg: {df['size_mod'].mean():.2f}x")

        # Save detailed CSV
        csv_file = f"{BACKTEST_OUTPUT}/signals_{self.start_date}_to_{self.end_date}.csv"
        df.to_csv(csv_file, index=False)
        print(f"\n💾 Detailed signals saved to: {csv_file}")

        # Save summary JSON
        summary = {
            'period': {
                'start': str(self.start_date),
                'end': str(self.end_date)
            },
            'stats': {
                'trading_days': len(self.daily_stats),
                'total_signals': len(df),
                'avg_signals_per_day': len(df) / max(len(self.daily_stats), 1),
                'responsive': int(len(df[df['type']=='RESPONSIVE'])),
                'recapture': int(len(df[df['type']=='RECAPTURE'])),
                'flip': int(len(df[df['type']=='FLIP'])),
                'long': int(len(df[df['direction']=='LONG'])),
                'short': int(len(df[df['direction']=='SHORT']))
            },
            'zone_distribution': {
                f'zone_{zone}': int(len(df[df['zone']==zone]))
                for zone in sorted(df['zone'].unique())
            },
            'top_days': [
                {'date': date, 'signals': count, 'range': self.daily_stats.get(date, {}).get('range', 0)}
                for date, count in top_days
            ]
        }

        json_file = f"{BACKTEST_OUTPUT}/summary_{self.start_date}_to_{self.end_date}.json"
        with open(json_file, 'w') as f:
            json.dump(summary, f, indent=4)
        print(f"💾 Summary saved to: {json_file}")

        # ✅ NEW: Trade Results Report
        if self.trades:
            print("\n" + "="*60)
            print("💰 TRADE RESULTS (MAE/MFE ANALYSIS)")
            print("="*60)

            trades_df = pd.DataFrame(self.trades)

            # Overall trade stats
            total_trades = len(trades_df)
            winning_trades = len(trades_df[trades_df['pnl'] > 0])
            losing_trades = len(trades_df[trades_df['pnl'] < 0])
            breakeven_trades = len(trades_df[trades_df['pnl'] == 0])

            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

            print(f"\n📊 PERFORMANCE METRICS")
            print(f"   Total Trades: {total_trades}")
            print(f"   Winners: {winning_trades} ({win_rate:.1f}%)")
            print(f"   Losers: {losing_trades}")
            print(f"   Breakeven: {breakeven_trades}")

            # P&L Stats
            total_pnl = trades_df['pnl'].sum()
            avg_pnl = trades_df['pnl'].mean()
            avg_winner = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
            avg_loser = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0

            print(f"\n💵 PROFIT & LOSS")
            print(f"   Total P&L: {total_pnl:.2f} pts (${total_pnl * 50:.2f})")
            print(f"   Avg P&L: {avg_pnl:.2f} pts")
            print(f"   Avg Winner: {avg_winner:.2f} pts")
            print(f"   Avg Loser: {avg_loser:.2f} pts")
            if avg_loser != 0:
                profit_factor = abs(avg_winner / avg_loser)
                print(f"   Profit Factor: {profit_factor:.2f}")

            # MAE/MFE Stats
            print(f"\n📉 MAE/MFE ANALYSIS")
            print(f"   Avg MAE (Max Adverse): {trades_df['mae'].mean():.2f} pts")
            print(f"   Avg MFE (Max Favorable): {trades_df['mfe'].mean():.2f} pts")
            print(f"   Max MAE: {trades_df['mae'].max():.2f} pts")
            print(f"   Max MFE: {trades_df['mfe'].max():.2f} pts")

            # Exit reason breakdown
            print(f"\n🚪 EXIT REASONS")
            for reason, count in trades_df['exit_reason'].value_counts().items():
                pct = (count / total_trades) * 100
                print(f"   {reason}: {count} ({pct:.1f}%)")

            # Duration stats
            print(f"\n⏱️  TRADE DURATION")
            print(f"   Avg: {trades_df['duration_minutes'].mean():.1f} minutes")
            print(f"   Min: {trades_df['duration_minutes'].min():.1f} minutes")
            print(f"   Max: {trades_df['duration_minutes'].max():.1f} minutes")

            # Direction breakdown
            print(f"\n🎯 DIRECTION BREAKDOWN")
            for direction in ['LONG', 'SHORT']:
                dir_trades = trades_df[trades_df['direction'] == direction]
                if len(dir_trades) > 0:
                    dir_pnl = dir_trades['pnl'].sum()
                    dir_wins = len(dir_trades[dir_trades['pnl'] > 0])
                    dir_wr = (dir_wins / len(dir_trades)) * 100
                    print(f"   {direction}: {len(dir_trades)} trades | {dir_pnl:.2f} pts | {dir_wr:.1f}% WR")

            # Save trades CSV
            trades_csv = f"{BACKTEST_OUTPUT}/trades_{self.start_date}_to_{self.end_date}.csv"
            trades_df.to_csv(trades_csv, index=False)
            print(f"\n💾 Trade details saved to: {trades_csv}")

        else:
            print("\n⚠️  No trades executed (signals may not have met entry criteria)")

        # ✅ NEW: Order Book Analysis Report
        if self.analyze_orderbook and self.ob_analyzer:
            print("\n" + "="*60)
            print("📊 ORDER BOOK FLIP ANALYSIS")
            print("="*60)

            # Generate summary report
            df_ob = self.ob_analyzer.generate_summary_report()

            if not df_ob.empty:
                # Export detailed order book analysis
                ob_csv_file = f"{BACKTEST_OUTPUT}/flip_orderbook_{self.start_date}_to_{self.end_date}.csv"
                self.ob_analyzer.export_to_csv(ob_csv_file)
                print(f"\n💾 Order book analysis saved to: {ob_csv_file}")

                # Generate quality distribution chart
                ob_chart_file = f"{BACKTEST_OUTPUT}/flip_quality_{self.start_date}_to_{self.end_date}.png"
                try:
                    self.ob_analyzer.plot_quality_distribution(ob_chart_file)
                    print(f"📊 Quality chart saved to: {ob_chart_file}")
                except Exception as e:
                    print(f"⚠️  Could not generate quality chart: {e}")
            else:
                print("\n⚠️  No FLIP signals were analyzed (may need to implement failure tracking)")
                print("   See ORDERBOOK_WORKFLOW.md for integration details")

        print("\n" + "="*60)

    def plot_results(self):
        """Generate visualization charts"""
        if not self.signals:
            print("⚠️ No signals to plot")
            return

        print("\n📊 Generating Charts...")

        df = pd.DataFrame(self.signals)
        df['date'] = pd.to_datetime(df['time']).dt.date

        # Set style
        sns.set_style("whitegrid")
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle(f'Backtest Results: {self.start_date} to {self.end_date}', fontsize=16, fontweight='bold')

        # 1. Signals per day
        daily_counts = df.groupby('date').size()
        axes[0, 0].bar(range(len(daily_counts)), daily_counts.values, color='steelblue')
        axes[0, 0].set_title('Signals Per Day', fontweight='bold')
        axes[0, 0].set_xlabel('Trading Day')
        axes[0, 0].set_ylabel('Signal Count')
        axes[0, 0].grid(axis='y', alpha=0.3)

        # 2. Signal type distribution
        type_counts = df['type'].value_counts()
        colors = ['#2ecc71', '#e74c3c', '#3498db']  # Green, Red, Blue for RESPONSIVE, RECAPTURE, FLIP
        axes[0, 1].pie(type_counts.values, labels=type_counts.index, autopct='%1.1f%%',
                       colors=colors[:len(type_counts)], startangle=90)
        axes[0, 1].set_title('Signal Type Distribution', fontweight='bold')

        # 3. Zone distribution
        zone_counts = df['zone'].value_counts().sort_index()
        axes[1, 0].bar(zone_counts.index, zone_counts.values, color='coral')
        axes[1, 0].set_title('Zone Distribution', fontweight='bold')
        axes[1, 0].set_xlabel('Zone')
        axes[1, 0].set_ylabel('Signal Count')
        axes[1, 0].set_xticks(zone_counts.index)
        axes[1, 0].grid(axis='y', alpha=0.3)

        # 4. Direction distribution
        direction_counts = df['direction'].value_counts()
        colors_dir = ['#3498db', '#e67e22']
        axes[1, 1].pie(direction_counts.values, labels=direction_counts.index, autopct='%1.1f%%',
                       colors=colors_dir, startangle=90)
        axes[1, 1].set_title('Long vs Short Signals', fontweight='bold')

        plt.tight_layout()

        # Save plot
        plot_file = f"{BACKTEST_OUTPUT}/charts_{self.start_date}_to_{self.end_date}.png"
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        print(f"✅ Charts saved to: {plot_file}")

        # Show plot (optional - comment out for headless environments)
        # plt.show()

    def run_full_backtest(self):
        """Execute complete backtest workflow"""
        print("\n" + "="*60)
        print("🚀 STARTING FULL BACKTEST")
        print("="*60 + "\n")

        # Step 1: Generate plans
        self.generate_historical_plans()

        # Step 2: Run backtest
        self.run_backtest()

        # Step 3: Generate report
        self.generate_report()

        # Step 4: Plot results
        try:
            self.plot_results()
        except Exception as e:
            print(f"⚠️ Could not generate charts: {e}")

        print("\n" + "="*60)
        print("✅ BACKTEST COMPLETE!")
        print("="*60)

    def _process_signal_as_trade(self, signal, current_price, timestamp):
        """
        Process a signal as a trade entry

        Handles:
        - Opening new position if no position open
        - Flipping position if opposite signal
        - Ignoring signal if same direction already open
        """
        signal_direction = signal['direction']  # 'LONG' or 'SHORT'

        # If no position, open new trade
        if self.open_position is None:
            self.open_position = {
                'direction': signal_direction,
                'entry_price': current_price,
                'entry_time': timestamp,
                'entry_signal': signal,
                'mae': 0.0,  # Maximum Adverse Excursion
                'mfe': 0.0,  # Maximum Favorable Excursion
                'running_pnl': 0.0
            }
            return

        # If opposite signal, close current and open new
        if signal_direction != self.open_position['direction']:
            # Close existing position
            self._close_trade(current_price, timestamp, reason="FLIP")

            # Open new position in opposite direction
            self.open_position = {
                'direction': signal_direction,
                'entry_price': current_price,
                'entry_time': timestamp,
                'entry_signal': signal,
                'mae': 0.0,
                'mfe': 0.0,
                'running_pnl': 0.0
            }

        # If same direction signal, ignore (already in trade)

    def _update_trade_metrics(self, bar_high, bar_low, bar_close, timestamp):
        """
        Update MAE/MFE for open position based on current bar

        MAE: Maximum Adverse Excursion (worst drawdown)
        MFE: Maximum Favorable Excursion (best profit)
        """
        if not self.open_position:
            return

        entry_price = self.open_position['entry_price']
        direction = self.open_position['direction']

        if direction == 'LONG':
            # For long trades
            # MFE is highest point above entry
            # MAE is lowest point below entry
            favorable_move = bar_high - entry_price
            adverse_move = entry_price - bar_low

            # Track running P&L
            self.open_position['running_pnl'] = bar_close - entry_price

            # Update MFE (max profit)
            if favorable_move > self.open_position['mfe']:
                self.open_position['mfe'] = favorable_move

            # Update MAE (max loss)
            if adverse_move > self.open_position['mae']:
                self.open_position['mae'] = adverse_move

            # Check stop/target
            if adverse_move >= self.STOP_LOSS:
                self._close_trade(entry_price - self.STOP_LOSS, timestamp, reason="STOP")
            elif favorable_move >= self.TARGET_PROFIT:
                self._close_trade(entry_price + self.TARGET_PROFIT, timestamp, reason="TARGET")

        else:  # SHORT
            # For short trades
            # MFE is lowest point below entry
            # MAE is highest point above entry
            favorable_move = entry_price - bar_low
            adverse_move = bar_high - entry_price

            # Track running P&L
            self.open_position['running_pnl'] = entry_price - bar_close

            # Update MFE (max profit)
            if favorable_move > self.open_position['mfe']:
                self.open_position['mfe'] = favorable_move

            # Update MAE (max loss)
            if adverse_move > self.open_position['mae']:
                self.open_position['mae'] = adverse_move

            # Check stop/target
            if adverse_move >= self.STOP_LOSS:
                self._close_trade(entry_price + self.STOP_LOSS, timestamp, reason="STOP")
            elif favorable_move >= self.TARGET_PROFIT:
                self._close_trade(entry_price - self.TARGET_PROFIT, timestamp, reason="TARGET")

    def _close_trade(self, exit_price, exit_time, reason="MANUAL"):
        """
        Close open position and record trade results

        Args:
            exit_price: Price at which trade exits
            exit_time: Timestamp of exit
            reason: Exit reason (STOP/TARGET/EOD/FLIP/MANUAL)
        """
        if not self.open_position:
            return

        # Calculate final P&L
        entry_price = self.open_position['entry_price']
        direction = self.open_position['direction']

        if direction == 'LONG':
            pnl = exit_price - entry_price
        else:  # SHORT
            pnl = entry_price - exit_price

        # Calculate trade duration
        duration = (exit_time - self.open_position['entry_time']).total_seconds() / 60  # minutes

        # Record completed trade
        trade_record = {
            'entry_time': self.open_position['entry_time'],
            'exit_time': exit_time,
            'duration_minutes': duration,
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': pnl,
            'mae': self.open_position['mae'],  # Max loss during trade
            'mfe': self.open_position['mfe'],  # Max profit during trade
            'exit_reason': reason,
            'entry_signal_type': self.open_position['entry_signal']['type'],
            'entry_zone': self.open_position['entry_signal']['zone'],
            'entry_level_price': self.open_position['entry_signal']['price']
        }

        self.trades.append(trade_record)

        # Clear open position
        self.open_position = None


# ==============================================================================
# QUICK BACKTEST RUNNER
# ==============================================================================
def quick_backtest(days_back=7, enable_poc=False, enable_orderbook=False, ob_api_key=None):
    """
    Quick backtest for last N trading days

    Args:
        days_back: Number of trading days to test
        enable_poc: Enable POC distance filter
        enable_orderbook: Enable order book FLIP analysis (NEW)
        ob_api_key: Databento API key for order book data (NEW)
    """
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)  # Yesterday
    start_date = end_date - timedelta(days=days_back + 5)  # Add buffer for weekends

    backtester = TradingBotBacktester(
        start_date,
        end_date,
        enable_poc,
        analyze_orderbook=enable_orderbook,
        databento_api_key=ob_api_key
    )
    backtester.run_full_backtest()

    return backtester


# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    print("="*60)
    print("   ES TRADING BOT BACKTESTER")
    print("   ✅ WITH ORDER BOOK FLIP ANALYSIS")
    print("="*60)
    print("\n1. Quick Backtest (Last 7 trading days)")
    print("2. Quick Backtest (Last 30 trading days)")
    print("3. Custom Date Range")
    print("4. Extended Backtest (Last 90 days)")

    choice = input("\nSelect Option [1-4]: ").strip()

    enable_poc = input("Enable POC Filter? [y/N]: ").strip().lower() == 'y'
    enable_ob = input("Enable Order Book Analysis? [y/N]: ").strip().lower() == 'y'

    ob_key = None
    if enable_ob:
        ob_key = input("Enter Databento API Key (or press Enter to skip): ").strip()
        if not ob_key:
            print("⚠️  No API key provided, order book analysis will be disabled")
            enable_ob = False

    if choice == "1":
        print("\n🔬 Running 7-Day Backtest...")
        quick_backtest(days_back=7, enable_poc=enable_poc, enable_orderbook=enable_ob, ob_api_key=ob_key)

    elif choice == "2":
        print("\n🔬 Running 30-Day Backtest...")
        quick_backtest(days_back=30, enable_poc=enable_poc, enable_orderbook=enable_ob, ob_api_key=ob_key)

    elif choice == "3":
        start_str = input("Start Date (YYYY-MM-DD): ").strip()
        end_str = input("End Date (YYYY-MM-DD): ").strip()

        try:
            start = datetime.strptime(start_str, "%Y-%m-%d").date()
            end = datetime.strptime(end_str, "%Y-%m-%d").date()

            backtester = TradingBotBacktester(
                start,
                end,
                enable_poc,
                analyze_orderbook=enable_ob,
                databento_api_key=ob_key
            )
            backtester.run_full_backtest()
        except ValueError:
            print("❌ Invalid date format!")

    elif choice == "4":
        print("\n🔬 Running 90-Day Backtest (this may take a while)...")
        quick_backtest(days_back=90, enable_poc=enable_poc, enable_orderbook=enable_ob, ob_api_key=ob_key)

    else:
        print("❌ Invalid choice")
