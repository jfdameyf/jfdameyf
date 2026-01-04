#!/bin/bash

echo "======================================================================"
echo "GC (GOLD FUTURES) OPTIMIZATION SETUP"
echo "======================================================================"
echo ""

# Check for required files
echo "Checking required scripts..."
echo ""

files_ok=true

if [ -f "generate_levels_ENHANCED_GC.py" ]; then
    echo "✅ Level generator: generate_levels_ENHANCED_GC.py"
else
    echo "❌ Level generator: generate_levels_ENHANCED_GC.py NOT FOUND"
    files_ok=false
fi

if [ -f "trading_bot_GC_FIXED.py" ]; then
    echo "✅ Trading bot: trading_bot_GC_FIXED.py"
else
    echo "❌ Trading bot: trading_bot_GC_FIXED.py NOT FOUND"
    files_ok=false
fi

if [ -f "backtest_bot_GC_COMPLETE.py" ]; then
    echo "✅ Backtester: backtest_bot_GC_COMPLETE.py"
else
    echo "❌ Backtester: backtest_bot_GC_COMPLETE.py NOT FOUND"
    files_ok=false
fi

if [ -f "optimize_parameters_GC.py" ]; then
    echo "✅ Optimizer: optimize_parameters_GC.py"
else
    echo "❌ Optimizer: optimize_parameters_GC.py NOT FOUND"
    files_ok=false
fi

echo ""
echo "Checking data files..."
echo ""

levels_ok=false

if [ -f "critical_levels_GC_master.csv" ]; then
    echo "✅ GC levels: critical_levels_GC_master.csv"
    levels_ok=true
elif [ -f "critical_levels_master_enhanced_GC.csv" ]; then
    echo "⚠️  Found: critical_levels_master_enhanced_GC.csv"
    echo "   Optimizer expects: critical_levels_GC_master.csv"
    echo ""
    read -p "Copy enhanced file to expected name? [Y/n]: " rename
    if [ "$rename" != "n" ] && [ "$rename" != "N" ]; then
        cp critical_levels_master_enhanced_GC.csv critical_levels_GC_master.csv
        echo "✅ File copied successfully"
        levels_ok=true
    fi
else
    echo "❌ No GC levels file found!"
    echo ""
    echo "You need to generate GC levels first:"
    echo "  1. Run: python generate_levels_ENHANCED_GC.py"
    echo "  2. Select option 2 (Last 30 days)"
    echo "  3. Wait for levels to be generated"
    echo ""
    echo "After generating levels, run this script again."
    exit 1
fi

echo ""

if [ "$files_ok" = false ]; then
    echo "❌ Missing required script files!"
    exit 1
fi

if [ "$levels_ok" = false ]; then
    echo "❌ GC levels file required before optimization!"
    exit 1
fi

echo "======================================================================"
echo "GC OPTIMIZATION PARAMETERS"
echo "======================================================================"
echo ""
echo "Based on previous optimizations:"
echo "  ES: 60min cooldown, 3pt target, 2pt stop → 67.2% WR, \$67.91 expectancy"
echo "  NQ: 60min cooldown, 15pt target, 4pt stop → 57.6% WR, \$138.79 expectancy"
echo ""
echo "GC optimization will test:"
echo "  Cooldown: [15, 30, 45, 60, 90, 120] minutes"
echo "  Targets: [2.0, 3.0, 4.0, 5.0, 6.0, 8.0] points"
echo "  Stops: [1.0, 1.5, 2.0, 2.5, 3.0, 4.0] points"
echo "  Total combinations: ~216"
echo ""
echo "Expected runtime: 30-60 minutes"
echo ""
echo "======================================================================"
echo ""

read -p "Ready to start optimization? [Y/n]: " proceed
if [ "$proceed" = "n" ] || [ "$proceed" = "N" ]; then
    echo "Optimization cancelled."
    exit 0
fi

echo ""
echo "Starting GC optimization..."
echo ""
echo "Run the following command:"
echo ""
echo "  python optimize_parameters_GC.py"
echo ""
echo "The optimizer will:"
echo "  1. Generate daily plans for the test period"
echo "  2. Test all parameter combinations"
echo "  3. Rank results by win rate and expectancy"
echo "  4. Save results to: backtest_results_GC/optimization_results_*.csv"
echo ""

