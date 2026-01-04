"""
INSTITUTIONAL LEVEL AUDITOR - IMPROVED VERSION
Adds critical missing features: POC/VAH/VAL, Previous Day Levels, Opening Range
"""

import databento as db
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time as dt_time
import pytz
import os
import sys

# --- CONFIGURATION ---
API_KEY = # will place your databento API key here
SYMBOL = "ES.v.0"
OUTPUT_FILE = "critical_levels_master_final.csv"
INPUT_FILE = "critical_levels_master_final.csv"
TICK_SIZE = 0.25
MIN_SINGLE_PRINT_TICKS = 8
ZONE_TOLERANCE = 0.50

# STRATEGY SETTINGS
RECENT_DAYS_THRESHOLD = 3
LIQUIDITY_MIN_SIZE = 400
LIQUIDITY_MIN_MINS = 10

# --- HELPER: ROBUST DELTA CALCULATION ---
def calculate_price_stats(df):
    if df.empty: return pd.DataFrame()
    df = df.copy()
    if 'size' not in df.columns or 'side' not in df.columns: return pd.DataFrame()

    side_array = df['side'].values
    if side_array.dtype.kind in 'SUO': is_buy = (side_array == 'A')
    else: is_buy = (side_array == 65)

    vol_array = df['size'].values
    signed_vol = np.where(is_buy, vol_array, -vol_array)
    df['signed_vol'] = signed_vol

    stats = df.groupby('price').agg(total_vol=('size', 'sum'), delta=('signed_vol', 'sum'))

    mask_corrupt = stats['delta'].abs() > stats['total_vol']
    if mask_corrupt.any(): stats.loc[mask_corrupt, 'delta'] = 0
    return stats

# --- NEW: VOLUME PROFILE CALCULATION ---
def calculate_volume_profile_levels(df, value_area_pct=0.70):
    """
    Generate POC, VAH, VAL for the session
    These are THE most important levels for institutional trading
    """
    if df.empty:
        return None

    # Group by price and sum volume
    vol_col = 'size' if 'size' in df.columns else 'volume'

    try:
        price_volume = df.groupby('price')[vol_col].sum().sort_index()
    except:
        return None

    if price_volume.empty:
        return None

    # Point of Control (highest volume price)
    poc_price = price_volume.idxmax()
    total_volume = price_volume.sum()
    target_va_volume = total_volume * value_area_pct

    # Build Value Area around POC
    current_volume = price_volume.loc[poc_price]
    vah_price = poc_price
    val_price = poc_price

    above_poc = price_volume.loc[poc_price:].iloc[1:]
    below_poc = price_volume.loc[:poc_price].iloc[:-1].sort_index(ascending=False)

    idx_above = 0
    idx_below = 0

    while current_volume < target_va_volume:
        if idx_above >= len(above_poc) and idx_below >= len(below_poc):
            break

        vol_above = above_poc.iloc[idx_above] if idx_above < len(above_poc) else 0
        vol_below = below_poc.iloc[idx_below] if idx_below < len(below_poc) else 0

        # Add the side with more volume
        if vol_above >= vol_below and idx_above < len(above_poc):
            current_volume += vol_above
            vah_price = above_poc.index[idx_above]
            idx_above += 1
        elif vol_below > vol_above and idx_below < len(below_poc):
            current_volume += vol_below
            val_price = below_poc.index[idx_below]
            idx_below += 1
        else:
            break

    print(f"      [VP] POC: {poc_price:.2f}, VAH: {vah_price:.2f}, VAL: {val_price:.2f}")

    return {
        'POC': float(poc_price),
        'VAH': float(vah_price),
        'VAL': float(val_price),
        'total_volume': int(total_volume)
    }

