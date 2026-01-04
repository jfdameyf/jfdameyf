"""
GC Optimization Runner - Complete Setup and Execution
Automates the optimization process for gold futures
"""

import os
import sys
from datetime import datetime, timedelta
import pytz

NY_TZ = pytz.timezone('America/New_York')

def check_prerequisites():
    """Check if required files exist"""
    print("="*70)
    print("GC OPTIMIZATION - PREREQUISITE CHECK")
    print("="*70 + "\n")

    required_files = {
        'generate_levels_ENHANCED_GC.py': 'Level generator script',
        'trading_bot_GC_FIXED.py': 'GC trading bot',
        'backtest_bot_GC_COMPLETE.py': 'GC backtester',
        'optimize_parameters_GC.py': 'GC optimizer'
    }

    all_exist = True
    for filename, description in required_files.items():
        if os.path.exists(filename):
            print(f"✅ {description}: {filename}")
        else:
            print(f"❌ {description}: {filename} NOT FOUND")
            all_exist = False

    print()

    # Check data files
    data_files = {
        'critical_levels_GC_master.csv': 'GC trading levels (REQUIRED before optimization)',
        'gc_daily_context.json': 'GC daily context (Generated during optimization)'
    }

    print("Data Files:")
    for filename, description in data_files.items():
        if os.path.exists(filename):
            print(f"✅ {description}: {filename}")
        else:
            print(f"⚠️  {description}: {filename} - NEEDS GENERATION")

    print("\n" + "="*70 + "\n")

    return all_exist

def run_optimization():
    """Run the GC optimization with recommended parameters"""
    print("="*70)
    print("GC PARAMETER OPTIMIZATION")
    print("="*70)
    print()

    print("Based on ES and NQ optimization results:")
    print("  ES Optimal: 60min cooldown, 3pt target, 2pt stop → 67.2% WR, $67.91 expectancy")
    print("  NQ Optimal: 60min cooldown, 15pt target, 4pt stop → 57.6% WR, $138.79 expectancy")
    print()
    print("For GC (Gold), we'll test:")
    print("  Cooldown: [15, 30, 45, 60, 90, 120] minutes")
    print("  Targets: [2.0, 3.0, 4.0, 5.0, 6.0, 8.0] points")
    print("  Stops: [1.0, 1.5, 2.0, 2.5, 3.0, 4.0] points")
    print()

    # Date range
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)

    print("Select optimization period:")
    print("  1. Last 30 days (recommended - matches NQ)")
    print("  2. Last 60 days (comprehensive - matches ES)")
    print("  3. Last 90 days (extended)")
    print("  4. Custom date range")

    choice = input("\nSelect [1-4, default=1]: ").strip()

    if choice == "2":
        start_date = end_date - timedelta(days=60)
        days_desc = "60-day"
    elif choice == "3":
        start_date = end_date - timedelta(days=90)
        days_desc = "90-day"
    elif choice == "4":
        start_str = input("Start Date (YYYY-MM-DD): ").strip()
        end_str = input("End Date (YYYY-MM-DD, or Enter for yesterday): ").strip()
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            if end_str:
                end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
            days_desc = "custom"
        except ValueError:
            print("Invalid date format! Using 30 days.")
            start_date = end_date - timedelta(days=30)
            days_desc = "30-day"
    else:
        start_date = end_date - timedelta(days=30)
        days_desc = "30-day"

    print(f"\n📊 Running {days_desc} GC optimization: {start_date} to {end_date}")
    print()

    # POC filter
    enable_poc = input("Enable POC Distance Filter? [y/N]: ").strip().lower() == 'y'

    print("\n" + "="*70)
    print(f"Starting {days_desc} optimization...")
    print(f"This will test ~216 parameter combinations")
    print(f"Expected runtime: 30-60 minutes")
    print("="*70 + "\n")

    # Import and run optimizer
    try:
        from optimize_parameters_GC import ParameterOptimizer

        optimizer = ParameterOptimizer(start_date, end_date, enable_poc)

        # Run with default ranges
        optimizer.run_optimization(
            cooldown_options=[15, 30, 45, 60, 90, 120],
            target_options=[2.0, 3.0, 4.0, 5.0, 6.0, 8.0],
            stop_options=[1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
        )

        # Generate report
        optimizer.generate_report()
        optimizer.save_results()

        print("\n" + "="*70)
        print("✅ OPTIMIZATION COMPLETE!")
        print("="*70)

    except ImportError as e:
        print(f"❌ Error importing optimizer: {e}")
        print("Make sure optimize_parameters_GC.py exists and dependencies are installed.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Optimization failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def main():
    print("\n" + "="*70)
    print("GC (GOLD FUTURES) OPTIMIZATION RUNNER")
    print("="*70 + "\n")

    # Check prerequisites
    if not check_prerequisites():
        print("❌ Missing required script files!")
        print("Please ensure all GC scripts are present before running optimization.")
        sys.exit(1)

    # Check for levels file
    if not os.path.exists('critical_levels_GC_master.csv') and not os.path.exists('critical_levels_master_enhanced_GC.csv'):
        print("⚠️  WARNING: No GC levels file found!")
        print()
        print("You need to generate GC levels first:")
        print("  1. Run: python generate_levels_ENHANCED_GC.py")
        print("  2. Select date range (30 days recommended)")
        print("  3. Wait for levels to be generated")
        print()

        generate_now = input("Would you like guidance on generating levels? [y/N]: ").strip().lower()
        if generate_now == 'y':
            print("\n" + "="*70)
            print("TO GENERATE GC LEVELS:")
            print("="*70)
            print()
            print("Run the following command in your terminal:")
            print()
            print("  python generate_levels_ENHANCED_GC.py")
            print()
            print("When prompted:")
            print("  - Select option 2 (Last 30 days)")
            print("  - Wait for data to be fetched and processed")
            print("  - Output will be saved to: critical_levels_master_enhanced_GC.csv")
            print()
            print("Then rename the file:")
            print("  mv critical_levels_master_enhanced_GC.csv critical_levels_GC_master.csv")
            print()
            print("After that, run this optimization script again.")
            print("="*70)
            sys.exit(0)
        else:
            print("\n❌ Cannot proceed without GC levels file.")
            print("Generate levels first, then run this script again.")
            sys.exit(1)

    # Check which levels file exists
    if os.path.exists('critical_levels_master_enhanced_GC.csv') and not os.path.exists('critical_levels_GC_master.csv'):
        print("📝 Found: critical_levels_master_enhanced_GC.csv")
        print("   The optimizer expects: critical_levels_GC_master.csv")
        print()
        rename = input("Copy enhanced file to expected name? [Y/n]: ").strip().lower()
        if rename != 'n':
            os.system('cp critical_levels_master_enhanced_GC.csv critical_levels_GC_master.csv')
            print("✅ File copied successfully")
            print()

    # Ready to optimize
    print("✅ All prerequisites met!")
    print()

    proceed = input("Ready to start optimization? [Y/n]: ").strip().lower()
    if proceed == 'n':
        print("Optimization cancelled.")
        sys.exit(0)

    # Run optimization
    run_optimization()

if __name__ == "__main__":
    main()
