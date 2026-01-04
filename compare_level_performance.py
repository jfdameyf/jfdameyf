#!/usr/bin/env python3
"""
Quick comparison of baseline vs enhanced level performance
"""

import json
import pandas as pd

def compare_performance():
    # Load summaries
    try:
        with open('backtest_results/summary_BASELINE_ES.json', 'r') as f:
            baseline = json.load(f)
    except FileNotFoundError:
        print("ERROR: summary_BASELINE_ES.json not found!")
        print("Run backtest with baseline levels first")
        return

    try:
        with open('backtest_results/summary_ENHANCED_ES.json', 'r') as f:
            enhanced = json.load(f)
    except FileNotFoundError:
        print("ERROR: summary_ENHANCED_ES.json not found!")
        print("Run backtest with enhanced levels first")
        return

    # Extract performance metrics
    baseline_perf = baseline['performance']
    enhanced_perf = enhanced['performance']

    print("=" * 70)
    print("BASELINE vs ENHANCED LEVEL PERFORMANCE COMPARISON")
    print("=" * 70)

    # Key metrics comparison
    metrics = [
        ('Total Trades', 'total_trades', ''),
        ('Winners', 'winners', ''),
        ('Win Rate', 'win_rate', '%'),
        ('Expectancy', 'expectancy_dollars', '$'),
        ('Total P&L', 'total_pnl_dollars', '$')
    ]

    for label, key, unit in metrics:
        base_val = baseline_perf[key]
        enh_val = enhanced_perf[key]
        diff = enh_val - base_val
        pct_change = (diff / base_val * 100) if base_val != 0 else 0

        print(f"\n{label}:")
        if unit == '$':
            print(f"  Baseline:  ${base_val:>10.2f}")
            print(f"  Enhanced:  ${enh_val:>10.2f}")
            print(f"  Change:    ${diff:>10.2f} ({pct_change:+.1f}%)")
        elif unit == '%':
            print(f"  Baseline:  {base_val:>10.1f}%")
            print(f"  Enhanced:  {enh_val:>10.1f}%")
            print(f"  Change:    {diff:>10.1f} pts ({pct_change:+.1f}%)")
        else:
            print(f"  Baseline:  {base_val:>10}")
            print(f"  Enhanced:  {enh_val:>10}")
            print(f"  Change:    {diff:>10.0f} ({pct_change:+.1f}%)")

    # MFE/MAE comparison
    if 'mfe_mae' in baseline:
        baseline_mfe = baseline['mfe_mae']
        enhanced_mfe = enhanced['mfe_mae']

        print("\n" + "=" * 70)
        print("MFE/MAE ANALYSIS (Edge Quality)")
        print("=" * 70)

        print(f"\nAvg MFE (Max Favorable Excursion):")
        print(f"  Baseline: {baseline_mfe['avg_mfe']:>7.2f} pts")
        print(f"  Enhanced: {enhanced_mfe['avg_mfe']:>7.2f} pts")
        print(f"  Change:   {enhanced_mfe['avg_mfe'] - baseline_mfe['avg_mfe']:>+7.2f} pts")

        print(f"\nAvg MAE (Max Adverse Excursion):")
        print(f"  Baseline: {baseline_mfe['avg_mae']:>7.2f} pts")
        print(f"  Enhanced: {enhanced_mfe['avg_mae']:>7.2f} pts")
        print(f"  Change:   {enhanced_mfe['avg_mae'] - baseline_mfe['avg_mae']:>+7.2f} pts")

        print(f"\nCapture Efficiency:")
        print(f"  Baseline: {baseline_mfe['avg_efficiency']:>7.1f}%")
        print(f"  Enhanced: {enhanced_mfe['avg_efficiency']:>7.1f}%")
        print(f"  Change:   {enhanced_mfe['avg_efficiency'] - baseline_mfe['avg_efficiency']:>+7.1f}%")

    # Decision criteria
    print("\n" + "=" * 70)
    print("DECISION")
    print("=" * 70)

    wr_change = enhanced_perf['win_rate'] - baseline_perf['win_rate']
    exp_change = enhanced_perf['expectancy_dollars'] - baseline_perf['expectancy_dollars']

    if wr_change >= 3.0 and exp_change >= 15.0:
        print("\n✓ RECOMMENDATION: Use enhanced levels permanently")
        print(f"  - Win rate improved by {wr_change:.1f}%")
        print(f"  - Expectancy improved by ${exp_change:.2f}")
        print("  - This is statistically significant improvement")
    elif wr_change >= 1.0 and exp_change >= 5.0:
        print("\n⚠ RECOMMENDATION: Test on larger sample (90 days)")
        print(f"  - Win rate improved by {wr_change:.1f}%")
        print(f"  - Expectancy improved by ${exp_change:.2f}")
        print("  - Improvement marginal - need more data for confidence")
    elif abs(wr_change) <= 1.0:
        print("\n⚠ RECOMMENDATION: Investigate further")
        print(f"  - Win rate changed by {wr_change:+.1f}%")
        print(f"  - Expectancy changed by ${exp_change:+.2f}")
        print("  - No meaningful improvement - may need tuning")
    else:
        print("\n✗ RECOMMENDATION: Revert to baseline")
        print(f"  - Win rate decreased by {wr_change:.1f}%")
        print("  - Enhanced levels underperformed")
        print("  - Review enhancement logic")

    print("\n" + "=" * 70)

    # Compare trade files if they exist
    try:
        baseline_trades = pd.read_csv('backtest_results/trades_BASELINE_ES.csv')
        enhanced_trades = pd.read_csv('backtest_results/trades_ENHANCED_ES.csv')

        print("\nZONE PERFORMANCE COMPARISON")
        print("=" * 70)

        print("\nBASELINE Zone Performance:")
        baseline_zone = baseline_trades.groupby('zone')['pnl'].agg(['count', 'mean', 'sum'])
        print(baseline_zone.to_string())

        print("\nENHANCED Zone Performance:")
        enhanced_zone = enhanced_trades.groupby('zone')['pnl'].agg(['count', 'mean', 'sum'])
        print(enhanced_zone.to_string())

    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"\nNote: Could not compare trade files: {e}")

if __name__ == "__main__":
    compare_performance()