# --- NEW: PREVIOUS DAY LEVELS ---
def get_previous_day_reference_levels(current_date_obj, api_key):
    """
    Fetch previous trading day's key levels
    Returns: dict with PDH, PDL, PDC, or None
    """
    et_tz = pytz.timezone('America/New_York')

    # Look back up to 5 days to find previous trading day
    for days_back in range(1, 6):
        prev_date = current_date_obj - timedelta(days=days_back)

        # Skip weekends
        if prev_date.weekday() >= 5:
            continue

        start_dt = et_tz.localize(datetime.combine(prev_date, dt_time(9, 30)))
        end_dt = et_tz.localize(datetime.combine(prev_date, dt_time(16, 15)))

        try:
            df = get_databento_data(api_key, start_dt, end_dt, "trades")

            if df is not None and not df.empty:
                pdh = df['price'].max()
                pdl = df['price'].min()
                pdc = df['price'].iloc[-1]  # Last trade price

                print(f"      [PD] PDH: {pdh:.2f}, PDL: {pdl:.2f}, PDC: {pdc:.2f} ({prev_date.strftime('%Y-%m-%d')})")

                return {
                    'PDH': float(pdh),
                    'PDL': float(pdl),
                    'PDC': float(pdc),
                    'date': prev_date.strftime('%Y-%m-%d')
                }
        except:
            continue

    return None

# --- NEW: OPENING RANGE ---
def calculate_opening_range(df, or_minutes=30):
    """
    Calculate Opening Range High/Low
    Default: First 30 minutes (9:30-10:00 ET)
    """
    if df.empty:
        return None

    # Get opening range period
    or_start = df.between_time('09:30', '10:00').copy()

    if or_start.empty:
        return None

    orh = or_start['price'].max()
    orl = or_start['price'].min()
    open_price = or_start['price'].iloc[0]
    range_size = orh - orl

    print(f"      [OR] ORH: {orh:.2f}, ORL: {orl:.2f}, Range: {range_size:.2f}")

    return {
        'ORH': float(orh),
        'ORL': float(orl),
        'OPEN': float(open_price),
        'range_size': float(range_size)
    }

# --- PHASE 1: DATABASE MAINTENANCE ---
def load_and_clean_database(file_path):
    if not os.path.exists(file_path): return pd.DataFrame()
    print(f"   [MAINTENANCE] Loading {file_path}...")
    try: df = pd.read_csv(file_path)
    except: return pd.DataFrame()

    if df.empty: return df
    if 'trading_date' in df.columns: df = df.drop(columns=['trading_date'])
    if 'created_at' not in df.columns: df['created_at'] = pd.to_datetime(df['level_date']).dt.strftime('%Y-%m-%d 00:00:00')

    cols_check = ['volume', 'delta', 'strategy', 'category', 'hit_count', 'time_spent_mins']
    for c in cols_check:
        if c not in df.columns: df[c] = 0 if c in ['volume','delta'] else 0.0
    if 'last_hit_timestamp' not in df.columns: df['last_hit_timestamp'] = ""
    return df

def purge_dates_from_database(df, start_date_str, end_date_str):
    if df.empty: return df
    print(f"   [PURGE] Clearing data for range {start_date_str} to {end_date_str}...")
    try:
        s_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        e_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        df['temp_date'] = pd.to_datetime(df['level_date']).dt.date
        mask_keep = (df['temp_date'] < s_date) | (df['temp_date'] > e_date)
        return df[mask_keep].drop(columns=['temp_date'])
    except Exception as e:
        print(f"   [PURGE ERROR] {e}")
        return df

# --- PHASE 2: DATA FETCHING ---
def get_databento_data(api_key, start_dt, end_dt, schema):
    print(f"   Fetching {schema} data from {start_dt.strftime('%Y-%m-%d %H:%M')} to {end_dt.strftime('%H:%M')}...")
    client = db.Historical(key=api_key)

    try:
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3", schema=schema, stype_in="continuous",
            symbols=[SYMBOL], start=start_dt, end=end_dt
        ).to_df()

        if data.empty: return None
        if 'price' in data.columns and data['price'].mean() > 10000: data['price'] = data['price'] / 1e9
        data.index = pd.to_datetime(data.index, unit='ns')
        if data.index.tz is None: data.index = data.index.tz_localize('UTC')
        data.index = data.index.tz_convert(pytz.timezone('America/New_York'))
        return data

    except Exception as ex:
        if "dataset_unavailable_range" in str(ex):
             print(f"   [SKIP] Data not yet available.")
             return None
        print(f"   Error fetching data: {ex}"); return None

