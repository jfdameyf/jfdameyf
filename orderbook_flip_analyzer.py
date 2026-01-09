"""
Order Book FLIP Analyzer
Analyzes Level 2/3 order book data around FLIP signals to measure liquidity quality

Required dependencies: pandas, numpy, databento, matplotlib, seaborn, pytz
Install with: pip install pandas numpy databento matplotlib seaborn pytz
"""

# Import standard library modules
from datetime import datetime, timedelta
from collections import defaultdict
import logging

# Try importing required dependencies with helpful error messages
try:
    import pandas as pd
except ImportError as e:
    raise ImportError(
        "pandas is required for OrderBookFlipAnalyzer. "
        "Install with: pip install pandas"
    ) from e

try:
    import numpy as np
except ImportError as e:
    raise ImportError(
        "numpy is required for OrderBookFlipAnalyzer. "
        "Install with: pip install numpy"
    ) from e

try:
    import databento as db
except ImportError as e:
    raise ImportError(
        "databento is required for OrderBookFlipAnalyzer. "
        "Install with: pip install databento"
    ) from e

try:
    import matplotlib.pyplot as plt
    import seaborn as sns
except ImportError:
    # Matplotlib/seaborn are only needed for plotting, allow import to succeed
    plt = None
    sns = None
    logging.warning("matplotlib/seaborn not available - plotting will be disabled")

try:
    import pytz
    NY_TZ = pytz.timezone('America/New_York')
except ImportError:
    # pytz is optional, can use UTC if not available
    pytz = None
    NY_TZ = None
    logging.warning("pytz not available - using UTC for timestamps")


