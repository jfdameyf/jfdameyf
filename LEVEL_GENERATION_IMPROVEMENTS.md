# Critical Level Generation - Proposed Improvements

## 🚨 Critical Missing Features

### 1. **Volume Profile Levels (HIGHEST PRIORITY)**

**Current State:** Script calculates volume/delta but doesn't generate POC/VAH/VAL levels.

**Why Critical:**
- Your trading bot uses POC for distance filtering
- POC is one of the most respected levels in the market
- VAH/VAL define value area boundaries

**Proposed Addition:**
```python
def calculate_volume_profile_levels(df, value_area_pct=0.70):
    """
    Generate POC, VAH, VAL for the session
    These are THE most important levels for institutional trading
    """
    if df.empty:
        return None

    # Group by price and sum volume
    vol_col = 'volume' if 'volume' in df.columns else 'size'
    price_volume = df.groupby('price')[vol_col].sum().sort_index()

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

    return {
        'POC': float(poc_price),
        'VAH': float(vah_price),
        'VAL': float(val_price),
        'total_volume': int(total_volume)
    }

def add_volume_profile_levels(levels_list, vp_data, session_ts, symbol):
    """Add POC/VAH/VAL as critical levels"""
    if not vp_data:
        return

    # POC - Highest priority
    levels_list.append({
        'price': vp_data['POC'],
        'created_at': session_ts,
        'level_type': 'POC',
        'category': 'VOLUME_PROFILE',
        'strategy': 'REVERSAL_ENTRY',
        'engagement': 'MAGNETIC_ZONE',
        'volume': vp_data['total_volume'],
        'delta': 0,
        'score': 15.0,  # Highest score - most important level
        'note': f"POC - Point of Control"
    })

    # VAH - Value Area High
    levels_list.append({
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

    # VAL - Value Area Low
    levels_list.append({
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
```

**Integration:**
```python
# In process_day_data(), after generating other levels:
vp_data = calculate_volume_profile_levels(trades_df)
if vp_data:
    vp_levels = []
    add_volume_profile_levels(vp_levels, vp_data, session_ts, SYMBOL)
    all_levels = pd.concat([vol_levels, tail_levels, liq_levels, pd.DataFrame(vp_levels)])
```

---

## 2. **Previous Day Levels (HIGH PRIORITY)**

**Current State:** Only analyzes current day.

**Why Important:**
- Previous day high/low/close are watched by ALL traders
- Often act as support/resistance
- Required for gap analysis

**Proposed Addition:**
```python
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

                return {
                    'PDH': float(pdh),
                    'PDL': float(pdl),
                    'PDC': float(pdc),
                    'date': prev_date.strftime('%Y-%m-%d')
                }
        except:
            continue

    return None

def add_previous_day_levels(levels_list, pd_data, session_ts):
    """Add previous day high/low/close as levels"""
    if not pd_data:
        return

    levels_list.append({
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

    levels_list.append({
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

    levels_list.append({
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
```

---

## 3. **Opening Range Levels (MEDIUM PRIORITY)**

**Current State:** No opening range detection.

**Why Important:**
- First 30-60 minutes establishes the day's range
- Opening range breakouts are high-probability setups
- ORH/ORL often act as support/resistance all day

**Proposed Addition:**
```python
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

    # Opening price (first trade)
    open_price = or_start['price'].iloc[0]

    return {
        'ORH': float(orh),
        'ORL': float(orl),
        'OPEN': float(open_price),
        'range_size': float(orh - orl)
    }

def add_opening_range_levels(levels_list, or_data, session_ts):
    """Add opening range levels"""
    if not or_data:
        return

    # Only add if opening range is meaningful (not too tight)
    if or_data['range_size'] < 2.0:  # ES: less than 2 points
        return

    levels_list.append({
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

    levels_list.append({
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
```

---

## 4. **Delta Flip Detection (MEDIUM PRIORITY)**

**Current State:** Calculates delta but doesn't identify flip zones.

**Why Important:**
- Delta flips show where buying/selling pressure reverses
- Often precede major moves
- High-edge reversal zones

