# Order Book Analysis for FLIP Strategy Backtest

## Overview
This document outlines the approach for integrating Level 2/3 order book data analysis to measure liquidity changes and price action effectiveness around FLIP levels (failed support/resistance that becomes the opposite type).

## Objectives
1. **Measure liquidity absorption** at levels before they fail
2. **Track order book changes** when levels transition from one type to another
3. **Identify high-probability FLIP setups** based on order flow patterns
4. **Quantify the "footprint" of failed levels** to validate the FLIP strategy

---

## Data Requirements

### Level 2 Data (Market Depth)
- **Bid/Ask ladder snapshot** at key moments:
  - When level first approached
  - During violation (extension phase)
  - At moment of failure (blowout)
  - During retest from opposite side (flip trigger)

- **Metrics to capture:**
  - Total bid/ask size within 5 ticks of level
  - Bid/ask imbalance ratio
  - Large orders (>100 contracts for ES/NQ, >50 for GC)
  - Order book delta (cumulative bid - ask)

### Level 3 Data (Order-by-Order)
- **Order flow events:**
  - Aggressive buy/sell volume
  - Passive fills vs active fills
  - Stacked orders pulled before fills
  - Absorption patterns (large bids/asks absorbing market orders)

### Databento Schema Recommendations
```python
# For Level 2 snapshots
schema = "mbp-10"  # Market by price, 10 levels deep

# For Level 3 tick-by-tick
schema = "mbp-1"   # Best bid/offer with volume
# or
schema = "trades"  # Trade feed with aggressor side
```

---

## Analysis Framework

### Phase 1: Level Failure Analysis
Track order book behavior during level violation:

**Metrics:**
1. **Pre-Violation Absorption**
   - How much volume was absorbed at the level before failure?
   - Did large orders get pulled before violation?
   - Ratio of passive fills to aggressive fills

2. **Violation Characteristics**
   - Aggressive volume during violation (market orders)
   - Speed of extension beyond level
   - Order book imbalance during extension

3. **Failure Signal Strength**
   - Volume required to push past blowout threshold
   - Order book depth on opposite side during blowout
   - Whether stops likely triggered (rapid acceleration)

### Phase 2: FLIP Retest Analysis
Track order book when price returns to test from opposite side:

**Metrics:**
1. **Approach Phase**
   - Order book buildup as price approaches flip level
   - Are large orders placed in advance?
   - Bid/ask ratio shift compared to original test

2. **At the Flip Level**
   - Absorption capacity (can it absorb sellers if old RES→new SUP?)
   - Stacked orders vs thin book
   - Aggressive vs passive fills on the retest

3. **Post-Flip Behavior**
   - Did level hold with low absorption (strong level)?
   - Or required heavy absorption (weak level)?
   - Price action after: bounce vs grind vs fail again

---

## Implementation Design

### New Module: `orderbook_flip_analyzer.py`

```python
class OrderBookFlipAnalyzer:
    """
    Analyze order book dynamics around FLIP levels
    """

    def __init__(self, databento_client):
        self.client = databento_client
        self.flip_analysis = []

    def analyze_flip_level(self, level_price, fail_time, flip_time, symbol):
        """
        Analyze order book around a single FLIP event

        Args:
            level_price: The price level that failed and flipped
            fail_time: Timestamp when level reached FAILED state
            flip_time: Timestamp when flip signal triggered
            symbol: Trading instrument

        Returns:
            Dictionary with order book metrics
        """

        # Fetch Level 2 data around failure
        pre_fail_book = self._fetch_orderbook_snapshot(
            symbol, fail_time - timedelta(minutes=5), fail_time
        )

        # Fetch Level 2 data around flip trigger
        flip_book = self._fetch_orderbook_snapshot(
            symbol, flip_time - timedelta(minutes=5), flip_time
        )

        # Calculate absorption metrics
        fail_absorption = self._calculate_absorption(
            pre_fail_book, level_price, direction='original'
        )

        flip_absorption = self._calculate_absorption(
            flip_book, level_price, direction='flipped'
        )

        # Compare order flow
        comparison = {
            'level': level_price,
            'fail_time': fail_time,
            'flip_time': flip_time,
            'fail_absorption': fail_absorption,
            'flip_absorption': flip_absorption,
            'liquidity_shift': flip_absorption - fail_absorption,
            'order_book_quality': self._assess_book_quality(flip_book, level_price)
        }

        return comparison

    def _calculate_absorption(self, orderbook_data, level_price, direction):
        """
        Calculate how much volume was absorbed near the level

        Returns:
            Float: Total contracts absorbed within 5 ticks
        """
        # Implementation: Sum bid/ask volume within proximity
        pass

    def _assess_book_quality(self, orderbook_data, level_price):
        """
        Assess order book quality at flip level

        Returns:
            String: "STRONG" | "MODERATE" | "WEAK"
        """
        # Strong: Large stacked orders, minimal imbalance
        # Moderate: Decent size but some imbalance
        # Weak: Thin book, large imbalances
        pass

    def generate_flip_heatmap(self, flip_events):
        """
        Generate heatmap visualization of order book changes
        Shows liquidity distribution before/after flip
        """
        # Visualization using matplotlib/seaborn
        pass
```

---

## Integration with Backtest Framework

### Modify `TradingBotBacktester` class:

