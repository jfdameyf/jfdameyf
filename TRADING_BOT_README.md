# ES Futures Trading Bot

Automated trading signal generator for E-mini S&P 500 (ES) futures with comprehensive backtesting capabilities.

## 📁 Project Structure

```
.
├── trading_bot.py              # Original bot (reference only)
├── trading_bot_FIXED.py        # ✅ USE THIS - Fixed and improved version
├── backtest_bot.py             # Backtesting engine
├── backtest_compare.py         # Configuration comparison tool
├── requirements.txt            # Python dependencies
│
├── TRADING_BOT_ANALYSIS.md     # Detailed bug analysis
├── FIXES_SUMMARY.md            # Quick reference for fixes
├── BACKTESTING_GUIDE.md        # Backtesting documentation
└── TRADING_BOT_README.md       # This file
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configuration

Edit `trading_bot_FIXED.py` and add your credentials:

```python
API_KEY = "your_databento_api_key_here"
DISCORD_WEBHOOK_URL = "your_discord_webhook_url_here"  # Optional
```

### 3. Add Your Levels

Create `critical_levels_master_final.csv` with your support/resistance levels:

```csv
price,category,score,level_type
5950.00,Weekly Level,2.5,RES
5900.00,Daily Support,2.0,SUP
5850.00,Monthly POC,3.0,SUP
```

**Columns:**
- `price`: Level price (e.g., 5950.00)
- `category`: Description (e.g., "Weekly Support")
- `score`: Importance weight (1.0-5.0, higher = more important)
- `level_type`: SUP or RES (optional, auto-detected)

### 4. Generate Daily Plan

Run this **before market open each day**:

```bash
python trading_bot_FIXED.py
# Select: 1 (Run Market Planner)
# Press Enter for today's date
```

This creates `daily_context_v2.json` with:
- Support/resistance levels organized by zones
- Previous day volume profile (POC, VAH, VAL)
- Predicted daily range
- Market context assessment

### 5. Start Live Signal Bot

During market hours (9:30 AM - 4:00 PM ET):

```bash
python trading_bot_FIXED.py
# Select: 2 (Run Live Signals)
```

Bot will:
- Connect to Databento live feed
- Monitor price action
- Print signals when setups occur
- Log all activity to `logs/` directory

## 📊 How the Strategy Works

### Zone-Based Entry Logic

The bot organizes levels into 4 zones based on distance from current price:

**Zone 1 (Nearest):**
- **Entry:** Responsive/Limit orders
- **Trigger:** Price within 2 points of level
- **Logic:** Immediate mean reversion at strong levels

**Zone 2:**
- **Entry:** Responsive/Limit orders
- **Trigger:** Price within 4 points of level
- **Logic:** Similar to Zone 1, slightly looser proximity

**Zone 3:**
- **Entry:** Recapture/Market orders
- **Trigger:** Violation → Extension → Reclaim
- **Logic:** Requires level to fail first, then recapture

**Zone 4 (Furthest):**
- **Entry:** Recapture/Market orders
- **Trigger:** Violation → Extension (≥0.75pts) → Reclaim
- **Logic:** Conservative, only fires after clear rejection

### Recapture Detection (Zones 3 & 4)

**Support (Long Setup):**
1. **WATCHING:** Monitoring level
2. **VIOLATED:** Price breaks below
3. **EXTENSION:** Tracks how far below (0.75-15pts)
4. **TRIGGERED:** Price reclaims above level + 0.50pt buffer
5. **FAILED:** Extension exceeds 15pts (likely trend)

**Resistance (Short Setup):**
- Same logic, inverted

### POC Distance Filter (Optional)

When enabled (`ENABLE_POC_FILTER = True`):

- **Danger Zone (>50pts from POC):** No signals - likely trending
- **Sweet Spot (10-20pts from POC):** 1.25x size modifier
- **Standard (<10pts or >20pts):** Normal size

**Use when:** You want fewer, higher-quality setups in balanced markets

**Disable when:** You want all opportunities regardless of trend extension

## 🧪 Backtesting

### Why Backtest?

Validate that:
1. The bot fixes work (generates signals on historical data)
2. Your configuration is optimal
3. Signal quality meets expectations

### Quick 7-Day Backtest

```bash
python backtest_bot.py
# Select: 1
# POC Filter: N
```

**Expected:** 20-50 signals (3-7 per day)

### Compare Configurations

Find optimal settings:

```bash
python backtest_compare.py
# Select: 2 (Compare POC Filter - 30 days)
```

Outputs:
- Side-by-side comparison
- Performance scores
- Recommendation for best config

### Results Location

All backtest outputs saved to `backtest_results/`:
- `signals_[dates].csv` - All signals with timestamps
- `summary_[dates].json` - Statistics and metrics
- `charts_[dates].png` - Visual analysis
- `comparison_[dates].csv` - Config comparison

📖 **See BACKTESTING_GUIDE.md for detailed instructions**

## 📈 Signal Examples

### Responsive Entry (Zone 1/2)

```
🚀 SIGNAL FIRED @ 5950.00
   Type: LIMIT / RESPONSIVE
   Size: 1.0x
   Info: Zone 1: Responsive Trade @ 1.5pts. POC Check Disabled
   Time: 10:45:23
