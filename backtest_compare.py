"""
Backtest Comparison Tool
Runs multiple configurations and compares results
"""

import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
from backtest_bot import TradingBotBacktester

BACKTEST_OUTPUT = "backtest_results"
os.makedirs(BACKTEST_OUTPUT, exist_ok=True)

class BacktestComparator:
    def __init__(self, start_date, end_date):
        """
        Compare different strategy configurations

        Args:
            start_date: datetime.date - First day to test
            end_date: datetime.date - Last day to test
        """
        self.start_date = start_date
        self.end_date = end_date
        self.results = {}

    def run_configuration(self, name, enable_poc_filter):
        """Run a single configuration"""
        print(f"\n{'='*60}")
        print(f"🧪 Testing Configuration: {name}")
        print(f"{'='*60}")

        backtester = TradingBotBacktester(
            self.start_date,
            self.end_date,
            enable_poc_filter=enable_poc_filter
        )

        backtester.run_full_backtest()

        # Store results
        self.results[name] = {
            'signals': backtester.signals,
            'daily_stats': backtester.daily_stats,
            'config': {
                'poc_filter': enable_poc_filter
            }
        }

        return backtester

    def compare_configurations(self):
        """Compare all tested configurations"""
        print("\n" + "="*60)
        print("📊 CONFIGURATION COMPARISON")
        print("="*60)

        if not self.results:
            print("❌ No results to compare!")
            return

        comparison = []

        for name, data in self.results.items():
            signals = data['signals']
            df = pd.DataFrame(signals) if signals else pd.DataFrame()

            stats = {
                'Configuration': name,
                'POC Filter': 'ON' if data['config']['poc_filter'] else 'OFF',
                'Total Signals': len(signals),
                'Avg/Day': len(signals) / max(len(data['daily_stats']), 1),
                'Responsive': len(df[df['type']=='RESPONSIVE']) if not df.empty else 0,
                'Recapture': len(df[df['type']=='RECAPTURE']) if not df.empty else 0,
                'Flip': len(df[df['type']=='FLIP']) if not df.empty else 0,
                'Zone 1': len(df[df['zone']==1]) if not df.empty else 0,
                'Zone 2': len(df[df['zone']==2]) if not df.empty else 0,
                'Zone 3': len(df[df['zone']==3]) if not df.empty else 0,
                'Zone 4': len(df[df['zone']==4]) if not df.empty else 0,
            }

            comparison.append(stats)

        # Create comparison DataFrame
        comp_df = pd.DataFrame(comparison)

        print("\n" + comp_df.to_string(index=False))

        # Save comparison
        csv_file = f"{BACKTEST_OUTPUT}/comparison_{self.start_date}_to_{self.end_date}.csv"
        comp_df.to_csv(csv_file, index=False)
        print(f"\n💾 Comparison saved to: {csv_file}")

        # Plot comparison
        self._plot_comparison(comp_df)

        return comp_df

    def _plot_comparison(self, comp_df):
        """Generate comparison charts"""
        print("\n📊 Generating Comparison Charts...")

        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle(f'Configuration Comparison: {self.start_date} to {self.end_date}',
                     fontsize=16, fontweight='bold')

        # 1. Total signals comparison
        axes[0, 0].bar(comp_df['Configuration'], comp_df['Total Signals'], color='steelblue')
        axes[0, 0].set_title('Total Signals by Configuration', fontweight='bold')
        axes[0, 0].set_ylabel('Signal Count')
        axes[0, 0].tick_params(axis='x', rotation=45)
        axes[0, 0].grid(axis='y', alpha=0.3)

        # 2. Avg signals per day
        axes[0, 1].bar(comp_df['Configuration'], comp_df['Avg/Day'], color='coral')
        axes[0, 1].set_title('Average Signals Per Day', fontweight='bold')
        axes[0, 1].set_ylabel('Signals/Day')
        axes[0, 1].tick_params(axis='x', rotation=45)
        axes[0, 1].grid(axis='y', alpha=0.3)

        # 3. Signal type breakdown
        x = np.arange(len(comp_df))
        width = 0.25
        axes[1, 0].bar(x - width, comp_df['Responsive'], width, label='Responsive', color='#2ecc71')
        axes[1, 0].bar(x, comp_df['Recapture'], width, label='Recapture', color='#e74c3c')
        axes[1, 0].bar(x + width, comp_df['Flip'], width, label='Flip', color='#3498db')
        axes[1, 0].set_title('Signal Type Breakdown', fontweight='bold')
        axes[1, 0].set_ylabel('Signal Count')
        axes[1, 0].set_xticks(x)
        axes[1, 0].set_xticklabels(comp_df['Configuration'], rotation=45)
        axes[1, 0].legend()
        axes[1, 0].grid(axis='y', alpha=0.3)

        # 4. Zone distribution
        zone_cols = ['Zone 1', 'Zone 2', 'Zone 3', 'Zone 4']
        zone_data = comp_df[zone_cols].values

        x = np.arange(len(comp_df))
        width = 0.2

        for i, zone in enumerate(zone_cols):
            offset = (i - 1.5) * width
            axes[1, 1].bar(x + offset, comp_df[zone], width, label=zone)

        axes[1, 1].set_title('Zone Distribution', fontweight='bold')
        axes[1, 1].set_ylabel('Signal Count')
        axes[1, 1].set_xticks(x)
        axes[1, 1].set_xticklabels(comp_df['Configuration'], rotation=45)
        axes[1, 1].legend()
        axes[1, 1].grid(axis='y', alpha=0.3)

        plt.tight_layout()

        # Save plot
        plot_file = f"{BACKTEST_OUTPUT}/comparison_charts_{self.start_date}_to_{self.end_date}.png"
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        print(f"✅ Comparison charts saved to: {plot_file}")

    def find_best_configuration(self):
        """Identify which configuration performed best"""
        if not self.results:
            print("❌ No results to analyze!")
            return

        print("\n" + "="*60)
        print("🏆 BEST CONFIGURATION ANALYSIS")
        print("="*60)

        scores = {}

        for name, data in self.results.items():
            signals = data['signals']
            trading_days = len(data['daily_stats'])

            if not signals or trading_days == 0:
                scores[name] = 0
                continue

            # Score based on:
            # - Total signals (want enough opportunities)
            # - Not too many (quality > quantity)
            # - Good distribution across zones
            # - Balanced long/short

            df = pd.DataFrame(signals)

            total_signals = len(signals)
            avg_per_day = total_signals / trading_days

            # Ideal: 3-10 signals per day
            signal_score = 1.0
            if avg_per_day < 3:
                signal_score = avg_per_day / 3.0
            elif avg_per_day > 10:
                signal_score = 10.0 / avg_per_day

            # Zone diversity (prefer signals from multiple zones)
            zone_diversity = len(df['zone'].unique()) / 4.0

            # Direction balance (prefer ~50/50 long/short)
            long_pct = len(df[df['direction']=='LONG']) / total_signals
            balance_score = 1.0 - abs(0.5 - long_pct) * 2

            # Combined score
            score = (signal_score * 0.5) + (zone_diversity * 0.3) + (balance_score * 0.2)
            scores[name] = score * 100

            print(f"\n{name}:")
            print(f"   Signals/Day: {avg_per_day:.1f}")
            print(f"   Zone Diversity: {zone_diversity * 100:.0f}%")
            print(f"   Long/Short Balance: {balance_score * 100:.0f}%")
            print(f"   OVERALL SCORE: {score * 100:.1f}/100")

        # Find winner
        best_config = max(scores.items(), key=lambda x: x[1])

        print("\n" + "="*60)
        print(f"🏆 WINNER: {best_config[0]}")
        print(f"   Score: {best_config[1]:.1f}/100")
        print("="*60)

        return best_config[0]


