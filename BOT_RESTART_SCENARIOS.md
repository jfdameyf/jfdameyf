# Trading Bot Restart Scenarios

## What Happens When You Restart the Bot?

### ✅ CORRECT Workflow

**Day 1:**
```bash
9:20 AM: python3 trading_bot_FIXED.py → 1 (Run Planner)
9:30 AM: python3 trading_bot_FIXED.py → 2 (Start Bot)
         Bot loads Day 1 plan ✅
         Bot runs with Day 1 levels ✅

2:00 PM: Bot crashes or you close it
```

**Day 2:**
```bash
9:20 AM: python3 trading_bot_FIXED.py → 1 (Run Planner) ← IMPORTANT!
9:30 AM: python3 trading_bot_FIXED.py → 2 (Start Bot)
         Bot loads Day 2 plan ✅
         Bot detects Day 2 levels ✅
         Bot runs normally ✅
```

**Output at startup:**
```
🤖 INITIALIZING LIVE SIGNAL BOT...
   POC Filter Enabled: False
✅ Context Loaded: 2025-01-07 09:19:42
✅ Support Levels: 15
   - 6032.50 [1]
   - 6028.75 [1]
   - 6025.00 [2]
✅ Resistance Levels: 18
   - 6058.25 [1]
   - 6062.00 [1]
   - 6065.50 [2]
```

---

### ❌ WRONG: Restart Without Running Planner

**Day 1:**
```bash
9:20 AM: python3 trading_bot_FIXED.py → 1 (Run Planner)
9:30 AM: python3 trading_bot_FIXED.py → 2 (Start Bot)
         Bot runs with Day 1 plan ✅

2:00 PM: Bot crashes or you close it
```

**Day 2:**
```bash
9:30 AM: python3 trading_bot_FIXED.py → 2 (Start Bot) ← FORGOT TO RUN PLANNER!
         Bot loads plan from JSON → Gets Day 1 plan (STALE!)
         Bot detects stale plan ⚠️
         Bot WARNS you but continues running
```

**Output at startup:**
```
🤖 INITIALIZING LIVE SIGNAL BOT...
   POC Filter Enabled: False

============================================================
⚠️  WARNING: STALE PLAN DETECTED!
   Plan Date: 2025-01-06
   Today's Date: 2025-01-07
   >>> RUN MARKET PLANNER FOR TODAY FIRST! <<<
============================================================

✅ Context Loaded: 2025-01-06 09:19:42
✅ Support Levels: 15
```

**What happens:**
- Bot runs but with WRONG levels from Day 1
- Signals will be based on stale levels
- **You need to stop the bot and run the planner!**

---

### ✅ FIXED: Mid-Day Restart After Planner Ran

**Scenario: Bot crashes at 2pm, you already ran planner in morning**

```bash
Day 2, 9:20 AM: python3 trading_bot_FIXED.py → 1 (Run Planner)
                Day 2 plan saved to JSON ✅

Day 2, 9:30 AM: python3 trading_bot_FIXED.py → 2 (Start Bot)
                Bot runs with Day 2 plan ✅

Day 2, 2:00 PM: Bot crashes

Day 2, 2:05 PM: python3 trading_bot_FIXED.py → 2 (Restart Bot)
                Bot loads from JSON → Gets Day 2 plan ✅
                No warning (plan is current) ✅
                Bot continues normally ✅
```

---

## Overnight Operation (Bot Never Stops)

**Best case: Bot runs continuously**

```bash
Day 1, 9:20 AM: Run Planner → Day 1 plan
Day 1, 9:30 AM: Start Bot → Loads Day 1 plan

Day 1 runs all day...

Day 2, 9:20 AM: Run Planner → Day 2 plan saved to JSON
Day 2, 9:30 AM: Bot detects new day automatically
                Bot prints: "🌅 NEW TRADING DAY DETECTED"
                Bot reloads from JSON → Gets Day 2 plan ✅
                Bot clears signal cooldowns ✅
                Bot continues running ✅
```

**Output when new day detected:**
```
============================================================
🌅 NEW TRADING DAY DETECTED: 2025-01-07
   Previous: 2025-01-06
   Reloading daily plan and clearing state...
============================================================

✅ Loaded plan for 2025-01-07: 15 SUP, 18 RES
✅ Previous Day POC: 6047.50
```

**If you FORGOT to run planner:**
```
============================================================
🌅 NEW TRADING DAY DETECTED: 2025-01-07
   Previous: 2025-01-06
   Reloading daily plan and clearing state...
============================================================

✅ Loaded plan for 2025-01-06: 15 SUP, 18 RES  ← STALE!
⚠️  WARNING: No plan available for new day!
   Run MarketPlanner to generate today's plan!
```

