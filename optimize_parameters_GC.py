"""
GC Trading Bot - Parameter Optimization Tool
Tests multiple combinations of target/stop/cooldown to find optimal settings
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import json
import os
from itertools import product
import time

# Import GC backtester
from backtest_bot_GC_COMPLETE import TradingBotBacktester

NY_TZ = pytz.timezone('America/New_York')
BACKTEST_OUTPUT = "backtest_results_GC"
os.makedirs(BACKTEST_OUTPUT, exist_ok=True)

# ==============================================================================
# PARAMETER OPTIMIZER (GC)
# ==============================================================================
class ParameterOptimizer:
    def __init__(self, start_date, end_date, enable_poc_filter=False):
        """
        Initialize GC parameter optimization

        Args:
            start_date: datetime.date - First day to test
            end_date: datetime.date - Last day to test
            enable_poc_filter: bool - Enable POC distance filtering
        """
        self.start_date = start_date
        self.end_date = end_date
        self.enable_poc_filter = enable_poc_filter
        self.results = []
        self.shared_plans = None  # Will be set on first valid test

        print(f"🔬 GC PARAMETER OPTIMIZER INITIALIZED")
        print(f"   Period: {start_date} to {end_date}")
        print(f"   POC Filter: {enable_poc_filter}\n")

    def run_optimization(self,
                        cooldown_options=[15, 30, 45, 60, 90, 120],
                        target_options=[2.0, 3.0, 4.0, 5.0, 6.0, 8.0],
                        stop_options=[1.0, 1.5, 2.0, 2.5, 3.0, 4.0]):
        """
        Run grid search optimization for GC

        Args:
            cooldown_options: List of cooldown periods to test (minutes)
            target_options: List of profit targets to test (points)
            stop_options: List of stop losses to test (points)
        """
        # Generate all combinations
        combinations = list(product(cooldown_options, target_options, stop_options))

        total_tests = len(combinations)
        print(f"🔄 STARTING GC GRID SEARCH OPTIMIZATION")
        print(f"   Cooldown options: {cooldown_options}")
        print(f"   Target options: {target_options}")
        print(f"   Stop options: {stop_options}")
        print(f"   Total combinations: {total_tests}")
        print("="*80 + "\n")

        start_time = time.time()

        for idx, (cooldown, target, stop) in enumerate(combinations, 1):
            print(f"[{idx}/{total_tests}] Testing: Cooldown={cooldown}min, Target={target}pts, Stop={stop}pts")

            # Only test valid combinations (target > stop makes sense)
            if target / stop < 1.2:  # Risk/reward should be at least 1.2:1
                print(f"   ⚠️ SKIPPED: Poor risk/reward ratio ({target/stop:.2f}:1)")
                continue

            try:
                # Run backtest with these parameters
                backtester = TradingBotBacktester(
                    self.start_date,
                    self.end_date,
                    enable_poc_filter=self.enable_poc_filter,
                    signal_cooldown_minutes=cooldown,
                    target_points=target,
                    stop_points=stop
                )

                # Generate plans only once (reuse for all tests)
                if self.shared_plans is None:
                    backtester.generate_historical_plans()
                    self.shared_plans = backtester.daily_plans
                else:
                    backtester.daily_plans = self.shared_plans

                # Run backtest
                backtester.run_backtest()

                # Extract key metrics
                if backtester.trades:
                    df_trades = pd.DataFrame(backtester.trades)

                    wins = len(df_trades[df_trades['outcome'] == 'WIN'])
                    losses = len(df_trades[df_trades['outcome'] == 'LOSS'])
                    total_trades = len(df_trades)

                    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
                    total_pnl = df_trades['pnl'].sum()
                    avg_pnl = df_trades['pnl'].mean()
                    expectancy = avg_pnl * 20  # GC: $20/point

                    avg_mfe = df_trades['mfe'].mean()
                    avg_mae = df_trades['mae'].mean()
                    mfe_mae_ratio = avg_mfe / avg_mae if avg_mae > 0 else 0

                    # Calculate Sharpe-like score (consistency)
                    std_pnl = df_trades['pnl'].std()
                    sharpe = (avg_pnl / std_pnl) if std_pnl > 0 else 0

                    # Calculate max drawdown
                    cumulative = df_trades.sort_values('entry_time')['pnl'].cumsum()
                    running_max = cumulative.cummax()
                    drawdown = running_max - cumulative
                    max_dd = drawdown.max()

                    result = {
                        'cooldown': cooldown,
                        'target': target,
                        'stop': stop,
                        'risk_reward': round(target / stop, 2),
                        'total_signals': len(backtester.signals),
                        'avg_signals_per_day': round(len(backtester.signals) / len(backtester.daily_stats), 1),
                        'total_trades': total_trades,
                        'winners': wins,
                        'losers': losses,
                        'win_rate': round(win_rate, 1),
                        'total_pnl_pts': round(total_pnl, 2),
                        'total_pnl_dollars': round(total_pnl * 20, 0),
                        'avg_pnl_per_trade': round(avg_pnl, 2),
                        'expectancy': round(expectancy, 2),
                        'avg_mfe': round(avg_mfe, 2),
                        'avg_mae': round(avg_mae, 2),
                        'mfe_mae_ratio': round(mfe_mae_ratio, 2),
                        'sharpe_score': round(sharpe, 2),
                        'max_drawdown': round(max_dd, 2),
                        'profit_factor': round(
                            df_trades[df_trades['pnl'] > 0]['pnl'].sum() /
                            abs(df_trades[df_trades['pnl'] < 0]['pnl'].sum())
                            if len(df_trades[df_trades['pnl'] < 0]) > 0 else 0,
                            2
                        )
                    }

                    self.results.append(result)

                    print(f"   ✅ Trades: {total_trades}, WR: {win_rate:.1f}%, P&L: ${total_pnl*20:.0f}, Exp: ${expectancy:.0f}")

                    # === ZONE & CATEGORY ANALYSIS ===
                    print(f"   📍 ZONES:")
                    for zone in sorted(df_trades['zone'].unique()):
                        zone_trades = df_trades[df_trades['zone'] == zone]
                        zone_wr = len(zone_trades[zone_trades['outcome'] == 'WIN']) / len(zone_trades) * 100
                        zone_exp = zone_trades['pnl'].mean() * 100
                        zone_pnl = zone_trades['pnl'].sum() * 100
                        print(f"      Z{zone}: {len(zone_trades)}t WR={zone_wr:.0f}% Exp=${zone_exp:.0f} P&L=${zone_pnl:.0f}")

                    print(f"   📊 TYPES:")
                    for cat in sorted(df_trades['type'].unique()):
                        cat_trades = df_trades[df_trades['type'] == cat]
                        cat_wr = len(cat_trades[cat_trades['outcome'] == 'WIN']) / len(cat_trades) * 100
                        cat_exp = cat_trades['pnl'].mean() * 100
                        print(f"      {cat}: {len(cat_trades)}t WR={cat_wr:.0f}% Exp=${cat_exp:.0f}")

                    scratches = df_trades[df_trades['outcome'] == 'SCRATCH']
                    if len(scratches) > 0:
                        scratch_avg = scratches['pnl'].mean() * 100
                        near_target = scratches[scratches['mfe'] >= target * 0.8]
                        print(f"   💫 SCRATCH: {len(scratches)}t Avg=${scratch_avg:.0f} | {len(near_target)} near target")

                else:
                    print(f"   ⚠️ No trades generated")

            except Exception as e:
                print(f"   ❌ Error: {e}")

        elapsed = time.time() - start_time
        print(f"\n{'='*80}")
        print(f"✅ GC OPTIMIZATION COMPLETE")
        print(f"   Tested: {len(self.results)} configurations")
        print(f"   Time: {elapsed/60:.1f} minutes")
        print(f"{'='*80}\n")

    def analyze_results(self):
        """Analyze and rank optimization results"""
        if not self.results:
            print("❌ No results to analyze!")
            return

        df = pd.DataFrame(self.results)

        print(f"📊 GC OPTIMIZATION RESULTS")
        print("="*80)

        # Sort by different criteria
        print(f"\n🏆 TOP 10 BY EXPECTANCY (Most Important)")
        print("-"*80)
        top_expectancy = df.nlargest(10, 'expectancy')
        print(top_expectancy[['cooldown', 'target', 'stop', 'win_rate', 'expectancy',
                              'total_pnl_dollars', 'mfe_mae_ratio', 'avg_signals_per_day']].to_string(index=False))

        print(f"\n🎯 TOP 10 BY WIN RATE")
        print("-"*80)
        top_winrate = df.nlargest(10, 'win_rate')
        print(top_winrate[['cooldown', 'target', 'stop', 'win_rate', 'expectancy',
                          'total_pnl_dollars', 'total_trades']].to_string(index=False))

        print(f"\n💰 TOP 10 BY TOTAL P&L")
        print("-"*80)
        top_pnl = df.nlargest(10, 'total_pnl_dollars')
        print(top_pnl[['cooldown', 'target', 'stop', 'win_rate', 'expectancy',
                      'total_pnl_dollars', 'total_trades']].to_string(index=False))

        print(f"\n📈 TOP 10 BY MFE/MAE RATIO (Edge Quality)")
        print("-"*80)
        top_edge = df.nlargest(10, 'mfe_mae_ratio')
        print(top_edge[['cooldown', 'target', 'stop', 'win_rate', 'mfe_mae_ratio',
                       'expectancy', 'total_pnl_dollars']].to_string(index=False))

        print(f"\n⚖️ TOP 10 BY SHARPE SCORE (Consistency)")
        print("-"*80)
        top_sharpe = df.nlargest(10, 'sharpe_score')
        print(top_sharpe[['cooldown', 'target', 'stop', 'win_rate', 'sharpe_score',
                         'expectancy', 'max_drawdown']].to_string(index=False))

        # Find optimal configuration using composite score
        print(f"\n🔍 COMPOSITE SCORE ANALYSIS")
        print("-"*80)

        # Normalize metrics to 0-1 scale
        df['norm_expectancy'] = (df['expectancy'] - df['expectancy'].min()) / (df['expectancy'].max() - df['expectancy'].min()) if df['expectancy'].max() > df['expectancy'].min() else 0
        df['norm_winrate'] = df['win_rate'] / 100
        df['norm_mfe_mae'] = (df['mfe_mae_ratio'] - df['mfe_mae_ratio'].min()) / (df['mfe_mae_ratio'].max() - df['mfe_mae_ratio'].min()) if df['mfe_mae_ratio'].max() > df['mfe_mae_ratio'].min() else 0
        df['norm_sharpe'] = (df['sharpe_score'] - df['sharpe_score'].min()) / (df['sharpe_score'].max() - df['sharpe_score'].min()) if df['sharpe_score'].max() > df['sharpe_score'].min() else 0

        # Composite score (weighted average)
        df['composite_score'] = (
            df['norm_expectancy'] * 0.35 +      # 35% weight on expectancy
            df['norm_winrate'] * 0.25 +         # 25% weight on win rate
            df['norm_mfe_mae'] * 0.20 +         # 20% weight on edge quality
            df['norm_sharpe'] * 0.20            # 20% weight on consistency
        ) * 100

        top_composite = df.nlargest(10, 'composite_score')
        print(top_composite[['cooldown', 'target', 'stop', 'composite_score', 'win_rate',
                            'expectancy', 'mfe_mae_ratio', 'total_pnl_dollars']].to_string(index=False))

        # Best overall
        best = df.loc[df['composite_score'].idxmax()]

        print(f"\n{'='*80}")
        print(f"🏆 RECOMMENDED GC CONFIGURATION")
        print(f"{'='*80}")
        print(f"   Cooldown: {best['cooldown']} minutes")
        print(f"   Target: {best['target']} points")
        print(f"   Stop: {best['stop']} points")
        print(f"   Risk/Reward: {best['risk_reward']}:1")
        print(f"\n   EXPECTED PERFORMANCE:")
        print(f"   Signals/Day: {best['avg_signals_per_day']}")
        print(f"   Win Rate: {best['win_rate']:.1f}%")
        print(f"   Expectancy: ${best['expectancy']:.2f}/trade")
        print(f"   Total P&L: ${best['total_pnl_dollars']:.0f} over {len(self.shared_plans)} days")
        print(f"   MFE/MAE Ratio: {best['mfe_mae_ratio']}")
        print(f"   Sharpe Score: {best['sharpe_score']}")
        print(f"   Max Drawdown: {best['max_drawdown']} pts")
        print(f"{'='*80}\n")

        # Save results
        csv_file = f"{BACKTEST_OUTPUT}/optimization_results_{self.start_date}_to_{self.end_date}.csv"
        df.to_csv(csv_file, index=False)
        print(f"💾 Full results saved to: {csv_file}\n")

        # Save best config as JSON
        best_config = {
            'period': {
                'start': str(self.start_date),
                'end': str(self.end_date)
            },
            'best_configuration': {
                'cooldown_minutes': int(best['cooldown']),
                'target_points': float(best['target']),
                'stop_points': float(best['stop']),
                'risk_reward_ratio': float(best['risk_reward'])
            },
            'expected_performance': {
                'signals_per_day': float(best['avg_signals_per_day']),
                'win_rate': float(best['win_rate']),
                'expectancy_dollars': float(best['expectancy']),
                'total_pnl_dollars': float(best['total_pnl_dollars']),
                'mfe_mae_ratio': float(best['mfe_mae_ratio']),
                'sharpe_score': float(best['sharpe_score']),
                'composite_score': float(best['composite_score'])
            }
        }

        json_file = f"{BACKTEST_OUTPUT}/best_config_{self.start_date}_to_{self.end_date}.json"
        with open(json_file, 'w') as f:
            json.dump(best_config, f, indent=4)
        print(f"💾 Best configuration saved to: {json_file}\n")

        return best


# ==============================================================================
# PRESET OPTIMIZATION PROFILES (GC)
# ==============================================================================

def quick_optimize(days_back=30, enable_poc=False):
    """
    Quick GC optimization with common parameter ranges

    Tests:
    - Cooldowns: 30, 45, 60, 90 minutes
    - Targets: 10, 12, 15, 20 points
    - Stops: 6, 8, 10 points
    Total: 48 combinations
    """
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back + 5)

    optimizer = ParameterOptimizer(start_date, end_date, enable_poc)

    optimizer.run_optimization(
        cooldown_options=[30, 45, 60, 90],
        target_options=[10.0, 12.0, 15.0, 20.0],
        stop_options=[6.0, 8.0, 10.0]
    )

    optimizer.analyze_results()
    return optimizer


def comprehensive_optimize(days_back=30, enable_poc=False):
    """
    Comprehensive GC optimization (takes longer)

    Tests:
    - Cooldowns: 15, 30, 45, 60, 90, 120 minutes
    - Targets: 8, 10, 12, 15, 20, 25 points
    - Stops: 4, 6, 8, 10, 12 points
    Total: ~150 combinations
    """
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back + 5)

    optimizer = ParameterOptimizer(start_date, end_date, enable_poc)

    optimizer.run_optimization(
        cooldown_options=[15, 30, 45, 60, 90, 120],
        target_options=[2.0, 3.0, 4.0, 5.0, 6.0, 8.0],
        stop_options=[4.0, 6.0, 8.0, 10.0, 12.0]
    )

    optimizer.analyze_results()
    return optimizer


def custom_optimize(days_back=30, enable_poc=False,
                   cooldowns=None, targets=None, stops=None):
    """
    Custom GC optimization with user-defined ranges

    Args:
        days_back: Number of days to test
        enable_poc: Enable POC filter
        cooldowns: List of cooldown periods (minutes)
        targets: List of profit targets (points)
        stops: List of stop losses (points)
    """
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back + 5)

    optimizer = ParameterOptimizer(start_date, end_date, enable_poc)

    # Use defaults if not provided (GC-appropriate)
    if cooldowns is None:
        cooldowns = [30, 45, 60, 90]
    if targets is None:
        targets = [10.0, 12.0, 15.0, 20.0]
    if stops is None:
        stops = [6.0, 8.0, 10.0]

    optimizer.run_optimization(
        cooldown_options=cooldowns,
        target_options=targets,
        stop_options=stops
    )

    optimizer.analyze_results()
    return optimizer


# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    print("="*80)
    print("   GC TRADING BOT - PARAMETER OPTIMIZATION")
    print("="*80)
    print("\n1. Quick Optimize (48 combinations, ~10 mins)")
    print("   Cooldowns: 30, 45, 60, 90 min")
    print("   Targets: 10, 12, 15, 20 pts")
    print("   Stops: 6, 8, 10 pts")
    print("\n2. Comprehensive Optimize (~150 combinations, ~30 mins)")
    print("   Cooldowns: 15, 30, 45, 60, 90, 120 min")
    print("   Targets: 8, 10, 12, 15, 20, 25 pts")
    print("   Stops: 4, 6, 8, 10, 12 pts")
    print("\n3. Custom Optimize (specify your own ranges)")

    choice = input("\nSelect Option [1-3]: ").strip()

    enable_poc = input("Enable POC Filter? [y/N]: ").strip().lower() == 'y'

    if choice == "1":
        print("\n🔬 Running Quick GC Optimization (30 days)...")
        quick_optimize(days_back=30, enable_poc=enable_poc)

    elif choice == "2":
        print("\n🔬 Running Comprehensive GC Optimization (30 days)...")
        print("⚠️ This will take 20-40 minutes. Be patient!\n")
        comprehensive_optimize(days_back=30, enable_poc=enable_poc)

    elif choice == "3":
        # Get custom ranges
        print("\nEnter parameter ranges (comma-separated):")
        cooldown_input = input("Cooldowns (minutes) [30,45,60,90]: ").strip()
        target_input = input("Targets (points) [10,12,15,20]: ").strip()
        stop_input = input("Stops (points) [6,8,10]: ").strip()

        cooldowns = [int(x) for x in cooldown_input.split(',')] if cooldown_input else None
        targets = [float(x) for x in target_input.split(',')] if target_input else None
        stops = [float(x) for x in stop_input.split(',')] if stop_input else None

        total_combos = (len(cooldowns) if cooldowns else 4) * \
                      (len(targets) if targets else 4) * \
                      (len(stops) if stops else 3)

        print(f"\n🔬 Running Custom GC Optimization ({total_combos} combinations)...")
        custom_optimize(days_back=30, enable_poc=enable_poc,
                       cooldowns=cooldowns, targets=targets, stops=stops)

    else:
        print("❌ Invalid choice")