# ==============================================================================
# PRESET COMPARISONS
# ==============================================================================

def compare_poc_filter(days_back=30):
    """Compare POC filter ON vs OFF"""
    from datetime import datetime
    import pytz

    NY_TZ = pytz.timezone('America/New_York')
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back + 5)

    comp = BacktestComparator(start_date, end_date)

    # Test POC filter OFF (default)
    comp.run_configuration("POC Filter OFF", enable_poc_filter=False)

    # Test POC filter ON
    comp.run_configuration("POC Filter ON", enable_poc_filter=True)

    # Compare
    comp.compare_configurations()
    comp.find_best_configuration()

    return comp


def compare_all_configs(days_back=30):
    """
    Run comprehensive comparison of all major configurations
    This helps identify optimal settings
    """
    from datetime import datetime
    import pytz

    NY_TZ = pytz.timezone('America/New_York')
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back + 5)

    comp = BacktestComparator(start_date, end_date)

    # Configuration matrix
    configs = [
        ("Default (POC OFF)", False),
        ("POC Filter ON", True),
    ]

    for name, poc in configs:
        comp.run_configuration(name, enable_poc_filter=poc)

    # Compare all
    comp.compare_configurations()
    winner = comp.find_best_configuration()

    print("\n" + "="*60)
    print("💡 RECOMMENDATION")
    print("="*60)
    print(f"\nBased on the backtest, use: {winner}")
    print("\nTo apply this configuration:")
    print("1. Open trading_bot_FIXED.py")
    print("2. Find the ENABLE_POC_FILTER setting at the top")
    print(f"3. Set ENABLE_POC_FILTER = {configs[0][1] if winner == configs[0][0] else configs[1][1]}")
    print("="*60)

    return comp


# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    print("="*60)
    print("   BACKTEST COMPARISON TOOL")
    print("="*60)
    print("\n1. Compare POC Filter (ON vs OFF) - 7 days")
    print("2. Compare POC Filter (ON vs OFF) - 30 days")
    print("3. Compare POC Filter (ON vs OFF) - 90 days")
    print("4. Full Configuration Test (30 days)")

    choice = input("\nSelect Option [1-4]: ").strip()

    if choice == "1":
        print("\n🔬 Comparing POC Filter Settings (7 days)...")
        compare_poc_filter(days_back=7)

    elif choice == "2":
        print("\n🔬 Comparing POC Filter Settings (30 days)...")
        compare_poc_filter(days_back=30)

    elif choice == "3":
        print("\n🔬 Comparing POC Filter Settings (90 days)...")
        compare_poc_filter(days_back=90)

    elif choice == "4":
        print("\n🔬 Running Full Configuration Comparison...")
        compare_all_configs(days_back=30)

    else:
        print("❌ Invalid choice")
