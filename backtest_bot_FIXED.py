"""
ES Trading Bot Backtester - FIXED VERSION
Replays historical data with proper signal deduplication
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
# BACKTESTER - FIXED VERSION
# ==============================================================================
class TradingBotBacktester:
    def __init__(self, start_date, end_date, enable_poc_filter=False, signal_cooldown_minutes=15):
        """
        Initialize backtester

        Args:
            start_date: datetime.date - First day to test
            end_date: datetime.date - Last day to test
            enable_poc_filter: bool - Enable POC distance filtering
            signal_cooldown_minutes: int - Minimum time between signals on same level (default: 15 min)
        """
        self.start_date = start_date
        self.end_date = end_date
        self.enable_poc_filter = enable_poc_filter
        self.signal_cooldown = timedelta(minutes=signal_cooldown_minutes)

        if "YOUR_DATABENTO" in API_KEY:
            print("❌ ERROR: Please set your Databento API Key")
            sys.exit(1)

        self.client = db.Historical(API_KEY)
        self.planner = MarketPlanner()

        # Results tracking
        self.daily_plans = {}
        self.signals = []
        self.daily_stats = {}

        # ✅ FIX: Track last signal time per level (session-wide)
        self.last_signal_time = {}

        print(f"🔬 BACKTESTER INITIALIZED (FIXED VERSION)")
        print(f"   Period: {start_date} to {end_date}")
        print(f"   POC Filter: {enable_poc_filter}")
        print(f"   Signal Cooldown: {signal_cooldown_minutes} minutes")
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

            # ✅ FIX: Reset signal tracking at start of each day
            self.last_signal_time = {}

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

                # Track day stats
                day_signals = []
                tick_count = 0

                # Replay each bar
                for timestamp, bar in bars.iterrows():
                    tick_count += 1
                    current_price = bar['close']

                    # Check all levels
                    signals_this_bar = self._evaluate_bar(
                        strategy, current_price, timestamp, plan
                    )

                    day_signals.extend(signals_this_bar)

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
                    print(f"      🔔 {sig['time'].strftime('%H:%M')} | {sig['type']} @ {sig['price']:.2f} | Zone {sig['zone']}")

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

        return strategy

    def _evaluate_bar(self, strategy, current_price, timestamp, plan):
        """
        ✅ FIXED: Evaluate a single price bar with proper deduplication
        """
        signals = []
        scan_range = 20.0  # Only check levels within 20 points

        # Check support levels
        for level in plan.get('levels', {}).get('raw_sup', []):
            if abs(current_price - level['price']) <= scan_range:
                level['type'] = 'SUP'
                signal = self._check_signal_with_cooldown(
                    strategy, current_price, level, timestamp
                )
                if signal:
                    signals.append(signal)

        # Check resistance levels
        for level in plan.get('levels', {}).get('raw_res', []):
            if abs(current_price - level['price']) <= scan_range:
                level['type'] = 'RES'
                signal = self._check_signal_with_cooldown(
                    strategy, current_price, level, timestamp
                )
                if signal:
                    signals.append(signal)

        return signals

    def _check_signal_with_cooldown(self, strategy, current_price, level, timestamp):
        """
        ✅ NEW: Check signal with cooldown period enforcement
        """
        # Create unique key for this level + direction
        signal_key = f"{level['price']:.2f}_{level['type']}"

        # Check if we recently fired a signal on this level
        if signal_key in self.last_signal_time:
            time_since_last = timestamp - self.last_signal_time[signal_key]
            if time_since_last < self.signal_cooldown:
                # Still in cooldown period, skip
                return None

        # Check if signal should fire
        action, modifier, message = strategy.check_entry_signal(current_price, level)

        signal = None

        if action == "IMMEDIATE_ENTRY":
            signal = {
                'time': timestamp,
                'type': 'RESPONSIVE',
                'direction': 'LONG' if level['type'] == 'SUP' else 'SHORT',
                'price': level['price'],
                'zone': strategy.get_zone_number(level),
                'size_mod': modifier,
                'message': message
            }

        elif action == "RECAPTURE_ENTRY":
            signal = {
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

        # If signal fired, record timestamp
        if signal:
            self.last_signal_time[signal_key] = timestamp

        return signal

    def generate_report(self):
        """Generate comprehensive backtest report"""
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

        # ✅ NEW: Signal quality assessment
        avg_per_day = len(df) / max(len(self.daily_stats), 1)
        print(f"\n🎯 QUALITY ASSESSMENT")
        if avg_per_day < 2:
            print(f"   ⚠️ LOW: Only {avg_per_day:.1f} signals/day. Consider loosening filters.")
        elif avg_per_day > 15:
            print(f"   ⚠️ HIGH: {avg_per_day:.1f} signals/day. May include noise.")
        else:
            print(f"   ✅ GOOD: {avg_per_day:.1f} signals/day is within healthy range (3-10).")

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
        colors = ['#2ecc71', '#e74c3c']
        axes[0, 1].pie(type_counts.values, labels=type_counts.index, autopct='%1.1f%%',
                       colors=colors, startangle=90)
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


# ==============================================================================
# QUICK BACKTEST RUNNER
# ==============================================================================
def quick_backtest(days_back=7, enable_poc=False, cooldown_minutes=15):
    """
    Quick backtest for last N trading days

    Args:
        days_back: Number of trading days to test
        enable_poc: Enable POC distance filter
        cooldown_minutes: Minutes between signals on same level (default: 15)
    """
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)  # Yesterday
    start_date = end_date - timedelta(days=days_back + 5)  # Add buffer for weekends

    backtester = TradingBotBacktester(start_date, end_date, enable_poc, cooldown_minutes)
    backtester.run_full_backtest()

    return backtester


# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    print("="*60)
    print("   ES TRADING BOT BACKTESTER (FIXED)")
    print("="*60)
    print("\n1. Quick Backtest (Last 7 trading days)")
    print("2. Quick Backtest (Last 30 trading days)")
    print("3. Custom Date Range")
    print("4. Extended Backtest (Last 90 days)")

    choice = input("\nSelect Option [1-4]: ").strip()

    enable_poc = input("Enable POC Filter? [y/N]: ").strip().lower() == 'y'

    # ✅ NEW: Ask for cooldown period
    cooldown_input = input("Signal Cooldown (minutes) [15]: ").strip()
    cooldown = int(cooldown_input) if cooldown_input else 15

    if choice == "1":
        print(f"\n🔬 Running 7-Day Backtest (cooldown: {cooldown}min)...")
        quick_backtest(days_back=7, enable_poc=enable_poc, cooldown_minutes=cooldown)

    elif choice == "2":
        print(f"\n🔬 Running 30-Day Backtest (cooldown: {cooldown}min)...")
        quick_backtest(days_back=30, enable_poc=enable_poc, cooldown_minutes=cooldown)

    elif choice == "3":
        start_str = input("Start Date (YYYY-MM-DD): ").strip()
        end_str = input("End Date (YYYY-MM-DD): ").strip()

        try:
            start = datetime.strptime(start_str, "%Y-%m-%d").date()
            end = datetime.strptime(end_str, "%Y-%m-%d").date()

            backtester = TradingBotBacktester(start, end, enable_poc, cooldown)
            backtester.run_full_backtest()
        except ValueError:
            print("❌ Invalid date format!")

    elif choice == "4":
        print(f"\n🔬 Running 90-Day Backtest (cooldown: {cooldown}min)...")
        quick_backtest(days_back=90, enable_poc=enable_poc, cooldown_minutes=cooldown)

    else:
        print("❌ Invalid choice")