---

## Summary: Key Rules

### Rule 1: Always Run Planner Before Starting Bot
```bash
# Morning routine (EVERY trading day):
python3 trading_bot_FIXED.py → 1  # Generate today's plan
python3 trading_bot_FIXED.py → 2  # Start live bot
```

### Rule 2: If Bot Crashes Mid-Day
```bash
# Just restart it:
python3 trading_bot_FIXED.py → 2

# As long as you ran planner in the morning, it will load the correct plan
```

### Rule 3: Bot Detects Stale Plans
```bash
# If you see this warning:
⚠️  WARNING: STALE PLAN DETECTED!

# Then:
1. Stop the bot (Ctrl+C)
2. Run planner: python3 trading_bot_FIXED.py → 1
3. Restart bot: python3 trading_bot_FIXED.py → 2
```

### Rule 4: Leave Bot Running Overnight (Optional)
```bash
# Day 1 morning:
Run planner → Start bot → Leave running

# Day 2 morning:
Run planner → Bot auto-reloads

# This works indefinitely
```

---

## Automated Solutions

### Option A: Cron Job for Planner

Never manually run the planner again:

```bash
crontab -e

# Add this line:
20 9 * * 1-5 cd /home/user/jfdameyf && python3 trading_bot_FIXED.py <<< "1"
```

Now:
- Planner runs automatically at 9:20 AM every weekday
- Just start bot once, leave it running forever
- Bot auto-reloads plan each day at 9:30 AM

### Option B: Systemd Service

Run bot as a background service:

```bash
# /etc/systemd/system/es-trading-bot.service
[Unit]
Description=ES Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/user/jfdameyf
ExecStartPre=/usr/bin/python3 /home/user/jfdameyf/trading_bot_FIXED.py <<< "1"
ExecStart=/usr/bin/python3 /home/user/jfdameyf/trading_bot_FIXED.py <<< "2"
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable es-trading-bot
sudo systemctl start es-trading-bot
```

Bot runs automatically on system boot, restarts if it crashes.

---

## Troubleshooting

### "No signals firing in morning"

**Diagnosis:**
```bash
# While bot is running, check the logs or status output
# Look for:
Plan Date: 2025-01-06  ← If this is yesterday, you have stale plan!
Today's Date: 2025-01-07
```

**Fix:**
```bash
1. Stop bot (Ctrl+C)
2. Run planner
3. Restart bot
```

### "Bot shows stale plan warning at startup"

**This means:**
- You started the bot without running planner first
- Or the planner failed to run

**Fix:**
```bash
1. Stop bot (Ctrl+C)
2. Run planner: python3 trading_bot_FIXED.py → 1
3. Verify plan created:
   cat es_daily_context.json  # Check timestamp
4. Restart bot: python3 trading_bot_FIXED.py → 2
```

### "Bot doesn't detect new day"

**Check:**
- Is the bot actually running overnight? (ps aux | grep trading_bot)
- Did the planner run this morning? (ls -lt es_daily_context.json)
- Are there errors in the logs?

**Manual reload:**
```bash
# If bot is stuck with old plan:
1. Stop and restart bot - it will check plan at startup
2. Or wait - next time you call evaluate_market() it will check
```

---

## Best Practice: Daily Checklist

### Every Trading Day (Automated):

**9:15 AM - Pre-market:**
- [ ] Verify cron job ran (check es_daily_context.json timestamp)
- [ ] Or manually run planner if no cron

**9:25 AM - Just before open:**
- [ ] Check bot is running: `ps aux | grep trading_bot`
- [ ] If not running, start it
- [ ] Check for "STALE PLAN" warning
- [ ] Verify plan date matches today

**During trading hours:**
- [ ] Monitor signals firing
- [ ] If bot crashes, just restart it (plan already loaded)

**After market close:**
- [ ] Review signals that fired
- [ ] Check bot logs
- [ ] (Optional) Stop bot or leave running

---

## Files That Matter

**Plan Storage:**
- `es_daily_context.json` - ES plan
- `nq_daily_context.json` - NQ plan
- `gc_daily_context.json` - GC plan

**When planner runs, it updates these files**

**When bot starts:**
1. Loads from these files
2. Checks if plan date matches today
3. Warns if stale

**When new day detected:**
1. Reloads from these files
2. Uses whatever plan is there
3. Warns if still stale

**Therefore:**
Run planner before starting bot, or schedule it with cron!