```python
class TradingBotBacktester:
    def __init__(self, start_date, end_date, enable_poc_filter=False,
                 analyze_orderbook=False):
        # ... existing code ...

        self.analyze_orderbook = analyze_orderbook
        if analyze_orderbook:
            self.ob_analyzer = OrderBookFlipAnalyzer(self.client)

    def _track_flip_event(self, level, fail_time):
        """Called when a level reaches FAILED state"""
        if self.analyze_orderbook:
            # Store for later analysis when flip fires
            self.pending_flips[level['price']] = {
                'fail_time': fail_time,
                'original_type': level['type']
            }

    def _on_flip_signal(self, signal, timestamp):
        """Called when FLIP signal fires"""
        level_price = signal['price']

        if self.analyze_orderbook and level_price in self.pending_flips:
            flip_data = self.pending_flips[level_price]

            # Run order book analysis
            ob_analysis = self.ob_analyzer.analyze_flip_level(
                level_price=level_price,
                fail_time=flip_data['fail_time'],
                flip_time=timestamp,
                symbol=SYMBOL
            )

            # Attach to signal
            signal['orderbook_analysis'] = ob_analysis
```

---

## Visualization Outputs

### 1. **FLIP Order Book Comparison Chart**
Side-by-side ladder comparison:
- Left: Order book at failure
- Right: Order book at flip trigger
- Highlight: Liquidity shift

### 2. **Absorption Heatmap**
Color-coded visualization:
- Green: High liquidity support
- Yellow: Moderate liquidity
- Red: Thin liquidity (risky)

### 3. **FLIP Success Correlation**
Scatter plot:
- X-axis: Order book quality score
- Y-axis: FLIP signal success rate
- Shows correlation between liquidity and outcome

---

## Key Metrics to Report

### Per-FLIP Analysis
```
FLIP Level: 5925.50 (Old RES → New SUP)
─────────────────────────────────────────
Failure Phase:
  • Time: 2024-12-15 10:23:15
  • Absorption at level: 2,450 contracts
  • Violation volume: 1,890 contracts (77% of absorption)
  • Order book pulled: 560 contracts (23%)

Flip Trigger Phase:
  • Time: 2024-12-15 11:45:32
  • Absorption at level: 3,120 contracts (+27%)
  • Bid/Ask ratio: 2.3:1 (favorable for SUP)
  • Large orders (>100): 8 bids, 2 asks
  • Order book quality: STRONG

Outcome:
  • Signal success: ✅ YES (held on retest)
  • MFE: +8.5 pts
  • MAE: -1.25 pts
```

### Aggregate Statistics
- **FLIP success rate by order book quality**
- **Average absorption differential** (flip vs fail)
- **Correlation between liquidity shift and signal quality**

---

## Implementation Phases

### Phase 1: Data Collection ✅ (Ready to implement)
- Modify backtest to track FLIP events
- Store timestamps for failure and flip trigger
- Identify levels that need order book analysis

### Phase 2: Order Book Fetching (Week 1)
- Implement Databento MBP-10 data fetching
- Cache order book snapshots around key events
- Build helper functions for book parsing

### Phase 3: Metric Calculation (Week 1-2)
- Implement absorption calculations
- Build order book quality scoring
- Create liquidity shift metrics

### Phase 4: Analysis Integration (Week 2)
- Integrate with existing backtest framework
- Attach order book data to FLIP signals
- Update CSV logs to include OB metrics

### Phase 5: Visualization (Week 3)
- Build order book comparison charts
- Create absorption heatmaps
- Generate correlation plots

---

## Expected Insights

### What We'll Learn:
1. **FLIP signal quality predictors**
   - Does stronger order book at flip = higher success?
   - Is there a minimum liquidity threshold?

2. **Market microstructure patterns**
   - How do institutions set up levels?
   - Are large orders placed in advance or reactively?

3. **Optimization opportunities**
   - Should we filter FLIPs by order book quality?
   - Can we add a "liquidity score" size modifier?

4. **Risk management**
   - Identify high-risk FLIPs (thin liquidity)
   - Adjust position sizing based on absorption capacity

---

## Notes

- **Data costs**: Databento charges per GB for historical Level 2/3 data. Estimate ~$50-200 for 30-90 days depending on granularity.

- **Processing time**: Order book analysis adds significant computation. Consider:
  - Parallel processing for multiple FLIP events
  - Caching preprocessed order book data
  - Progressive analysis (start with key levels only)

- **Alternative approach**: If Level 2/3 data too expensive, could use:
  - Volume profile analysis (already available via Databento OHLCV)
  - Delta divergence (bid vs ask volume)
  - Large trade detection (>100 lot trades near level)

---

## Next Steps

1. ✅ Update backtest framework to recognize FLIP signals (COMPLETE)
2. ⏳ Implement basic FLIP tracking in backtest (save fail/flip timestamps)
3. ⏳ Test Databento MBP schema fetching on sample dates
4. ⏳ Build OrderBookFlipAnalyzer skeleton class
5. ⏳ Run pilot analysis on 5-10 FLIP events to validate approach
6. ⏳ Iterate on metrics based on pilot findings
7. ⏳ Scale to full backtest with order book integration

---

## Questions for Consideration

1. **Granularity**: Should we analyze order book tick-by-tick or at key snapshots only?
2. **Proximity threshold**: How many ticks from level price should we include in absorption calc?
3. **Time windows**: How far before/after failure and flip should we analyze?
4. **Success criteria**: What defines a successful FLIP? Hold for N points? Bounce amplitude?

