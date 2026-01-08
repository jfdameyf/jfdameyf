# Which Backtest Files to Use - Quick Reference

## 🎯 TLDR - What You Should Use

**For standard backtesting:**
- ✅ **Use:** `backtest_compare.py`
- 📄 **Imports:** `backtest_bot.py` (automatically)

**For order book analysis:**
- ✅ **Use:** `backtest_bot.py` directly OR `backtest_compare.py`
- 🔑 **Need:** Databento API key
- 📊 **Analyzes:** FLIP signal quality with Level 2 data

---

## 📁 File Breakdown

### **Core Files (What You Run)**

#### 1. `backtest_compare.py` ⭐ **RECOMMENDED**
**What it does:**
- Runs multiple backtest configurations (POC filter ON/OFF)
- Generates comparison charts
- Shows which settings work best

**How to run:**
```bash
python backtest_compare.py
# Select option 1, 2, 3, or 4
```

**Imports:** `backtest_bot.py` automatically

**When to use:** When you want to compare different strategy settings

---

#### 2. `backtest_bot.py` ⭐ **NOW WITH ORDER BOOK**
**What it does:**
- Main ES backtest engine
- ✅ **NEW:** Includes order book FLIP analysis
- Can run standalone or via backtest_compare.py

**How to run standalone:**
```bash
python backtest_bot.py
# Will ask: Enable Order Book Analysis? [y/N]
# If yes, asks for Databento API key
```

**How to use with order book:**
```python
from backtest_bot import TradingBotBacktester

backtester = TradingBotBacktester(
    start_date=start,
    end_date=end,
    enable_poc_filter=False,
    analyze_orderbook=True,  # ← Enable order book
    databento_api_key="your_key_here"
)
backtester.run_full_backtest()
```

**When to use:**
- For quick standalone backtests
- When you want order book analysis
- When you need programmatic control

---

### **Alternative Backtest Engines (Advanced)**

#### 3. `backtest_bot_FIXED.py`
**What it is:** Variant of backtest_bot.py with bug fixes
**Size:** ~540 lines
**When to use:** If you encounter bugs in main backtest_bot.py
**Note:** Has same features as backtest_bot.py

#### 4. `backtest_bot_COMPLETE.py`
**What it is:** ES backtest with **MFE/MAE tracking**
**Size:** ~800 lines
**Extra features:**
- Max Favorable Excursion (how far trade went in your favor)
- Max Adverse Excursion (how far trade went against you)
- Per-trade outcome analysis

**When to use:** When you need detailed trade performance metrics

**How to switch to COMPLETE:**
```python
# In backtest_compare.py, change line 13 from:
from backtest_bot import TradingBotBacktester

# To:
from backtest_bot_COMPLETE import TradingBotBacktester
```

#### 5. `backtest_bot_NQ_COMPLETE.py`
**What it is:** NQ version with MFE/MAE tracking
**When to use:** For NQ-specific backtesting with performance metrics

#### 6. `backtest_bot_GC_COMPLETE.py`
**What it is:** GC (Gold) version with MFE/MAE tracking
**When to use:** For GC-specific backtesting with performance metrics

---

### **Documentation/Examples (Don't Run These)**

#### 7. `backtest_with_orderbook_example.py` ❌ **NOT A BACKTEST**
**What it is:** Code examples and integration patterns
**Purpose:** Documentation showing HOW to integrate order book
**Don't run this:** It's just examples, not a working backtest

**Use it for:** Copy/paste code when integrating order book into other files

---

## 🚀 Usage Scenarios

### **Scenario 1: Standard Backtest (No Order Book)**
```bash
# Just run this:
python backtest_compare.py
# Select option (1-4)
# Choose POC filter (y/N)
```

**Uses:** `backtest_compare.py` → imports `backtest_bot.py`

---

### **Scenario 2: Backtest WITH Order Book Analysis**

**Option A: Use backtest_bot.py directly**
```bash
python backtest_bot.py
# Enable Order Book Analysis? y
# Enter Databento API Key: your_key
```

**Option B: Use programmatically**
```python
from backtest_bot import TradingBotBacktester

backtester = TradingBotBacktester(
    start_date=start,
    end_date=end,
    analyze_orderbook=True,
    databento_api_key="dbxxxxxx"
)
backtester.run_full_backtest()
```

**Option C: Modify backtest_compare.py**
```python
# Add to compare_poc_filter() function:
comp.run_configuration(
    "POC Filter OFF",
    enable_poc_filter=False,
    # ↓ Add these:
    analyze_orderbook=True,
    databento_api_key="your_key"
)
```

---

### **Scenario 3: Need Trade Performance Metrics (MFE/MAE)**
```bash
# Option 1: Switch backtest_compare.py to use COMPLETE
# Edit line 13 in backtest_compare.py:
from backtest_bot_COMPLETE import TradingBotBacktester

# Option 2: Run COMPLETE directly
python backtest_bot_COMPLETE.py
```

**Uses:** `backtest_bot_COMPLETE.py` (ES with MFE/MAE)

---

## 🎨 Integration Points Added to backtest_bot.py