class OrderBookFlipAnalyzer:
    """
    Analyze order book dynamics around FLIP level events

    A FLIP occurs when a failed support becomes resistance (or vice versa).
    This class measures order book quality, liquidity absorption, and
    microstructure changes to validate FLIP signal quality.
    """

    def __init__(self, databento_client, symbol="ES.c.0", tick_proximity=5):
        """
        Initialize the order book analyzer

        Args:
            databento_client: Databento Historical client instance
            symbol: Trading instrument (default: ES.c.0)
            tick_proximity: How many ticks from level to include in analysis (default: 5)
        """
        self.client = databento_client
        self.symbol = symbol
        self.tick_proximity = tick_proximity

        # Storage for analysis results
        self.flip_analyses = []
        self.pending_flips = {}  # Track levels that failed but haven't flipped yet

        # Instrument-specific settings
        self.tick_size = self._get_tick_size(symbol)
        self.large_order_threshold = self._get_large_order_threshold(symbol)

        logging.info(f"OrderBookFlipAnalyzer initialized for {symbol}")
        logging.info(f"  Tick size: {self.tick_size}")
        logging.info(f"  Large order threshold: {self.large_order_threshold} contracts")
        logging.info(f"  Proximity window: {tick_proximity} ticks")

    def _get_tick_size(self, symbol):
        """Get tick size for instrument"""
        if symbol.startswith("ES"):
            return 0.25
        elif symbol.startswith("NQ"):
            return 0.25
        elif symbol.startswith("GC"):
            return 0.10
        else:
            return 0.25  # Default

    def _get_large_order_threshold(self, symbol):
        """Get threshold for what constitutes a 'large' order"""
        if symbol.startswith("ES"):
            return 100  # 100+ contracts is large for ES
        elif symbol.startswith("NQ"):
            return 100
        elif symbol.startswith("GC"):
            return 50   # Gold has smaller typical sizes
        else:
            return 100

    # ==========================================================================
    # MAIN ANALYSIS METHODS
    # ==========================================================================

    def analyze_flip_level(self, level_price, fail_time, flip_time,
                           original_type='RES', flip_type='SUP'):
        """
        Analyze order book around a single FLIP event

        This is the main entry point for analyzing a flip. It fetches order book
        data before the failure and at the flip trigger, then compares them.

        Args:
            level_price: The price level that failed and flipped
            fail_time: Timestamp when level reached FAILED state (blowout)
            flip_time: Timestamp when flip signal triggered (recapture from opposite side)
            original_type: Original level type ('SUP' or 'RES')
            flip_type: New level type after flip ('RES' or 'SUP')

        Returns:
            Dictionary with comprehensive order book analysis
        """
        logging.info(f"\n{'='*60}")
        logging.info(f"Analyzing FLIP: {level_price:.2f} ({original_type}→{flip_type})")
        logging.info(f"  Failure: {fail_time}")
        logging.info(f"  Flip:    {flip_time}")
        logging.info(f"{'='*60}")

        try:
            # Fetch order book data around failure
            fail_book = self._fetch_orderbook_snapshot(
                start_time=fail_time - timedelta(minutes=10),
                end_time=fail_time + timedelta(minutes=2),
                focus_time=fail_time
            )

            # Fetch order book data around flip trigger
            flip_book = self._fetch_orderbook_snapshot(
                start_time=flip_time - timedelta(minutes=10),
                end_time=flip_time + timedelta(minutes=2),
                focus_time=flip_time
            )

            # Calculate metrics for failure phase
            fail_metrics = self._analyze_orderbook_phase(
                fail_book, level_price, original_type, phase='failure'
            )

            # Calculate metrics for flip phase
            flip_metrics = self._analyze_orderbook_phase(
                flip_book, level_price, flip_type, phase='flip'
            )

            # Compare the two phases
            comparison = self._compare_phases(fail_metrics, flip_metrics)

            # Assess overall quality
            quality_score = self._assess_flip_quality(
                fail_metrics, flip_metrics, comparison
            )

            # Build comprehensive result
            result = {
                'level_price': level_price,
                'original_type': original_type,
                'flip_type': flip_type,
                'fail_time': fail_time,
                'flip_time': flip_time,
                'time_between': (flip_time - fail_time).total_seconds() / 60,  # minutes

                # Phase metrics
                'failure_phase': fail_metrics,
                'flip_phase': flip_metrics,

                # Comparison metrics
                'liquidity_shift': comparison['liquidity_shift'],
                'absorption_delta': comparison['absorption_delta'],
                'imbalance_improvement': comparison['imbalance_improvement'],
                'large_order_shift': comparison['large_order_shift'],

                # Overall assessment
                'quality_score': quality_score['score'],
                'quality_rating': quality_score['rating'],
                'confidence': quality_score['confidence'],
                'recommendation': quality_score['recommendation']
            }

            # Store result
            self.flip_analyses.append(result)

            logging.info(f"✅ Analysis complete: {quality_score['rating']} quality")
            logging.info(f"   Score: {quality_score['score']:.1f}/100")

            return result

        except Exception as e:
            logging.error(f"❌ Error analyzing flip level: {e}")
            return None

    def track_level_failure(self, level_price, fail_time, original_type):
        """
        Track a level failure for future flip analysis

        Call this when a level reaches FAILED state in the backtest.
        Stores metadata for later analysis when/if the flip triggers.

        Args:
            level_price: Price level that failed
            fail_time: Timestamp of failure
            original_type: 'SUP' or 'RES'
        """
        key = f"{level_price:.2f}"
        self.pending_flips[key] = {
            'price': level_price,
            'fail_time': fail_time,
            'original_type': original_type,
            'flip_type': 'RES' if original_type == 'SUP' else 'SUP'
        }
        logging.debug(f"📊 Tracking failed level: {level_price:.2f} {original_type}")

    def process_flip_signal(self, signal, flip_time):
        """
        Process a flip signal and run analysis if we tracked its failure

        Call this when a FLIP signal fires in the backtest.
        If we previously tracked this level's failure, run full analysis.

        Args:
            signal: Signal dictionary from backtest
            flip_time: Timestamp when flip signal fired

        Returns:
            Analysis result dict, or None if level wasn't tracked
        """
        level_price = signal.get('price')
        key = f"{level_price:.2f}"

        if key in self.pending_flips:
            pending = self.pending_flips[key]

            # Run full analysis
            analysis = self.analyze_flip_level(
                level_price=pending['price'],
                fail_time=pending['fail_time'],
                flip_time=flip_time,
                original_type=pending['original_type'],
                flip_type=pending['flip_type']
            )

            # Remove from pending
            del self.pending_flips[key]

            return analysis
        else:
            logging.warning(f"⚠️ FLIP signal at {level_price:.2f} but no tracked failure")
            return None

    # ==========================================================================
    # ORDER BOOK DATA FETCHING
    # ==========================================================================

    def _fetch_orderbook_snapshot(self, start_time, end_time, focus_time):
        """
        Fetch Level 2 order book data for a time window

        Args:
            start_time: Start of window
            end_time: End of window
            focus_time: The key moment we're analyzing (failure or flip)

        Returns:
            DataFrame with order book data

        TODO: Implement actual Databento MBP-10 fetching
        Currently returns mock data structure
        """
        logging.debug(f"Fetching order book: {start_time} to {end_time}")

        # TODO: Implement real Databento fetch
        # Example implementation:
        """
        try:
            book_data = self.client.timeseries.get_range(
                dataset="GLBX.MDP3",
                schema="mbp-10",  # Market by price, 10 levels
                symbols=[self.symbol],
                stype_in="continuous",
                start=start_time,
                end=end_time
            ).to_df()

            return book_data
        except Exception as e:
            logging.error(f"Error fetching order book: {e}")
            return pd.DataFrame()
        """

        # For now, return empty DataFrame
        # This allows the skeleton to be tested without actual data
        return pd.DataFrame()

    # ==========================================================================
    # ORDER BOOK ANALYSIS METHODS
    # ==========================================================================

    def _analyze_orderbook_phase(self, book_data, level_price, level_type, phase='failure'):
        """
        Analyze order book for a specific phase (failure or flip)

        Args:
            book_data: Order book DataFrame
            level_price: Price level being analyzed
            level_type: 'SUP' or 'RES'
            phase: 'failure' or 'flip'

        Returns:
            Dictionary with phase metrics
        """
        if book_data.empty:
            # Return empty metrics if no data
            return self._empty_phase_metrics()

        # Calculate key metrics
        metrics = {
            'phase': phase,
            'level_type': level_type,

            # Liquidity metrics
            'total_bid_size': self._calculate_total_bid_size(book_data, level_price),
            'total_ask_size': self._calculate_total_ask_size(book_data, level_price),
            'total_liquidity': 0,  # Will be sum of above

            # Absorption at level
            'absorption_at_level': self._calculate_absorption_at_level(
                book_data, level_price, level_type
            ),

            # Order book imbalance
            'bid_ask_ratio': 0,  # Will be calculated
            'imbalance_score': self._calculate_imbalance(book_data, level_price),

            # Large orders
            'large_bids': self._count_large_orders(book_data, level_price, 'bid'),
            'large_asks': self._count_large_orders(book_data, level_price, 'ask'),
            'total_large_orders': 0,  # Will be sum

            # Order book depth quality
            'depth_quality': self._assess_depth_quality(book_data, level_price, level_type),

            # Aggressive flow
            'aggressive_buy_volume': self._calculate_aggressive_volume(book_data, 'buy'),
            'aggressive_sell_volume': self._calculate_aggressive_volume(book_data, 'sell'),

            # Book stability
            'pulled_orders': self._detect_pulled_orders(book_data, level_price),
        }

        # Calculate derived metrics
        metrics['total_liquidity'] = metrics['total_bid_size'] + metrics['total_ask_size']
        metrics['total_large_orders'] = metrics['large_bids'] + metrics['large_asks']

        if metrics['total_ask_size'] > 0:
            metrics['bid_ask_ratio'] = metrics['total_bid_size'] / metrics['total_ask_size']
        else:
            metrics['bid_ask_ratio'] = 99.0  # Infinite bid dominance

        return metrics

    def _empty_phase_metrics(self):
        """Return empty metrics structure when no data available"""
        return {
            'phase': 'unknown',
            'level_type': 'UNKNOWN',
            'total_bid_size': 0,
            'total_ask_size': 0,
            'total_liquidity': 0,
            'absorption_at_level': 0,
            'bid_ask_ratio': 1.0,
            'imbalance_score': 0,
            'large_bids': 0,
            'large_asks': 0,
            'total_large_orders': 0,
            'depth_quality': 'UNKNOWN',
            'aggressive_buy_volume': 0,
            'aggressive_sell_volume': 0,
            'pulled_orders': 0,
        }

    def _calculate_total_bid_size(self, book_data, level_price):
        """
        Calculate total bid size within proximity of level

        TODO: Implement with real order book data
        """
        # Placeholder
        return 0

    def _calculate_total_ask_size(self, book_data, level_price):
        """
        Calculate total ask size within proximity of level

        TODO: Implement with real order book data
        """
        # Placeholder
        return 0

    def _calculate_absorption_at_level(self, book_data, level_price, level_type):
        """
        Calculate how much volume was absorbed exactly at the level

        For SUP: Look at bid size at level_price
        For RES: Look at ask size at level_price

        TODO: Implement with real order book data
        """
        # Placeholder
        return 0

    def _calculate_imbalance(self, book_data, level_price):
        """
        Calculate order book imbalance near the level

        Returns:
            Float from -1.0 (ask dominated) to +1.0 (bid dominated)

        TODO: Implement with real order book data
        """
        # Placeholder
        return 0.0

    def _count_large_orders(self, book_data, level_price, side):
        """
        Count large orders (>threshold) near the level

        Args:
            book_data: Order book data
            level_price: Price level
            side: 'bid' or 'ask'

        Returns:
            Integer count of large orders

        TODO: Implement with real order book data
        """
        # Placeholder
        return 0

    def _assess_depth_quality(self, book_data, level_price, level_type):
        """
        Assess overall order book depth quality

        Returns:
            String: 'STRONG' | 'MODERATE' | 'WEAK' | 'VERY_WEAK'

        Criteria:
        - STRONG: Deep book, stacked orders, minimal imbalance
        - MODERATE: Decent depth but some imbalance
        - WEAK: Thin book or large imbalances
        - VERY_WEAK: Extremely thin, high risk of false signals

        TODO: Implement with real metrics
        """
        # Placeholder - return MODERATE for now
        return 'MODERATE'

    def _calculate_aggressive_volume(self, book_data, direction):
        """
        Calculate aggressive (market order) volume in direction

        Aggressive volume indicates market orders that crossed the spread,
        showing strong conviction to get filled immediately.

        Args:
            book_data: Trade data DataFrame (NOT order book, despite parameter name)
                      Should contain 'side' and 'size' columns from Databento trades
            direction: 'buy' or 'sell'

        Returns:
            Integer: Total aggressive volume in the specified direction

        Note: This function is somewhat misnamed - it should accept trade data
        rather than order book data. Trade data contains the aggressor side flag.

        In Databento trade data:
        - 'side' field: 'A' = trade at ask (buyer-initiated/aggressive buy)
                       'B' = trade at bid (seller-initiated/aggressive sell)
        - 'size' field: Contract quantity for the trade
        """
        if book_data.empty:
            return 0

        # Check if we have required columns
        if 'side' not in book_data.columns or 'size' not in book_data.columns:
            logging.warning("Trade data missing 'side' or 'size' columns - cannot calculate aggressive volume")
            return 0

        try:
            if direction == 'buy':
                # Aggressive buys: trades at ask (side == 'A')
                aggressive_trades = book_data[book_data['side'] == 'A']
                return int(aggressive_trades['size'].sum())

            elif direction == 'sell':
                # Aggressive sells: trades at bid (side == 'B')
                aggressive_trades = book_data[book_data['side'] == 'B']
                return int(aggressive_trades['size'].sum())

            else:
                logging.warning(f"Invalid direction: {direction}. Must be 'buy' or 'sell'")
                return 0

        except Exception as e:
            logging.error(f"Error calculating aggressive volume: {e}")
            return 0

    def _detect_pulled_orders(self, book_data, level_price):
        """
        Detect orders that were placed then pulled before execution

        This is a bearish sign - indicates lack of conviction

        TODO: Requires tracking order additions/cancellations
        """
        # Placeholder
        return 0

    # ==========================================================================
    # COMPARISON AND QUALITY ASSESSMENT
    # ==========================================================================

    def _compare_phases(self, fail_metrics, flip_metrics):
        """
        Compare failure phase vs flip phase to identify improvements

        Args:
            fail_metrics: Metrics from failure phase
            flip_metrics: Metrics from flip phase

        Returns:
            Dictionary with comparison metrics
        """
        comparison = {
            # Liquidity changes
            'liquidity_shift': flip_metrics['total_liquidity'] - fail_metrics['total_liquidity'],
            'liquidity_shift_pct': 0,

            # Absorption changes
            'absorption_delta': flip_metrics['absorption_at_level'] - fail_metrics['absorption_at_level'],
            'absorption_delta_pct': 0,

            # Imbalance improvement
            'imbalance_improvement': self._calculate_imbalance_improvement(
                fail_metrics, flip_metrics
            ),

            # Large order changes
            'large_order_shift': flip_metrics['total_large_orders'] - fail_metrics['total_large_orders'],

            # Depth quality change
            'depth_improved': self._compare_depth_quality(
                fail_metrics['depth_quality'],
                flip_metrics['depth_quality']
            ),
        }

        # Calculate percentages
        if fail_metrics['total_liquidity'] > 0:
            comparison['liquidity_shift_pct'] = (
                comparison['liquidity_shift'] / fail_metrics['total_liquidity'] * 100
            )

        if fail_metrics['absorption_at_level'] > 0:
            comparison['absorption_delta_pct'] = (
                comparison['absorption_delta'] / fail_metrics['absorption_at_level'] * 100
            )

        return comparison

    def _calculate_imbalance_improvement(self, fail_metrics, flip_metrics):
        """
        Calculate whether imbalance improved in favor of new level type

        For SUP flip: Want bid_ask_ratio to increase (more bids)
        For RES flip: Want bid_ask_ratio to decrease (more asks)

        Returns:
            Float: Positive = improved, Negative = deteriorated
        """
        flip_type = flip_metrics['level_type']

        if flip_type == 'SUP':
            # Want higher bid/ask ratio
            return flip_metrics['bid_ask_ratio'] - fail_metrics['bid_ask_ratio']
        else:  # RES
            # Want lower bid/ask ratio (more asks)
            return fail_metrics['bid_ask_ratio'] - flip_metrics['bid_ask_ratio']

    def _compare_depth_quality(self, fail_quality, flip_quality):
        """
        Compare depth quality ratings

        Returns:
            Boolean: True if quality improved
        """
        quality_rank = {
            'VERY_WEAK': 0,
            'WEAK': 1,
            'MODERATE': 2,
            'STRONG': 3,
            'UNKNOWN': 1  # Treat unknown as weak
        }

        fail_rank = quality_rank.get(fail_quality, 1)
        flip_rank = quality_rank.get(flip_quality, 1)

        return flip_rank > fail_rank

    def _assess_flip_quality(self, fail_metrics, flip_metrics, comparison):
        """
        Assess overall FLIP signal quality based on all metrics

        Returns:
            Dictionary with:
            - score: 0-100 quality score
            - rating: 'EXCELLENT' | 'GOOD' | 'FAIR' | 'POOR'
            - confidence: 'HIGH' | 'MEDIUM' | 'LOW'
            - recommendation: 'TAKE' | 'CONSIDER' | 'SKIP'
        """
        score = 50.0  # Start at neutral

        # Factor 1: Liquidity improvement (+/- 20 points)
        if comparison['liquidity_shift'] > 0:
            score += min(20, comparison['liquidity_shift_pct'] / 5)
        else:
            score += max(-20, comparison['liquidity_shift_pct'] / 5)

        # Factor 2: Absorption strength (+/- 15 points)
        if flip_metrics['absorption_at_level'] > fail_metrics['absorption_at_level']:
            score += 15
        else:
            score -= 10

        # Factor 3: Depth quality (+/- 15 points)
        depth_scores = {'VERY_WEAK': -15, 'WEAK': -5, 'MODERATE': 5, 'STRONG': 15}
        score += depth_scores.get(flip_metrics['depth_quality'], 0)

        # Factor 4: Large order support (+/- 10 points)
        if comparison['large_order_shift'] > 0:
            score += min(10, comparison['large_order_shift'] * 2)
        else:
            score -= 5

        # Factor 5: Imbalance improvement (+/- 10 points)
        if comparison['imbalance_improvement'] > 0:
            score += min(10, comparison['imbalance_improvement'] * 10)
        else:
            score -= 10

        # Clamp score to 0-100
        score = max(0, min(100, score))

        # Determine rating
        if score >= 75:
            rating = 'EXCELLENT'
            confidence = 'HIGH'
            recommendation = 'TAKE'
        elif score >= 60:
            rating = 'GOOD'
            confidence = 'HIGH'
            recommendation = 'TAKE'
        elif score >= 45:
            rating = 'FAIR'
            confidence = 'MEDIUM'
            recommendation = 'CONSIDER'
        elif score >= 30:
            rating = 'POOR'
            confidence = 'LOW'
            recommendation = 'SKIP'
        else:
            rating = 'VERY_POOR'
            confidence = 'LOW'
            recommendation = 'SKIP'

        return {
            'score': score,
            'rating': rating,
            'confidence': confidence,
            'recommendation': recommendation
        }

    # ==========================================================================
    # REPORTING AND VISUALIZATION
    # ==========================================================================

    def generate_summary_report(self):
        """
        Generate summary report of all analyzed FLIP events

        Returns:
            DataFrame with summary statistics
        """
        if not self.flip_analyses:
            print("❌ No FLIP analyses to report")
            return pd.DataFrame()

        print("\n" + "="*80)
        print("📊 ORDER BOOK FLIP ANALYSIS SUMMARY")
        print("="*80)

        df = pd.DataFrame(self.flip_analyses)

        # Overall stats
        print(f"\n📈 OVERALL STATISTICS")
        print(f"   Total FLIPs Analyzed: {len(df)}")
        print(f"   Average Quality Score: {df['quality_score'].mean():.1f}/100")

        # Rating distribution
        print(f"\n⭐ QUALITY DISTRIBUTION")
        for rating in ['EXCELLENT', 'GOOD', 'FAIR', 'POOR', 'VERY_POOR']:
            count = len(df[df['quality_rating'] == rating])
            pct = (count / len(df) * 100) if len(df) > 0 else 0
            print(f"   {rating:12s}: {count:3d} ({pct:5.1f}%)")

        # Recommendation breakdown
        print(f"\n💡 RECOMMENDATIONS")
        for rec in ['TAKE', 'CONSIDER', 'SKIP']:
            count = len(df[df['recommendation'] == rec])
            pct = (count / len(df) * 100) if len(df) > 0 else 0
            print(f"   {rec:10s}: {count:3d} ({pct:5.1f}%)")

        # Liquidity insights
        print(f"\n💰 LIQUIDITY INSIGHTS")
        print(f"   Avg Liquidity Shift: {df['liquidity_shift'].mean():+,.0f} contracts")
        print(f"   Avg Absorption Delta: {df['absorption_delta'].mean():+,.0f} contracts")

        return df

    def export_to_csv(self, filename='flip_orderbook_analysis.csv'):
        """
        Export analysis results to CSV

        Args:
            filename: Output CSV filename
        """
        if not self.flip_analyses:
            logging.warning("No analyses to export")
            return

        df = pd.DataFrame(self.flip_analyses)

        # Flatten nested dicts
        # TODO: Expand nested failure_phase and flip_phase dicts

        df.to_csv(filename, index=False)
        logging.info(f"✅ Exported {len(df)} analyses to {filename}")

    def plot_quality_distribution(self, save_path='flip_quality_distribution.png'):
        """
        Plot distribution of FLIP quality scores

        Args:
            save_path: Where to save the chart
        """
        if plt is None or sns is None:
            logging.warning("matplotlib/seaborn not available - skipping plot generation")
            print("⚠️  matplotlib/seaborn not installed - cannot generate quality chart")
            print("   Install with: pip install matplotlib seaborn")
            return

        if not self.flip_analyses:
            logging.warning("No analyses to plot")
            return

        df = pd.DataFrame(self.flip_analyses)

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        # Histogram of quality scores
        axes[0].hist(df['quality_score'], bins=20, color='steelblue', edgecolor='black')
        axes[0].set_title('FLIP Quality Score Distribution', fontweight='bold')
        axes[0].set_xlabel('Quality Score (0-100)')
        axes[0].set_ylabel('Frequency')
        axes[0].axvline(df['quality_score'].mean(), color='red',
                        linestyle='--', label=f'Mean: {df["quality_score"].mean():.1f}')
        axes[0].legend()
        axes[0].grid(alpha=0.3)

        # Rating counts
        rating_order = ['VERY_POOR', 'POOR', 'FAIR', 'GOOD', 'EXCELLENT']
        rating_counts = df['quality_rating'].value_counts().reindex(rating_order, fill_value=0)

        colors = ['#e74c3c', '#e67e22', '#f39c12', '#2ecc71', '#27ae60']
        axes[1].bar(range(len(rating_counts)), rating_counts.values, color=colors)
        axes[1].set_xticks(range(len(rating_counts)))
        axes[1].set_xticklabels(rating_counts.index, rotation=45)
        axes[1].set_title('FLIP Quality Rating Breakdown', fontweight='bold')
        axes[1].set_ylabel('Count')
        axes[1].grid(axis='y', alpha=0.3)

        plt.tight_layout()
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        logging.info(f"✅ Quality distribution chart saved to {save_path}")
        plt.close()


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def create_analyzer_from_api_key(api_key, symbol="ES.c.0"):
    """
    Convenience function to create analyzer with Databento API key

    Args:
        api_key: Databento API key string
        symbol: Trading instrument

    Returns:
        OrderBookFlipAnalyzer instance
    """
    client = db.Historical(api_key)
    return OrderBookFlipAnalyzer(client, symbol=symbol)


# ==============================================================================
# EXAMPLE USAGE
# ==============================================================================

if __name__ == "__main__":
    # Example: How to use the analyzer

    print("="*80)
    print("OrderBook FLIP Analyzer - Skeleton Demo")
    print("="*80)

    # NOTE: This is a skeleton. Real usage requires:
    # 1. Valid Databento API key
    # 2. Implementing _fetch_orderbook_snapshot() with actual MBP data
    # 3. Implementing calculation methods with real order book data

    print("\nTo use this analyzer:")
    print("1. Set up Databento API key")
    print("2. Implement order book data fetching")
    print("3. Integrate with backtest framework")
    print("\nSee orderbook_analysis_design.md for full implementation plan")
