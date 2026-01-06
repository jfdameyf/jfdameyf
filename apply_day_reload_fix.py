#!/usr/bin/env python3
"""
Apply day reload fix to NQ and GC trading bots
"""

import re

DAY_RELOAD_CODE = '''        # Check if new trading day started
        today = datetime.now(NY_TZ).date()

        if today != self.current_trading_day:
            print(f"\\n{'='*60}")
            print(f"🌅 NEW TRADING DAY DETECTED: {today}")
            print(f"   Previous: {self.current_trading_day}")
            print(f"   Reloading daily plan and clearing state...")
            print(f"{'='*60}\\n")

            # Reload context for new day
            self.strategy.context = self.strategy.load_latest_context()
            self.strategy.pd_poc = self.strategy.context.get('pd_profile', {}).get('POC', None) if self.strategy.context else None

            # Clear daily state
            self.active_signals.clear()
            self.strategy.active_monitors.clear()
            self.strategy.save_state()

            # Update tracking
            self.current_trading_day = today

            # Verify new plan loaded
            if self.strategy.context:
                plan_date = self.strategy.context.get('timestamp', 'UNKNOWN')
                sup = len(self.strategy.context.get('levels', {}).get('raw_sup', []))
                res = len(self.strategy.context.get('levels', {}).get('raw_res', []))
                print(f"✅ Loaded plan for {plan_date}: {sup} SUP, {res} RES")
                if self.strategy.pd_poc:
                    print(f"✅ Previous Day POC: {self.strategy.pd_poc:.2f}")
                print()
            else:
                print("⚠️  WARNING: No plan available for new day!")
                print("   Run MarketPlanner to generate today's plan!\\n")

'''

def apply_fix(filepath):
    """Apply the day reload fix to a trading bot file"""
    print(f"Processing: {filepath}")

    with open(filepath, 'r') as f:
        content = f.read()

    # Find the evaluate_market function and add day reload code after the docstring
    pattern = r'(def evaluate_market\(self, current_price\):.*?""".*?""")'

    if re.search(pattern, content, re.DOTALL):
        # Add the day reload code after the docstring
        content = re.sub(
            pattern,
            r'\1\n' + DAY_RELOAD_CODE,
            content,
            flags=re.DOTALL
        )

        # Fix .seconds to .total_seconds()
        content = content.replace(
            'if (current_time - last_fired).seconds < 300:',
            'if (current_time - last_fired).total_seconds() < 300:  # FIX: use total_seconds()'
        )

        with open(filepath, 'w') as f:
            f.write(content)

        print(f"   ✅ Applied fix")
        return True
    else:
        print(f"   ❌ Could not find evaluate_market function")
        return False


if __name__ == "__main__":
    files = ['trading_bot_NQ_FIXED.py', 'trading_bot_GC_FIXED.py']

    print("="*60)
    print("APPLYING DAY RELOAD FIX TO TRADING BOTS")
    print("="*60)
    print()

    for filepath in files:
        apply_fix(filepath)
        print()

    print("="*60)
    print("✅ FIX COMPLETE")
    print("="*60)