### **Point 1: Initialization (lines 41-95)**
```python
def __init__(self, start_date, end_date, enable_poc_filter=False,
             analyze_orderbook=False, databento_api_key=None):
    # ...
    self.ob_analyzer = None

    if analyze_orderbook and databento_api_key:
        self.ob_analyzer = create_analyzer_from_api_key(databento_api_key, SYMBOL)
```

### **Point 2: FLIP Signal Analysis (lines 294-339)**
```python
elif action == "FLIP_ENTRY":
    signal = {...}

    if self.analyze_orderbook and self.ob_analyzer:
        ob_result = self.ob_analyzer.process_flip_signal(signal, timestamp)
        if ob_result:
            signal['orderbook'] = ob_result
            # Shows quality rating in console
```

### **Point 3: Report Generation (lines 436-461)**
```python
if self.analyze_orderbook and self.ob_analyzer:
    print("\n📊 ORDER BOOK FLIP ANALYSIS")
    self.ob_analyzer.generate_summary_report()
    self.ob_analyzer.export_to_csv(...)
    self.ob_analyzer.plot_quality_distribution(...)
```

### **Point 4: Live Display (lines 199-207)**
```python
# Shows FLIP quality in backtest output
if sig_type == 'FLIP' and 'orderbook' in sig:
    ob = sig['orderbook']
    quality_str = f" | Quality: {ob['quality_rating']} ({ob['quality_score']:.0f})"
```

---

## 📊 Output Files Generated

### **Standard Backtest (backtest_compare.py)**
```
backtest_results/
├── signals_2024-12-01_to_2024-12-31.csv
├── summary_2024-12-01_to_2024-12-31.json
├── charts_2024-12-01_to_2024-12-31.png
└── comparison_charts_2024-12-01_to_2024-12-31.png
```

### **WITH Order Book Analysis**
```
backtest_results/
├── signals_2024-12-01_to_2024-12-31.csv
├── summary_2024-12-01_to_2024-12-31.json
├── charts_2024-12-01_to_2024-12-31.png
├── flip_orderbook_2024-12-01_to_2024-12-31.csv  ← NEW
└── flip_quality_2024-12-01_to_2024-12-31.png    ← NEW
```

**Order book CSV includes:**
- level_price
- original_type → flip_type
- quality_score (0-100)
- quality_rating (EXCELLENT/GOOD/FAIR/POOR)
- recommendation (TAKE/CONSIDER/SKIP)
- liquidity_shift
- absorption_delta
- And more...

---

## 🔧 Next Steps

### **Phase 1: Run Standard Backtest (Now)**
```bash
python backtest_compare.py
```

### **Phase 2: Implement Order Book Fetching (Week 1-2)**
Follow `ORDERBOOK_WORKFLOW.md` to:
1. Get Databento API key
2. Implement `_fetch_orderbook_snapshot()` in orderbook_flip_analyzer.py
3. Implement calculation methods

### **Phase 3: Run WITH Order Book (Week 2-3)**
```bash
python backtest_bot.py
# Enable Order Book Analysis? y
```

---

## ❓ FAQ

**Q: Which file should I edit to add features?**
A: Edit `backtest_bot.py` - it's the main engine that everything uses

**Q: Can I use order book analysis with backtest_compare.py?**
A: Yes! Either:
- Modify backtest_compare.py to pass analyze_orderbook=True
- Or backtest_compare.py will automatically use backtest_bot.py which already has it integrated

**Q: What if I want NQ or GC with order book?**
A: Add the same integration points to backtest_bot_NQ_COMPLETE.py or backtest_bot_GC_COMPLETE.py (copy from backtest_bot.py lines 41-95, 294-339, 436-461)

**Q: Will this break my existing backtests?**
A: No! Order book analysis is **optional**. If you don't enable it, everything works exactly as before.

**Q: Do I need COMPLETE version?**
A: Not required. Use COMPLETE only if you need MFE/MAE metrics for trade analysis.

---

## 📋 Recommended File Structure

```
Your Current Setup (Recommended):
├── backtest_bot.py              ← Main engine (now with order book!)
├── backtest_compare.py          ← What you run for comparisons
├── orderbook_flip_analyzer.py   ← Order book analysis class
├── ORDERBOOK_WORKFLOW.md        ← Implementation guide
└── WHICH_FILES_TO_USE.md        ← This file

Alternative Engines (Optional):
├── backtest_bot_FIXED.py        ← Bug-fixed variant
├── backtest_bot_COMPLETE.py     ← With MFE/MAE
├── backtest_bot_NQ_COMPLETE.py  ← NQ with MFE/MAE
└── backtest_bot_GC_COMPLETE.py  ← GC with MFE/MAE

Documentation (Reference Only):
└── backtest_with_orderbook_example.py  ← Code examples
```

---

## ✅ Summary

**For 99% of use cases:**
- Run `backtest_compare.py` (standard)
- OR run `backtest_bot.py` (with order book option)

**Everything else is:**
- Alternative versions (COMPLETE, FIXED, NQ, GC)
- Documentation (example.py files)

**Order book integration is in:** `backtest_bot.py` (lines 41-95, 294-339, 436-461)

**To enable order book:** Pass `analyze_orderbook=True` and `databento_api_key="..."`
