"""
INSTITUTIONAL LEVEL AUDITOR - ENHANCED VERSION (GC GOLD FUTURES)
Focuses on improving QUALITY of tick-data-derived levels
No theoretical constructs - only objective, evidence-based levels

Adapted for GC (Gold Futures)
- Symbol: GC.c.0
- Tick size: 0.10 (10 cents per troy ounce)
- Point value: $100/point (vs ES $50, NQ $20)
- RTH hours: 8:20 AM - 1:30 PM ET (main pit session)
- Typical daily range: $10-30
- Lower volume than ES/NQ - adjusted thresholds accordingly
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
SYMBOL = "GC.c.0"

# Output file
OUTPUT_FILE = "critical_levels_master_enhanced_GC.csv"
INPUT_FILE = "critical_levels_master_enhanced_GC.csv"
TICK_SIZE = 0.10  # Gold: 10 cents per tick
MIN_SINGLE_PRINT_TICKS = 10  # Adjusted for smaller tick size
ZONE_TOLERANCE = 0.20  # Tighter tolerance for gold

# STRATEGY SETTINGS
RECENT_DAYS_THRESHOLD = 3
LIQUIDITY_MIN_SIZE = 75  # GC: Much lower volume than ES/NQ
LIQUIDITY_MIN_MINS = 10

# ENHANCED SETTINGS
MULTI_DAY_PERSISTENCE_THRESHOLD = 3  # Level must appear 3+ days to be "persistent"
PERFORMANCE_BOOST_THRESHOLD = 5      # Levels hit 5+ times get major boost
STRONG_TAIL_VOLUME_THRESHOLD = 2500  # GC: Adjusted for gold volume profile

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

# --- NEW: DELTA EXHAUSTION DETECTION ---
def detect_delta_exhaustion_zones(df):
    """
    Find prices where cumulative delta flipped - objective evidence of exhaustion
    This is DATA-DRIVEN, not theoretical
    """
    if df.empty:
        return pd.DataFrame()

    price_stats = calculate_price_stats(df)
    if price_stats.empty:
        return pd.DataFrame()

    print(f"      [DELTA] Scanning for exhaustion zones...")

    # Sort by price and calculate cumulative delta
    price_stats = price_stats.sort_index()
    price_stats['cumulative_delta'] = price_stats['delta'].cumsum()

    # Rolling average to smooth noise
    window = 10
    price_stats['delta_trend'] = price_stats['cumulative_delta'].rolling(window, center=True).mean()

    # Find where trend changes direction (inflection points)
    price_stats['trend_direction'] = np.sign(price_stats['delta_trend'].diff())
    price_stats['flip'] = price_stats['trend_direction'].diff().abs()

    # Flips are where direction changed (value = 2)
    flip_zones = price_stats[price_stats['flip'] == 2.0]

    if flip_zones.empty:
        return pd.DataFrame()

    levels = []
    session_ts = df.index[-1].strftime('%Y-%m-%d %H:%M:%S')

    # Only keep significant flips (high volume)
    vol_threshold = price_stats['total_vol'].quantile(0.80)

    for price, row in flip_zones.iterrows():
        vol = row['total_vol']
        delta = row['delta']

        if vol < vol_threshold:
            continue  # Skip low-volume flips

        # Determine exhaustion type based on delta sign
        if delta < 0:
            exhaustion_type = "BUYING_EXHAUSTION"
            engagement = "SHORT_DEFENSE"
            note = f"Buying exhausted: {delta:+.0f}Δ"
        else:
            exhaustion_type = "SELLING_EXHAUSTION"
            engagement = "LONG_DEFENSE"
            note = f"Selling exhausted: {delta:+.0f}Δ"

        levels.append({
            'price': price,
            'created_at': session_ts,
            'level_type': exhaustion_type,
            'category': 'DELTA_EXHAUSTION',
            'strategy': 'REVERSAL_ENTRY',
            'engagement': engagement,
            'volume': int(vol),
            'delta': int(delta),
            'score': 8.5,
            'note': note
        })

    print(f"      [DELTA] Found {len(levels)} exhaustion zones")
    return pd.DataFrame(levels)

# --- ENHANCED: SINGLE PRINT STRENGTH CLASSIFICATION ---
def classify_single_print_strength(block, price_stats, session_high, session_low, block_time):
    """
    Rate tail strength by multiple objective factors
    Not all tails are equal!
    """
    block_start = block[0]
    block_end = block[-1]
    tick_count = int(round((block_end - block_start) / TICK_SIZE)) + 1

    # Calculate volume and delta at this tail
    block_vol = 0
    block_delta = 0
    for p in block:
        if p in price_stats.index:
            block_vol += price_stats.at[p, 'total_vol']
            block_delta += price_stats.at[p, 'delta']

    # Factor 1: Volume strength
    if block_vol > STRONG_TAIL_VOLUME_THRESHOLD:
        volume_score = 10
        vol_strength = "HIGH"
    elif block_vol > STRONG_TAIL_VOLUME_THRESHOLD / 2:
        volume_score = 7
        vol_strength = "MODERATE"
    else:
        volume_score = 4
        vol_strength = "LOW"

    # Factor 2: Delta imbalance
    delta_ratio = abs(block_delta) / block_vol if block_vol > 0 else 0
    if delta_ratio > 0.6:
        delta_score = 10
        delta_strength = "STRONG"
    elif delta_ratio > 0.4:
        delta_score = 7
        delta_strength = "MODERATE"
    else:
        delta_score = 4
        delta_strength = "WEAK"

    # Factor 3: Proximity to actual extreme
    is_buying_tail = abs(block_start - session_low) <= (TICK_SIZE * 1.1)
    is_selling_tail = abs(block_end - session_high) <= (TICK_SIZE * 1.1)

    if is_buying_tail:
        distance = abs(block_start - session_low)
    elif is_selling_tail:
        distance = abs(block_end - session_high)
    else:
        distance = min(abs(block_start - session_low), abs(block_end - session_high))

    if distance < 0.5:  # Gold: tighter tolerance
        proximity_score = 10
    elif distance < 1.5:
        proximity_score = 7
    else:
        proximity_score = 4

    # Factor 4: Time of day (early tails more significant for gold pit hours)
    hour = block_time.hour if block_time else 10
    if hour < 10:  # Gold: early morning (8:20-10:00)
        timing_score = 10
        timing_strength = "EARLY"
    elif hour < 12:  # Gold: midday (10:00-12:00)
        timing_score = 7
        timing_strength = "MIDDAY"
    else:  # Gold: late session (12:00-13:30)
        timing_score = 5
        timing_strength = "LATE"

    # Composite score
    composite = (volume_score + delta_score + proximity_score + timing_score) / 4

    if composite >= 8:
        overall_strength = "STRONG"
        score_mult = 1.3
    elif composite >= 6:
        overall_strength = "MODERATE"
        score_mult = 1.0
    else:
        overall_strength = "WEAK"
        score_mult = 0.8

    return {
        'strength': overall_strength,
        'score_multiplier': score_mult,
        'components': {
            'volume': vol_strength,
            'delta': delta_strength,
            'timing': timing_strength
        },
        'note_suffix': f"[{overall_strength}: Vol={vol_strength}, Δ={delta_strength}, Time={timing_strength}]"
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

# --- NEW: MULTI-DAY PERSISTENCE ANALYSIS ---
def identify_persistent_levels(master_df, current_date, lookback_days=10, tolerance=0.2):
    """
    Find levels that appear on multiple days = institutional levels
    This is OBJECTIVE - based on repeated observation
    """
    if master_df.empty:
        return []

    print(f"      [PERSISTENCE] Checking last {lookback_days} days...")

    # Get recent dates
    cutoff = current_date - timedelta(days=lookback_days)
    recent = master_df[pd.to_datetime(master_df['level_date']).dt.date >= cutoff]

    if recent.empty:
        return []

    # Group levels by price (with tolerance)
    level_clusters = {}

    for _, row in recent.iterrows():
        price = row['price']
        date = row['level_date']

        # Find existing cluster
        found_cluster = None
        for cluster_price in level_clusters:
            if abs(price - cluster_price) <= tolerance:
                found_cluster = cluster_price
                break

        if found_cluster:
            if date not in level_clusters[found_cluster]['dates']:
                level_clusters[found_cluster]['dates'].add(date)
                level_clusters[found_cluster]['count'] += 1
        else:
            level_clusters[price] = {
                'price': price,
                'dates': {date},
                'count': 1
            }

    # Extract persistent levels (appear 3+ times)
    persistent = []
    for cluster in level_clusters.values():
        if cluster['count'] >= MULTI_DAY_PERSISTENCE_THRESHOLD:
            boost = 1.0 + (cluster['count'] * 0.15)  # +15% per occurrence
            persistent.append({
                'price': cluster['price'],
                'days': cluster['count'],
                'boost': boost,
                'note': f"Appeared {cluster['count']} days"
            })

    if persistent:
        print(f"      [PERSISTENCE] Found {len(persistent)} persistent levels")

    return persistent

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
            # Enhanced scoring based on size and duration
            size_score = min(data['max_sz'] / 200, 5)  # GC: Adjusted for lower volume
            duration_score = min(dur / 30, 5)
            score = 10.0 + size_score + duration_score

            levels.append({
                'price': p,
                'created_at': data['start'].strftime('%Y-%m-%d %H:%M:%S'),
                'level_type': data['type'],
                'category': 'LIQUIDITY',
                'strategy': 'REVERSAL_ENTRY',
                'engagement': 'LONG_DEFENSE' if 'BID' in data['type'] else 'SHORT_DEFENSE',
                'volume': 0,
                'delta': 0,
                'score': score,
                'note': f"Resting: {int(data['max_sz'])} lots for {int(dur)}m"
            })

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

        levels.append({
            'price': price,
            'created_at': session_ts,
            'level_type': l_type,
            'engagement': eng,
            'category': cat,
            'strategy': strat,
            'volume': int(vol),
            'delta': int(delta),
            'score': round(np.log1p(vol) * mult, 2),
            'note': f"Vol: {int(vol)} | Ratio: {imbalance_ratio:.2f}"
        })

    return pd.DataFrame(levels)

def detect_tpo_single_prints(df):
    """ENHANCED: Now classifies tail strength - GOLD RTH HOURS"""
    # Gold RTH: 9:30 AM - 4:15 PM ET (matching ES/NQ)
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
                if price in first_touches:
                    price_exact_time_map[price] = first_touches[price].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    price_exact_time_map[price] = period_start.strftime('%Y-%m-%d %H:%M:%S')
            price_tpo_map[price].add(period_start)

    single_print_prices = sorted([p for p, periods in price_tpo_map.items() if len(periods) == 1])
    if not single_print_prices: return pd.DataFrame()

    blocks = []; current_block = [single_print_prices[0]]
    for p in single_print_prices[1:]:
        if abs(p - current_block[-1]) <= TICK_SIZE * 1.1: current_block.append(p)
        else: blocks.append(current_block); current_block = [p]
    blocks.append(current_block)

    levels = []
    session_high, session_low = rth['price'].max(), rth['price'].min()

    for block in blocks:
        height = block[-1] - block[0]
        tick_count = int(round(height / TICK_SIZE)) + 1
        block_start, block_end = block[0], block[-1]

        # Calculate block volume and delta
        block_vol = 0; block_delta = 0
        for p in block:
            if p in price_stats.index:
                block_vol += price_stats.at[p, 'total_vol']
                block_delta += price_stats.at[p, 'delta']

        is_buying_tail = abs(block_start - session_low) <= (TICK_SIZE * 1.1)
        is_selling_tail = abs(block_end - session_high) <= (TICK_SIZE * 1.1)

        exact_ts = price_exact_time_map.get(block_start, "")

        # Get timestamp for strength calculation
        try:
            block_time = pd.to_datetime(exact_ts)
        except:
            block_time = None

        # Classify strength
        strength_data = classify_single_print_strength(
            block, price_stats, session_high, session_low, block_time
        )

        base = {
            'created_at': exact_ts,
            'volume': int(block_vol),
            'delta': int(block_delta),
            'strategy': 'REVERSAL_ENTRY',
            'category': 'SINGLE_PRINT'
        }

        if is_buying_tail and tick_count >= MIN_SINGLE_PRINT_TICKS:
            base_score = 10.0 * strength_data['score_multiplier']
            levels.append({
                **base,
                'price': block_end,
                'level_type': 'BUYING_TAIL',
                'engagement': 'LONG_DEFENSE',
                'score': base_score,
                'note': f"Tail ({tick_count}t) {strength_data['note_suffix']}"
            })
        elif is_selling_tail and tick_count >= MIN_SINGLE_PRINT_TICKS:
            base_score = 10.0 * strength_data['score_multiplier']
            levels.append({
                **base,
                'price': block_start,
                'level_type': 'SELLING_TAIL',
                'engagement': 'SHORT_DEFENSE',
                'score': base_score,
                'note': f"Tail ({tick_count}t) {strength_data['note_suffix']}"
            })
        elif tick_count >= 4:
            midpoint = round((block_start + block_end) / 2 / TICK_SIZE) * TICK_SIZE
            base_score = 7.5 * strength_data['score_multiplier']
            levels.append({
                **base,
                'price': midpoint,
                'level_type': 'GAP_ZONE',
                'engagement': 'NEUTRAL_ZONE',
                'score': base_score,
                'note': f"Gap ({tick_count}t) {strength_data['note_suffix']}"
            })

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
        if "OVERNIGHT" in row['category'] or "LIQUIDITY" in row['category']:
            final_levels.append(row)
            continue

        upper, lower = lvl + 0.5, lvl - 0.5  # GC: Tighter range
        above_count = ohlc[ohlc['close'] > upper].shape[0]
        below_count = ohlc[ohlc['close'] < lower].shape[0]

        if (above_count / total_bars) > 0.20 and (below_count / total_bars) > 0.20:
            if row['strategy'] == 'REVERSAL_ENTRY':
                row['category'] = 'MAGNET'
                row['strategy'] = 'TARGET_EXIT'
                row['engagement'] = 'NEUTRAL_ZONE'
                row['note'] += " [RECLASS: CHOP]"
                row['score'] *= 0.7  # Reduce score for choppy levels

        final_levels.append(row)

    return pd.DataFrame(final_levels)

def audit_historical_levels(existing_levels_df, current_day_df, current_date_obj):
    if existing_levels_df.empty or current_day_df.empty: return existing_levels_df
    existing_levels_df['created_at_dt'] = pd.to_datetime(existing_levels_df['created_at'], errors='coerce')
    mask_old = existing_levels_df['created_at_dt'].dt.date < current_date_obj
    day_high = current_day_df['price'].max() + ZONE_TOLERANCE
    day_low = current_day_df['price'].min() - ZONE_TOLERANCE
    mask_range = (existing_levels_df['price'] >= day_low) & (existing_levels_df['price'] <= day_high)
    target_indices = existing_levels_df[mask_old & mask_range].index

    if len(target_indices) == 0:
        return existing_levels_df.drop(columns=['created_at_dt'])

    print(f"      [AUDIT] Updating stats for {len(target_indices)} historical levels...")
    prices = current_day_df['price'].values
    timestamps = current_day_df.index.values.astype(np.int64) // 10**9

    for idx in target_indices:
        level_price = existing_levels_df.at[idx, 'price']
        in_zone = np.abs(prices - level_price) <= ZONE_TOLERANCE
        if not np.any(in_zone): continue

        zone_indices = np.where(in_zone)[0]
        added_seconds = 0
        if len(zone_indices) > 1:
            in_zone_ts = timestamps[zone_indices]
            diffs = np.diff(in_zone_ts)
            valid_diffs = diffs[diffs < 60]
            added_seconds = np.sum(valid_diffs)

        transitions = np.diff(in_zone.astype(int))
        entries = np.sum(transitions == 1)
        if in_zone[0]: entries += 1

        existing_hits = float(existing_levels_df.at[idx, 'hit_count'])
        existing_time = float(existing_levels_df.at[idx, 'time_spent_mins'])

        existing_levels_df.at[idx, 'hit_count'] = existing_hits + entries
        existing_levels_df.at[idx, 'time_spent_mins'] = round(existing_time + (added_seconds / 60.0), 2)
        existing_levels_df.at[idx, 'last_hit_timestamp'] = current_day_df.index[zone_indices[-1]].strftime('%Y-%m-%d %H:%M:%S')

    return existing_levels_df.drop(columns=['created_at_dt'])

# --- ENHANCED: PERFORMANCE-BASED WEIGHTING ---
def apply_performance_weighting(levels_df):
    """
    Dramatically boost levels that actually worked
    This is OBJECTIVE - based on actual trading history
    """
    for idx, row in levels_df.iterrows():
        hit_count = row.get('hit_count', 0)
        time_spent = row.get('time_spent_mins', 0)

        if hit_count == 0:
            continue  # New level, no history

        # Performance multiplier based on hits
        if hit_count >= PERFORMANCE_BOOST_THRESHOLD:
            performance_mult = 1.5
            levels_df.at[idx, 'note'] += f" [PROVEN: {int(hit_count)} hits]"
        elif hit_count >= 3:
            performance_mult = 1.3
            levels_df.at[idx, 'note'] += f" [TESTED: {int(hit_count)}x]"
        elif hit_count >= 2:
            performance_mult = 1.1
        else:
            performance_mult = 1.0

        # Additional boost for "sticky" levels (price spends time there)
        avg_time_per_hit = time_spent / hit_count if hit_count > 0 else 0
        if avg_time_per_hit > 10:  # More than 10 mins per hit
            performance_mult *= 1.2
            levels_df.at[idx, 'note'] += " [STICKY]"

        levels_df.at[idx, 'score'] *= performance_mult

    return levels_df

# --- ENHANCED: PERSISTENCE-AWARE MERGING ---
def filter_and_rank_levels(levels_df, persistent_levels, max_levels=12):
    if levels_df.empty: return levels_df

    # Apply persistence boosts BEFORE merging
    for persist in persistent_levels:
        mask = (levels_df['price'] >= persist['price'] - 0.2) & \
               (levels_df['price'] <= persist['price'] + 0.2)

        if mask.any():
            levels_df.loc[mask, 'score'] *= persist['boost']
            levels_df.loc[mask, 'note'] += f" [{persist['note']}]"

    levels_df = levels_df.sort_values('score', ascending=False)
    merged_levels = {}

    for _, row in levels_df.iterrows():
        price = row['price']
        found = False

        for existing in list(merged_levels.keys()):
            if abs(price - existing) <= 0.5:  # GC: Tighter merge tolerance
                # Merge - keep higher score
                if row['score'] > merged_levels[existing]['score']:
                    old_cat = merged_levels[existing]['category']
                    merged_levels[existing] = row.to_dict()
                    merged_levels[existing]['note'] += f" + {old_cat}"
                else:
                    merged_levels[existing]['score'] += (row['score'] * 0.3)
                    merged_levels[existing]['volume'] += row['volume']
                    merged_levels[existing]['delta'] += row['delta']
                    cat = row['category']
                    if cat not in merged_levels[existing]['note']:
                        merged_levels[existing]['note'] += f" + {cat}"

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
        if "LIQUIDITY" in level['category']:
            level['session_context'] = "RESTING_ORDER"
        else:
            nearby = trades[(trades['price'] >= level['price']-0.10) & (trades['price'] <= level['price']+0.10)]
            if not nearby.empty:
                # Gold RTH hours: 8:20-13:30
                am = nearby.between_time('08:20', '11:00')['size'].sum()
                pm = nearby.between_time('11:00', '13:30')['size'].sum()
                level['session_context'] = "AM_SESSION" if am > pm else "PM_SESSION"
            else:
                ts = pd.to_datetime(level['created_at'])
                if 8 <= ts.hour < 14: level['session_context'] = "RTH/THIN"
                else: level['session_context'] = "ETH/PASSIVE"

        ts = pd.to_datetime(level['created_at'])
        is_closing_hour = ts.hour >= 13  # Gold closes at 13:30

        if level['session_context'] == "PM_SESSION" and not is_closing_hour:
             level['score'] = level['score'] * 0.75
             level['note'] += " [PM_WEAK]"

        enhanced.append(level)

    return pd.DataFrame(enhanced)

def process_day_data(day_df, full_df, date_obj, use_l2, master_df):
    """ENHANCED: Now includes delta exhaustion and persistence analysis"""
    if 'action' in day_df.columns:
        trades_df = day_df[day_df['action'] == 'T'].copy()
    else:
        trades_df = day_df.copy()

    # EXISTING LEVEL TYPES
    vol_levels = identify_and_classify_levels(trades_df)
    tail_levels = detect_tpo_single_prints(trades_df)

    liq_levels = pd.DataFrame()
    if use_l2:
        liq_levels = detect_liquidity_walls(day_df, LIQUIDITY_MIN_SIZE, LIQUIDITY_MIN_MINS)

    # NEW: DELTA EXHAUSTION ZONES
    delta_levels = detect_delta_exhaustion_zones(trades_df)

    # NEW: IDENTIFY PERSISTENT LEVELS
    persistent = identify_persistent_levels(master_df, date_obj, lookback_days=10, tolerance=0.2)

    # COMBINE ALL
    all_levels = pd.concat([vol_levels, tail_levels, liq_levels, delta_levels], ignore_index=True)

    # Apply performance weighting
    all_levels = apply_performance_weighting(all_levels)

    # Filter and rank with persistence awareness
    final_levels = filter_and_rank_levels(all_levels, persistent, max_levels=12)

    return final_levels

def main():
    print("=== INSTITUTIONAL LEVEL AUDITOR V20.0 (ENHANCED - GC GOLD) ===")
    print("    SYMBOL: GC (Gold Futures)")
    print("    RTH HOURS: 8:20 AM - 1:30 PM ET")
    print("    FOCUS: Quality improvement of tick-data-derived levels")
    print("    NEW: Delta exhaustion, multi-day persistence, strength classification")
    print("    NO THEORETICAL CONSTRUCTS - Only objective, evidence-based levels")
    print()

    if "YOUR" in API_KEY:
        print("Set API Key")
        return

    # --- FLEXIBLE DATE SELECTION ---
    print("Date Range Selection:")
    print("  1. Last 5 days (quick)")
    print("  2. Last 30 days (backtest)")
    print("  3. Last 90 days (comprehensive)")
    print("  4. Custom date range")

    choice = input("\nSelect option [1-4, default=1]: ").strip()

    today = datetime.now().date()

    if choice == "2":
        start_date = today - timedelta(days=30)
        end_date = today
        print(f"   [30-DAY] Generating levels for last 30 days")
    elif choice == "3":
        start_date = today - timedelta(days=90)
        end_date = today
        print(f"   [90-DAY] Generating levels for last 90 days")
    elif choice == "4":
        start_input = input("Start Date (YYYY-MM-DD): ").strip()
        end_input = input("End Date (YYYY-MM-DD, or Enter for today): ").strip()

        try:
            start_date = datetime.strptime(start_input, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_input, "%Y-%m-%d").date() if end_input else today
            print(f"   [CUSTOM] {start_date} to {end_date}")
        except ValueError:
            print("Invalid date format! Using last 5 days.")
            start_date = today - timedelta(days=5)
            end_date = today
    else:
        # Default: last 5 days
        start_date = today - timedelta(days=5)
        end_date = today
        print(f"   [5-DAY] Generating levels for last 5 days")

    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')

    print(f"   Date Range: {start_str} to {end_str}")

    master_df = load_and_clean_database(INPUT_FILE)
    if not master_df.empty:
        master_df = purge_dates_from_database(master_df, start_str, end_str)

    cutoff_date = today - timedelta(days=RECENT_DAYS_THRESHOLD)
    et_tz = pytz.timezone('America/New_York')

    curr = start_date
    while curr <= end_date:
        day_str = curr.strftime('%Y-%m-%d')

        is_recent = (curr >= cutoff_date)
        schema = "mbp-10" if is_recent else "trades"
        use_l2 = is_recent

        print(f"\n--- Processing {day_str} ({schema}) ---")

        # Gold RTH: 8:20 AM - 1:30 PM ET
        req_start = datetime.combine(curr, dt_time(8, 20))
        req_end = datetime.combine(curr, dt_time(13, 30))

        req_start_tz = et_tz.localize(req_start)
        req_end_tz = et_tz.localize(req_end)

        if req_start_tz.astimezone(pytz.utc) > datetime.now(pytz.utc):
            print("   [SKIP] Date is in the future.")
            curr += timedelta(days=1)
            continue

        df = get_databento_data(API_KEY, req_start_tz, req_end_tz, schema)

        if df is not None and not df.empty:
            audit_df = df
            if schema == 'mbp-10' and 'action' in df.columns:
                audit_df = df[df['action'] == 'T'].copy()

            if not master_df.empty:
                master_df = audit_historical_levels(master_df, audit_df, curr)

            # ENHANCED: Pass master_df for persistence analysis
            new_levels = process_day_data(df, df, curr, use_l2, master_df)

            if not new_levels.empty:
                verified = integrity_check_and_reclassify(audit_df, new_levels)
                context = analyze_session_context(audit_df, verified)
                context['level_date'] = day_str
                context['symbol'] = SYMBOL
                context['analysis_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                for c in ['hit_count','time_spent_mins','last_hit_timestamp']:
                    context[c] = 0 if c!='last_hit_timestamp' else ""

                master_df = pd.concat([master_df, context], ignore_index=True)

        curr += timedelta(days=1)

    print(f"\nSaving database to {OUTPUT_FILE}...")
    cols = ['created_at', 'level_date', 'symbol', 'price', 'strategy', 'category',
            'engagement', 'score', 'level_type', 'session_context', 'volume', 'delta',
            'hit_count', 'time_spent_mins', 'last_hit_timestamp', 'note']

    for c in cols:
        if c not in master_df.columns:
            master_df[c] = ""

    master_df[cols].to_csv(OUTPUT_FILE, index=False)

    # Print summary
    print("\n" + "="*60)
    print("LEVEL GENERATION SUMMARY (GOLD)")
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
            print(f"   {lvl['price']:7.2f} | {lvl['category']:17s} | {lvl['level_type']:20s} | {lvl['score']:4.1f}")
            print(f"            {lvl['note'][:70]}")

        # Show performance stats
        proven_levels = latest_levels[latest_levels['note'].str.contains('PROVEN', na=False)]
        if not proven_levels.empty:
            print(f"\n*** {len(proven_levels)} PROVEN LEVELS (5+ hits) ***")

        persistent = latest_levels[latest_levels['note'].str.contains('Appeared', na=False)]
        if not persistent.empty:
            print(f"*** {len(persistent)} PERSISTENT LEVELS (multi-day) ***")

    print("\n" + "="*60)
    print("Done.")

if __name__ == "__main__":
    main()
