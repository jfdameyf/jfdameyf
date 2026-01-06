"""
NQ Trading Bot - FIXED VERSION
Incorporates all ES optimizations scaled for NQ volatility
"""

import pandas as pd
import numpy as np
import databento as db
import yfinance as yf
import joblib
import json
import os
import sys
import requests
from datetime import datetime, time, timedelta
import pytz
import warnings
import logging

# ==============================================================================
# ⚙️ CONFIGURATION
# ==============================================================================

API_KEY = # will place your databento API key here
DISCORD_WEBHOOK_URL = # will place your discord webhook url here

# --- STRATEGY SETTINGS ---
ENABLE_POC_FILTER = False

# --- SYMBOLOGY (NQ) ---
SYMBOL = "NQ.c.0"
LIVE_SYMBOL = "NQ.c.0"

NY_TZ = pytz.timezone('America/New_York')

# Files
CRITICAL_LEVELS_FILE = "critical_levels_NQ_master.csv"
OUTPUT_FILE = "nq_daily_context.json"
STATE_FILE = "nq_strategy_state.json"
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Heuristics (NQ Specific - ~4x ES volatility)
BUFFER_PCT = 0.20
MIN_LEVEL_SEPARATION = 15.0  # NQ levels need more separation

warnings.filterwarnings('ignore')

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'{LOG_DIR}/nq_bot_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)