# --- PHASE 3: LEVEL GENERATION ---
def detect_liquidity_walls(df_full, min_size, min_duration_minutes):
    if df_full.empty: return pd.DataFrame()
    book_cols = [c for c in df_full.columns if 'sz_0' in c]
    if not book_cols: return pd.DataFrame()

    print(f"      [L2] Scanning for Liquidity Walls > {min_size} lots...")
    cols_to_use = book_cols + [c for c in df_full.columns if 'px_0' in c]
    df_resampled = df_full[cols_to_use].resample('1s').max().dropna()

    walls = {}

    def scan_side(sz_prefix, px_prefix, side_type):
        for i in range(10):
            sz_col = f"{sz_prefix}_0{i}"
            px_col = f"{px_prefix}_0{i}"
            mask = df_resampled[sz_col] >= min_size
            if not mask.any(): continue
            sightings = df_resampled.loc[mask, [px_col, sz_col]]
            for ts, row in sightings.iterrows():
                p = row[px_col]
                s = row[sz_col]
                if p not in walls:
                    walls[p] = {'start': ts, 'end': ts, 'max_sz': s, 'type': side_type}
                else:
                    if walls[p]['type'] == side_type and (ts - walls[p]['end']).total_seconds() < 60:
                        walls[p]['end'] = ts
                        walls[p]['max_sz'] = max(walls[p]['max_sz'], s)

    scan_side('bid_sz', 'bid_px', 'BID_WALL')
    scan_side('ask_sz', 'ask_px', 'ASK_WALL')

    levels = []
    for p, data in walls.items():
        dur = (data['end'] - data['start']).total_seconds() / 60.0
        if dur >= min_duration_minutes:
            score = 10.0 + (min(dur,60)/60)
            levels.append({'price': p, 'created_at': data['start'].strftime('%Y-%m-%d %H:%M:%S'), 'level_type': data['type'], 'category': 'LIQUIDITY', 'strategy': 'REVERSAL_ENTRY', 'engagement': 'LONG_DEFENSE' if 'BID' in data['type'] else 'SHORT_DEFENSE', 'volume': 0, 'delta': 0, 'score': score, 'note': f"Resting: {int(data['max_sz'])} lots for {int(dur)}m"})
    return pd.DataFrame(levels)

def identify_and_classify_levels(df):
    if df.empty: return pd.DataFrame()
    session_high, session_low = df['price'].max(), df['price'].min()
    range_size = session_high - session_low
    session_ts = df.index[-1].strftime('%Y-%m-%d %H:%M:%S')
    price_stats = calculate_price_stats(df)
    if price_stats.empty: return pd.DataFrame()
    levels = []
    vol_threshold = price_stats['total_vol'].quantile(0.95)
    magnet_threshold = price_stats['total_vol'].quantile(0.99)
    significant = price_stats[price_stats['total_vol'] >= vol_threshold]

    for price, row in significant.iterrows():
        vol = row['total_vol']; delta = row['delta']
        imbalance_ratio = abs(delta) / vol if vol > 0 else 0

        dist_edge = min(abs(session_high - price), abs(session_low - price))
        is_edge = dist_edge < (range_size * 0.15)
        is_massive = vol > magnet_threshold

        if is_edge:
            if is_massive and imbalance_ratio > 0.60:
                 cat, strat, mult = "MAGNET_ZONE", "TARGET_EXIT", 1.5
            elif is_massive:
                 cat, strat, mult = "SUPER_WALL", "REVERSAL_ENTRY", 3.0
            else:
                 cat, strat, mult = "WALL", "REVERSAL_ENTRY", 2.0

            if abs(price - session_low) < abs(price - session_high): l_type, eng = "BID_ABSORPTION", "LONG_DEFENSE"
            else: l_type, eng = "ASK_ABSORPTION", "SHORT_DEFENSE"

        elif is_massive:
            cat, strat, mult = "MAGNET", "TARGET_EXIT", 1.5; l_type, eng = "MAGNET", "NEUTRAL_ZONE"
        else: continue

        levels.append({'price': price, 'created_at': session_ts, 'level_type': l_type, 'engagement': eng, 'category': cat, 'strategy': strat, 'volume': int(vol), 'delta': int(delta), 'score': round(np.log1p(vol) * mult, 2), 'note': f"Vol: {int(vol)} | Ratio: {imbalance_ratio:.2f}"})
    return pd.DataFrame(levels)

