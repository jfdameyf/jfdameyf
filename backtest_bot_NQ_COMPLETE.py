"""
NQ Trading Bot Backtester - COMPLETE VERSION
With MFE/MAE Analysis, Trade Outcomes, and Strict RTH Filtering
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

# Import from NQ bot
from trading_bot_NQ_FIXED import StrategyManager, MarketPlanner

# Configuration
API_KEY = # will place your databento API key here
SYMBOL = "NQ.c.0"
NY_TZ = pytz.timezone('America/New_York')

CRITICAL_LEVELS_FILE = "critical_levels_NQ_master.csv"
BACKTEST_OUTPUT = "backtest_results_NQ"
os.makedirs(BACKTEST_OUTPUT, exist_ok=True)

# ==============================================================================
# BACKTESTER WITH MFE/MAE ANALYSIS (NQ)
# ==============================================================================
class TradingBotBacktester:
    def __init__(self, start_date, end_date, enable_poc_filter=False,
                 signal_cooldown_minutes=60, target_points=10.0, stop_points=6.0):
        """
        Initialize NQ backtester with trade outcome analysis

        Args:
            start_date: datetime.date - First day to test
            end_date: datetime.date - Last day to test
            enable_poc_filter: bool - Enable POC distance filtering
            signal_cooldown_minutes: int - Minimum time between signals (default: 60)
            target_points: float - Profit target in points (default: 10.0)
            stop_points: float - Stop loss in points (default: 6.0)
        """
        self.start_date = start_date
        self.end_date = end_date
        self.enable_poc_filter = enable_poc_filter
        self.signal_cooldown = timedelta(minutes=signal_cooldown_minutes)
        self.target_points = target_points
        self.stop_points = stop_points

        if "YOUR_DATABENTO" in API_KEY:
            print("❌ ERROR: Please set your Databento API Key")
            sys.exit(1)

        self.client = db.Historical(API_KEY)
        self.planner = MarketPlanner()

        # Results tracking
        self.daily_plans = {}
        self.signals = []
        self.trades = []  # Track full trade outcomes
        self.daily_stats = {}

        # Track last signal time per level (session-wide)
        self.last_signal_time = {}

        print(f"🔬 NQ BACKTESTER INITIALIZED (COMPLETE VERSION)")
        print(f"   Period: {start_date} to {end_date}")
        print(f"   POC Filter: {enable_poc_filter}")
        print(f"   Signal Cooldown: {signal_cooldown_minutes} minutes")
        print(f"   Target: {target_points} pts | Stop: {stop_points} pts")
        print(f"   Point Value: $20/point (NQ)")
        print(f"   Symbol: {SYMBOL}\n")

    def generate_historical_plans(self):
        """Generate daily trading plans for each day in backtest period"""
        print("📅 Generating Historical NQ Plans...")
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
                with open('nq_daily_context.json', 'r') as f:
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
        print(f"✅ Generated {len(self.daily_plans)} daily NQ plans\n")

    def run_backtest(self):
        """Main backtesting loop - replays historical data with trade analysis"""
        print("🔄 Running NQ Backtest with Trade Analysis...")
        print("="*60 + "\n")

        for date_str, plan in self.daily_plans.items():
            print(f"📈 Backtesting: {date_str}")

            # Reset signal tracking at start of each day
            self.last_signal_time = {}

            # Parse date
            test_date = datetime.strptime(date_str, '%Y-%m-%d').date()

            # ✅ FIX: Strict RTH hours (9:30 - 16:00 ET)
            start_dt = NY_TZ.localize(datetime.combine(test_date, time(9, 30)))
            end_dt = NY_TZ.localize(datetime.combine(test_date, time(16, 0)))

            try:
                # Fetch minute bars for RTH session
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

                # ✅ FIX: Verify all bars are within RTH
                bars = bars.between_time('09:30', '16:00')

                if bars.empty:
                    print(f"   ⚠️ No RTH data")
                    continue

                # Initialize strategy for this day
                strategy = self._create_strategy_for_day(plan)

                # Track day stats
                day_signals = []
                day_trades = []
                tick_count = 0

                # Replay each bar
                for idx, (timestamp, bar) in enumerate(bars.iterrows()):
                    tick_count += 1
                    current_price = bar['close']

                    # ✅ ADDITIONAL CHECK: Verify timestamp is within RTH
                    hour = timestamp.hour
                    minute = timestamp.minute

                    if not (9 <= hour < 16 or (hour == 9 and minute >= 30)):
                        continue  # Skip non-RTH bars

                    # Check all levels for signals
                    signals_this_bar = self._evaluate_bar(
                        strategy, current_price, timestamp, plan
                    )

                    for signal in signals_this_bar:
                        # Calculate MFE/MAE for this signal
                        trade_outcome = self._calculate_trade_outcome(
                            signal, bars, idx, timestamp
                        )

                        if trade_outcome:
                            day_signals.append(signal)
                            day_trades.append(trade_outcome)

                # Store results
                self.signals.extend(day_signals)
                self.trades.extend(day_trades)

                self.daily_stats[date_str] = {
                    'signals': len(day_signals),
                    'ticks': tick_count,
                    'high': bars['high'].max(),
                    'low': bars['low'].min(),
                    'close': bars['close'].iloc[-1],
                    'range': bars['high'].max() - bars['low'].min(),
                    'winners': sum(1 for t in day_trades if t['outcome'] == 'WIN'),
                    'losers': sum(1 for t in day_trades if t['outcome'] == 'LOSS')
                }

                win_rate = (self.daily_stats[date_str]['winners'] / len(day_signals) * 100) if day_signals else 0

                print(f"   ✅ {len(day_signals)} signals | Range: {self.daily_stats[date_str]['range']:.2f}pts | Win Rate: {win_rate:.0f}%")

                # Print signal details (RTH only)
                for sig in day_signals[:5]:  # Show first 5
                    print(f"      🔔 {sig['time'].strftime('%H:%M')} | {sig['type']} @ {sig['price']:.2f} | Zone {sig['zone']}")

                if len(day_signals) > 5:
                    print(f"      ... and {len(day_signals) - 5} more")

            except Exception as e:
                print(f"   ❌ Error: {e}")

        print("\n" + "="*60)
        print(f"✅ Backtest Complete: {len(self.signals)} total signals, {len(self.trades)} trades analyzed")

    def _create_strategy_for_day(self, plan):
        """Create a StrategyManager instance pre-loaded with a specific day's plan"""
        strategy = StrategyManager.__new__(StrategyManager)
        strategy.context = plan
        strategy.pd_poc = plan.get('pd_profile', {}).get('POC', None)
        strategy.use_poc_filter = self.enable_poc_filter
        strategy.active_monitors = {}

        # NQ Thresholds (4x ES)
        strategy.POC_SWEET_SPOT_MIN = 40.0
        strategy.POC_SWEET_SPOT_MAX = 80.0
        strategy.POC_DANGER_THRESHOLD = 200.0

        return strategy

    def _evaluate_bar(self, strategy, current_price, timestamp, plan):
        """Evaluate a single price bar with strict cooldown"""
        signals = []
        scan_range = 80.0  # NQ: 80pts (ES was 20pts)

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
        Check signal with strict cooldown enforcement
        ✅ FIX: Improved key generation to prevent duplicates
        """
        # Create unique key: price_type_zone
        zone = strategy.get_zone_number(level)
        signal_key = f"{level['price']:.2f}_{level['type']}_Z{zone}"

        # Check cooldown
        if signal_key in self.last_signal_time:
            time_since_last = timestamp - self.last_signal_time[signal_key]
            if time_since_last < self.signal_cooldown:
                return None  # Still in cooldown

        # Check if signal should fire
        action, modifier, message = strategy.check_entry_signal(current_price, level)

        signal = None

        if action == "IMMEDIATE_ENTRY":
            signal = {
                'time': timestamp,
                'type': 'RESPONSIVE',
                'direction': 'LONG' if level['type'] == 'SUP' else 'SHORT',
                'price': level['price'],
                'entry_price': current_price,  # Actual fill price
                'zone': zone,
                'size_mod': modifier,
                'message': message
            }

        elif action == "RECAPTURE_ENTRY":
            signal = {
                'time': timestamp,
                'type': 'RECAPTURE',
                'direction': 'LONG' if level['type'] == 'SUP' else 'SHORT',
                'price': level['price'],
                'entry_price': current_price,
                'zone': zone,
                'size_mod': modifier,
                'message': message
            }

        elif action == "FLIP_ENTRY":
            signal = {
                'time': timestamp,
                'type': 'FLIP',
                'direction': 'LONG' if level['type'] == 'SUP' else 'SHORT',
                'price': level['price'],
                'entry_price': current_price,
                'zone': zone,
                'size_mod': modifier,
                'message': message
            }

        # Record signal time
        if signal:
            self.last_signal_time[signal_key] = timestamp

        return signal

    def _calculate_trade_outcome(self, signal, bars, entry_idx, entry_time):
        """
        Calculate MFE/MAE and trade outcome for NQ

        Args:
            signal: Signal dictionary
            bars: Full day's price bars
            entry_idx: Index of entry bar
            entry_time: Entry timestamp

        Returns:
            Dictionary with trade outcome metrics
        """
        entry_price = signal['entry_price']
        direction = signal['direction']

        # Get subsequent bars (up to 2 hours or end of day)
        max_bars = 120  # 2 hours
        subsequent_bars = bars.iloc[entry_idx:entry_idx + max_bars]

        if subsequent_bars.empty:
            return None

        # Initialize tracking
        mfe = 0.0  # Maximum Favorable Excursion
        mae = 0.0  # Maximum Adverse Excursion
        exit_price = None
        exit_time = None
        exit_reason = "EOD"
        outcome = "SCRATCH"
        bars_held = 0

        # Track price movement
        for idx, (ts, bar) in enumerate(subsequent_bars.iterrows()):
            high = bar['high']
            low = bar['low']
            close = bar['close']

            if direction == 'LONG':
                # Favorable = higher, Adverse = lower
                favorable_move = high - entry_price
                adverse_move = entry_price - low

                # Update MFE/MAE
                if favorable_move > mfe:
                    mfe = favorable_move

                if adverse_move > mae:
                    mae = adverse_move

                # Check target hit
                if high >= entry_price + self.target_points:
                    exit_price = entry_price + self.target_points
                    exit_time = ts
                    exit_reason = "TARGET"
                    outcome = "WIN"
                    bars_held = idx
                    break

                # Check stop hit
                if low <= entry_price - self.stop_points:
                    exit_price = entry_price - self.stop_points
                    exit_time = ts
                    exit_reason = "STOP"
                    outcome = "LOSS"
                    bars_held = idx
                    break

            else:  # SHORT
                # Favorable = lower, Adverse = higher
                favorable_move = entry_price - low
                adverse_move = high - entry_price

                # Update MFE/MAE
                if favorable_move > mfe:
                    mfe = favorable_move

                if adverse_move > mae:
                    mae = adverse_move

                # Check target hit
                if low <= entry_price - self.target_points:
                    exit_price = entry_price - self.target_points
                    exit_time = ts
                    exit_reason = "TARGET"
                    outcome = "WIN"
                    bars_held = idx
                    break

                # Check stop hit
                if high >= entry_price + self.stop_points:
                    exit_price = entry_price + self.stop_points
                    exit_time = ts
                    exit_reason = "STOP"
                    outcome = "LOSS"
                    bars_held = idx
                    break

        # If no exit triggered, use close of last bar
        if exit_price is None:
            exit_price = subsequent_bars.iloc[-1]['close']
            exit_time = subsequent_bars.index[-1]
            bars_held = len(subsequent_bars) - 1

            # Determine outcome at EOD
            if direction == 'LONG':
                pnl = exit_price - entry_price
            else:
                pnl = entry_price - exit_price

            if pnl >= self.target_points * 0.5:  # At least half target
                outcome = "WIN"
            elif pnl <= -self.stop_points * 0.5:  # At least half stop
                outcome = "LOSS"
            else:
                outcome = "SCRATCH"

        # Calculate P&L
        if direction == 'LONG':
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price

        return {
            'entry_time': entry_time,
            'entry_price': entry_price,
            'exit_time': exit_time,
            'exit_price': exit_price,
            'direction': direction,
            'type': signal['type'],
            'zone': signal['zone'],
            'mfe': round(mfe, 2),
            'mae': round(mae, 2),
            'pnl': round(pnl, 2),
            'pnl_ticks': round(pnl * 4, 0),  # NQ = $20/point = $5/tick
            'outcome': outcome,
            'exit_reason': exit_reason,
            'bars_held': bars_held,
            'efficiency': round((pnl / mfe * 100) if mfe > 0 else 0, 1)  # How much of MFE was captured
        }

    def generate_report(self):
        """Generate comprehensive backtest report with trade analysis"""
        print("\n" + "="*60)
        print("📊 NQ BACKTEST REPORT")
        print("="*60)

        if not self.signals:
            print("❌ No signals generated during backtest period!")
            return

        df_signals = pd.DataFrame(self.signals)
        df_trades = pd.DataFrame(self.trades)

        # Overall stats
        print(f"\n📈 OVERALL STATISTICS")
        print(f"   Period: {self.start_date} to {self.end_date}")
        print(f"   Trading Days: {len(self.daily_stats)}")
        print(f"   Total Signals: {len(df_signals)}")
        print(f"   Avg Signals/Day: {len(df_signals) / max(len(self.daily_stats), 1):.1f}")

        # Signal breakdown
        print(f"\n🎯 SIGNAL BREAKDOWN")
        print(f"   Responsive: {len(df_signals[df_signals['type']=='RESPONSIVE'])}")
        print(f"   Recapture: {len(df_signals[df_signals['type']=='RECAPTURE'])}")
        print(f"   Flip: {len(df_signals[df_signals['type']=='FLIP'])}")
        print(f"\n   Long Signals: {len(df_signals[df_signals['direction']=='LONG'])}")
        print(f"   Short Signals: {len(df_signals[df_signals['direction']=='SHORT'])}")

        # Zone distribution
        print(f"\n📍 ZONE DISTRIBUTION")
        for zone in sorted(df_signals['zone'].unique()):
            count = len(df_signals[df_signals['zone']==zone])
            pct = (count / len(df_signals)) * 100
            print(f"   Zone {zone}: {count} ({pct:.1f}%)")

        # ✅ NEW: TRADE PERFORMANCE
        if not df_trades.empty:
            wins = len(df_trades[df_trades['outcome'] == 'WIN'])
            losses = len(df_trades[df_trades['outcome'] == 'LOSS'])
            scratches = len(df_trades[df_trades['outcome'] == 'SCRATCH'])
            total_trades = len(df_trades)

            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

            avg_win = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if wins > 0 else 0
            avg_loss = df_trades[df_trades['pnl'] < 0]['pnl'].mean() if losses > 0 else 0

            total_pnl = df_trades['pnl'].sum()
            avg_pnl = df_trades['pnl'].mean()

            print(f"\n💰 TRADE PERFORMANCE")
            print(f"   Total Trades: {total_trades}")
            print(f"   Winners: {wins} ({win_rate:.1f}%)")
            print(f"   Losers: {losses} ({(losses/total_trades*100):.1f}%)")
            print(f"   Scratches: {scratches} ({(scratches/total_trades*100):.1f}%)")
            print(f"\n   Avg Win: {avg_win:.2f} pts (${avg_win * 20:.0f})")
            print(f"   Avg Loss: {avg_loss:.2f} pts (${avg_loss * 20:.0f})")
            print(f"   Win/Loss Ratio: {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "   Win/Loss Ratio: N/A")
            print(f"\n   Total P&L: {total_pnl:.2f} pts (${total_pnl * 20:.0f})")
            print(f"   Avg P&L/Trade: {avg_pnl:.2f} pts (${avg_pnl * 20:.0f})")
            print(f"   Expectancy: ${avg_pnl * 20:.2f} per trade")

            # MFE/MAE Analysis
            avg_mfe = df_trades['mfe'].mean()
            avg_mae = df_trades['mae'].mean()
            avg_efficiency = df_trades['efficiency'].mean()

            print(f"\n📊 MFE/MAE ANALYSIS")
            print(f"   Avg MFE (Max Favorable): {avg_mfe:.2f} pts")
            print(f"   Avg MAE (Max Adverse): {avg_mae:.2f} pts")
            print(f"   Avg Capture Efficiency: {avg_efficiency:.1f}%")
            print(f"   MFE/MAE Ratio: {avg_mfe/avg_mae:.2f}" if avg_mae > 0 else "   MFE/MAE Ratio: N/A")

            # Zone performance
            print(f"\n🎯 PERFORMANCE BY ZONE")
            for zone in sorted(df_trades['zone'].unique()):
                zone_trades = df_trades[df_trades['zone'] == zone]
                zone_wins = len(zone_trades[zone_trades['outcome'] == 'WIN'])
                zone_total = len(zone_trades)
                zone_wr = (zone_wins / zone_total * 100) if zone_total > 0 else 0
                zone_pnl = zone_trades['pnl'].sum()

                print(f"   Zone {zone}: {zone_total} trades, {zone_wr:.0f}% WR, {zone_pnl:+.1f} pts")

        # Quality assessment
        avg_per_day = len(df_signals) / max(len(self.daily_stats), 1)
        print(f"\n🎯 QUALITY ASSESSMENT")
        if avg_per_day < 2:
            print(f"   ⚠️ LOW: Only {avg_per_day:.1f} signals/day. Consider loosening filters.")
        elif avg_per_day > 15:
            print(f"   ⚠️ HIGH: {avg_per_day:.1f} signals/day. May still include noise.")
        else:
            print(f"   ✅ GOOD: {avg_per_day:.1f} signals/day is within healthy range (3-10).")

        # Save detailed CSVs
        csv_signals = f"{BACKTEST_OUTPUT}/signals_{self.start_date}_to_{self.end_date}.csv"
        df_signals.to_csv(csv_signals, index=False)
        print(f"\n💾 Signals saved to: {csv_signals}")

        csv_trades = f"{BACKTEST_OUTPUT}/trades_{self.start_date}_to_{self.end_date}.csv"
        df_trades.to_csv(csv_trades, index=False)
        print(f"💾 Trades saved to: {csv_trades}")

        # Save summary JSON
        summary = {
            'period': {
                'start': str(self.start_date),
                'end': str(self.end_date)
            },
            'stats': {
                'trading_days': len(self.daily_stats),
                'total_signals': len(df_signals),
                'avg_signals_per_day': len(df_signals) / max(len(self.daily_stats), 1),
            },
            'performance': {
                'total_trades': len(df_trades),
                'winners': int(wins) if not df_trades.empty else 0,
                'losers': int(losses) if not df_trades.empty else 0,
                'win_rate': float(win_rate) if not df_trades.empty else 0,
                'total_pnl_points': float(total_pnl) if not df_trades.empty else 0,
                'total_pnl_dollars': float(total_pnl * 20) if not df_trades.empty else 0,
                'avg_pnl_per_trade': float(avg_pnl) if not df_trades.empty else 0,
                'expectancy_dollars': float(avg_pnl * 20) if not df_trades.empty else 0
            },
            'mfe_mae': {
                'avg_mfe': float(avg_mfe) if not df_trades.empty else 0,
                'avg_mae': float(avg_mae) if not df_trades.empty else 0,
                'avg_efficiency': float(avg_efficiency) if not df_trades.empty else 0
            }
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

        df_signals = pd.DataFrame(self.signals)
        df_trades = pd.DataFrame(self.trades)

        # Set style
        sns.set_style("whitegrid")
        fig = plt.figure(figsize=(20, 12))
        gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)

        fig.suptitle(f'NQ Backtest Results: {self.start_date} to {self.end_date}',
                     fontsize=16, fontweight='bold')

        # 1. Signals per day
        ax1 = fig.add_subplot(gs[0, 0])
        daily_counts = df_signals.groupby(pd.to_datetime(df_signals['time']).dt.date).size()
        ax1.bar(range(len(daily_counts)), daily_counts.values, color='steelblue')
        ax1.set_title('Signals Per Day', fontweight='bold')
        ax1.set_xlabel('Trading Day')
        ax1.set_ylabel('Signal Count')
        ax1.grid(axis='y', alpha=0.3)

        # 2. Win Rate
        ax2 = fig.add_subplot(gs[0, 1])
        if not df_trades.empty:
            outcome_counts = df_trades['outcome'].value_counts()
            colors = ['#2ecc71', '#e74c3c', '#95a5a6']
            ax2.pie(outcome_counts.values, labels=outcome_counts.index, autopct='%1.1f%%',
                   colors=colors, startangle=90)
            ax2.set_title('Trade Outcomes', fontweight='bold')

        # 3. Zone performance
        ax3 = fig.add_subplot(gs[0, 2])
        if not df_trades.empty:
            zone_performance = df_trades.groupby('zone')['pnl'].sum()
            colors_zone = ['#3498db', '#e67e22', '#9b59b6', '#1abc9c']
            ax3.bar(zone_performance.index, zone_performance.values, color=colors_zone)
            ax3.set_title('P&L by Zone', fontweight='bold')
            ax3.set_xlabel('Zone')
            ax3.set_ylabel('Total P&L (points)')
            ax3.grid(axis='y', alpha=0.3)
            ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

        # 4. MFE Distribution
        ax4 = fig.add_subplot(gs[1, 0])
        if not df_trades.empty:
            ax4.hist(df_trades['mfe'], bins=20, color='green', alpha=0.7, edgecolor='black')
            ax4.set_title('MFE Distribution', fontweight='bold')
            ax4.set_xlabel('Max Favorable Excursion (points)')
            ax4.set_ylabel('Count')
            ax4.grid(axis='y', alpha=0.3)

        # 5. MAE Distribution
        ax5 = fig.add_subplot(gs[1, 1])
        if not df_trades.empty:
            ax5.hist(df_trades['mae'], bins=20, color='red', alpha=0.7, edgecolor='black')
            ax5.set_title('MAE Distribution', fontweight='bold')
            ax5.set_xlabel('Max Adverse Excursion (points)')
            ax5.set_ylabel('Count')
            ax5.grid(axis='y', alpha=0.3)

        # 6. MFE vs MAE Scatter
        ax6 = fig.add_subplot(gs[1, 2])
        if not df_trades.empty:
            colors_outcome = df_trades['outcome'].map({'WIN': 'green', 'LOSS': 'red', 'SCRATCH': 'gray'})
            ax6.scatter(df_trades['mae'], df_trades['mfe'], c=colors_outcome, alpha=0.6)
            ax6.set_title('MFE vs MAE', fontweight='bold')
            ax6.set_xlabel('MAE (points)')
            ax6.set_ylabel('MFE (points)')
            ax6.grid(alpha=0.3)

        # 7. Cumulative P&L
        ax7 = fig.add_subplot(gs[2, :])
        if not df_trades.empty:
            df_trades_sorted = df_trades.sort_values('entry_time')
            cumulative_pnl = df_trades_sorted['pnl'].cumsum()
            ax7.plot(range(len(cumulative_pnl)), cumulative_pnl.values, linewidth=2, color='navy')
            ax7.fill_between(range(len(cumulative_pnl)), cumulative_pnl.values, alpha=0.3, color='navy')
            ax7.set_title('Cumulative P&L', fontweight='bold')
            ax7.set_xlabel('Trade Number')
            ax7.set_ylabel('Cumulative P&L (points)')
            ax7.grid(alpha=0.3)
            ax7.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

        plt.tight_layout()

        # Save plot
        plot_file = f"{BACKTEST_OUTPUT}/charts_{self.start_date}_to_{self.end_date}.png"
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        print(f"✅ Charts saved to: {plot_file}")

    def run_full_backtest(self):
        """Execute complete backtest workflow"""
        print("\n" + "="*60)
        print("🚀 STARTING FULL NQ BACKTEST WITH TRADE ANALYSIS")
        print("="*60 + "\n")

        self.generate_historical_plans()
        self.run_backtest()
        self.generate_report()

        try:
            self.plot_results()
        except Exception as e:
            print(f"⚠️ Could not generate charts: {e}")

        print("\n" + "="*60)
        print("✅ NQ BACKTEST COMPLETE!")
        print("="*60)


# ==============================================================================
# QUICK BACKTEST RUNNER
# ==============================================================================
def quick_backtest(days_back=7, enable_poc=False, cooldown_minutes=60,
                   target_points=10.0, stop_points=6.0):
    """Quick NQ backtest with trade analysis"""
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back + 5)

    backtester = TradingBotBacktester(
        start_date, end_date, enable_poc, cooldown_minutes,
        target_points, stop_points
    )
    backtester.run_full_backtest()

    return backtester


# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    print("="*60)
    print("   NQ TRADING BOT BACKTESTER (COMPLETE)")
    print("="*60)
    print("\n1. Quick Backtest (Last 7 trading days)")
    print("2. Quick Backtest (Last 30 trading days)")
    print("3. Custom Date Range")
    print("4. Extended Backtest (Last 90 days)")

    choice = input("\nSelect Option [1-4]: ").strip()

    enable_poc = input("Enable POC Filter? [y/N]: ").strip().lower() == 'y'

    cooldown_input = input("Signal Cooldown (minutes) [60]: ").strip()
    cooldown = int(cooldown_input) if cooldown_input else 60

    target_input = input("Target (points) [10.0]: ").strip()
    target = float(target_input) if target_input else 10.0

    stop_input = input("Stop (points) [6.0]: ").strip()
    stop = float(stop_input) if stop_input else 6.0

    if choice == "1":
        print(f"\n🔬 Running 7-Day NQ Backtest...")
        quick_backtest(7, enable_poc, cooldown, target, stop)

    elif choice == "2":
        print(f"\n🔬 Running 30-Day NQ Backtest...")
        quick_backtest(30, enable_poc, cooldown, target, stop)

    elif choice == "3":
        start_str = input("Start Date (YYYY-MM-DD): ").strip()
        end_str = input("End Date (YYYY-MM-DD): ").strip()

        try:
            start = datetime.strptime(start_str, "%Y-%m-%d").date()
            end = datetime.strptime(end_str, "%Y-%m-%d").date()

            backtester = TradingBotBacktester(start, end, enable_poc, cooldown, target, stop)
            backtester.run_full_backtest()
        except ValueError:
            print("❌ Invalid date format!")

    elif choice == "4":
        print(f"\n🔬 Running 90-Day NQ Backtest...")
        quick_backtest(90, enable_poc, cooldown, target, stop)

    else:
        print("❌ Invalid choice")