# ==============================================================================
# 1️⃣ STRATEGY MANAGER (NQ - ES Logic Adapted)
# ==============================================================================
class StrategyManager:
    def __init__(self):
        self.context = self.load_latest_context()
        self.pd_poc = self.context.get('pd_profile', {}).get('POC', None) if self.context else None
        self.use_poc_filter = ENABLE_POC_FILTER

        # ✅ NQ VOLATILITY SCALING (4x ES base)
        self.POC_SWEET_SPOT_MIN = 40.0   # ES: 10
        self.POC_SWEET_SPOT_MAX = 80.0   # ES: 20
        self.POC_DANGER_THRESHOLD = 200.0 # ES: 50

        # Load active recapture monitors
        self.active_monitors = self.load_state()

        if not self.use_poc_filter:
            logging.info("NOTE: POC Distance Filter is DISABLED.")

    def load_latest_context(self):
        """Loads the most recent plan with validation"""
        if not os.path.exists(OUTPUT_FILE):
            logging.error(f"ERROR: {OUTPUT_FILE} not found. Run MarketPlanner first.")
            return {}
        try:
            with open(OUTPUT_FILE, 'r') as f:
                content = f.read()
                if not content.strip():
                    logging.error("ERROR: Context file is empty!")
                    return {}

                data = json.loads(content)
                if not data:
                    return {}

                last_date = list(data.keys())[-1]
                plan = data[last_date]

                if plan is None:
                    logging.error(f"ERROR: Plan for {last_date} is corrupted (NULL).")
                    return {}

                # Validate freshness
                plan_date = datetime.strptime(last_date, '%Y-%m-%d').date()
                today = datetime.now(NY_TZ).date()
                age_days = (today - plan_date).days

                if age_days > 1:
                    logging.warning(f"WARNING: Plan is {age_days} days old!")

                # Validate required fields
                required = ['current_price', 'levels', 'pd_profile']
                missing = [f for f in required if f not in plan]
                if missing:
                    logging.error(f"ERROR: Plan missing fields: {missing}")
                    return {}

                logging.info(f"Strategy Loaded NQ Plan for: {last_date}")
                return plan
        except Exception as e:
            logging.error(f"ERROR: Error loading context: {e}")
            return {}

    def load_state(self):
        """Loads active monitors with cleanup"""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    data = json.load(f)

                # Clean up stale monitors (>2 days old)
                cutoff = (datetime.now() - timedelta(days=2)).timestamp()
                cleaned = {k: v for k, v in data.items()
                          if v.get('timestamp', cutoff + 1) > cutoff}

                if len(cleaned) < len(data):
                    logging.info(f"Cleaned {len(data) - len(cleaned)} stale monitors")

                logging.info(f"Resumed: Tracking {len(cleaned)} NQ recaptures.")
                return cleaned
            except:
                return {}
        return {}

    def save_state(self):
        """Saves monitors with timestamps"""
        try:
            # Add timestamp to monitors
            for monitor in self.active_monitors.values():
                if 'timestamp' not in monitor:
                    monitor['timestamp'] = datetime.now().timestamp()

            with open(STATE_FILE, 'w') as f:
                json.dump(self.active_monitors, f, indent=4)
        except Exception as e:
            logging.warning(f"WARNING: Failed to save state: {e}")

    def get_poc_distance_modifier(self, current_price):
        """POC distance logic (NQ scaled)"""
        if self.pd_poc is None:
            return True, 1.0, "No POC Data"

        dist = abs(current_price - self.pd_poc)

        if dist > self.POC_DANGER_THRESHOLD:
            return False, 0.0, f"🚫 DANGER ZONE: Too far from POC ({dist:.1f} pts)."
        elif self.POC_SWEET_SPOT_MIN <= dist <= self.POC_SWEET_SPOT_MAX:
            return True, 1.25, f"✨ SWEET SPOT: {dist:.1f} pts from POC."
        else:
            return True, 1.0, f"Standard Distance ({dist:.1f} pts)."

    def get_zone_number(self, level_dict):
        """Extract zone number"""
        zone_str = level_dict.get('zone', 'Zone 1')
        if "Zone 1" in zone_str: return 1
        if "Zone 2" in zone_str: return 2
        if "Zone 3" in zone_str: return 3
        if "Zone 4" in zone_str: return 4
        return 1

    def check_entry_signal(self, current_price, level_info):
        """
        ✅ IMPROVED: Added proximity checks (scaled for NQ)
        """
        zone = self.get_zone_number(level_info)
        level_price = level_info['price']

        l_type = level_info.get('type', 'SUP' if current_price > level_price else 'RES')

        modifier = 1.0
        reason = "Standard"

        # Calculate distance
        distance = abs(current_price - level_price)

        logging.debug(f"Checking {l_type} @ {level_price:.2f} | Zone {zone} | Current: {current_price:.2f} | Dist: {distance:.2f}")

        # POC CHECK
        if self.use_poc_filter:
            tradable, modifier, reason = self.get_poc_distance_modifier(current_price)
            if not tradable:
                return "NO_TRADE", 0.0, reason
        else:
            reason = "POC Check Disabled"

        # ZONES 1 & 2: Responsive (with proximity check)
        # ✅ NQ SCALING: 6pts for Zone 1, 12pts for Zone 2 (vs ES 2/4)
        if zone in [1, 2]:
            proximity_threshold = 6.0 if zone == 1 else 12.0

            if distance <= proximity_threshold:
                return "IMMEDIATE_ENTRY", modifier, f"Zone {zone}: Responsive @ {distance:.1f}pts. {reason}"
            else:
                return "WAIT", 0.0, f"Zone {zone}: Waiting for approach (dist: {distance:.1f})"

        # ZONES 3 & 4: Recapture
        elif zone in [3, 4]:
            signal = self.detect_level_recapture(current_price, level_price, l_type)

            if signal == "TRIGGER":
                return "RECAPTURE_ENTRY", modifier, f"Zone {zone}: Recaptured! {reason}"
            elif signal == "WAITING_FOR_RECLAIM":
                return "WAIT", 0.0, f"Zone {zone}: Monitoring... {reason}"
            else:
                return "WAIT", 0.0, f"Zone {zone}: Too far / No setup."

        return "NO_TRADE", 0.0, "Unknown Zone"

    def detect_level_recapture(self, current_price, level_price, level_type):
        """
        ✅ IMPROVED: Relaxed thresholds (NQ scaled from ES)
        ES: 0.75pt min, 15pt blowout, 0.50 buffer
        NQ: 3pt min, 50pt blowout, 2pt buffer (4x scaling)
        """
        key = f"{level_price:.2f}_{level_type}"
        state_changed = False

        if key not in self.active_monitors:
            self.active_monitors[key] = {'state': 'WATCHING', 'extension': 0.0}
            state_changed = True

        monitor = self.active_monitors[key]
        current_state = monitor['state']
        result_signal = "WAIT"

        # ✅ NQ THRESHOLDS (4x ES)
        MIN_EXTENSION = 3.0      # ES: 0.75
        BLOWOUT_THRESHOLD = 50.0 # ES: 15
        RECLAIM_BUFFER = 2.0     # ES: 0.50

        # SUPPORT (Long)
        if level_type == 'SUP':
            violation_dist = level_price - current_price

            if current_state == 'WATCHING':
                if current_price < level_price:
                    monitor['state'] = 'VIOLATED'
                    monitor['extension'] = float(violation_dist)
                    state_changed = True
                    result_signal = "WAITING_FOR_RECLAIM"
                    logging.info(f"Monitor {key}: VIOLATED (ext: {violation_dist:.2f})")

            elif current_state == 'VIOLATED':
                if current_price < level_price:
                    if violation_dist > monitor['extension']:
                        monitor['extension'] = float(violation_dist)
                        state_changed = True

                    if violation_dist > BLOWOUT_THRESHOLD:
                        monitor['state'] = 'FAILED'
                        state_changed = True
                        result_signal = "CANCEL"
                        logging.info(f"Monitor {key}: FAILED (blowout: {violation_dist:.2f})")
                    else:
                        result_signal = "WAITING_FOR_RECLAIM"

                # RECLAIM TRIGGER
                elif current_price > level_price + RECLAIM_BUFFER:
                    if monitor['extension'] >= MIN_EXTENSION:
                        monitor['state'] = 'TRIGGERED'
                        logging.info(f"SIGNAL - Monitor {key}: TRIGGERED! (ext: {monitor['extension']:.2f})")
                        self.active_monitors.pop(key)
                        self.save_state()
                        return "TRIGGER"
                    else:
                        monitor['state'] = 'WATCHING'
                        monitor['extension'] = 0.0
                        state_changed = True
                        result_signal = "RESET"
                        logging.info(f"Monitor {key}: RESET (insufficient extension)")

        # RESISTANCE (Short)
        elif level_type == 'RES':
            violation_dist = current_price - level_price

            if current_state == 'WATCHING':
                if current_price > level_price:
                    monitor['state'] = 'VIOLATED'
                    monitor['extension'] = float(violation_dist)
                    state_changed = True
                    result_signal = "WAITING_FOR_RECLAIM"
                    logging.info(f"Monitor {key}: VIOLATED (ext: {violation_dist:.2f})")

            elif current_state == 'VIOLATED':
                if current_price > level_price:
                    if violation_dist > monitor['extension']:
                        monitor['extension'] = float(violation_dist)
                        state_changed = True

                    if violation_dist > BLOWOUT_THRESHOLD:
                        monitor['state'] = 'FAILED'
                        state_changed = True
                        result_signal = "CANCEL"
                        logging.info(f"Monitor {key}: FAILED (blowout: {violation_dist:.2f})")
                    else:
                        result_signal = "WAITING_FOR_RECLAIM"

                # RECLAIM TRIGGER
                elif current_price < level_price - RECLAIM_BUFFER:
                    if monitor['extension'] >= MIN_EXTENSION:
                        monitor['state'] = 'TRIGGERED'
                        logging.info(f"SIGNAL - Monitor {key}: TRIGGERED! (ext: {monitor['extension']:.2f})")
                        self.active_monitors.pop(key)
                        self.save_state()
                        return "TRIGGER"
                    else:
                        monitor['state'] = 'WATCHING'
                        monitor['extension'] = 0.0
                        state_changed = True
                        result_signal = "RESET"
                        logging.info(f"Monitor {key}: RESET (insufficient extension)")

        if state_changed:
            self.save_state()

        return result_signal