def detect_tpo_single_prints(df):
    rth = df.between_time('09:30', '16:15').copy()
    if rth.empty: return pd.DataFrame()
    price_stats = calculate_price_stats(rth)
    tpo_periods = rth.groupby(pd.Grouper(freq='30min'))
    price_tpo_map = {}; price_exact_time_map = {}
    for period_start, period_data in tpo_periods:
        if period_data.empty: continue
        period_data = period_data.sort_index()
        first_touches = period_data.assign(ts_lookup=period_data.index).drop_duplicates(subset='price', keep='first').set_index('price')['ts_lookup']
        low_tick = int(period_data['price'].min() / TICK_SIZE)
        high_tick = int(period_data['price'].max() / TICK_SIZE)
        for tick in range(low_tick, high_tick + 1):
            price = tick * TICK_SIZE
            if price not in price_tpo_map:
                price_tpo_map[price] = set()
                if price in first_touches: price_exact_time_map[price] = first_touches[price].strftime('%Y-%m-%d %H:%M:%S')
                else: price_exact_time_map[price] = period_start.strftime('%Y-%m-%d %H:%M:%S')
            price_tpo_map[price].add(period_start)
    single_print_prices = sorted([p for p, periods in price_tpo_map.items() if len(periods) == 1])
    if not single_print_prices: return pd.DataFrame()
    blocks = []; current_block = [single_print_prices[0]]
    for p in single_print_prices[1:]:
        if abs(p - current_block[-1]) <= TICK_SIZE * 1.1: current_block.append(p)
        else: blocks.append(current_block); current_block = [p]
    blocks.append(current_block)
    levels = []; session_high, session_low = rth['price'].max(), rth['price'].min()
    for block in blocks:
        height = block[-1] - block[0]; tick_count = int(round(height / TICK_SIZE)) + 1
        block_start, block_end = block[0], block[-1]
        block_vol = 0; block_delta = 0
        for p in block:
            if p in price_stats.index: block_vol += price_stats.at[p, 'total_vol']; block_delta += price_stats.at[p, 'delta']
        is_buying_tail = abs(block_start - session_low) <= (TICK_SIZE * 1.1)
        is_selling_tail = abs(block_end - session_high) <= (TICK_SIZE * 1.1)
        exact_ts = price_exact_time_map.get(block_start, "")
        base = {'created_at': exact_ts, 'volume': int(block_vol), 'delta': int(block_delta), 'strategy': 'REVERSAL_ENTRY', 'category': 'SINGLE_PRINT'}
        if is_buying_tail and tick_count >= MIN_SINGLE_PRINT_TICKS: levels.append({**base, 'price': block_end, 'level_type': 'BUYING_TAIL', 'engagement': 'LONG_DEFENSE', 'score': 10.0, 'note': f"Tail ({tick_count}t)"})
        elif is_selling_tail and tick_count >= MIN_SINGLE_PRINT_TICKS: levels.append({**base, 'price': block_start, 'level_type': 'SELLING_TAIL', 'engagement': 'SHORT_DEFENSE', 'score': 10.0, 'note': f"Tail ({tick_count}t)"})
        elif tick_count >= 4: midpoint = round((block_start + block_end) / 2 / TICK_SIZE) * TICK_SIZE; levels.append({**base, 'price': midpoint, 'level_type': 'GAP_ZONE', 'engagement': 'NEUTRAL_ZONE', 'score': 7.5, 'note': f"Gap ({tick_count}t)"})
    return pd.DataFrame(levels)

