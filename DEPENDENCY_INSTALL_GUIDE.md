# Order Book Analysis - Dependency Installation Guide

## The Issue

The error you got:
```
⚠️  Could not import OrderBookFlipAnalyzer: No module named 'pandas'
   Order book analysis will be DISABLED
```

This means Python can't import the required dependencies (`pandas`, `numpy`, `databento`, etc.).

---

## Solution

You need to install the required dependencies. **But first**, check which Python environment you're using:

### Step 1: Check Your Python Environment

If you normally run `backtest_bot.py` successfully, it means pandas is already installed in whatever environment you use. You need to use **that same environment**.

**Are you using a virtual environment or conda?**

```bash
# Check if you're in a virtual environment
which python
# or
python --version

# If you use conda
conda env list

# If you use venv
# Look for (venv) or (env) in your terminal prompt
```

---

### Step 2: Install Dependencies

**Option A: If you're already using a virtual environment**
```bash
# Activate your environment first (if not already active)
# For venv:
source venv/bin/activate
# or
source env/bin/activate

# For conda:
conda activate your_env_name

# Then install:
pip install pandas numpy databento matplotlib seaborn pytz
```

**Option B: If using system Python**
```bash
pip install pandas numpy databento matplotlib seaborn pytz

# Or with pip3 if needed:
pip3 install pandas numpy databento matplotlib seaborn pytz
```

**Option C: If you have a requirements.txt**
```bash
pip install -r requirements.txt
```

---

### Step 3: Verify Installation

Test that the import works:
```bash
python -c "from orderbook_flip_analyzer import OrderBookFlipAnalyzer; print('✅ Import successful')"
```

If successful, you should see:
```
✅ Import successful
```

---

## Quick Check: Do You Already Have These?

Since `backtest_bot.py` also requires pandas/numpy, if you can run it successfully, these are already installed. The issue is likely:

1. **Wrong Python executable** - You might be running backtest_bot with a different python
2. **Virtual environment not activated** - You need to activate your env first
3. **Different user/permissions** - Check if you're running as the same user

**Try this:**
```bash
# Find which python runs backtest_bot successfully
which python

# Check what's installed there
python -m pip list | grep -E "pandas|numpy|databento"
```

---

## Minimal Requirements

For order book analysis to work, you need:

**Required:**
- `pandas` - Data handling
- `numpy` - Numerical operations
- `databento` - Market data fetching

**Optional (analysis still works without these):**
- `matplotlib` - For charts
- `seaborn` - For better charts
- `pytz` - For timezones (falls back to UTC)

**Install minimal set:**
```bash
pip install pandas numpy databento
```

---

## Running Without Order Book (Fallback)

If you don't want to deal with dependencies right now, you can run backtests **without** order book analysis:

```bash
# When prompted "Enable Order Book Analysis?", just answer 'N'
python backtest_bot.py
# Enable Order Book Analysis? [y/N]: N  ← Just press N

# Or in backtest_compare.py, it will work normally without order book
python backtest_compare.py
```

The backtest will run normally, just without the order book quality scoring for FLIP signals.

---

## Next Steps

**After installing dependencies:**

1. **Test the import:**
   ```bash
   python -c "from orderbook_flip_analyzer import OrderBookFlipAnalyzer"
   ```

2. **Run backtest with order book:**
   ```bash
   python backtest_bot.py
   # Enable Order Book Analysis? [y/N]: y
   # Enter Databento API Key: your_key
   ```

3. **Follow the workflow:**
   See `ORDERBOOK_WORKFLOW.md` for implementing data fetching

---

## Still Having Issues?

If you're still getting import errors after installing:

1. **Check Python version:**
   ```bash
   python --version
   # Should be Python 3.7+
   ```

2. **Reinstall in the correct location:**
   ```bash
   # Use the SAME python that runs backtest_bot.py
   /path/to/your/python -m pip install pandas numpy databento
   ```

3. **Check installation:**
   ```bash
   python -m pip show pandas
   # Should show version and location
   ```

---

## Summary

**The typo "analyyzer" you saw was likely a display issue. The real problem is missing dependencies.**

✅ **Quick fix:** `pip install pandas numpy databento`

Then try running your backtest again!