```

**Meaning:**
- Price approached weekly resistance at 5950.00
- Within 1.5 points (close enough for Zone 1)
- Use limit order at the level
- Standard position size

### Recapture Entry (Zone 3/4)

```
🚀 SIGNAL FIRED @ 5902.50
   Type: MARKET / RECAPTURE
   Size: 1.0x
   Info: Zone 3: Recaptured! POC Check Disabled
   Time: 14:15:42
```

**Meaning:**
- Support at 5900.00 was violated
- Price dropped to ~5898.00 (2.5pt extension)
- Price reclaimed back above 5900.50
- Enter immediately at market (5902.50)

## 🔧 Configuration Options

### Key Settings (in `trading_bot_FIXED.py`)

```python
# POC Filter: Trend extension check
ENABLE_POC_FILTER = False  # Set True for quality > quantity

# Zone proximity thresholds (in check_entry_signal)
proximity_threshold = 2.0 if zone == 1 else 4.0

# Recapture thresholds (in detect_level_recapture)
MIN_EXTENSION = 0.75      # Minimum violation distance
BLOWOUT_THRESHOLD = 15.0  # Maximum extension (fails after)
RECLAIM_BUFFER = 0.50     # Confirmation buffer

# Level filtering
BUFFER_PCT = 0.20          # Range buffer (20%)
MIN_LEVEL_SEPARATION = 4.0 # Minimum distance between levels
```

### Tuning Guide

**More aggressive (more signals):**
- Increase `BUFFER_PCT` to 0.25-0.30
- Decrease `MIN_EXTENSION` to 0.50
- Increase proximity thresholds (3.0 / 5.0)

**More conservative (fewer, quality signals):**
- Enable POC filter
- Decrease `BUFFER_PCT` to 0.15
- Increase `MIN_EXTENSION` to 1.0
- Decrease proximity thresholds (1.5 / 3.0)

## 📋 Daily Workflow

### Pre-Market (8:00-9:30 AM ET)

1. **Generate today's plan:**
   ```bash
   python trading_bot_FIXED.py
   # Select: 1
   ```

2. **Review levels:**
   - Check `daily_context_v2.json`
   - Note support/resistance zones
   - Review market context (gap up/down/inside value)

3. **Optional: Check backtest:**
   ```bash
   python backtest_bot.py
   # Test yesterday to validate
   ```

### Market Hours (9:30 AM - 4:00 PM ET)

1. **Start bot:**
   ```bash
   python trading_bot_FIXED.py
   # Select: 2
   ```

2. **Monitor signals:**
   - Watch console for signal alerts
   - Check `logs/bot_YYYYMMDD.log` for details
   - Bot prints status every 5 minutes

3. **Manual execution:**
   - Bot generates signals only (no auto-trading)
   - You decide whether to take each trade
   - Consider market context, size, risk

### Post-Market (4:00-5:00 PM ET)

1. **Review performance:**
   - Check log file
   - Count signals fired
   - Assess quality vs noise

2. **Weekly: Run backtest:**
   ```bash
   python backtest_bot.py
   # Test last 7 days
   # Compare to live results
   ```

## 🐛 Troubleshooting

### Bot shows "No Context Loaded"

**Solution:** Run Market Planner first (mode 1)

### No signals for hours

**Check:**
1. Levels in range? (`daily_context_v2.json`)
2. Price moving? (check market activity)
3. POC filter blocking? (try disabling)
4. Log file shows "WAIT" reasons

### Price looks wrong (0.000006)

**Problem:** Price conversion error

**Solution:**
```python
# In LiveBot.start(), verify line ~764:
price = record.price / 1e9  # CORRECT
# NOT: price = record.price * 1e9
```

### Signals fire once then stop

**Problem:** Deduplication not timing out

**Solution:** Check `alert_signal()` uses time-based deduplication (5-min cooldown)

### Backtest shows 0 signals

**Check:**
1. `critical_levels_master_final.csv` exists
2. Date range has trading days
3. Databento API key valid
4. Levels within reasonable distance of price

📖 **See FIXES_SUMMARY.md for detailed troubleshooting**

## 📊 Performance Expectations

### Signal Frequency

**Healthy ranges:**
- **Balanced market:** 5-10 signals/day
- **Trending market:** 2-5 signals/day
- **Choppy/range:** 8-15 signals/day

### Quality Metrics

**Good backtest results:**
- Zone 1 & 2: 60-70% of signals
- Zone 3 & 4: 30-40% of signals
- Long/Short: 40/60 to 60/40 split
- Consistent daily signals (not all on 1-2 days)

**Red flags:**
- 0 signals over multiple days
- >90% from single zone
- >80% one direction (unless strong trend)
- >20 signals/day consistently

## 🔐 Security Notes

### API Keys

**Never commit API keys to git!**

Current setup uses placeholder:
```python
API_KEY = # will place your databento API key here
```

**Best practice:**
```bash
# Use environment variables
export DATABENTO_API_KEY="your_key_here"