**Proposed Addition:**
```python
def detect_delta_flip_zones(df, window_size=5):
    """
    Identify prices where delta flips from positive to negative or vice versa
    These are exhaustion/reversal zones
    """
    if df.empty:
        return pd.DataFrame()

    price_stats = calculate_price_stats(df)
    if price_stats.empty:
        return pd.DataFrame()

    # Calculate cumulative delta trend
    price_stats = price_stats.sort_index()
    price_stats['delta_ma'] = price_stats['delta'].rolling(window=window_size, center=True).mean()

    # Find sign changes
    price_stats['delta_sign'] = np.sign(price_stats['delta_ma'])
    price_stats['sign_change'] = price_stats['delta_sign'].diff().abs()

    # Delta flips are where sign changes from + to - or vice versa
    flip_zones = price_stats[price_stats['sign_change'] == 2.0]

    levels = []
    session_ts = df.index[-1].strftime('%Y-%m-%d %H:%M:%S')

    for price, row in flip_zones.iterrows():
        vol = row['total_vol']
        delta = row['delta']

        # Only significant flips
        if vol < price_stats['total_vol'].quantile(0.80):
            continue

        flip_type = "BUYING_EXHAUSTION" if delta < 0 else "SELLING_EXHAUSTION"
        engagement = "SHORT_DEFENSE" if delta < 0 else "LONG_DEFENSE"

        levels.append({
            'price': price,
            'created_at': session_ts,
            'level_type': flip_type,
            'category': 'DELTA_FLIP',
            'strategy': 'REVERSAL_ENTRY',
            'engagement': engagement,
            'volume': int(vol),
            'delta': int(delta),
            'score': 8.5,
            'note': f"Delta Flip: {delta:+.0f} (Vol: {int(vol)})"
        })

    return pd.DataFrame(levels)
```

---

## 5. **Overnight High/Low (MEDIUM-LOW PRIORITY)**

**Current State:** Mentions "OVERNIGHT" category but doesn't generate them.

**Why Important:**
- Shows overnight range
- Important for gap analysis
- Asia/Europe price discovery

**Proposed Addition:**
```python
def get_overnight_levels(current_date_obj, api_key):
    """
    Fetch overnight session (previous day 16:30 - current day 9:30)
    Returns overnight high/low
    """
    et_tz = pytz.timezone('America/New_York')

    # Overnight session definition
    prev_date = current_date_obj - timedelta(days=1)

    # Handle weekends
    if current_date_obj.weekday() == 0:  # Monday
        prev_date = current_date_obj - timedelta(days=3)  # Friday

    start_dt = et_tz.localize(datetime.combine(prev_date, dt_time(16, 30)))
    end_dt = et_tz.localize(datetime.combine(current_date_obj, dt_time(9, 30)))

    try:
        df = get_databento_data(api_key, start_dt, end_dt, "trades")

        if df is not None and not df.empty:
            onh = df['price'].max()
            onl = df['price'].min()

            return {
                'ONH': float(onh),
                'ONL': float(onl)
            }
    except:
        pass

    return None

def add_overnight_levels(levels_list, on_data, session_ts):
    """Add overnight high/low"""
    if not on_data:
        return

    levels_list.append({
        'price': on_data['ONH'],
        'created_at': session_ts,
        'level_type': 'ONH',
        'category': 'OVERNIGHT',
        'strategy': 'REVERSAL_ENTRY',
        'engagement': 'SHORT_DEFENSE',
        'volume': 0,
        'delta': 0,
        'score': 7.0,
        'note': "Overnight High"
    })

    levels_list.append({
        'price': on_data['ONL'],
        'created_at': session_ts,
        'level_type': 'ONL',
        'category': 'OVERNIGHT',
        'strategy': 'REVERSAL_ENTRY',
        'engagement': 'LONG_DEFENSE',
        'volume': 0,
        'delta': 0,
        'score': 7.0,
        'note': "Overnight Low"
    })
```

---

## 6. **Improved TPO Single Print Detection**

**Current Issue:** Buying/selling tail detection is too restrictive.

**Fix:**
```python
# CURRENT (Too restrictive):
is_buying_tail = abs(block_start - session_low) <= (TICK_SIZE * 1.1)

# IMPROVED (More realistic):
is_buying_tail = abs(block_start - session_low) <= (TICK_SIZE * 4)  # Within 1 point
is_strong_buying_tail = abs(block_start - session_low) <= (TICK_SIZE * 1.1)

# Adjust score based on proximity:
if is_strong_buying_tail:
    score = 12.0  # Right at session low
elif is_buying_tail:
    score = 10.0  # Near session low
```

