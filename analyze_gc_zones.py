#!/usr/bin/env python3
"""
GC Zone & Category Performance Analysis
Analyzes win rate, expectancy, and profitability by zone and signal type
"""

import pandas as pd
from datetime import datetime
import json
import os

def load_backtest_results(results_dir="backtest_results_GC"):
    """
    Load backtest results from JSON files
    Returns list of all trades from all parameter combinations
    """
    all_trades = []

    if not os.path.exists(results_dir):
        print(f"❌ Directory {results_dir} not found!")
        return None

    json_files = [f for f in os.listdir(results_dir) if f.endswith('.json')]

    if not json_files:
        print(f"❌ No JSON files found in {results_dir}!")
        return None

    print(f"📂 Found {len(json_files)} result files\n")

    for filename in json_files:
        filepath = os.path.join(results_dir, filename)
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            # Extract parameters from filename or data
            params = filename.replace('.json', '').replace('backtest_', '').split('_')

            if 'trades' in data:
                for trade in data['trades']:
                    trade['source_file'] = filename
                    all_trades.append(trade)
        except Exception as e:
            print(f"⚠️  Error loading {filename}: {e}")

    return all_trades


def analyze_by_zone(trades_df, target_pts, stop_pts, cooldown_min):
    """
    Analyze performance by zone for a specific parameter set
    """
    print("="*80)
    print(f"ZONE ANALYSIS: {cooldown_min}min cooldown / {target_pts}pt target / {stop_pts}pt stop")
    print("="*80)

    total_trades = len(trades_df)
    print(f"\n📊 Total Trades: {total_trades}\n")

    # Overall stats
    overall_wr = len(trades_df[trades_df['outcome'] == 'WIN']) / total_trades * 100
    overall_exp = trades_df['pnl'].mean() * 100  # GC: $100/point

    print(f"🎯 OVERALL PERFORMANCE")
    print(f"   Win Rate: {overall_wr:.1f}%")
    print(f"   Expectancy: ${overall_exp:.2f}/trade\n")

    # Zone breakdown
    print(f"{'='*80}")
    print(f"ZONE-BY-ZONE BREAKDOWN")
    print(f"{'='*80}\n")

    zones = sorted(trades_df['zone'].unique())

    zone_summary = []

    for zone in zones:
        zone_trades = trades_df[trades_df['zone'] == zone]
        zone_count = len(zone_trades)
        zone_pct = zone_count / total_trades * 100

        winners = zone_trades[zone_trades['outcome'] == 'WIN']
        losers = zone_trades[zone_trades['outcome'] == 'LOSS']
        scratches = zone_trades[zone_trades['outcome'] == 'SCRATCH']

        zone_wr = len(winners) / zone_count * 100 if zone_count > 0 else 0
        zone_pnl = zone_trades['pnl'].sum()
        zone_exp = zone_trades['pnl'].mean() * 100  # $100/point

        avg_mfe = zone_trades['mfe'].mean()
        avg_mae = zone_trades['mae'].mean()

        print(f"📍 ZONE {zone}")
        print(f"   Trades: {zone_count} ({zone_pct:.1f}% of total)")
        print(f"   Outcome: {len(winners)} wins, {len(losers)} losses, {len(scratches)} scratches")
        print(f"   Win Rate: {zone_wr:.1f}%")
        print(f"   Total P&L: ${zone_pnl * 100:.2f}")
        print(f"   Expectancy: ${zone_exp:.2f}/trade")
        print(f"   Avg MFE: {avg_mfe:.2f}pts | Avg MAE: {avg_mae:.2f}pts")

        # Direction split
        longs = zone_trades[zone_trades['direction'] == 'LONG']
        shorts = zone_trades[zone_trades['direction'] == 'SHORT']

        long_wr = len(longs[longs['outcome'] == 'WIN']) / len(longs) * 100 if len(longs) > 0 else 0
        short_wr = len(shorts[shorts['outcome'] == 'WIN']) / len(shorts) * 100 if len(shorts) > 0 else 0

        print(f"   Direction: {len(longs)} longs (WR: {long_wr:.1f}%), {len(shorts)} shorts (WR: {short_wr:.1f}%)")
        print()

        zone_summary.append({
            'zone': zone,
            'trades': zone_count,
            'pct_of_total': zone_pct,
            'win_rate': zone_wr,
            'expectancy': zone_exp,
            'total_pnl': zone_pnl * 100,
            'avg_mfe': avg_mfe,
            'avg_mae': avg_mae
        })

    # Summary table
    print(f"{'='*80}")
    print(f"ZONE COMPARISON")
    print(f"{'='*80}\n")
    print(f"{'Zone':>6} {'Trades':>8} {'% Total':>10} {'Win Rate':>10} {'Expectancy':>12} {'Total P&L':>12}")
    print("-"*80)
    for z in zone_summary:
        print(f"{z['zone']:>6} {z['trades']:>8} {z['pct_of_total']:>9.1f}% {z['win_rate']:>9.1f}% ${z['expectancy']:>10.2f} ${z['total_pnl']:>11.2f}")