def integrity_check_and_reclassify(df, levels_df):
    if levels_df.empty: return levels_df
    temp_df = df[['price']].copy()
    ohlc = temp_df['price'].resample('1min').ohlc().dropna()
    total_bars = ohlc.shape[0]
    if total_bars == 0: return levels_df
    final_levels = []
    for _, row in levels_df.iterrows():
        lvl = row['price']
        # Don't reclassify VP/Reference levels
        if row['category'] in ['VOLUME_PROFILE', 'REFERENCE', 'OPENING_RANGE']:
            final_levels.append(row)
            continue

        if "OVERNIGHT" in row['category'] or "LIQUIDITY" in row['category']: final_levels.append(row); continue
        upper, lower = lvl + 1.0, lvl - 1.0
        above_count = ohlc[ohlc['close'] > upper].shape[0]
        below_count = ohlc[ohlc['close'] < lower].shape[0]
        if (above_count / total_bars) > 0.20 and (below_count / total_bars) > 0.20:
            if row['strategy'] == 'REVERSAL_ENTRY': row['category'] = 'MAGNET'; row['strategy'] = 'TARGET_EXIT'; row['engagement'] = 'NEUTRAL_ZONE'; row['note'] += " [RECLASS: CHOP]"
        final_levels.append(row)
    return pd.DataFrame(final_levels)

def audit_historical_levels(existing_levels_df, current_day_df, current_date_obj):
    if existing_levels_df.empty or current_day_df.empty: return existing_levels_df
    existing_levels_df['created_at_dt'] = pd.to_datetime(existing_levels_df['created_at'], errors='coerce')
    mask_old = existing_levels_df['created_at_dt'].dt.date < current_date_obj
    day_high = current_day_df['price'].max() + ZONE_TOLERANCE; day_low = current_day_df['price'].min() - ZONE_TOLERANCE
    mask_range = (existing_levels_df['price'] >= day_low) & (existing_levels_df['price'] <= day_high)
    target_indices = existing_levels_df[mask_old & mask_range].index
    if len(target_indices) == 0: return existing_levels_df.drop(columns=['created_at_dt'])
    print(f"      [AUDIT] Updating stats for {len(target_indices)} historical levels...")
    prices = current_day_df['price'].values
    timestamps = current_day_df.index.values.astype(np.int64) // 10**9
    for idx in target_indices:
        level_price = existing_levels_df.at[idx, 'price']
        in_zone = np.abs(prices - level_price) <= ZONE_TOLERANCE
        if not np.any(in_zone): continue
        zone_indices = np.where(in_zone)[0]; added_seconds = 0
        if len(zone_indices) > 1:
            in_zone_ts = timestamps[zone_indices]; diffs = np.diff(in_zone_ts)
            valid_diffs = diffs[diffs < 60]; added_seconds = np.sum(valid_diffs)
        transitions = np.diff(in_zone.astype(int)); entries = np.sum(transitions == 1)
        if in_zone[0]: entries += 1
        existing_hits = float(existing_levels_df.at[idx, 'hit_count'])
        existing_time = float(existing_levels_df.at[idx, 'time_spent_mins'])
        existing_levels_df.at[idx, 'hit_count'] = existing_hits + entries
        existing_levels_df.at[idx, 'time_spent_mins'] = round(existing_time + (added_seconds / 60.0), 2)
        existing_levels_df.at[idx, 'last_hit_timestamp'] = current_day_df.index[zone_indices[-1]].strftime('%Y-%m-%d %H:%M:%S')
    return existing_levels_df.drop(columns=['created_at_dt'])

