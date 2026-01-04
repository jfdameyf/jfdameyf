#!/usr/bin/env python3
"""
Quick Zone Analysis - Works with optimizer output
Add this code to your optimizer to get zone statistics
"""

def analyze_zones_in_optimizer():
    """
    Add this function to optimize_parameters_GC.py
    Call it after line 156 where results are printed
    """

    analysis_code = '''
# ADD THIS AFTER LINE 156 in optimize_parameters_GC.py
# Right after: print(f"   ✅ Trades: {total_trades}, WR: {win_rate:.1f}%, P&L: ${total_pnl*20:.0f}, Exp: ${expectancy:.0f}")

# Zone analysis
print(f"   📍 ZONE BREAKDOWN:")
for zone in sorted(df_trades['zone'].unique()):
    zone_trades = df_trades[df_trades['zone'] == zone]
    zone_wr = len(zone_trades[zone_trades['outcome'] == 'WIN']) / len(zone_trades) * 100
    zone_exp = zone_trades['pnl'].mean() * 100  # $100/point for GC
    zone_pnl = zone_trades['pnl'].sum() * 100
    print(f"      Zone {zone}: {len(zone_trades)} trades, WR={zone_wr:.1f}%, Exp=${zone_exp:.0f}, P&L=${zone_pnl:.0f}")

# Category analysis
print(f"   📊 CATEGORY BREAKDOWN:")
for cat in sorted(df_trades['type'].unique()):
    cat_trades = df_trades[df_trades['type'] == cat]
    cat_wr = len(cat_trades[cat_trades['outcome'] == 'WIN']) / len(cat_trades) * 100
    cat_exp = cat_trades['pnl'].mean() * 100
    print(f"      {cat}: {len(cat_trades)} trades, WR={cat_wr:.1f}%, Exp=${cat_exp:.0f}")

# Scratch analysis
scratches = df_trades[df_trades['outcome'] == 'SCRATCH']
if len(scratches) > 0:
    scratch_pnl = scratches['pnl'].mean() * 100
    print(f"   💫 SCRATCHES: {len(scratches)} trades ({len(scratches)/total_trades*100:.1f}%), Avg=${scratch_pnl:.0f}")
    close_scratches = scratches[scratches['mfe'] >= target * 0.8]
    if len(close_scratches) > 0:
        print(f"      ⚠️  {len(close_scratches)} scratches got within 20% of {target}pt target!")
'''

    print("="*80)
    print("ZONE ANALYSIS CODE FOR OPTIMIZER")
    print("="*80)
    print()
    print("Copy this code into optimize_parameters_GC.py")
    print("Add it right after line 156 (the print statement with trades/WR/P&L)")
    print()
    print("="*80)
    print()
    print(analysis_code)
    print()
    print("="*80)
    print()
    print("WHAT THIS WILL SHOW:")
    print()
    print("For each parameter combination tested, you'll see:")
    print("1. Zone breakdown - trades, WR, expectancy, P&L by zone")
    print("2. Category breakdown - RESPONSIVE vs RECAPTURE performance")
    print("3. Scratch analysis - how many scratches, their avg P&L")
    print("4. Near-miss scratches - trades that got close to target")
    print()
    print("This will help you answer:")
    print("- Should I only trade Zone 1?")
    print("- Are RECAPTURE trades worth taking?")
    print("- Should I take partial profits before the full target?")
    print()


def create_modified_optimizer():
    """
    Creates a modified version of the optimizer with zone analysis built-in
    """
    print("\n" + "="*80)
    print("CREATING ENHANCED OPTIMIZER WITH ZONE ANALYSIS")
    print("="*80 + "\n")

    try:
        with open('optimize_parameters_GC.py', 'r') as f:
            original = f.read()

        # Find the line where results are printed
        target_line = 'print(f"   ✅ Trades: {total_trades}, WR: {win_rate:.1f}%, P&L: ${total_pnl*20:.0f}, Exp: ${expectancy:.0f}")'

        if target_line not in original:
            print("❌ Cannot find target line in optimizer")
            print("You may need to manually add the code shown above")
            return

        # Create the zone analysis code
        zone_code = '''

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
'''

        # Insert the code after the target line
        modified = original.replace(target_line, target_line + zone_code)

        # Save to new file
        with open('optimize_parameters_GC_WITH_ZONES.py', 'w') as f:
            f.write(modified)

        print("✅ Created: optimize_parameters_GC_WITH_ZONES.py")
        print()
        print("This enhanced optimizer will show zone/category stats for each parameter test")
        print()
        print("To use it:")
        print("   python3 optimize_parameters_GC_WITH_ZONES.py")
        print()

    except FileNotFoundError:
        print("❌ Cannot find optimize_parameters_GC.py")
        print("Make sure you're in the correct directory")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    print("\n🔬 GC ZONE ANALYSIS SETUP\n")
    print("Choose an option:\n")
    print("1. Show code to manually add to optimizer (recommended)")
    print("2. Auto-create enhanced optimizer file\n")

    choice = input("Enter choice (1 or 2): ").strip()

    if choice == "1":
        analyze_zones_in_optimizer()
    elif choice == "2":
        create_modified_optimizer()
    else:
        print("Invalid choice. Running option 1...\n")
        analyze_zones_in_optimizer()