# ==============================================================================
# 2️⃣ MARKET PLANNER (NQ Adaptation)
# ==============================================================================
class MarketPlanner:
    def __init__(self):
        if "YOUR_DATABENTO" in API_KEY:
            print("❌ ERROR: Please set your Databento API Key.")
            sys.exit(1)

        self.client = db.Historical(API_KEY)
        self.levels_df = self.load_levels()
        self.models = {}
        self.simulated_now = None

        print("ℹ️  Using NQ Fallback Logic (No ML Model)")

    @staticmethod
    def calculate_volume_profile_levels(df, value_area_pct=0.70):
        if df.empty: return None, None, None
        vol_col = 'volume' if 'volume' in df.columns else 'vol'
        try:
            price_volume = df.groupby('close')[vol_col].sum().sort_index()
        except KeyError:
            return None, None, None

        if price_volume.empty: return None, None, None

        poc_price = price_volume.idxmax()
        total_volume = price_volume.sum()
        target_va_volume = total_volume * value_area_pct
        current_volume = price_volume.loc[poc_price]

        vah_price, val_price = poc_price, poc_price
        above_poc = price_volume.loc[poc_price:].iloc[1:]
        below_poc = price_volume.loc[:poc_price].iloc[:-1].sort_index(ascending=False)

        idx_above, idx_below = 0, 0
        while current_volume < target_va_volume and (idx_above < len(above_poc) or idx_below < len(below_poc)):
            vol_above = above_poc.iloc[idx_above] if idx_above < len(above_poc) else 0
            vol_below = below_poc.iloc[idx_below] if idx_below < len(below_poc) else 0

            if vol_above >= vol_below and idx_above < len(above_poc):
                current_volume += vol_above; vah_price = above_poc.index[idx_above]; idx_above += 1
            elif vol_below > vol_above and idx_below < len(below_poc):
                current_volume += vol_below; val_price = below_poc.index[idx_below]; idx_below += 1
            else: break

        return float(poc_price), float(vah_price), float(val_price)

    def load_levels(self):
        try:
            df = pd.read_csv(CRITICAL_LEVELS_FILE)
            if 'score' not in df.columns: df['score'] = 1.0
            df['category'] = df['category'].fillna('')
            df['level_type'] = df['level_type'].fillna('')
            return df
        except:
            return pd.DataFrame()

    def calibrate_thresholds(self):
        print(f"   🧮 Calibrating NQ Order Flow...")
        end_dt = self.simulated_now - timedelta(minutes=60)
        start_dt = end_dt - timedelta(days=7)
        try:
            trades = self.client.timeseries.get_range(
                dataset="GLBX.MDP3", schema="trades", symbols=[SYMBOL],
                stype_in="continuous", start=start_dt, end=end_dt
            ).to_df()
            if trades.empty: raise Exception("No trade data")
            trades.index = trades.index.tz_convert(NY_TZ)
            rth = trades.between_time('09:30', '16:00').copy()
            rth['size'] = rth['size'].astype('int64'); rth['vol'] = rth['size']
            rth['delta'] = np.where(rth['side']=='B', rth['size'], -rth['size'])
            bars = rth.resample('1min').agg({'vol': 'sum', 'delta': 'sum'}).dropna()
            bars = bars[bars['vol'] > 0]
            quantiles = [0.75, 0.90, 0.95, 0.99]
            return {'vol': bars['vol'].quantile(quantiles).astype(int).to_dict(),
                    'delta': bars['delta'].abs().quantile(quantiles).astype(int).to_dict(), 'ratio': 0.30}
        except Exception as e:
            return {'vol': {0.90: 5000, 0.99: 12000}, 'delta': {0.90: 1500, 0.99: 4000}, 'ratio': 0.30}

    def get_market_data(self):
        available_end = (self.simulated_now - timedelta(minutes=60)).isoformat()
        start_dt = (self.simulated_now - timedelta(days=10)).replace(hour=0, minute=0)
        try:
            nq_df = self.client.timeseries.get_range(
                dataset="GLBX.MDP3", schema="ohlcv-1m", symbols=[SYMBOL],
                stype_in="continuous", start=start_dt, end=available_end
            ).to_df()
            if nq_df.index.tz is None: nq_df.index = nq_df.index.tz_localize('UTC')
            nq_df = nq_df.tz_convert(NY_TZ)
        except Exception as e:
            return None, None
        return nq_df, None

    def get_previous_day_profile(self, df):
        """Smart Date Finder (Handles Sundays/Holidays)"""
        current_date = self.simulated_now.date()
        past_data = df[df.index.date < current_date]

        if past_data.empty:
            return None

        unique_dates = np.sort(np.unique(past_data.index.date))[::-1]

        for check_date in unique_dates:
            day_slice = past_data[past_data.index.date == check_date]
            rth_slice = day_slice.between_time('09:30', '16:00')

            if not rth_slice.empty:
                poc, vah, val = self.calculate_volume_profile_levels(rth_slice)
                if poc is not None:
                    return {'date': check_date.strftime('%Y-%m-%d'), 'POC': poc, 'VAH': vah, 'VAL': val}

        return None

    def determine_context_edge(self, current_price, pd_profile):
        if not pd_profile or pd_profile['POC'] is None:
            return "Unknown", "Insufficient Data", 0
        vah = pd_profile['VAH']; val = pd_profile['VAL']
        if val <= current_price <= vah: return "Inside Value", "⚖️ Balance (Mean Reversion).", 0
        elif current_price < val: return "Below Value", "📉 Gap Down. Buy Support (+EV).", 1
        elif current_price > vah: return "Above Value", "📈 Gap Up. Trend Risk!", 2
        return "Unknown", "Neutral", 0

    def get_smart_levels(self, current_price, predicted_range):
        if self.levels_df.empty: return {}
        total_reach = predicted_range * (1 + BUFFER_PCT)
        candidates = self.levels_df.copy()
        candidates['dist'] = abs(candidates['price'] - current_price)
        active_df = candidates[candidates['dist'] <= total_reach].copy()
        res_df = active_df[active_df['price'] > current_price].copy()
        sup_df = active_df[active_df['price'] < current_price].copy()

        def get_levels_hybrid(df, direction_label):
            if df.empty: return []
            try:
                bins = np.linspace(0, total_reach, num=5)
                labels = ['Zone 1', 'Zone 2', 'Zone 3', 'Zone 4']
                df['zone'] = pd.cut(df['dist'], bins=bins, labels=labels, include_lowest=True)
                selected_levels = []
                for zone in labels:
                    zone_levels = df[df['zone'] == zone]
                    if zone_levels.empty: continue
                    sorted_levels = zone_levels.sort_values('score', ascending=False)
                    zone_picks = []
                    for _, row in sorted_levels.iterrows():
                        if len(zone_picks) >= 2: break
                        collision = False
                        for pick in zone_picks:
                            if abs(row['price'] - pick['price']) < MIN_LEVEL_SEPARATION:
                                collision = True; break
                        if not collision:
                            zone_picks.append({
                                'price': row['price'], 'category': row['category'],
                                'score': round(row['score'], 2), 'dist': round(row['dist'], 2), 'zone': zone
                            })
                    selected_levels.extend(zone_picks)
                ascending = True if direction_label == 'RES' else False
                return sorted(selected_levels, key=lambda x: x['price'], reverse=not ascending)
            except:
                return []

        res_levels = get_levels_hybrid(res_df, 'RES')
        sup_levels = get_levels_hybrid(sup_df, 'SUP')
        res_fmt = [f"{l['price']:.2f} [{l['zone']}] {l['category']}" for l in res_levels]
        sup_fmt = [f"{l['price']:.2f} [{l['zone']}] {l['category']}" for l in sup_levels]
        return {'res_distributed': res_fmt, 'sup_distributed': sup_fmt, 'raw_res': res_levels, 'raw_sup': sup_levels}

    def send_discord_report(self, plan):
        if not DISCORD_WEBHOOK_URL or "https" not in DISCORD_WEBHOOK_URL: return
        color = 0x99aab5
        context_str = plan.get('context_location', 'Unknown')
        if "Below Value" in context_str: color = 0x00ff00
        elif "Above Value" in context_str: color = 0xffa500
        elif "Inside Value" in context_str: color = 0xffff00

        def fmt_lvl(lvl_list): return "\n".join(lvl_list) if lvl_list else "None Found"
        embed = {
            "title": f"📅 NQ Plan ({SYMBOL}): {self.simulated_now.strftime('%Y-%m-%d')}",
            "description": f"**Price:** {plan['current_price']:.2f} | **Range:** +/- {plan['predicted_range']:.2f}",
            "color": color,
            "fields": [
                {"name": f"🧩 Context: {context_str}", "value": plan.get('context_insight', 'N/A'), "inline": False},
                {"name": "🔴 Resistance", "value": fmt_lvl(reversed(plan['levels']['res_distributed'])), "inline": True},
                {"name": "🟢 Support", "value": fmt_lvl(plan['levels']['sup_distributed']), "inline": True}
            ]
        }
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})
        except:
            pass

    def generate_plan_for_date(self, target_date_obj):
        self.simulated_now = NY_TZ.localize(datetime.combine(target_date_obj, time(9, 0)))
        print(f"\n🕰️  Processing NQ Plan for: {self.simulated_now.strftime('%Y-%m-%d')}")
        nq_hist, _ = self.get_market_data()
        if nq_hist is None or nq_hist.empty:
            print("❌ No Data Found.")
            return

        thresh_data = self.calibrate_thresholds()
        pd_profile = self.get_previous_day_profile(nq_hist)

        # NQ Range Estimate (~4x ES)
        pred_range = 220.0

        current_price = nq_hist['close'].iloc[-1]
        ctx_loc, ctx_insight, _ = self.determine_context_edge(current_price, pd_profile)
        print(f"   🧩 Context: {ctx_loc} -> {ctx_insight}")
        levels = self.get_smart_levels(current_price, pred_range)

        plan = {
            'timestamp': self.simulated_now.strftime('%Y-%m-%d %H:%M:%S'),
            'current_price': current_price, 'predicted_range': float(pred_range),
            'thresholds': thresh_data, 'pd_profile': pd_profile,
            'context_location': ctx_loc, 'context_insight': ctx_insight, 'levels': levels
        }
        self.save_plan_to_json(plan)
        if self.simulated_now.date() == datetime.now(NY_TZ).date(): self.send_discord_report(plan)

    def save_plan_to_json(self, plan):
        plan_date_key = self.simulated_now.strftime('%Y-%m-%d')
        full_data = {}
        if os.path.exists(OUTPUT_FILE):
            try:
                with open(OUTPUT_FILE, 'r') as f:
                    content = f.read()
                    if content.strip(): full_data = json.loads(content)
            except json.JSONDecodeError:
                full_data = {}
        full_data[plan_date_key] = plan
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(full_data, f, indent=4)
        print(f"   💾 Saved to {OUTPUT_FILE}")

    def run(self):
        print("--- 📅 NQ Market Planner ---")
        user_input = input("Enter Date (YYYY-MM-DD) or [Enter] for Today: ").strip()
        target_dates = [datetime.now(NY_TZ).date()] if not user_input else [datetime.strptime(user_input, "%Y-%m-%d").date()]
        for date_obj in target_dates:
            self.generate_plan_for_date(date_obj)


