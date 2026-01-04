#!/usr/bin/env python3
"""
Analyze GC trade patterns to understand why wider stops = lower win rates
"""

import sys
from datetime import datetime
from backtest_bot_GC_COMPLETE import GCBacktester
import pandas as pd

def analyze_parameter_set(cooldown, target, stop):
    """Run backtest and analyze trade patterns"""
    print(f"\n{'='*80}")
    print(f"ANALYZING: Cooldown={cooldown}min, Target={target}pts, Stop={stop}pts")
    print(f"Risk/Reward Ratio: {target/stop:.2f}:1")
    print(f"{'='*80}")

    # Run backtest
    backtester = GCBacktester(
        start_date=datetime(2024, 11, 1),
        end_date=datetime(2024, 12, 31),
        enable_poc_filter=False,
        signal_cooldown_minutes=cooldown,
        target_points=target,
        stop_points=stop
    )

    # Generate plans once
    backtester.generate_historical_plans()

    # Run backtest
    backtester.run_backtest()

    # Analyze trades
    trades = backtester.trades

    if not trades:
        print("❌ No trades generated")
        return None

    # Convert to DataFrame
    df = pd.DataFrame(trades)

    # Basic stats
    total_trades = len(df)
    winners = df[df['outcome'] == 'WIN']
    losers = df[df['outcome'] == 'LOSS']
    scratches = df[df['outcome'] == 'SCRATCH']

    win_rate = len(winners) / total_trades * 100
    total_pnl = df['pnl'].sum()
    expectancy = df['pnl'].mean()

    print(f"\n📊 OVERALL STATISTICS:")
    print(f"   Total Trades: {total_trades}")
    print(f"   Winners: {len(winners)} ({len(winners)/total_trades*100:.1f}%)")
    print(f"   Losers: {len(losers)} ({len(losers)/total_trades*100:.1f}%)")
    print(f"   Scratches: {len(scratches)} ({len(scratches)/total_trades*100:.1f}%)")
    print(f"   Win Rate: {win_rate:.1f}%")
    print(f"   Total P&L: ${total_pnl * 100:.2f}")
    print(f"   Expectancy: ${expectancy * 100:.2f}/trade")

    # Exit reason breakdown
    print(f"\n🚪 EXIT REASONS:")
    exit_counts = df['exit_reason'].value_counts()
    for reason, count in exit_counts.items():
        pct = count / total_trades * 100
        print(f"   {reason}: {count} ({pct:.1f}%)")

    # MFE/MAE Analysis
    print(f"\n📈 MFE/MAE ANALYSIS:")
    print(f"   Average MFE (Winners): {winners['mfe'].mean():.2f}pts")
    print(f"   Average MAE (Winners): {winners['mae'].mean():.2f}pts")
    print(f"   Average MFE (Losers): {losers['mfe'].mean():.2f}pts")
    print(f"   Average MAE (Losers): {losers['mae'].mean():.2f}pts")

    # Key insight: How many losers ALMOST hit target?
    losers_with_large_mfe = losers[losers['mfe'] >= target * 0.5]
    print(f"\n💡 LOSERS THAT ALMOST WON:")
    print(f"   Losers with MFE >= 50% of target: {len(losers_with_large_mfe)} ({len(losers_with_large_mfe)/len(losers)*100:.1f}% of losers)")

    if len(losers_with_large_mfe) > 0:
        print(f"   Average MFE for these trades: {losers_with_large_mfe['mfe'].mean():.2f}pts")
        print(f"   Average MAE for these trades: {losers_with_large_mfe['mae'].mean():.2f}pts")

    # Winners that almost lost
    winners_with_large_mae = winners[winners['mae'] >= stop * 0.5]
    print(f"\n💡 WINNERS THAT ALMOST LOST:")
    print(f"   Winners with MAE >= 50% of stop: {len(winners_with_large_mae)} ({len(winners_with_large_mae)/len(winners)*100:.1f}% of winners)")

    if len(winners_with_large_mae) > 0:
        print(f"   Average MAE for these trades: {winners_with_large_mae['mae'].mean():.2f}pts")
        print(f"   Average MFE for these trades: {winners_with_large_mae['mfe'].mean():.2f}pts")

    # Bars held analysis
    print(f"\n⏱️  TIME IN TRADE:")
    print(f"   Average bars held (all): {df['bars_held'].mean():.1f} bars ({df['bars_held'].mean():.1f} minutes)")
    print(f"   Average bars held (winners): {winners['bars_held'].mean():.1f} bars")
    print(f"   Average bars held (losers): {losers['bars_held'].mean():.1f} bars")

    # Direction analysis
    print(f"\n🎯 DIRECTION ANALYSIS:")
    long_trades = df[df['direction'] == 'LONG']
    short_trades = df[df['direction'] == 'SHORT']

    long_wr = len(long_trades[long_trades['outcome'] == 'WIN']) / len(long_trades) * 100 if len(long_trades) > 0 else 0
    short_wr = len(short_trades[short_trades['outcome'] == 'WIN']) / len(short_trades) * 100 if len(short_trades) > 0 else 0

    print(f"   Long trades: {len(long_trades)} (WR: {long_wr:.1f}%)")
    print(f"   Short trades: {len(short_trades)} (WR: {short_wr:.1f}%)")

    # Zone analysis
    print(f"\n🎯 ZONE ANALYSIS:")
    for zone in sorted(df['zone'].unique()):
        zone_trades = df[df['zone'] == zone]
        zone_wr = len(zone_trades[zone_trades['outcome'] == 'WIN']) / len(zone_trades) * 100
        print(f"   Zone {zone}: {len(zone_trades)} trades (WR: {zone_wr:.1f}%)")

    return {
        'cooldown': cooldown,
        'target': target,
        'stop': stop,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'expectancy': expectancy * 100,
        'total_pnl': total_pnl * 100,
        'losers_with_large_mfe': len(losers_with_large_mfe),
        'losers_with_large_mfe_pct': len(losers_with_large_mfe)/len(losers)*100 if len(losers) > 0 else 0
    }


def main():
    """Compare different parameter sets"""

    # Test sets to compare
    test_sets = [
        # Short targets
        (60, 8, 6),   # Good WR
        (60, 12, 6),  # Medium WR
        (60, 25, 6),  # Low WR

        # Increasing stops with 25pt target
        (60, 25, 6),  # Low WR expected
        (60, 25, 12), # Even lower WR? (This is the mystery)
    ]

    results = []

    for cooldown, target, stop in test_sets:
        # Skip if poor risk/reward
        if target / stop < 1.2:
            print(f"\n⚠️  SKIPPING: Cooldown={cooldown}, Target={target}, Stop={stop} (Poor R/R: {target/stop:.2f}:1)")
            continue

        result = analyze_parameter_set(cooldown, target, stop)
        if result:
            results.append(result)

    # Summary comparison
    print(f"\n{'='*80}")
    print(f"SUMMARY COMPARISON")
    print(f"{'='*80}")
    print(f"{'Params':<20} {'Trades':>8} {'WR':>8} {'Exp':>10} {'P&L':>12} {'Losers w/ Large MFE':>20}")
    print(f"{'-'*80}")

    for r in results:
        params = f"{r['target']}pt / {r['stop']}pt"
        print(f"{params:<20} {r['total_trades']:>8} {r['win_rate']:>7.1f}% ${r['expectancy']:>9.2f} ${r['total_pnl']:>11.2f} {r['losers_with_large_mfe']:>10} ({r['losers_with_large_mfe_pct']:.0f}%)")


if __name__ == "__main__":
    main()
