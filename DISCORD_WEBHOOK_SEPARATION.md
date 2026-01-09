# Separate Discord Webhooks Configuration

## Overview

Your trading bots now support **two separate Discord webhooks** to prevent trade signal alerts from overwhelming your daily planning channel:

1. **DISCORD_WEBHOOK_URL** - For daily plan notifications (MarketPlanner)
2. **DISCORD_SIGNALS_WEBHOOK_URL** - For trade signal alerts (LiveBot)

This change applies to **all three bots**: ES, NQ, and GC.

---

## Why This Matters

### Problem Before:
```
#trading-es (single channel)
├── 📅 ES Daily Plan (once per day)
├── 🚀 ES LONG SIGNAL @ 5924.25
├── 🚀 ES SHORT SIGNAL @ 5935.50
├── 🚀 ES LONG SIGNAL @ 5920.75
├── 🚀 ES FLIP SIGNAL @ 5927.00
├── 🚀 ES SHORT SIGNAL @ 5938.25
└── ... (10-20 signals per day overwhelming the channel)
```

**Issues:**
- Trade signals drown out the daily plan
- Hard to find the morning context later in the day
- Channel becomes noisy and cluttered

### Solution After:
```
#es-daily-plan (low-frequency channel)
└── 📅 ES Daily Plan (once per day, easy to reference)

#es-signals (high-frequency channel)
├── 🚀 ES LONG SIGNAL @ 5924.25
├── 🚀 ES SHORT SIGNAL @ 5935.50
├── 🚀 ES LONG SIGNAL @ 5920.75
└── ... (all signals here)
```

**Benefits:**
✅ Daily plan stays accessible in clean channel
✅ Signals have dedicated channel for monitoring
✅ Better organization and less noise
✅ Easier to review signals separately from context

---

## Configuration

### Step 1: Create Two Discord Webhooks

**For Daily Plan Channel:**
1. Go to your Discord server
2. Create or select a channel (e.g., `#es-daily-plan`)
3. Edit Channel → Integrations → Webhooks → New Webhook
4. Copy webhook URL
5. Name it "ES Daily Plan" (or similar)

**For Trade Signals Channel:**
1. Create or select a different channel (e.g., `#es-signals`)
2. Edit Channel → Integrations → Webhooks → New Webhook
3. Copy webhook URL
4. Name it "ES Trade Signals" (or similar)

### Step 2: Configure the Bots

Open each bot file and set both webhook URLs:

**For ES Bot (trading_bot_FIXED.py):**
```python
# Discord Webhook URLs
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/123.../abc"  # Daily plan
DISCORD_SIGNALS_WEBHOOK_URL = "https://discord.com/api/webhooks/456.../def"  # Signals
```

**For NQ Bot (trading_bot_NQ_FIXED.py):**
```python
# Discord Webhook URLs
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/123.../nq-plan"
DISCORD_SIGNALS_WEBHOOK_URL = "https://discord.com/api/webhooks/456.../nq-signals"
```

**For GC Bot (trading_bot_GC_FIXED.py):**
```python
# Discord Webhook URLs
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/123.../gc-plan"
DISCORD_SIGNALS_WEBHOOK_URL = "https://discord.com/api/webhooks/456.../gc-signals"
```

---

## Backwards Compatibility

**If you don't want separate channels**, just leave `DISCORD_SIGNALS_WEBHOOK_URL` empty:

```python
# Discord Webhook URLs
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/123.../trading"
DISCORD_SIGNALS_WEBHOOK_URL = ""  # Leave empty - uses main webhook
```

The bot will automatically fall back to `DISCORD_WEBHOOK_URL` for both daily plans and trade signals.

**This is fully backwards compatible** - your existing configuration will continue to work without any changes!

---

## What Goes Where

### DISCORD_WEBHOOK_URL (Daily Plan Channel)
**Sent by:** MarketPlanner (Mode 1)

**Messages:**
- 📅 Daily pre-market plan
- Support/Resistance levels
- Context (Above/Below/Inside Value)
- Predicted range
- Previous day POC

**Frequency:** Once per trading day (usually run pre-market)

**Example:**
```
📅 ES Plan (ES.c.0): 2026-01-09
Price: 5925.50 | Range: +/- 18.75

🧩 Context: Below Value
Price below yesterday's value area - watching for support tests

🔴 Resistance
5935.00 [Zone 2] Strong
5940.25 [Zone 3] Moderate
5945.50 [Zone 4] Weak

🟢 Support
5920.00 [Zone 1] Strong
5915.50 [Zone 2] Moderate
5910.25 [Zone 3] Weak
```

### DISCORD_SIGNALS_WEBHOOK_URL (Trade Signals Channel)
**Sent by:** LiveBot (Mode 2)

**Messages:**
- 🚀 Trade signal alerts (LONG/SHORT)
- Entry price and type
- Position size modifier
- Signal details (Zone, proximity, delta)
- Current candle delta
- Session cumulative delta

**Frequency:** 5-20 times per trading day (whenever signals fire)

**Example:**
```
🚀 🟢 ES LONG SIGNAL
Entry Price: 5924.25
Type: LIMIT / RESPONSIVE
Size: 1.0x

📊 Details: Zone 1: Touch @ 5924.25 (0.50pts proximity)
🟢 Current Candle Delta: +450 contracts
🟢 Session Cumulative Delta (RTH): +2,150 contracts
⏰ Time: 2026-01-09 10:30:45 ET
```

---

## Recommended Channel Setup

