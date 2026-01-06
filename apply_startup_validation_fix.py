#!/usr/bin/env python3
"""
Apply startup plan validation fix to NQ and GC trading bots
"""

VALIDATION_CODE = '''
        # ✅ FIX: Validate plan is for today's date
        if self.strategy.context:
            plan_date_str = self.strategy.context.get('timestamp', '')
            if plan_date_str:
                try:
                    plan_date = datetime.strptime(plan_date_str.split()[0], '%Y-%m-%d').date()
                    if plan_date != self.current_trading_day:
                        print(f"\\n{'='*60}")
                        print(f"⚠️  WARNING: STALE PLAN DETECTED!")
                        print(f"   Plan Date: {plan_date}")
                        print(f"   Today's Date: {self.current_trading_day}")
                        print(f"   >>> RUN MARKET PLANNER FOR TODAY FIRST! <<<")
                        print(f"{'='*60}\\n")
                        # Don't exit - allow user to decide, but make it very clear
                except:
                    pass  # If we can't parse date, continue anyway
'''

def apply_validation_fix(filepath):
    """Add startup validation to a trading bot file"""
    print(f"Processing: {filepath}")

    with open(filepath, 'r') as f:
        lines = f.readlines()

    # Find the line with current_trading_day initialization
    insert_index = None
    for i, line in enumerate(lines):
        if 'self.current_trading_day = datetime.now(NY_TZ).date()' in line:
            insert_index = i + 1
            break

    if insert_index:
        lines.insert(insert_index, VALIDATION_CODE)

        with open(filepath, 'w') as f:
            f.writelines(lines)

        print(f"   ✅ Applied validation fix")
        return True
    else:
        print(f"   ❌ Could not find insertion point")
        return False


if __name__ == "__main__":
    files = ['trading_bot_NQ_FIXED.py', 'trading_bot_GC_FIXED.py']

    print("="*60)
    print("APPLYING STARTUP PLAN VALIDATION FIX")
    print("="*60)
    print()

    for filepath in files:
        apply_validation_fix(filepath)
        print()

    print("="*60)
    print("✅ VALIDATION FIX COMPLETE")
    print("="*60)