def filter_and_rank_levels(levels_df, max_levels=15):
    """
    IMPROVED: Category-aware merging with better tolerance
    """
    if levels_df.empty: return levels_df

    # Category-specific merge tolerances
    merge_tolerance = {
        'VOLUME_PROFILE': 0.5,   # Don't merge POC/VAH/VAL
        'REFERENCE': 0.5,         # Don't merge PDH/PDL
        'OPENING_RANGE': 0.75,    # Keep OR levels distinct
        'SINGLE_PRINT': 1.0,      # Can merge tails
        'LIQUIDITY': 0.75,        # Keep walls distinct
        'DEFAULT': 1.0
    }

    levels_df = levels_df.sort_values('score', ascending=False)
    merged_levels = {}

    for _, row in levels_df.iterrows():
        price = row['price']
        category = row['category']

        # Get tolerance for this category
        tolerance = merge_tolerance.get(category, merge_tolerance['DEFAULT'])

        found = False
        for existing in list(merged_levels.keys()):
            if abs(price - existing) <= tolerance:
                # Merge - keep higher score as primary
                if row['score'] > merged_levels[existing]['score']:
                    old_cat = merged_levels[existing]['category']
                    merged_levels[existing] = row.to_dict()
                    merged_levels[existing]['note'] += f" + {old_cat}"
                else:
                    merged_levels[existing]['note'] += f" + {category}"
                    merged_levels[existing]['score'] += (row['score'] * 0.2)
                found = True
                break

        if not found:
            merged_levels[price] = row.to_dict()

    final_list = list(merged_levels.values())
    result_df = pd.DataFrame(final_list)

    if not result_df.empty:
        max_s = result_df['score'].max()
        if max_s > 0:
            result_df['score'] = (result_df['score'] / max_s) * 10

    return result_df.sort_values('score', ascending=False).head(max_levels)

def analyze_session_context(df, critical_levels):
    if critical_levels.empty: return critical_levels
    if 'action' in df.columns: trades = df[df['action'] == 'T'].copy()
    else: trades = df.copy()
    enhanced = []
    for _, level in critical_levels.iterrows():
        # Don't change session context for VP/Reference levels
        if level['category'] in ['VOLUME_PROFILE', 'REFERENCE', 'OPENING_RANGE']:
            level['session_context'] = "KEY_LEVEL"
        elif "LIQUIDITY" in level['category']:
            level['session_context'] = "RESTING_ORDER"
        else:
            nearby = trades[(trades['price'] >= level['price']-0.25) & (trades['price'] <= level['price']+0.25)]
            if not nearby.empty:
                am = nearby.between_time('09:30', '12:00')['size'].sum()
                pm = nearby.between_time('13:30', '16:15')['size'].sum()
                level['session_context'] = "AM_SESSION" if am > pm else "PM_SESSION"
            else:
                ts = pd.to_datetime(level['created_at'])
                if 9 <= ts.hour < 16: level['session_context'] = "RTH/THIN"
                else: level['session_context'] = "ETH/PASSIVE"

        ts = pd.to_datetime(level['created_at'])
        is_closing_hour = ts.hour >= 15

        if level['session_context'] == "PM_SESSION" and not is_closing_hour and level['category'] not in ['VOLUME_PROFILE', 'REFERENCE']:
             level['score'] = level['score'] * 0.75
             level['note'] += " [PM_WEAK]"

        enhanced.append(level)
    return pd.DataFrame(enhanced)