### Option 1: Dedicated Channels Per Instrument
```
Discord Server
├── 📂 ES Trading
│   ├── #es-daily-plan (DISCORD_WEBHOOK_URL)
│   └── #es-signals (DISCORD_SIGNALS_WEBHOOK_URL)
├── 📂 NQ Trading
│   ├── #nq-daily-plan
│   └── #nq-signals
└── 📂 GC Trading
    ├── #gc-daily-plan
    └── #gc-signals
```

**Pros:**
- Complete separation by instrument
- Easy to focus on one market
- Clean organization

**Cons:**
- More channels to manage
- Need to switch channels to see different instruments

### Option 2: Combined Plans, Separate Signals
```
Discord Server
├── #trading-plans (all daily plans)
├── #es-signals
├── #nq-signals
└── #gc-signals
```

**Pros:**
- See all daily contexts in one place
- Signals still separated by instrument
- Fewer channels

**Cons:**
- Plans from different instruments mixed together

### Option 3: Everything Together (Original)
```
Discord Server
└── #trading (all plans and signals)
```

**Pros:**
- Simplest setup
- One place for everything

**Cons:**
- Signals can bury daily plan
- Gets noisy with multiple instruments
- Hard to review historical plans

---

## Testing Your Configuration

### Test Daily Plan Webhook:
```bash
python trading_bot_FIXED.py
# Select mode 1 (Market Planner)
# Check your daily plan channel for the plan notification
```

### Test Signals Webhook:
```bash
python trading_bot_FIXED.py
# Select mode 2 (Live Signals)
# Wait for a signal to fire
# Check your signals channel for the alert
```

### Verify Separation:
- ✅ Daily plan appears in DISCORD_WEBHOOK_URL channel
- ✅ Trade signals appear in DISCORD_SIGNALS_WEBHOOK_URL channel
- ✅ No messages in wrong channels

---

## Troubleshooting

### Signals Not Appearing
**Check:**
1. Is `DISCORD_SIGNALS_WEBHOOK_URL` set correctly?
2. Does the webhook URL start with `https://discord.com/api/webhooks/`?
3. Is the webhook still active in Discord (not deleted)?
4. Run bot with test signal and check console for errors

### Both Going to Same Channel
**Likely Cause:**
- `DISCORD_SIGNALS_WEBHOOK_URL` is empty or invalid
- Bot falls back to `DISCORD_WEBHOOK_URL`

**Fix:**
- Set `DISCORD_SIGNALS_WEBHOOK_URL` to valid webhook
- Verify URL is complete and correct

### Nothing Working
**Check:**
1. Both webhook URLs are set
2. Webhooks are created in Discord
3. Bot has internet connectivity
4. Discord server is accessible
5. Webhook URLs are not expired/revoked

---

## Migration Guide

### If You Already Have a Setup

**Current Setup:**
```python
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/123.../trading"
```

**After Update (No Changes Required):**
```python
# Old configuration still works!
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/123.../trading"
DISCORD_SIGNALS_WEBHOOK_URL = ""  # Empty = uses main webhook
```

**To Enable Separation:**
1. Create new webhook in Discord for signals channel
2. Copy new webhook URL
3. Paste into `DISCORD_SIGNALS_WEBHOOK_URL`
4. Restart bot

```python
# New configuration with separation
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/123.../trading"  # Plans
DISCORD_SIGNALS_WEBHOOK_URL = "https://discord.com/api/webhooks/456.../signals"  # Signals
```

---

## Advanced: Using Same Webhook for Multiple Bots

You can use the same signals channel for multiple instruments:

```python
# ES Bot
DISCORD_SIGNALS_WEBHOOK_URL = "https://discord.com/api/webhooks/456.../all-signals"

# NQ Bot
DISCORD_SIGNALS_WEBHOOK_URL = "https://discord.com/api/webhooks/456.../all-signals"

# GC Bot
DISCORD_SIGNALS_WEBHOOK_URL = "https://discord.com/api/webhooks/456.../all-signals"
```

**Result:**
```
#all-signals
├── 🚀 ES LONG SIGNAL @ 5924.25
├── 🚀 NQ SHORT SIGNAL @ 21150.00
├── 🚀 GC LONG SIGNAL @ 2875.30
└── ...
```

The embeds clearly show which instrument (ES/NQ/GC) each signal is for.

---

## Summary

### Configuration Variables

| Variable | Purpose | Used By | Frequency |
|----------|---------|---------|-----------|
| `DISCORD_WEBHOOK_URL` | Daily plans | MarketPlanner | 1x per day |
| `DISCORD_SIGNALS_WEBHOOK_URL` | Trade signals | LiveBot | 5-20x per day |

### Implementation Details

**MarketPlanner (Mode 1):**
- Always uses `DISCORD_WEBHOOK_URL`
- Sends daily context notification
- Not affected by signals webhook

**LiveBot (Mode 2):**
- Uses `DISCORD_SIGNALS_WEBHOOK_URL` if set
- Falls back to `DISCORD_WEBHOOK_URL` if empty
- Sends trade alert notifications

### Key Benefits

✅ **Separation** - Keep plans separate from high-frequency signals
✅ **Organization** - Easier to find and reference daily context
✅ **Flexibility** - Use one or two channels as needed
✅ **Backwards Compatible** - Existing setups continue working
✅ **Multi-Instrument** - Apply to ES, NQ, and GC bots

---

## Next Steps

1. **Create webhooks** in Discord for your desired channel setup
2. **Copy URLs** from Discord webhook settings
3. **Update configuration** in bot files
4. **Test** by running MarketPlanner and LiveBot
5. **Verify** messages appear in correct channels

Enjoy your cleaner, more organized Discord notifications! 🚀