# ==============================================================================
# 3️⃣ LIVE BOT (NQ - With ES Improvements)
# ==============================================================================
class LiveBot:
    def __init__(self):
        print("\n🤖 INITIALIZING NQ LIVE BOT...")
        print(f"   POC Filter: {ENABLE_POC_FILTER}")
        self.strategy = StrategyManager()
        self.active_signals = {}  # Time-based deduplication
        self.live_client = db.Live(API_KEY)
        self.tick_count = 0
        self.last_status_time = datetime.now()
        self.current_trading_day = datetime.now(NY_TZ).date()  # Track current day for reload

        # ✅ FIX: Validate plan is for today's date
        if self.strategy.context:
            plan_date_str = self.strategy.context.get('timestamp', '')
            if plan_date_str:
                try:
                    plan_date = datetime.strptime(plan_date_str.split()[0], '%Y-%m-%d').date()
                    if plan_date != self.current_trading_day:
                        print(f"\n{'='*60}")
                        print(f"⚠️  WARNING: STALE PLAN DETECTED!")
                        print(f"   Plan Date: {plan_date}")
                        print(f"   Today's Date: {self.current_trading_day}")
                        print(f"   >>> RUN MARKET PLANNER FOR TODAY FIRST! <<<")
                        print(f"{'='*60}\n")
                        # Don't exit - allow user to decide, but make it very clear
                except:
                    pass  # If we can't parse date, continue anyway

    def print_bot_status(self):
        """Print diagnostic status"""
        print("\n" + "="*60)
        print(f"🤖 NQ BOT STATUS @ {datetime.now(NY_TZ).strftime('%H:%M:%S')}")
        print("="*60)

        if self.strategy.context:
            price = self.strategy.context.get('current_price', 'N/A')
            print(f"📊 Plan Date: {self.strategy.context.get('timestamp', 'Unknown')}")
            print(f"💰 Reference Price: {price}")

            sup_count = len(self.strategy.context.get('levels', {}).get('raw_sup', []))
            res_count = len(self.strategy.context.get('levels', {}).get('raw_res', []))
            print(f"📍 Active Levels: {sup_count} SUP, {res_count} RES")
        else:
            print("❌ NO CONTEXT LOADED")

        print(f"👁️  Active Monitors: {len(self.strategy.active_monitors)}")
        for key, monitor in list(self.strategy.active_monitors.items())[:5]:
            print(f"   {key}: {monitor['state']} (ext: {monitor.get('extension', 0):.2f})")

        print(f"🔥 Unique Signals: {len(self.active_signals)}")
        print(f"📊 Ticks: {self.tick_count}")
        print("="*60 + "\n")

    def evaluate_market(self, current_price):
        """
        ✅ IMPROVED: Only check levels within range
        """
        # Check if new trading day started
        today = datetime.now(NY_TZ).date()

        if today != self.current_trading_day:
            print(f"
{'='*60}")
            print(f"🌅 NEW TRADING DAY DETECTED: {today}")
            print(f"   Previous: {self.current_trading_day}")
            print(f"   Reloading daily plan and clearing state...")
            print(f"{'='*60}
")

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
                print("   Run MarketPlanner to generate today's plan!
")


        scan_range = 80.0  # NQ: 80pts (ES was 20pts - 4x scaling)

        if 'raw_sup' in self.strategy.context.get('levels', {}):
            for level in self.strategy.context['levels']['raw_sup']:
                if abs(current_price - level['price']) <= scan_range:
                    level['type'] = 'SUP'
                    self.process_signal(current_price, level)

        if 'raw_res' in self.strategy.context.get('levels', {}):
            for level in self.strategy.context['levels']['raw_res']:
                if abs(current_price - level['price']) <= scan_range:
                    level['type'] = 'RES'
                    self.process_signal(current_price, level)

    def process_signal(self, price, level):
        action, mod, msg = self.strategy.check_entry_signal(price, level)

        if action == "IMMEDIATE_ENTRY":
            self.alert_signal(level['price'], "LIMIT / RESPONSIVE", mod, msg)
        elif action == "RECAPTURE_ENTRY":
            self.alert_signal(price, "MARKET / RECAPTURE", mod, msg)

    def alert_signal(self, price, order_type, size_mod, message):
        """
        ✅ FIXED: Time-based deduplication (60-min cooldown for NQ)
        """
        signal_key = f"{price:.2f}_{order_type}"
        current_time = datetime.now()

        # 60-minute cooldown (optimized from ES results)
        if signal_key in self.active_signals:
            last_fired = self.active_signals[signal_key]
            if (current_time - last_fired).seconds < 3600:  # 60 minutes
                return

        print(f"\n{'='*60}")
        print(f"🚀 NQ SIGNAL FIRED @ {price:.2f}")
        print(f"   Type: {order_type}")
        print(f"   Size: {size_mod}x")
        print(f"   Info: {message}")
        print(f"   Time: {current_time.strftime('%H:%M:%S')}")
        print("="*60 + "\n")

        self.active_signals[signal_key] = current_time

        logging.info(f"SIGNAL: {order_type} @ {price:.2f} | Size: {size_mod}x | {message}")

    def start(self):
        """
        ✅ IMPROVED: Pre-flight checks and corrected price conversion
        """
        # Pre-flight diagnostics
        print("\n" + "="*60)
        print("🔍 PRE-FLIGHT DIAGNOSTICS")
        print("="*60)

        if not self.strategy.context:
            print("❌ FATAL: No context loaded. Run Market Planner first!")
            return

        levels = self.strategy.context.get('levels', {})
        sup_levels = levels.get('raw_sup', [])
        res_levels = levels.get('raw_res', [])

        print(f"✅ Context Loaded: {self.strategy.context.get('timestamp')}")
        print(f"✅ Support Levels: {len(sup_levels)}")
        for lvl in sup_levels[:3]:
            print(f"   - {lvl['price']:.2f} [{lvl['zone']}]")

        print(f"✅ Resistance Levels: {len(res_levels)}")
        for lvl in res_levels[:3]:
            print(f"   - {lvl['price']:.2f} [{lvl['zone']}]")

        if not sup_levels and not res_levels:
            print("❌ FATAL: No levels defined!")
            return

        print(f"✅ POC Filter: {'ENABLED' if self.strategy.use_poc_filter else 'DISABLED'}")
        if self.strategy.pd_poc:
            print(f"✅ Previous Day POC: {self.strategy.pd_poc:.2f}")

        print("="*60 + "\n")

        print(f"📡 Connecting to NQ Live Stream ({LIVE_SYMBOL})...")
        print("   Waiting for setups...\n")

        try:
            self.live_client.subscribe(
                dataset="GLBX.MDP3",
                schema="trades",
                stype_in="continuous",
                symbols=[LIVE_SYMBOL]
            )

            for record in self.live_client:
                if hasattr(record, 'price') and hasattr(record, 'hd'):
                    # ✅ FIX: Correct price conversion
                    price = record.price / 1e9  # DIVIDE not multiply!

                    # Debug first few prices
                    if self.tick_count < 5:
                        print(f"DEBUG: Raw: {record.price}, Converted: {price:.2f}")

                    self.tick_count += 1
                    self.evaluate_market(price)

                    # Status every 5 minutes
                    if (datetime.now() - self.last_status_time).seconds >= 300:
                        self.print_bot_status()
                        self.last_status_time = datetime.now()
        self.current_trading_day = datetime.now(NY_TZ).date()  # Track current day for reload

        except KeyboardInterrupt:
            print("\n🛑 NQ Bot Stopped.")
            self.print_bot_status()


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    print("==========================================")
    print("   NQ ALGO ASSISTANT (FIXED)   ")
    print("==========================================")
    print("1. Run NQ Planner (Generate Daily Plan)")
    print("2. Run NQ Live Signals (Real-time)")

    choice = input("Select Mode [1/2]: ").strip()

    if choice == "1":
        MarketPlanner().run()
    elif choice == "2":
        bot = LiveBot()
        bot.start()
    else:
        print("Invalid choice.")