**Also Add Mid-Day Extensions:**
```python
def detect_midday_extensions(df):
    """
    Identify prices that were only touched during midday chop
    These are weak levels that get re-tested
    """
    rth = df.between_time('09:30', '16:15').copy()

    if rth.empty:
        return pd.DataFrame()

    # Define midday as 11:30-14:00
    midday = rth.between_time('11:30', '14:00')
    open_drive = rth.between_time('09:30', '11:30')
    close_drive = rth.between_time('14:00', '16:15')

    midday_prices = set(midday['price'].unique())
    other_prices = set(open_drive['price'].unique()) | set(close_drive['price'].unique())

    # Prices ONLY touched during midday chop
    midday_only = midday_prices - other_prices

    levels = []
    session_ts = df.index[-1].strftime('%Y-%m-%d %H:%M:%S')

    for price in midday_only:
        price_data = midday[midday['price'] == price]
        vol = price_data['size'].sum() if 'size' in price_data else 0

        levels.append({
            'price': price,
            'created_at': session_ts,
            'level_type': 'MIDDAY_EXTENSION',
            'category': 'WEAK_LEVEL',
            'strategy': 'FADE_ENTRY',
            'engagement': 'NEUTRAL_ZONE',
            'volume': int(vol),
            'delta': 0,
            'score': 5.0,  # Low score - weak level
            'note': f"Midday chop zone"
        })

    return pd.DataFrame(levels)
```

---

## 7. **Liquidity Pull Detection**

**Current Issue:** Detects resting liquidity but not when it's pulled.

**Why Important:**
- Fake walls (spoofing)
- Real institutional orders that get pulled before being hit

**Proposed Addition:**
```python
def detect_pulled_liquidity(df_full, min_size=400, pull_threshold=0.8):
    """
    Identify prices where large orders were placed then pulled
    These can become "magnet" levels - price is drawn back to test them
    """
    if df_full.empty:
        return pd.DataFrame()

    book_cols = [c for c in df_full.columns if 'sz_0' in c]
    if not book_cols:
        return pd.DataFrame()

    levels = []
    df_1s = df_full.resample('1s').mean()

    pulled_walls = {}

    # Track each price level over time
    for col in ['bid_px_00', 'ask_px_00']:
        size_col = col.replace('px', 'sz')

        for idx in range(len(df_1s) - 60):  # Need at least 60 seconds
            window = df_1s.iloc[idx:idx+60]

            # Find large resting orders
            large_orders = window[window[size_col] >= min_size]

            if len(large_orders) < 10:  # Must rest for at least 10 seconds
                continue

            price = large_orders[col].mode()[0]  # Most common price
            max_size = large_orders[size_col].max()

            # Check if order was pulled (size drops significantly)
            final_size = window[size_col].iloc[-1]

            if final_size < (max_size * pull_threshold):
                # Order was pulled!
                if price not in pulled_walls:
                    pulled_walls[price] = {
                        'max_size': max_size,
                        'timestamp': window.index[0],
                        'side': 'BID' if 'bid' in col else 'ASK'
                    }

    # Create levels from pulled walls
    for price, data in pulled_walls.items():
        levels.append({
            'price': price,
            'created_at': data['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
            'level_type': f"PULLED_{data['side']}_WALL",
            'category': 'LIQUIDITY_PULL',
            'strategy': 'MAGNET_TARGET',
            'engagement': 'NEUTRAL_ZONE',
            'volume': 0,
            'delta': 0,
            'score': 8.0,
            'note': f"Pulled {data['side']} wall ({int(data['max_size'])} lots)"
        })

    return pd.DataFrame(levels)
```

---

## 8. **Round Number Levels**

**Current State:** Not generated.

**Why Important:**
- Psychological levels (6000.00, 6050.00, 6100.00)
- Options strike prices
- Institutional order clustering

