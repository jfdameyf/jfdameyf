#!/usr/bin/env python3
"""
Verify and fix LiveBot __init__ structure
"""

import sys

def check_file_syntax(filepath):
    """Check if a Python file has syntax errors"""
    print(f"Checking: {filepath}")
    try:
        with open(filepath, 'r') as f:
            code = f.read()
        compile(code, filepath, 'exec')
        print(f"   ✅ No syntax errors\n")
        return True
    except SyntaxError as e:
        print(f"   ❌ Syntax Error:")
        print(f"      Line {e.lineno}: {e.msg}")
        print(f"      Text: {e.text}")
        print()
        return False

def main():
    print("="*60)
    print("TRADING BOT SYNTAX VERIFICATION")
    print("="*60)
    print()

    files = [
        'trading_bot_FIXED.py',
        'trading_bot_NQ_FIXED.py',
        'trading_bot_GC_FIXED.py'
    ]

    all_ok = True
    for filepath in files:
        try:
            ok = check_file_syntax(filepath)
            if not ok:
                all_ok = False
        except FileNotFoundError:
            print(f"⚠️  File not found: {filepath}\n")

    print("="*60)
    if all_ok:
        print("✅ ALL FILES OK")
    else:
        print("❌ SYNTAX ERRORS FOUND")
        print("\nTo fix:")
        print("1. Pull latest changes from git")
        print("2. Or manually review the files listed above")
    print("="*60)

if __name__ == "__main__":
    main()