def process_day_data(day_df, full_df, date_obj, use_l2, api_key):
    """
    IMPROVED: Now includes VP, Previous Day, and Opening Range
    """
    if 'action' in day_df.columns: trades_df = day_df[day_df['action'] == 'T'].copy()
    else: trades_df = day_df.copy()

    session_ts = trades_df.index[-1].strftime('%Y-%m-%d %H:%M:%S')

    # EXISTING LEVELS
    vol_levels = identify_and_classify_levels(trades_df)
    tail_levels = detect_tpo_single_prints(trades_df)

    liq_levels = pd.DataFrame()
    if use_l2: liq_levels = detect_liquidity_walls(day_df, LIQUIDITY_MIN_SIZE, LIQUIDITY_MIN_MINS)

    # NEW: VOLUME PROFILE
    vp_data = calculate_volume_profile_levels(trades_df)
    vp_levels = []
    if vp_data:
        vp_levels.append({
            'price': vp_data['POC'],
            'created_at': session_ts,
            'level_type': 'POC',
            'category': 'VOLUME_PROFILE',
            'strategy': 'REVERSAL_ENTRY',
            'engagement': 'MAGNETIC_ZONE',
            'volume': vp_data['total_volume'],
            'delta': 0,
            'score': 15.0,
            'note': f"POC - Point of Control"
        })

        vp_levels.append({
            'price': vp_data['VAH'],
            'created_at': session_ts,
            'level_type': 'VAH',
            'category': 'VOLUME_PROFILE',
            'strategy': 'REVERSAL_ENTRY',
            'engagement': 'SHORT_DEFENSE',
            'volume': 0,
            'delta': 0,
            'score': 12.0,
            'note': f"VAH - Value Area High"
        })

        vp_levels.append({
            'price': vp_data['VAL'],
            'created_at': session_ts,
            'level_type': 'VAL',
            'category': 'VOLUME_PROFILE',
            'strategy': 'REVERSAL_ENTRY',
            'engagement': 'LONG_DEFENSE',
            'volume': 0,
            'delta': 0,
            'score': 12.0,
            'note': f"VAL - Value Area Low"
        })

    # NEW: PREVIOUS DAY LEVELS
    pd_data = get_previous_day_reference_levels(date_obj, api_key)
    pd_levels = []
    if pd_data:
        pd_levels.append({
            'price': pd_data['PDH'],
            'created_at': session_ts,
            'level_type': 'PDH',
            'category': 'REFERENCE',
            'strategy': 'REVERSAL_ENTRY',
            'engagement': 'SHORT_DEFENSE',
            'volume': 0,
            'delta': 0,
            'score': 11.0,
            'note': f"Previous Day High ({pd_data['date']})"
        })

        pd_levels.append({
            'price': pd_data['PDL'],
            'created_at': session_ts,
            'level_type': 'PDL',
            'category': 'REFERENCE',
            'strategy': 'REVERSAL_ENTRY',
            'engagement': 'LONG_DEFENSE',
            'volume': 0,
            'delta': 0,
            'score': 11.0,
            'note': f"Previous Day Low ({pd_data['date']})"
        })

        pd_levels.append({
            'price': pd_data['PDC'],
            'created_at': session_ts,
            'level_type': 'PDC',
            'category': 'REFERENCE',
            'strategy': 'REVERSAL_ENTRY',
            'engagement': 'NEUTRAL_ZONE',
            'volume': 0,
            'delta': 0,
            'score': 9.0,
            'note': f"Previous Day Close ({pd_data['date']})"
        })

    # NEW: OPENING RANGE
    or_data = calculate_opening_range(trades_df)
    or_levels = []
    if or_data and or_data['range_size'] >= 2.0:  # Only if meaningful range
        or_levels.append({
            'price': or_data['ORH'],
            'created_at': session_ts,
            'level_type': 'ORH',
            'category': 'OPENING_RANGE',
            'strategy': 'BREAKOUT_ENTRY',
            'engagement': 'SHORT_DEFENSE',
            'volume': 0,
            'delta': 0,
            'score': 10.0,
            'note': f"Opening Range High (Range: {or_data['range_size']:.2f})"
        })

        or_levels.append({
            'price': or_data['ORL'],
            'created_at': session_ts,
            'level_type': 'ORL',
            'category': 'OPENING_RANGE',
            'strategy': 'BREAKOUT_ENTRY',
            'engagement': 'LONG_DEFENSE',
            'volume': 0,
            'delta': 0,
            'score': 10.0,
            'note': f"Opening Range Low (Range: {or_data['range_size']:.2f})"
        })

    # COMBINE ALL LEVELS
    return pd.concat([
        vol_levels,
        tail_levels,
        liq_levels,
        pd.DataFrame(vp_levels),
        pd.DataFrame(pd_levels),
        pd.DataFrame(or_levels)
    ], ignore_index=True)