**Proposed Addition:**
```python
def generate_round_number_levels(session_high, session_low, interval=25.0):
    """
    Generate round number levels within session range
    ES: Use 25-point intervals (6000, 6025, 6050, 6075, 6100)
    NQ: Use 100-point intervals (20000, 20100, 20200)
    """
    levels = []

    # Find first round number above session low
    start = np.ceil(session_low / interval) * interval

    current = start
    while current <= session_high:
        # Score based on "roundness"
        if current % (interval * 4) == 0:  # Super round (e.g., 6000, 6100)
            score = 9.0
            note = "Major Round Number"
        elif current % (interval * 2) == 0:  # Mid round (e.g., 6050)
            score = 7.0
            note = "Round Number"
        else:  # Regular interval
            score = 5.0
            note = "Quarter Level"

        levels.append({
            'price': current,
            'level_type': 'ROUND_NUMBER',
            'category': 'PSYCHOLOGICAL',
            'strategy': 'REVERSAL_ENTRY',
            'engagement': 'NEUTRAL_ZONE',
            'volume': 0,
            'delta': 0,
            'score': score,
            'note': note
        })

        current += interval

    return levels
```

---

## 9. **Improved Level Merging**

**Current Issue:** Merges levels within 1 point - might be too aggressive.

**Improvement:**
```python
def filter_and_rank_levels(levels_df, max_levels=15, merge_tolerance=None):
    """
    Improved merging with category-aware tolerance
    """
    if levels_df.empty:
        return levels_df

    # Default merge tolerance based on level type
    if merge_tolerance is None:
        merge_tolerance = {
            'VOLUME_PROFILE': 0.5,  # Don't merge POC/VAH/VAL
            'REFERENCE': 0.5,        # Don't merge PDH/PDL
            'SINGLE_PRINT': 1.0,     # Can merge tails
            'LIQUIDITY': 0.75,       # Keep walls distinct
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
                # Merge logic - keep higher score level as primary
                if row['score'] > merged_levels[existing]['score']:
                    # New level is more important - replace
                    old_category = merged_levels[existing]['category']
                    merged_levels[existing] = row.to_dict()
                    merged_levels[existing]['note'] += f" + {old_category}"
                else:
                    # Existing level is more important - just add note
                    merged_levels[existing]['note'] += f" + {category}"
                    merged_levels[existing]['score'] += (row['score'] * 0.2)

                found = True
                break

        if not found:
            merged_levels[price] = row.to_dict()

    result_df = pd.DataFrame(list(merged_levels.values()))

    # Normalize scores to 0-10 WITHIN each category
    for category in result_df['category'].unique():
        mask = result_df['category'] == category
        if mask.sum() > 0:
            cat_scores = result_df.loc[mask, 'score']
            max_score = cat_scores.max()
            if max_score > 0:
                # Keep absolute importance but normalize within category
                result_df.loc[mask, 'score'] = (cat_scores / max_score) * 10

    return result_df.sort_values('score', ascending=False).head(max_levels)
```

---

## 10. **Better Scoring System**

**Current Issue:** Scores normalized to 0-10, making cross-day comparison difficult.

**Improvement:**
```python
def calculate_absolute_score(level_dict, session_stats):
    """
    Calculate absolute score based on multiple factors
    Returns 0-100 score that's comparable across days
    """
    base_score = 0

    # Category base scores (0-30)
    category_scores = {
        'VOLUME_PROFILE': 30,  # POC/VAH/VAL = highest priority
        'REFERENCE': 25,        # PDH/PDL/PDC
        'OPENING_RANGE': 20,    # ORH/ORL
        'SINGLE_PRINT': 15,     # Tails and gaps
        'LIQUIDITY': 20,        # L2 walls
        'DELTA_FLIP': 15,       # Exhaustion zones
        'OVERNIGHT': 12,        # ONH/ONL
        'PSYCHOLOGICAL': 10,    # Round numbers
        'WEAK_LEVEL': 5         # Midday chop
    }

    base_score = category_scores.get(level_dict['category'], 10)

    # Volume factor (0-25)
    if 'volume' in level_dict and session_stats['total_volume'] > 0:
        vol_percentile = level_dict['volume'] / session_stats['total_volume']
        vol_score = min(vol_percentile * 100, 25)
        base_score += vol_score

    # Historical performance (0-25)
    if 'hit_count' in level_dict and level_dict['hit_count'] > 0:
        # More hits = more respected level
        hit_score = min(level_dict['hit_count'] * 2, 15)

        # Time spent at level
        time_score = 0
        if 'time_spent_mins' in level_dict:
            # More time = stronger level
            time_score = min(level_dict['time_spent_mins'] / 10, 10)

        base_score += hit_score + time_score

    # Position in range (0-20)
    range_position_score = 0
    if 'session_high' in session_stats and 'session_low' in session_stats:
        range_size = session_stats['session_high'] - session_stats['session_low']
        if range_size > 0:
            # Levels at extremes more important
            dist_from_mid = abs(level_dict['price'] - (session_stats['session_high'] + session_stats['session_low']) / 2)
            position_in_range = dist_from_mid / (range_size / 2)
            range_position_score = position_in_range * 20

    base_score += range_position_score

    return min(base_score, 100)
```