# In code:
import os
API_KEY = os.getenv('DATABENTO_API_KEY')
```

### Live Trading

This bot:
- ✅ Generates signals only
- ✅ Logs all activity
- ❌ Does NOT auto-execute trades
- ❌ Does NOT connect to broker

**To add auto-trading:**
- Implement broker API integration
- Add order management
- Include risk controls (position limits, max loss)
- Test extensively in paper trading

## 📚 Documentation Index

1. **TRADING_BOT_ANALYSIS.md**
   - Detailed bug analysis
   - 10 issues identified and fixed
   - Root cause explanations

2. **FIXES_SUMMARY.md**
   - Quick reference for fixes
   - Testing checklist
   - Expected behavior guide

3. **BACKTESTING_GUIDE.md**
   - Complete backtesting tutorial
   - Configuration comparison
   - Results interpretation

4. **TRADING_BOT_README.md** (this file)
   - Overall project guide
   - Strategy explanation
   - Daily workflow

## 🎯 Next Steps

### 1. Validate Fixes

```bash
# Run 30-day backtest
python backtest_bot.py
# Select: 2

# Should show 60-200 signals (healthy range)
```

### 2. Optimize Configuration

```bash
# Compare POC filter settings
python backtest_compare.py
# Select: 2

# Apply winner to live bot
```

### 3. Paper Trade

- Run bot for 1 week
- Don't execute trades yet
- Compare signals to backtest expectations
- Verify quality in real-time

### 4. Refine Levels

- Track which levels produce best signals
- Remove levels that rarely get touched
- Add levels from recent price action
- Maintain `critical_levels_master_final.csv`

### 5. Go Live (Carefully)

- Start with 1 contract
- Only take highest-conviction setups (Zone 1)
- Build confidence gradually
- Track all trades vs backtest predictions

## 🙏 Credits

**Built using:**
- Databento (market data)
- yfinance (VIX data)
- pandas/numpy (data processing)
- matplotlib/seaborn (visualization)

**Strategy concepts:**
- Volume Profile (POC, VAH, VAL)
- Support/Resistance zones
- Mean reversion + breakout logic
- Position sizing via confidence modifiers

## 📝 License

For personal use. Not financial advice. Trade at your own risk.

---

**Questions? Issues?**

- Check the relevant documentation file
- Review backtest results for validation
- Compare to historical market data
- Test in paper trading before going live

**Good luck! 🚀**