def analyze_by_category(trades_df, target_pts, stop_pts, cooldown_min):
    """
    Analyze performance by signal category (RESPONSIVE vs RECAPTURE)
    """
    print("\n" + "="*80)
    print(f"CATEGORY ANALYSIS")
    print(f"{'='*80}\n")

    total_trades = len(trades_df)

    categories = sorted(trades_df['type'].unique())

    for cat in categories:
        cat_trades = trades_df[trades_df['type'] == cat]
        cat_count = len(cat_trades)
        cat_pct = cat_count / total_trades * 100

        winners = cat_trades[cat_trades['outcome'] == 'WIN']
        cat_wr = len(winners) / cat_count * 100 if cat_count > 0 else 0
        cat_exp = cat_trades['pnl'].mean() * 100

        print(f"📊 {cat} TRADES")
        print(f"   Count: {cat_count} ({cat_pct:.1f}% of total)")
        print(f"   Win Rate: {cat_wr:.1f}%")
        print(f"   Expectancy: ${cat_exp:.2f}/trade")

        # Zone distribution within category
        print(f"   Zone Distribution:")
        for zone in sorted(cat_trades['zone'].unique()):
            zone_in_cat = cat_trades[cat_trades['zone'] == zone]
            zone_wr = len(zone_in_cat[zone_in_cat['outcome'] == 'WIN']) / len(zone_in_cat) * 100
            print(f"      Zone {zone}: {len(zone_in_cat)} trades (WR: {zone_wr:.1f}%)")
        print()


def cross_analysis(trades_df, target_pts, stop_pts, cooldown_min):
    """
    Cross-tabulation: Zone vs Category
    """
    print("\n" + "="*80)
    print(f"ZONE × CATEGORY CROSS-ANALYSIS")
    print(f"{'='*80}\n")

    zones = sorted(trades_df['zone'].unique())
    categories = sorted(trades_df['type'].unique())

    print(f"{'Zone/Type':<15}", end='')
    for cat in categories:
        print(f"{cat:>20}", end='')
    print()
    print("-"*80)

    for zone in zones:
        print(f"Zone {zone:<12}", end='')
        for cat in categories:
            subset = trades_df[(trades_df['zone'] == zone) & (trades_df['type'] == cat)]
            if len(subset) > 0:
                wr = len(subset[subset['outcome'] == 'WIN']) / len(subset) * 100
                exp = subset['pnl'].mean() * 100
                print(f"{len(subset):>6} ({wr:>5.1f}%/${exp:>5.0f})", end='')
            else:
                print(f"{'N/A':>20}", end='')
        print()