---

## Implementation Priority

### Phase 1 (Do Immediately):
1. ✅ **Volume Profile (POC/VAH/VAL)** - Critical for bot's POC filter
2. ✅ **Previous Day Levels (PDH/PDL/PDC)** - Universal reference points
3. ✅ **Opening Range (ORH/ORL)** - High probability levels

### Phase 2 (Next Week):
4. ✅ **Delta Flip Detection** - Higher edge reversals
5. ✅ **Improved Level Merging** - Better level quality
6. ✅ **Absolute Scoring System** - Cross-day comparison

### Phase 3 (When Time Permits):
7. ⚠️ **Overnight Levels** - Useful but lower priority
8. ⚠️ **Round Numbers** - Easy to add, moderate value
9. ⚠️ **Pulled Liquidity** - Advanced but high edge
10. ⚠️ **Midday Extensions** - Nice to have

---

## Expected Impact on Trading

### Current System:
- 10-12 levels per day
- Mix of volume, delta, TPO, L2
- No volume profile reference
- No previous day context

### Improved System:
- 15-20 levels per day
- **Includes POC/VAH/VAL** (most important!)
- **Includes PDH/PDL/PDC** (universal reference)
- **Includes ORH/ORL** (day structure)
- Better categorization
- Absolute scoring for comparison

### Performance Improvement Estimate:
- **Current win rate:** 67% (ES), 58% (NQ)
- **Expected with better levels:** 70-75% (ES), 62-67% (NQ)
- **Reason:** Better levels = better entries = fewer false signals

---

## NQ-Specific Considerations

For NQ, adjust thresholds 4x:

```python
# ES Settings
MIN_SINGLE_PRINT_TICKS = 8  # 2 points
LIQUIDITY_MIN_SIZE = 400
ROUND_NUMBER_INTERVAL = 25.0

# NQ Settings
MIN_SINGLE_PRINT_TICKS_NQ = 32  # 8 points (4x)
LIQUIDITY_MIN_SIZE_NQ = 100     # NQ has different liquidity profile
ROUND_NUMBER_INTERVAL_NQ = 100.0  # 100-point intervals
```

---

## Quick Win: Add Just POC/VAH/VAL

If you only do ONE thing, add volume profile:

```python
# In process_day_data(), add this:
def process_day_data(day_df, full_df, date_obj, use_l2):
    trades_df = day_df[day_df['action'] == 'T'] if 'action' in day_df else day_df
    session_ts = trades_df.index[-1].strftime('%Y-%m-%d %H:%M:%S')

    # EXISTING LEVELS
    vol_levels = identify_and_classify_levels(trades_df)
    tail_levels = detect_tpo_single_prints(trades_df)
    liq_levels = detect_liquidity_walls(day_df, ...) if use_l2 else pd.DataFrame()

    # NEW: VOLUME PROFILE
    vp_data = calculate_volume_profile_levels(trades_df)
    vp_levels = []
    if vp_data:
        add_volume_profile_levels(vp_levels, vp_data, session_ts, SYMBOL)

    # COMBINE ALL
    return pd.concat([
        vol_levels,
        tail_levels,
        liq_levels,
        pd.DataFrame(vp_levels)
    ], ignore_index=True)
```

This single change will add the 3 most important levels (POC/VAH/VAL) to every day!
