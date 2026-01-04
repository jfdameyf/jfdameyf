#!/usr/bin/env python3
"""
Quick script to revert GC trading hours from 9:30-16:15 back to pit session 8:20-13:30
"""

import re

def revert_file(filepath, replacements):
    """Apply replacements to a file"""
    try:
        with open(filepath, 'r') as f:
            content = f.read()

        original_content = content

        for old, new in replacements:
            content = content.replace(old, new)

        if content != original_content:
            with open(filepath, 'w') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"❌ Error with {filepath}: {e}")
        return False


def main():
    print("="*80)
    print("REVERTING GC TO PIT SESSION HOURS (8:20 AM - 1:30 PM ET)")
    print("="*80)
    print()

    files_to_update = [
        ('generate_levels_ENHANCED_GC.py', [
            ("rth = df.between_time('09:30', '16:15').copy()",
             "rth = df.between_time('08:20', '13:30').copy()"),
            ("# Gold RTH: 9:30 AM - 4:15 PM ET (matching ES/NQ)",
             "# Gold RTH: 8:20 AM - 1:30 PM ET (pit session)"),
        ]),

        ('backtest_bot_GC_COMPLETE.py', [
            ("print(f\"   RTH Hours: 9:30 AM - 4:15 PM ET (matching ES/NQ)\")",
             "print(f\"   RTH Hours: 8:20 AM - 1:30 PM ET (pit session)\")"),
            ("# ✅ EXTENDED: RTH hours (9:30 AM - 4:15 PM ET - matching ES/NQ)",
             "# ✅ RTH hours (8:20 AM - 1:30 PM ET - gold pit session)"),
            ("start_dt = NY_TZ.localize(datetime.combine(test_date, time(9, 30)))",
             "start_dt = NY_TZ.localize(datetime.combine(test_date, time(8, 20)))"),
            ("end_dt = NY_TZ.localize(datetime.combine(test_date, time(16, 15)))",
             "end_dt = NY_TZ.localize(datetime.combine(test_date, time(13, 30)))"),
            ("bars = bars.between_time('09:30', '16:15')",
             "bars = bars.between_time('08:20', '13:30')"),
            ("# ✅ ADDITIONAL CHECK: Verify timestamp is within RTH (9:30 AM - 4:15 PM)",
             "# ✅ ADDITIONAL CHECK: Verify timestamp is within RTH (8:20 AM - 1:30 PM)"),
            ("if not ((hour == 9 and minute >= 30) or (10 <= hour < 16) or (hour == 16 and minute <= 15)):",
             "if not ((hour == 8 and minute >= 20) or (9 <= hour < 13) or (hour == 13 and minute <= 30)):"),
        ]),

        ('trading_bot_GC_FIXED.py', [
            ("rth = trades.between_time('09:30', '16:15').copy()",
             "rth = trades.between_time('08:20', '13:30').copy()"),
            ("rth_slice = day_slice.between_time('09:30', '16:15')",
             "rth_slice = day_slice.between_time('08:20', '13:30')"),
        ]),
    ]

    updated_count = 0

    for filepath, replacements in files_to_update:
        print(f"Processing: {filepath}")
        if revert_file(filepath, replacements):
            print(f"   ✅ Updated")
            updated_count += 1
        else:
            print(f"   ⚠️  No changes needed (already reverted?)")

    print()
    print("="*80)
    print(f"✅ REVERT COMPLETE - Updated {updated_count} file(s)")
    print("="*80)
    print()
    print("NEXT STEPS:")
    print("1. Regenerate levels with pit hours:")
    print("   python3 generate_levels_ENHANCED_GC.py")
    print()
    print("2. Re-run optimization:")
    print("   python3 optimize_parameters_GC.py")
    print()
    print("3. Compare results to extended hours version")
    print()


if __name__ == "__main__":
    main()