def main():
    print("=== INSTITUTIONAL LEVEL AUDITOR V19.0 (IMPROVED) ===")
    print("    NEW: POC/VAH/VAL, Previous Day Levels, Opening Range")
    print()

    if "YOUR" in API_KEY: print("Set API Key"); return

    # --- AUTOMATION FIX: AUTO-SELECT DATES ---
    today = datetime.now().date()
    start_date = today - timedelta(days=5)
    end_date = today

    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')

    print(f"   [AUTO] Date Range: {start_str} to {end_str}")

    master_df = load_and_clean_database(INPUT_FILE)
    if not master_df.empty: master_df = purge_dates_from_database(master_df, start_str, end_str)

    cutoff_date = today - timedelta(days=RECENT_DAYS_THRESHOLD)
    et_tz = pytz.timezone('America/New_York')

    curr = start_date
    while curr <= end_date:
        day_str = curr.strftime('%Y-%m-%d')

        is_recent = (curr >= cutoff_date)
        schema = "mbp-10" if is_recent else "trades"
        use_l2 = is_recent

        print(f"\n--- Processing {day_str} ({schema}) ---")

        req_start = datetime.combine(curr, dt_time(9, 0))
        req_end = datetime.combine(curr, dt_time(16, 30))

        req_start_tz = et_tz.localize(req_start); req_end_tz = et_tz.localize(req_end)

        if req_start_tz.astimezone(pytz.utc) > datetime.now(pytz.utc):
            print("   [SKIP] Date is in the future.")
            curr += timedelta(days=1); continue

        df = get_databento_data(API_KEY, req_start_tz, req_end_tz, schema)

        if df is not None and not df.empty:
            audit_df = df
            if schema == 'mbp-10' and 'action' in df.columns: audit_df = df[df['action'] == 'T'].copy()

            if not master_df.empty:
                master_df = audit_historical_levels(master_df, audit_df, curr)

            # IMPROVED: Now passes api_key for previous day lookup
            new_levels = process_day_data(df, df, curr, use_l2, API_KEY)

            if not new_levels.empty:
                verified = integrity_check_and_reclassify(audit_df, new_levels)
                final = filter_and_rank_levels(verified, max_levels=15)  # Increased from 12
                context = analyze_session_context(audit_df, final)
                context['level_date'] = day_str; context['symbol'] = SYMBOL
                context['analysis_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                for c in ['hit_count','time_spent_mins','last_hit_timestamp']: context[c] = 0 if c!='last_hit_timestamp' else ""
                master_df = pd.concat([master_df, context], ignore_index=True)

        curr += timedelta(days=1)

    print(f"\nSaving database to {OUTPUT_FILE}...")
    cols = ['created_at', 'level_date', 'symbol', 'price', 'strategy', 'category', 'engagement', 'score', 'level_type', 'session_context', 'volume', 'delta', 'hit_count', 'time_spent_mins', 'last_hit_timestamp', 'note']
    for c in cols:
        if c not in master_df.columns: master_df[c] = ""
    master_df[cols].to_csv(OUTPUT_FILE, index=False)

    # Print summary
    print("\n" + "="*60)
    print("LEVEL GENERATION SUMMARY")
    print("="*60)

    if not master_df.empty:
        latest_date = master_df['level_date'].max()
        latest_levels = master_df[master_df['level_date'] == latest_date]

        print(f"\nLatest Day: {latest_date}")
        print(f"Total Levels: {len(latest_levels)}")

        print("\nBy Category:")
        for cat in latest_levels['category'].unique():
            count = len(latest_levels[latest_levels['category'] == cat])
            print(f"   {cat}: {count}")

        print("\nTop 10 Levels by Score:")
        top10 = latest_levels.nlargest(10, 'score')[['price', 'category', 'level_type', 'score', 'note']]
        for _, lvl in top10.iterrows():
            print(f"   {lvl['price']:7.2f} | {lvl['category']:17s} | {lvl['level_type']:20s} | {lvl['score']:4.1f} | {lvl['note'][:40]}")

    print("\n" + "="*60)
    print("Done.")

if __name__ == "__main__":
    main()
