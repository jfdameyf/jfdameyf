import pandas as pd
import numpy as np
import databento as db
import yfinance as yf
import joblib
import json
import os
import sys
import shutil
import requests
from datetime import datetime, time, timedelta
import pytz
import warnings
import asyncio
import threading
import logging

# ==============================================================================
# ⚙️ CONFIGURATION
# ==============================================================================

# ⚠️ ACTION REQUIRED: Replace with your actual key
API_KEY = ""  # will place your databento API key here
DISCORD_WEBHOOK_URL = ""  # will place your discord webhook url here

# --- STRATEGY SETTINGS ---
# Set to False to disable the "Danger Zone" (>50pts) filter
ENABLE_POC_FILTER = False

# --- SYMBOLOGY ---
SYMBOL = "ES.c.0"  # Continuous contract for history/backtest
LIVE_SYMBOL = "ES.c.0" # Live Front Month

NY_TZ = pytz.timezone('America/New_York')

# Files
CRITICAL_LEVELS_FILE = "critical_levels_master_final.csv"
OUTPUT_FILE = "daily_context_v2.json"
STATE_FILE = "strategy_state.json"
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Heuristics
BUFFER_PCT = 0.20
MIN_LEVEL_SEPARATION = 4.0

warnings.filterwarnings('ignore')

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(f'{LOG_DIR}/bot_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)

# ==============================================================================
# 1️⃣ STRATEGY MANAGER (The Logic Engine)
# ==============================================================================
class StrategyManager:
    def __init__(self):
        self.context = self.load_latest_context()
        self.pd_poc = self.context.get('pd_profile', {}).get('POC', None) if self.context else None
        self.use_poc_filter = ENABLE_POC_FILTER

        # Heuristics - RELAXED for better signal generation
        self.POC_SWEET_SPOT_MIN = 10.0
        self.POC_SWEET_SPOT_MAX = 20.0
        self.POC_DANGER_THRESHOLD = 50.0

        # Load active recapture monitors (Persistence)
        self.active_monitors = self.load_state()

        if not self.use_poc_filter:
            logging.info("NOTE: POC Distance Filter is DISABLED. All Zones active regardless of trend extension.")

    def load_latest_context(self):
        """Loads the most recent plan from the JSON file with validation."""
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

                # Check if the plan is None (Corrupted)
                if plan is None:
                    logging.error(f"ERROR: Plan for {last_date} is corrupted (NULL). Using empty context.")
                    return {}

                # ✅ NEW: Validate freshness
                plan_date = datetime.strptime(last_date, '%Y-%m-%d').date()
                today = datetime.now(NY_TZ).date()
                age_days = (today - plan_date).days

                if age_days > 1:
                    logging.warning(f"WARNING: Plan is {age_days} days old! Run MarketPlanner.")

                # ✅ NEW: Validate required fields
                required = ['current_price', 'levels', 'pd_profile']
                missing = [f for f in required if f not in plan]
                if missing:
                    logging.error(f"ERROR: Plan missing required fields: {missing}")
                    return {}

                logging.info(f"Strategy Loaded Plan for: {last_date}")
                return plan
        except Exception as e:
            logging.error(f"ERROR: Error loading context: {e}")
            return {}

    def load_state(self):
        """Loads active monitors from disk with cleanup."""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    data = json.load(f)

                # ✅ NEW: Clean up stale monitors (older than 2 days)
                cutoff = (datetime.now() - timedelta(days=2)).timestamp()
                cleaned = {k: v for k, v in data.items()
                          if v.get('timestamp', cutoff + 1) > cutoff}

                if len(cleaned) < len(data):
                    logging.info(f"Cleaned {len(data) - len(cleaned)} stale monitors")

                logging.info(f"Resumed Bot State: Tracking {len(cleaned)} potential recaptures.")
                return cleaned
            except:
                return {}
        return {}

    def save_state(self):
        """Saves current monitors to disk with timestamps."""
        try:
            # ✅ NEW: Add timestamp to monitors
            for monitor in self.active_monitors.values():
                if 'timestamp' not in monitor:
                    monitor['timestamp'] = datetime.now().timestamp()

            with open(STATE_FILE, 'w') as f:
                json.dump(self.active_monitors, f, indent=4)
        except Exception as e:
            logging.warning(f"WARNING: Failed to save state: {e}")

    def get_poc_distance_modifier(self, current_price):
        """
        Applies the "Danger Zone" (>50pts) logic.
        """
        if self.pd_poc is None:
            return True, 1.0, "No POC Data"

        dist = abs(current_price - self.pd_poc)

        # 1. DANGER ZONE (> 50 pts)
        if dist > self.POC_DANGER_THRESHOLD:
            return False, 0.0, f"🚫 DANGER ZONE: Too far from POC ({dist:.1f} pts). Trend likely."

        # 2. SWEET SPOT (10-20 pts)
        elif self.POC_SWEET_SPOT_MIN <= dist <= self.POC_SWEET_SPOT_MAX:
            return True, 1.25, f"✨ SWEET SPOT: {dist:.1f} pts from POC."

        # 3. STANDARD
        else:
            return True, 1.0, f"Standard Distance ({dist:.1f} pts)."

    def get_zone_number(self, level_dict):
        """Extracts zone number directly from your MarketPlanner JSON structure."""
        zone_str = level_dict.get('zone', 'Zone 1')
        if "Zone 1" in zone_str: return 1
        if "Zone 2" in zone_str: return 2
        if "Zone 3" in zone_str: return 3
        if "Zone 4" in zone_str: return 4
        return 1

    def check_entry_signal(self, current_price, level_info):
        """
        Decides entry type based on Zone with IMPROVED proximity checks.
        """
        zone = self.get_zone_number(level_info)
        level_price = level_info['price']

        l_type = level_info.get('type', 'SUP' if current_price > level_price else 'RES')

        modifier = 1.0
        reason = "Standard"

        # Calculate distance for proximity checks
        distance = abs(current_price - level_price)

        logging.debug(f"Checking {l_type} @ {level_price:.2f} | Zone {zone} | Current: {current_price:.2f} | Dist: {distance:.2f}")

        # --- 1. POC CHECK (Conditional) ---
        if self.use_poc_filter:
            tradable, modifier, reason = self.get_poc_distance_modifier(current_price)
            if not tradable:
                return "NO_TRADE", 0.0, reason
        else:
            reason = "POC Check Disabled"

        # --- 2. ZONE LOGIC ---

        # ZONES 1 & 2: Responsive / Touch Trading
        # ✅ FIX: Added proximity check
        if zone in [1, 2]:
            # Must be within reasonable distance to trigger
            proximity_threshold = 2.0 if zone == 1 else 4.0

            if distance <= proximity_threshold:
                return "IMMEDIATE_ENTRY", modifier, f"Zone {zone}: Responsive Trade @ {distance:.1f}pts. {reason}"
            else:
                return "WAIT", 0.0, f"Zone {zone}: Waiting for approach (dist: {distance:.1f})"

        # ZONES 3 & 4: Recapture Required
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
        Logic: Violation -> Extension -> Reclaim.
        ✅ IMPROVED: Relaxed thresholds for better signal generation
        """
        key = f"{level_price:.2f}_{level_type}"
        state_changed = False

        if key not in self.active_monitors:
            self.active_monitors[key] = {'state': 'WATCHING', 'extension': 0.0}
            state_changed = True

        monitor = self.active_monitors[key]
        current_state = monitor['state']
        result_signal = "WAIT"

        # ✅ IMPROVED: Relaxed thresholds
        MIN_EXTENSION = 0.75  # Reduced from 1.5
        BLOWOUT_THRESHOLD = 15.0  # Increased from 10.0
        RECLAIM_BUFFER = 0.50  # Increased from 0.25

        # --- LOGIC FOR SUPPORT (Long) ---
        if level_type == 'SUP':
            violation_dist = level_price - current_price

            if current_state == 'WATCHING':
                if current_price < level_price:
                    monitor['state'] = 'VIOLATED'
                    monitor['extension'] = float(violation_dist)
                    state_changed = True
                    result_signal = "WAITING_FOR_RECLAIM"
                    logging.info(f"Monitor {key}: VIOLATED (extension: {violation_dist:.2f})")

            elif current_state == 'VIOLATED':
                if current_price < level_price:
                    if violation_dist > monitor['extension']:
                        monitor['extension'] = float(violation_dist)
                        state_changed = True

                    if violation_dist > BLOWOUT_THRESHOLD:  # Blowout (Trend)
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
                        logging.info(f"SIGNAL - Monitor {key}: TRIGGERED! (extension: {monitor['extension']:.2f})")
                        self.active_monitors.pop(key)
                        self.save_state()
                        return "TRIGGER"
                    else:
                        monitor['state'] = 'WATCHING'
                        monitor['extension'] = 0.0
                        state_changed = True
                        result_signal = "RESET"
                        logging.info(f"Monitor {key}: RESET (insufficient extension)")

        # --- LOGIC FOR RESISTANCE (Short) ---
        elif level_type == 'RES':
            violation_dist = current_price - level_price

            if current_state == 'WATCHING':
                if current_price > level_price:
                    monitor['state'] = 'VIOLATED'
                    monitor['extension'] = float(violation_dist)
                    state_changed = True
                    result_signal = "WAITING_FOR_RECLAIM"
                    logging.info(f"Monitor {key}: VIOLATED (extension: {violation_dist:.2f})")

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
                        logging.info(f"SIGNAL - Monitor {key}: TRIGGERED! (extension: {monitor['extension']:.2f})")
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
# 2️⃣ MARKET PLANNER (The Pre-Market Context Generator)
# ==============================================================================
class MarketPlanner:
    def __init__(self):
        if "YOUR_DATABENTO" in API_KEY:
            print("❌ ERROR: Please paste your Databento API Key in the configuration section.")
            sys.exit(1)

        self.client = db.Historical(API_KEY)
        self.levels_df = self.load_levels()
        self.models = {}
        self.simulated_now = None

        try:
            self.models['s1_range'] = joblib.load("model_stage1_range_xgb.pkl")
            print("🧠 Models Loaded Successfully.")
        except Exception as e:
            print(f"⚠️ Models not found: {e}. Using Fallback logic.")

    @staticmethod
    def calculate_volume_profile_levels(df, value_area_pct=0.70):
        if df.empty: return None, None, None

        vol_col = 'volume' if 'volume' in df.columns else 'vol'
        try:
            price_volume = df.groupby('close')[vol_col].sum().sort_index()
        except KeyError: return None, None, None

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
            df['category'] = df['category'].fillna(''); df['level_type'] = df['level_type'].fillna('')
            return df
        except: return pd.DataFrame()

    def calibrate_thresholds(self):
        print(f"   🧮 Calibrating Order Flow on ({SYMBOL})...")
        end_dt = self.simulated_now - timedelta(minutes=60)
        start_dt = end_dt - timedelta(days=7)
        try:
            trades = self.client.timeseries.get_range(
                dataset="GLBX.MDP3", schema="trades", symbols=[SYMBOL],
                stype_in="continuous", start=start_dt, end=end_dt
            ).to_df()
            if trades.empty: raise Exception("No trade data returned")
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
            return {'vol': {0.90: 3000, 0.99: 8000}, 'delta': {0.90: 800, 0.99: 2000}, 'ratio': 0.30}

    def get_market_data(self):
        available_end = (self.simulated_now - timedelta(minutes=60)).isoformat()
        start_dt = (self.simulated_now - timedelta(days=10)).replace(hour=0, minute=0)
        try:
            es_df = self.client.timeseries.get_range(
                dataset="GLBX.MDP3", schema="ohlcv-1m", symbols=[SYMBOL],
                stype_in="continuous", start=start_dt, end=available_end
            ).to_df()
            if es_df.index.tz is None: es_df.index = es_df.index.tz_localize('UTC')
            es_df = es_df.tz_convert(NY_TZ)
        except Exception as e: return None, None

        vix = pd.DataFrame()
        try:
            vix = yf.download("^VIX", start=start_dt, end=self.simulated_now + timedelta(days=1), progress=False)
            if isinstance(vix.columns, pd.MultiIndex): vix = vix.xs('Close', level='Price', axis=1)
            else: vix = vix[['Close']]
            vix.columns = ['VIX_Close']
            if vix.index.tz is None: vix.index = vix.index.tz_localize(NY_TZ, ambiguous='naive')
            else: vix.index = vix.index.tz_convert(NY_TZ)
            vix = vix[vix.index <= self.simulated_now]
        except: pass
        return es_df, vix

    def process_features(self, es_df, vix_df):
        daily = es_df.resample('D').agg({'high':'max','low':'min','close':'last'}).dropna()
        daily['tr'] = np.maximum(daily['high']-daily['low'], np.abs(daily['high']-daily['close'].shift(1)))
        current_atr = daily['tr'].rolling(14).mean().iloc[-1] if not daily.empty else 35.0
        latest_vix = vix_df['VIX_Close'].iloc[-1] if not vix_df.empty else 15.0

        try:
            if daily.index[-1].date() == self.simulated_now.date():
                prev_close = daily['close'].iloc[-2]; prev_high = daily['high'].iloc[-2]; prev_low = daily['low'].iloc[-2]
            else:
                prev_close = daily['close'].iloc[-1]; prev_high = daily['high'].iloc[-1]; prev_low = daily['low'].iloc[-1]
            pd_range = prev_high - prev_low
            current_price = es_df['close'].iloc[-1]
            gap_points = current_price - prev_close
            gap_norm = gap_points / current_atr if current_atr > 0 else 0.0
        except: pd_range = 40.0; gap_norm = 0.0

        globex_start = self.simulated_now.replace(hour=18, minute=0, second=0, microsecond=0) - timedelta(days=1)
        on_session = es_df[es_df.index >= globex_start]
        if not on_session.empty: on_range = on_session['high'].max() - on_session['low'].min(); on_vol = on_session['volume'].sum()
        else: on_range = 20.0; on_vol = 100000.0

        return {'PD_RTH_Atr_14': float(current_atr), 'PD_RTH_Range': float(pd_range),
                'PD_VIX_Close': float(latest_vix), 'ON_Range': float(on_range),
                'ON_Volume': float(on_vol), 'Gap_Norm': float(gap_norm)}

    def get_previous_day_profile(self, df):
        current_date = self.simulated_now.date()
        past_data = df[df.index.date < current_date]

        if past_data.empty:
            print(f"   ⚠️ DEBUG: No history found before {current_date}.")
            return None

        unique_dates = np.sort(np.unique(past_data.index.date))[::-1]

        if len(unique_dates) == 0:
            print("   ⚠️ DEBUG: Unique dates list is empty.")
            return None

        for check_date in unique_dates:
            day_slice = past_data[past_data.index.date == check_date]
            rth_slice = day_slice.between_time('09:30', '16:00')

            if not rth_slice.empty:
                poc, vah, val = self.calculate_volume_profile_levels(rth_slice)

                if poc is not None:
                    return {'date': check_date.strftime('%Y-%m-%d'), 'POC': poc, 'VAH': vah, 'VAL': val}

        print("   ❌ DEBUG: Reviewed recent history but found NO valid RTH days.")
        return None

    def determine_context_edge(self, current_price, pd_profile):
        if not pd_profile or pd_profile['POC'] is None: return "Unknown", "Insufficient Data", 0
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
            except: return []

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
            "title": f"📅 ES Plan ({SYMBOL}): {self.simulated_now.strftime('%Y-%m-%d')}",
            "description": f"**Price:** {plan['current_price']:.2f} | **Range:** +/- {plan['predicted_range']:.2f}",
            "color": color,
            "fields": [
                {"name": f"🧩 Context: {context_str}", "value": plan.get('context_insight', 'N/A'), "inline": False},
                {"name": "🔴 Resistance", "value": fmt_lvl(reversed(plan['levels']['res_distributed'])), "inline": True},
                {"name": "🟢 Support", "value": fmt_lvl(plan['levels']['sup_distributed']), "inline": True}
            ]
        }
        try: requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})
        except: pass

    def generate_plan_for_date(self, target_date_obj):
        self.simulated_now = NY_TZ.localize(datetime.combine(target_date_obj, time(9, 0)))
        print(f"\n🕰️  Processing Plan for: {self.simulated_now.strftime('%Y-%m-%d')}")
        es_hist, vix_hist = self.get_market_data()
        if es_hist is None or es_hist.empty: return

        thresh_data = self.calibrate_thresholds()
        feats = self.process_features(es_hist, vix_hist)
        pd_profile = self.get_previous_day_profile(es_hist)

        pred_range = 55.0; trend_prob = 0.30
        if 's1_range' in self.models:
            try:
                X = pd.DataFrame([feats])[['ON_Range', 'PD_RTH_Atr_14', 'PD_RTH_Range', 'PD_VIX_Close', 'ON_Volume', 'Gap_Norm']]
                pred_range = self.models['s1_range'].predict(X)[0]
            except: pass

        current_price = es_hist['close'].iloc[-1]
        ctx_loc, ctx_insight, _ = self.determine_context_edge(current_price, pd_profile)
        print(f"   🧩 Context: {ctx_loc} -> {ctx_insight}")
        levels = self.get_smart_levels(current_price, pred_range)

        plan = {
            'timestamp': self.simulated_now.strftime('%Y-%m-%d %H:%M:%S'),
            'current_price': current_price, 'predicted_range': float(pred_range),
            'trend_prob': float(trend_prob), 'thresholds': thresh_data,
            'pd_profile': pd_profile, 'context_location': ctx_loc,
            'context_insight': ctx_insight, 'levels': levels
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
            except json.JSONDecodeError: full_data = {}
        full_data[plan_date_key] = plan
        with open(OUTPUT_FILE, 'w') as f: json.dump(full_data, f, indent=4)
        print(f"   💾 Saved to {OUTPUT_FILE}")

    def run(self):
        print("--- 📅 Market Planner ---")
        user_input = input("Enter Single Date (YYYY-MM-DD) or [Enter] for Today: ").strip()
        target_dates = [datetime.now(NY_TZ).date()] if not user_input else [datetime.strptime(user_input, "%Y-%m-%d").date()]
        for date_obj in target_dates: self.generate_plan_for_date(date_obj)

# ==============================================================================
# 3️⃣ LIVE BOT (The Signal Generator)
# ==============================================================================
class LiveBot:
    def __init__(self):
        print("\n🤖 INITIALIZING LIVE SIGNAL BOT...")
        print(f"   POC Filter Enabled: {ENABLE_POC_FILTER}")
        self.strategy = StrategyManager()
        self.active_signals = {}  # Now stores timestamp instead of True
        self.live_client = db.Live(API_KEY)
        self.tick_count = 0
        self.last_price = None  # Track for delta calculation
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
        """Print diagnostic status every 5 minutes"""
        print("\n" + "="*60)
        print(f"🤖 BOT STATUS @ {datetime.now(NY_TZ).strftime('%H:%M:%S')}")
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
        for key, monitor in list(self.strategy.active_monitors.items())[:5]:  # Show first 5
            print(f"   {key}: {monitor['state']} (ext: {monitor.get('extension', 0):.2f})")

        print(f"🔥 Unique Signals This Session: {len(self.active_signals)}")
        print(f"📊 Ticks Processed: {self.tick_count}")
        print("="*60 + "\n")

    def evaluate_market(self, current_price):
        """
        ✅ IMPROVED: Only check levels within reasonable distance
        ✅ FIX: Detect new trading day and reload plan
        """
        # Check if new trading day started
        today = datetime.now(NY_TZ).date()

        if today != self.current_trading_day:
            print(f"\n{'='*60}")
            print(f"🌅 NEW TRADING DAY DETECTED: {today}")
            print(f"   Previous: {self.current_trading_day}")
            print(f"   Reloading daily plan and clearing state...")
            print(f"{'='*60}\n")

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
                print("   Run MarketPlanner to generate today's plan!\n")

        scan_range = 20.0  # Only check levels within 20 points

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
            direction = "LONG" if level['type'] == 'SUP' else "SHORT"
            self.alert_signal(level['price'], "LIMIT / RESPONSIVE", direction, mod, msg)

        elif action == "RECAPTURE_ENTRY":
            direction = "LONG" if level['type'] == 'SUP' else "SHORT"
            self.alert_signal(price, "MARKET / RECAPTURE", direction, mod, msg)

    def alert_signal(self, price, order_type, direction, size_mod, message):
        """
        ✅ FIXED: Time-based deduplication instead of permanent blocking
        """
        signal_key = f"{price:.2f}_{order_type}_{direction}"
        current_time = datetime.now()

        # Only suppress duplicates within 5 minutes
        if signal_key in self.active_signals:
            last_fired = self.active_signals[signal_key]
            if (current_time - last_fired).total_seconds() < 300:  # FIX: use total_seconds()
                return

        # Emoji for direction
        direction_emoji = "🟢" if direction == "LONG" else "🔴"

        print(f"\n{'='*60}")
        print(f"🚀 {direction_emoji} {direction} SIGNAL @ {price:.2f}")
        print(f"   Type: {order_type}")
        print(f"   Size: {size_mod}x")
        print(f"   Info: {message}")
        print(f"   Time: {current_time.strftime('%H:%M:%S')}")
        print("="*60 + "\n")

        self.active_signals[signal_key] = current_time

        # Also log to file
        logging.info(f"SIGNAL: {direction} {order_type} @ {price:.2f} | Size: {size_mod}x | {message}")

        # Send Discord alert
        self.send_discord_alert(price, order_type, direction, size_mod, message, current_time)

    def send_discord_alert(self, price, order_type, direction, size_mod, message, timestamp):
        """Send signal alert to Discord webhook"""
        if not DISCORD_WEBHOOK_URL or "https" not in DISCORD_WEBHOOK_URL:
            return

        # Color based on direction
        color = 0x00ff00 if direction == "LONG" else 0xff0000  # Green for LONG, Red for SHORT

        # Emoji for visual clarity
        direction_emoji = "🟢" if direction == "LONG" else "🔴"

        embed = {
            "title": f"🚀 {direction_emoji} ES {direction} SIGNAL",
            "description": f"**Entry Price:** {price:.2f}\n**Type:** {order_type}\n**Size:** {size_mod}x",
            "color": color,
            "fields": [
                {"name": "📊 Details", "value": message, "inline": False},
                {"name": "⏰ Time", "value": timestamp.strftime('%Y-%m-%d %H:%M:%S ET'), "inline": False}
            ],
            "footer": {"text": "ES Trading Bot • Live Signal"}
        }

        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})
        except:
            pass  # Silently fail if Discord webhook errors

    def start(self):
        """
        ✅ IMPROVED: Pre-flight checks and better price handling
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
            print("❌ FATAL: No levels defined. Check critical_levels file.")
            return

        print(f"✅ POC Filter: {'ENABLED' if self.strategy.use_poc_filter else 'DISABLED'}")
        if self.strategy.pd_poc:
            print(f"✅ Previous Day POC: {self.strategy.pd_poc:.2f}")

        print("="*60 + "\n")

        print(f"📡 Connecting to Databento Live Stream ({LIVE_SYMBOL})...")
        print("   Waiting for setups...\n")

        try:
            self.live_client.subscribe(
                dataset="GLBX.MDP3",
                schema="trades",
                stype_in="continuous",
                symbols=[LIVE_SYMBOL]
            )

            for record in self.live_client:
                # Only process trade messages with valid prices
                if hasattr(record, 'price') and record.price > 0:
                    # For GLBX.MDP3 trades, price is in fixed-point with 9 decimal precision
                    price = record.price / 1e9  # Convert from fixed-point
                    current_time = datetime.now(NY_TZ).strftime('%H:%M:%S')

                    # Calculate delta from last price
                    delta = 0.0
                    if self.last_price is not None:
                        delta = price - self.last_price

                    # Show first 30 ticks to verify continuous stream
                    if self.tick_count < 30:
                        delta_str = f"{delta:+.2f}" if self.last_price is not None else "  --  "
                        print(f"[{current_time}] Price: {price:.2f}  |  Δ: {delta_str}")

                    # Update tracking
                    self.last_price = price
                    self.tick_count += 1
                    self.evaluate_market(price)

                    # Print status every 5 minutes
                    if (datetime.now() - self.last_status_time).seconds >= 300:
                        self.print_bot_status()
                        self.last_status_time = datetime.now()

        except KeyboardInterrupt:
            print("\n🛑 Bot Stopped.")
            self.print_bot_status()

# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    print("==========================================")
    print("   ES ALGO ASSISTANT: PLANNER & SIGNALS   ")
    print("==========================================")
    print("1. Run Market Planner (Generate Daily Plan)")
    print("2. Run Live Signals (Real-time Feed)")

    choice = input("Select Mode [1/2]: ").strip()

    if choice == "1":
        MarketPlanner().run()
    elif choice == "2":
        bot = LiveBot()
        bot.start()
    else:
        print("Invalid choice.")