def analyze_scratches(trades_df, target_pts, stop_pts):
    """
    Deep dive into SCRATCH trades
    """
    print("\n" + "="*80)
    print(f"SCRATCH TRADE ANALYSIS")
    print(f"{'='*80}\n")

    scratches = trades_df[trades_df['outcome'] == 'SCRATCH']
    total = len(trades_df)

    if len(scratches) == 0:
        print("✅ No scratch trades (all trades hit target or stop)\n")
        return

    scratch_pct = len(scratches) / total * 100
    avg_pnl = scratches['pnl'].mean() * 100
    total_pnl = scratches['pnl'].sum() * 100

    print(f"📋 SCRATCH STATISTICS")
    print(f"   Count: {len(scratches)} ({scratch_pct:.1f}% of all trades)")
    print(f"   Avg P&L: ${avg_pnl:.2f}")
    print(f"   Total P&L: ${total_pnl:.2f}")
    print(f"   Contribution to total P&L: {total_pnl / (trades_df['pnl'].sum() * 100) * 100:.1f}%\n")

    # How close did they get to target?
    print(f"💡 SCRATCH TRADE POTENTIAL")
    print(f"   Target: {target_pts}pts | Stop: {stop_pts}pts\n")

    # Scratches that got close to target
    half_target = target_pts * 0.5
    close_to_target = scratches[scratches['mfe'] >= target_pts * 0.8]

    print(f"   Scratches with MFE >= 80% of target ({target_pts * 0.8:.1f}pts):")
    print(f"      Count: {len(close_to_target)} ({len(close_to_target)/len(scratches)*100:.1f}% of scratches)")
    if len(close_to_target) > 0:
        print(f"      Avg MFE: {close_to_target['mfe'].mean():.2f}pts")
        print(f"      Avg final P&L: ${close_to_target['pnl'].mean() * 100:.2f}")

    print(f"\n   If profit taken at 80% of target ({target_pts * 0.8:.1f}pts):")
    print(f"      Could convert {len(close_to_target)} scratches to wins")
    print(f"      Win rate would increase by {len(close_to_target)/total*100:.1f}%")

    # Zone distribution of scratches
    print(f"\n   Scratches by Zone:")
    for zone in sorted(scratches['zone'].unique()):
        zone_scratches = scratches[scratches['zone'] == zone]
        print(f"      Zone {zone}: {len(zone_scratches)} ({len(zone_scratches)/len(scratches)*100:.1f}%)")


def main():
    """
    Main analysis runner
    """
    print("\n" + "="*80)
    print("GC TRADING BOT - ZONE & CATEGORY PERFORMANCE ANALYZER")
    print("="*80 + "\n")

    # For now, we'll create a mock analyzer that shows the structure
    # User will need to run this after generating backtest results

    print("📋 INSTRUCTIONS:")
    print()
    print("This script analyzes backtest results by zone and category.")
    print()
    print("To use it, you need backtest result files in backtest_results_GC/")
    print()
    print("Option 1: Generate fresh results")
    print("   python3 optimize_parameters_GC.py")
    print()
    print("Option 2: Run single backtest with specific parameters")
    print("   See analyze_specific_params() example below")
    print()
    print("="*80)

    # Check if results exist
    trades = load_backtest_results()

    if trades is None or len(trades) == 0:
        print("\n⚠️  No backtest results found. Please run optimizer first.")
        print("\nExample command:")
        print("   python3 optimize_parameters_GC.py")
        return

    # Convert to DataFrame
    df = pd.DataFrame(trades)

    print(f"\n✅ Loaded {len(df)} total trades from all parameter sets\n")

    # For demonstration, analyze all trades combined
    # In practice, you'd want to filter by specific parameters

    print("NOTE: Analyzing ALL trades across ALL parameter combinations.")
    print("For accurate analysis, filter by specific cooldown/target/stop.\n")

    analyze_by_zone(df, target_pts=25, stop_pts=12, cooldown_min=60)
    analyze_by_category(df, target_pts=25, stop_pts=12, cooldown_min=60)
    cross_analysis(df, target_pts=25, stop_pts=12, cooldown_min=60)
    analyze_scratches(df, target_pts=25, stop_pts=12)


def analyze_specific_params(cooldown=60, target=25.0, stop=12.0):
    """
    Example: Analyze a specific parameter combination
    This requires the backtest module to work
    """
    print("\n" + "="*80)
    print(f"ANALYZING SPECIFIC PARAMETERS")
    print(f"Cooldown: {cooldown}min | Target: {target}pts | Stop: {stop}pts")
    print("="*80)

    try:
        from backtest_bot_GC_COMPLETE import TradingBotBacktester
        from datetime import datetime

        backtester = TradingBotBacktester(
            start_date=datetime(2024, 11, 1),
            end_date=datetime(2024, 12, 31),
            signal_cooldown_minutes=cooldown,
            target_points=target,
            stop_points=stop
        )

        backtester.generate_historical_plans()
        backtester.run_backtest()

        df = pd.DataFrame(backtester.trades)

        analyze_by_zone(df, target, stop, cooldown)
        analyze_by_category(df, target, stop, cooldown)
        cross_analysis(df, target, stop, cooldown)
        analyze_scratches(df, target, stop)

    except ImportError:
        print("\n❌ Cannot import backtest module.")
        print("Make sure backtest_bot_GC_COMPLETE.py has valid API_KEY configured.")
    except Exception as e:
        print(f"\n❌ Error running backtest: {e}")


if __name__ == "__main__":
    main()

    # Uncomment to analyze specific parameters:
    # analyze_specific_params(cooldown=60, target=25.0, stop=12.0)
