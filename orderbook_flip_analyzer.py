"""
OrderBook FLIP Analyzer
Analyzes Level 2/3 order book data and Trade data around FLIP signals.
Measures Resting Liquidity vs. True Absorption to validate signal quality.

Required dependencies: pandas, numpy, databento, matplotlib, seaborn, pytz
Install with: pip install pandas numpy databento matplotlib seaborn pytz
"""

import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import databento as db
import matplotlib.pyplot as plt
import seaborn as sns
import pytz

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class OrderBookFlipAnalyzer:
    """
    Analyze order book dynamics and order flow around FLIP level events.
    """

    def __init__(self, databento_client, symbol="ES.c.0", tick_proximity=5):
        self.client = databento_client
        self.symbol = symbol
        self.tick_proximity = tick_proximity
        self.flip_analyses = []
        self.pending_flips = {}

        # Instrument settings
        self.tick_size = self._get_tick_size(symbol)
        self.large_order_threshold = self._get_large_order_threshold(symbol)
        self.absorption_thresholds = self._get_absorption_thresholds(symbol)

        logging.info(f"OrderBookFlipAnalyzer initialized for {symbol}")
        logging.info(f"  Tick size: {self.tick_size}")
        logging.info(f"  Large order threshold: {self.large_order_threshold} contracts")
        logging.info(f"  Absorption thresholds: High={self.absorption_thresholds['high']}, Medium={self.absorption_thresholds['medium']}")

    def _get_tick_size(self, symbol):
        """Get tick size for symbol (hardcoded for common futures)"""
        # Known tick sizes for CME futures
        if symbol.startswith("ES"):
            return 0.25
        elif symbol.startswith("NQ"):
            return 0.25
        elif symbol.startswith("GC"):
            return 0.10
        elif symbol.startswith("CL"):
            return 0.01
        else:
            logging.warning(f"Unknown symbol {symbol}, defaulting tick size to 0.25")
            return 0.25

    def _get_large_order_threshold(self, symbol):
        """Get threshold for what constitutes a 'large' order"""
        if symbol.startswith("ES"):
            return 100
        elif symbol.startswith("NQ"):
            return 100
        elif symbol.startswith("GC"):
            return 50
        else:
            return 100

    def _get_absorption_thresholds(self, symbol):
        """
        Get instrument-specific thresholds for true absorption scoring.

        Returns dict with 'high' and 'medium' thresholds in contracts.
        """
        if symbol.startswith("ES"):
            return {'high': 500, 'medium': 200}
        elif symbol.startswith("NQ"):
            return {'high': 300, 'medium': 100}
        elif symbol.startswith("GC"):
            return {'high': 100, 'medium': 50}
        else:
            return {'high': 500, 'medium': 200}

    # ==========================================================================
    # MAIN ANALYSIS METHOD
    # ==========================================================================

    def analyze_flip_level(self, level_price, fail_time, flip_time,
                           original_type='RES', flip_type='SUP'):
        """
        Analyze order book and trades around a single FLIP event.
        """
        logging.info(f"\n{'='*60}")
        logging.info(f"Analyzing FLIP: {level_price:.2f} ({original_type}→{flip_type})")
        logging.info(f"  Failure time: {fail_time}")
        logging.info(f"  Flip time: {flip_time}")
        logging.info(f"{'='*60}")

        try:
            # 1. Fetch Data (Book + Trades) for Failure Phase
            logging.info("Fetching failure phase data...")
            fail_book = self._fetch_orderbook_snapshot(
                start_time=fail_time - timedelta(minutes=10),
                end_time=fail_time + timedelta(minutes=2),
                focus_time=fail_time
            )
            fail_trades = self._fetch_trades_snapshot(
                start_time=fail_time - timedelta(minutes=10),
                end_time=fail_time + timedelta(minutes=2)
            )
            logging.info(f"  Order book records: {len(fail_book)}, Trade records: {len(fail_trades)}")

            # 2. Fetch Data (Book + Trades) for Flip Phase
            logging.info("Fetching flip phase data...")
            flip_book = self._fetch_orderbook_snapshot(
                start_time=flip_time - timedelta(minutes=10),
                end_time=flip_time + timedelta(minutes=2),
                focus_time=flip_time
            )
            flip_trades = self._fetch_trades_snapshot(
                start_time=flip_time - timedelta(minutes=10),
                end_time=flip_time + timedelta(minutes=2)
            )
            logging.info(f"  Order book records: {len(flip_book)}, Trade records: {len(flip_trades)}")

            # 3. Calculate Metrics
            logging.info("Calculating failure phase metrics...")
            fail_metrics = self._analyze_phase(
                fail_book, fail_trades, level_price, original_type, phase='failure'
            )

            logging.info("Calculating flip phase metrics...")
            flip_metrics = self._analyze_phase(
                flip_book, flip_trades, level_price, flip_type, phase='flip'
            )

            # 4. Compare & Score
            logging.info("Comparing phases and scoring quality...")
            comparison = self._compare_phases(fail_metrics, flip_metrics)
            quality_score = self._assess_flip_quality(fail_metrics, flip_metrics, comparison)

            # 5. Build Result
            result = {
                'level_price': level_price,
                'original_type': original_type,
                'flip_type': flip_type,
                'fail_time': fail_time,
                'flip_time': flip_time,
                'time_between': (flip_time - fail_time).total_seconds() / 60,
                'failure_phase': fail_metrics,
                'flip_phase': flip_metrics,
                'comparison': comparison,
                'quality_score': quality_score['score'],
                'quality_rating': quality_score['rating'],
                'confidence': quality_score['confidence'],
                'recommendation': quality_score['recommendation']
            }
            self.flip_analyses.append(result)

            logging.info(f"✅ Analysis complete: {quality_score['rating']} ({quality_score['score']:.1f}/100)")
            logging.info(f"   Confidence: {quality_score['confidence']} | Recommendation: {quality_score['recommendation']}")
            return result

        except Exception as e:
            logging.error(f"❌ Error analyzing flip level: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ==========================================================================
    # PENDING FLIP TRACKING
    # ==========================================================================

    def track_level_failure(self, level_price, fail_time, original_type):
        """
        Track a level failure for future flip analysis.
        Call this when a level reaches FAILED state in the backtest.
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
        Process a flip signal and run analysis if we tracked its failure.
        Call this when a FLIP signal fires in the backtest.
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
    # TRADE ENTRY/EXIT ANALYSIS (NEW)
    # ==========================================================================

    def analyze_trade_point(self, price, timestamp, direction, point_type='entry'):
        """
        Analyze orderbook quality at a trade entry or exit point.

        Args:
            price: Price level to analyze
            timestamp: When the trade event occurred
            direction: 'LONG' or 'SHORT'
            point_type: 'entry' or 'exit'

        Returns:
            Dictionary with orderbook metrics, or None if data unavailable
        """
        try:
            # Fetch orderbook snapshot (5 min before, 1 min after)
            book_data = self._fetch_orderbook_snapshot(
                start_time=timestamp - timedelta(minutes=5),
                end_time=timestamp + timedelta(minutes=1),
                focus_time=timestamp
            )

            # Fetch trade data for same window
            trade_data = self._fetch_trades_snapshot(
                start_time=timestamp - timedelta(minutes=5),
                end_time=timestamp + timedelta(minutes=1)
            )

            if book_data.empty and trade_data.empty:
                logging.warning(f"No orderbook data available for {point_type} at {price:.2f}")
                return None

            # Determine level type based on direction
            level_type = 'SUP' if direction == 'LONG' else 'RES'

            # Calculate all metrics using existing _analyze_phase method
            metrics = self._analyze_phase(
                book_data, trade_data, price, level_type, phase=point_type
            )

            # Add some context
            metrics['price'] = price
            metrics['timestamp'] = timestamp
            metrics['direction'] = direction
            metrics['point_type'] = point_type

            return metrics

        except Exception as e:
            logging.warning(f"Error analyzing {point_type} point at {price:.2f}: {e}")
            return None

    def analyze_trade_entry(self, entry_price, entry_time, direction):
        """Convenience method for analyzing trade entries."""
        return self.analyze_trade_point(entry_price, entry_time, direction, point_type='entry')

    def analyze_trade_exit(self, exit_price, exit_time, direction, exit_reason):
        """
        Convenience method for analyzing trade exits.
        Includes exit reason context.
        """
        metrics = self.analyze_trade_point(exit_price, exit_time, direction, point_type='exit')
        if metrics:
            metrics['exit_reason'] = exit_reason
        return metrics

    # ==========================================================================
    # DATA FETCHING
    # ==========================================================================

    def _fetch_orderbook_snapshot(self, start_time, end_time, focus_time):
        """Fetch Level 2 order book data (MBP-10 schema)"""
        try:
            data = self.client.timeseries.get_range(
                dataset="GLBX.MDP3",
                schema="mbp-10",
                symbols=[self.symbol],
                stype_in="continuous",
                start=start_time,
                end=end_time
            ).to_df()

            # Check for expected columns
            if not data.empty and 'bid_px_00' not in data.columns:
                logging.warning("Expected MBP-10 columns not found in order book data")
                logging.warning(f"Available columns: {list(data.columns)}")
                return pd.DataFrame()

            return data
        except Exception as e:
            logging.warning(f"Orderbook fetch failed: {e}")
            return pd.DataFrame()

    def _fetch_trades_snapshot(self, start_time, end_time):
        """
        Fetch Trade & Sales data to calculate aggressive volume and true absorption.
        Returns DataFrame with 'price', 'size', 'side' columns.
        """
        try:
            data = self.client.timeseries.get_range(
                dataset="GLBX.MDP3",
                schema="trades",
                symbols=[self.symbol],
                stype_in="continuous",
                start=start_time,
                end=end_time
            ).to_df()

            # Check for price conversion (Databento fixed-point format)
            if not data.empty and 'price' in data.columns:
                sample_price = data['price'].iloc[0]
                if sample_price > 1000000:
                    logging.warning(f"Trade prices appear to be in fixed-point format (sample: {sample_price})")
                    logging.warning("Converting prices from fixed-point (dividing by 1e9)")
                    data['price'] = data['price'] / 1e9

            # Validate required columns
            if not data.empty:
                required_cols = ['price', 'size', 'side']
                missing = [col for col in required_cols if col not in data.columns]
                if missing:
                    logging.warning(f"Trade data missing columns: {missing}")
                    logging.warning(f"Available columns: {list(data.columns)}")

            return data
        except Exception as e:
            logging.warning(f"Trade data fetch failed: {e}")
            return pd.DataFrame()

    # ==========================================================================
    # CORE METRICS CALCULATIONS
    # ==========================================================================

    def _analyze_phase(self, book_data, trade_data, level_price, level_type, phase):
        """Calculate all metrics for a specific phase."""
        if book_data.empty and trade_data.empty:
            logging.warning(f"No data available for {phase} phase")
            return self._empty_metrics(phase, level_type)

        metrics = {
            'phase': phase,
            'level_type': level_type,

            # -- Resting Liquidity (Order Book) --
            'resting_liquidity': self._calculate_resting_liquidity(book_data, level_price, level_type),
            'total_bid_depth': self._calculate_total_bid_size(book_data, level_price),
            'total_ask_depth': self._calculate_total_ask_size(book_data, level_price),
            'imbalance_score': self._calculate_imbalance(book_data, level_price),
            'large_orders': self._count_large_orders(book_data, level_price),

            # -- Execution Flow (Trades) --
            'true_absorption': self._calculate_true_absorption(trade_data, level_price),
            'aggressive_buy_vol': self._calculate_aggressive_volume(trade_data, 'buy'),
            'aggressive_sell_vol': self._calculate_aggressive_volume(trade_data, 'sell'),
        }

        # Assess depth quality based on Resting Liquidity
        metrics['depth_quality'] = self._assess_depth_quality(metrics)

        # Log phase summary
        logging.info(f"  {phase.upper()} phase metrics:")
        logging.info(f"    Resting liquidity: {metrics['resting_liquidity']} contracts")
        logging.info(f"    True absorption: {metrics['true_absorption']} contracts")
        logging.info(f"    Bid depth: {metrics['total_bid_depth']}, Ask depth: {metrics['total_ask_depth']}")
        logging.info(f"    Aggressive buy: {metrics['aggressive_buy_vol']}, Aggressive sell: {metrics['aggressive_sell_vol']}")
        logging.info(f"    Depth quality: {metrics['depth_quality']}")

        return metrics

    def _calculate_resting_liquidity(self, book_data, level_price, level_type):
        """
        Calculate volume SITTING at the level (Limit Orders).
        This represents passive liquidity resting in the book.
        """
        if book_data.empty:
            return 0

        snapshot = book_data.iloc[-1]
        resting_vol = 0

        # Use epsilon for float comparison (half a tick)
        epsilon = self.tick_size / 2

        if level_type == 'SUP':
            # Look for bids at the support level
            for i in range(10):
                px = snapshot.get(f'bid_px_{i:02d}', 0)
                sz = snapshot.get(f'bid_sz_{i:02d}', 0)
                if abs(px - level_price) < epsilon:
                    resting_vol += sz
        else:  # RES
            # Look for asks at the resistance level
            for i in range(10):
                px = snapshot.get(f'ask_px_{i:02d}', 0)
                sz = snapshot.get(f'ask_sz_{i:02d}', 0)
                if abs(px - level_price) < epsilon:
                    resting_vol += sz

        return int(resting_vol)

    def _calculate_true_absorption(self, trade_data, level_price):
        """
        Calculate volume TRADED exactly at the level (Passive Fills).
        This represents aggressive traders hitting the level but failing to move it.

        Critical for FLIP analysis: High absorption = strong level defense.
        """
        if trade_data.empty:
            return 0

        # ✅ FIX: Use tick_size/2 as epsilon instead of 1e-4
        epsilon = self.tick_size / 2

        # Filter for trades occurring exactly at the level
        at_level = trade_data[abs(trade_data['price'] - level_price) < epsilon]

        total_absorbed = int(at_level['size'].sum())
        num_trades = len(at_level)

        logging.debug(f"  True absorption at {level_price:.2f}: {total_absorbed} contracts ({num_trades} trades)")

        return total_absorbed

    def _calculate_aggressive_volume(self, trade_data, direction):
        """
        Calculate aggressive (market order) volume by direction using Trade data.

        Args:
            trade_data: DataFrame with 'side' and 'size' columns
            direction: 'buy' or 'sell'

        Returns:
            Integer: Total aggressive volume in the specified direction
        """
        if trade_data.empty:
            return 0

        # ✅ Defensive check for required columns
        if 'side' not in trade_data.columns or 'size' not in trade_data.columns:
            logging.warning("Trade data missing 'side' or 'size' columns - cannot calculate aggressive volume")
            return 0

        try:
            if direction == 'buy':
                # Aggressive buys: trades at ask (side='A' in Databento)
                aggressive_trades = trade_data[trade_data['side'] == 'A']

                # Fallback for alternative encodings
                if len(aggressive_trades) == 0:
                    aggressive_trades = trade_data[
                        (trade_data['side'] == 1) | (trade_data['side'] == 'Buy')
                    ]

                return int(aggressive_trades['size'].sum())

            elif direction == 'sell':
                # Aggressive sells: trades at bid (side='B' in Databento)
                aggressive_trades = trade_data[trade_data['side'] == 'B']

                # Fallback for alternative encodings
                if len(aggressive_trades) == 0:
                    aggressive_trades = trade_data[
                        (trade_data['side'] == 2) | (trade_data['side'] == 'Sell')
                    ]

                return int(aggressive_trades['size'].sum())

            else:
                logging.warning(f"Invalid direction: {direction}. Must be 'buy' or 'sell'")
                return 0

        except Exception as e:
            logging.error(f"Error calculating aggressive volume: {e}")
            return 0

    # ==========================================================================
    # HELPER CALCULATIONS
    # ==========================================================================

    def _calculate_total_bid_size(self, book_data, level_price):
        """Calculate total bid size within tick_proximity of level"""
        if book_data.empty:
            return 0

        snapshot = book_data.iloc[-1]
        total = 0
        limit = self.tick_size * self.tick_proximity

        for i in range(10):
            px = snapshot.get(f'bid_px_{i:02d}', 0)
            if abs(px - level_price) <= limit:
                total += snapshot.get(f'bid_sz_{i:02d}', 0)

        return int(total)

    def _calculate_total_ask_size(self, book_data, level_price):
        """Calculate total ask size within tick_proximity of level"""
        if book_data.empty:
            return 0

        snapshot = book_data.iloc[-1]
        total = 0
        limit = self.tick_size * self.tick_proximity

        for i in range(10):
            px = snapshot.get(f'ask_px_{i:02d}', 0)
            if abs(px - level_price) <= limit:
                total += snapshot.get(f'ask_sz_{i:02d}', 0)

        return int(total)

    def _calculate_imbalance(self, book_data, level_price):
        """
        Calculate order book imbalance near the level.
        Returns: Float from -1.0 (ask dominated) to +1.0 (bid dominated)
        """
        bid = self._calculate_total_bid_size(book_data, level_price)
        ask = self._calculate_total_ask_size(book_data, level_price)
        total = bid + ask

        if total == 0:
            return 0.0

        return (bid - ask) / total

    def _count_large_orders(self, book_data, level_price):
        """Count large orders (>threshold) near the level"""
        if book_data.empty:
            return 0

        snapshot = book_data.iloc[-1]
        count = 0
        limit = self.tick_size * self.tick_proximity

        # Check bids and asks
        for side in ['bid', 'ask']:
            for i in range(10):
                px = snapshot.get(f'{side}_px_{i:02d}', 0)
                sz = snapshot.get(f'{side}_sz_{i:02d}', 0)
                if abs(px - level_price) <= limit and sz >= self.large_order_threshold:
                    count += 1

        return count

    def _assess_depth_quality(self, metrics):
        """
        Assess order book depth quality based on liquidity and imbalance.
        Returns: 'STRONG' | 'MODERATE' | 'WEAK' | 'VERY_WEAK'
        """
        liq = metrics['total_bid_depth'] + metrics['total_ask_depth']
        resting = metrics['resting_liquidity']
        imbalance = abs(metrics['imbalance_score'])

        if liq > 2000 and resting > 500 and imbalance < 0.3:
            return 'STRONG'
        elif liq > 1000 and resting > 250:
            return 'MODERATE'
        elif liq > 500:
            return 'WEAK'

        return 'VERY_WEAK'

    def _empty_metrics(self, phase, level_type):
        """Return empty metrics structure when no data available"""
        return {
            'phase': phase,
            'level_type': level_type,
            'resting_liquidity': 0,
            'total_bid_depth': 0,
            'total_ask_depth': 0,
            'imbalance_score': 0,
            'large_orders': 0,
            'true_absorption': 0,
            'aggressive_buy_vol': 0,
            'aggressive_sell_vol': 0,
            'depth_quality': 'UNKNOWN'
        }

    # ==========================================================================
    # COMPARISON & SCORING
    # ==========================================================================

    def _compare_phases(self, fail, flip):
        """Compare failure phase vs flip phase to identify improvements"""
        return {
            'resting_liquidity_delta': flip['resting_liquidity'] - fail['resting_liquidity'],
            'true_absorption_delta': flip['true_absorption'] - fail['true_absorption'],
            'imbalance_improved': self._check_imbalance_improvement(fail, flip),
            'depth_improved': flip['depth_quality'] == 'STRONG' and fail['depth_quality'] != 'STRONG',
            'aggressive_flow_aligned': self._check_aggressive_flow_alignment(flip)
        }

    def _check_imbalance_improvement(self, fail, flip):
        """Check if imbalance improved in favor of new level type"""
        # If flipping to SUP, we want positive imbalance (more bids)
        if flip['level_type'] == 'SUP':
            return flip['imbalance_score'] > fail['imbalance_score']
        else:  # Flipping to RES, want negative imbalance (more asks)
            return flip['imbalance_score'] < fail['imbalance_score']

    def _check_aggressive_flow_alignment(self, flip):
        """Check if aggressive flow aligns with new level type"""
        if flip['level_type'] == 'SUP':
            # For SUP, want more aggressive buying
            return flip['aggressive_buy_vol'] > flip['aggressive_sell_vol']
        else:  # RES
            # For RES, want more aggressive selling
            return flip['aggressive_sell_vol'] > flip['aggressive_buy_vol']

    def _assess_flip_quality(self, fail, flip, comp):
        """
        Assess overall FLIP signal quality based on all metrics.

        Scoring factors:
        1. Resting Liquidity (Depth) - 25 points
        2. True Absorption (Execution) - 30 points
        3. Aggressive Flow Alignment - 20 points
        4. Order Book Imbalance - 15 points
        5. Depth Quality Improvement - 10 points

        Returns: Dict with score, rating, confidence, recommendation
        """
        score = 50  # Start at neutral

        # ✅ Use instrument-specific thresholds
        thresholds = self.absorption_thresholds

        # 1. Resting Liquidity (Depth) - Max 15 points
        if comp['resting_liquidity_delta'] > 0:
            score += 10
        if flip['depth_quality'] == 'STRONG':
            score += 15
        elif flip['depth_quality'] == 'MODERATE':
            score += 5

        # 2. True Absorption (Execution) - Max 20 points
        # High absorption at flip level = strong conviction
        if flip['true_absorption'] > thresholds['high']:
            score += 20
            logging.debug(f"  ✅ High absorption bonus: +20 (>{thresholds['high']} contracts)")
        elif flip['true_absorption'] > thresholds['medium']:
            score += 10
            logging.debug(f"  ✅ Medium absorption bonus: +10 (>{thresholds['medium']} contracts)")

        # 3. Aggressive Flow Alignment - Max 10 points
        if comp['aggressive_flow_aligned']:
            score += 10
            logging.debug("  ✅ Aggressive flow aligned: +10")

        # 4. Order Book Imbalance - Max 10 points
        if comp['imbalance_improved']:
            score += 10
            logging.debug("  ✅ Imbalance improved: +10")

        # 5. Depth Quality Improvement - Max 10 points
        if comp['depth_improved']:
            score += 10
            logging.debug("  ✅ Depth improved: +10")

        # Bonus: Both high resting AND high absorption (synergy)
        if flip['resting_liquidity'] > 300 and flip['true_absorption'] > thresholds['medium']:
            score += 5
            logging.debug("  ✅ Depth + Absorption synergy: +5")

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
    # REPORTING
    # ==========================================================================

    def generate_summary_report(self):
        """Generate summary report of all analyzed FLIP events"""
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
        print(f"   Average Time Between Fail→Flip: {df['time_between'].mean():.1f} minutes")

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

        print("="*80 + "\n")

        return df

    def export_to_csv(self, filename='flip_orderbook_analysis.csv'):
        """Export analysis results to CSV"""
        if not self.flip_analyses:
            logging.warning("No analyses to export")
            return

        # Flatten nested dicts for CSV export
        flat_data = []
        for analysis in self.flip_analyses:
            flat_row = {
                'level_price': analysis['level_price'],
                'original_type': analysis['original_type'],
                'flip_type': analysis['flip_type'],
                'time_between_min': analysis['time_between'],
                'quality_score': analysis['quality_score'],
                'quality_rating': analysis['quality_rating'],
                'confidence': analysis['confidence'],
                'recommendation': analysis['recommendation'],
            }

            # Add failure phase metrics
            for key, val in analysis['failure_phase'].items():
                flat_row[f'fail_{key}'] = val

            # Add flip phase metrics
            for key, val in analysis['flip_phase'].items():
                flat_row[f'flip_{key}'] = val

            # Add comparison metrics
            for key, val in analysis['comparison'].items():
                flat_row[f'comp_{key}'] = val

            flat_data.append(flat_row)

        df = pd.DataFrame(flat_data)
        df.to_csv(filename, index=False)
        logging.info(f"✅ Exported {len(df)} analyses to {filename}")

    def plot_quality_distribution(self, save_path='flip_quality_distribution.png'):
        """Plot distribution of FLIP quality scores"""
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
    print("="*80)
    print("OrderBook FLIP Analyzer - Enhanced Version")
    print("="*80)
    print("\nFeatures:")
    print("✅ Resting Liquidity (Order Book Depth)")
    print("✅ True Absorption (Actual Volume Traded at Level)")
    print("✅ Aggressive Flow Analysis (Buy vs Sell Pressure)")
    print("✅ Instrument-Specific Thresholds")
    print("✅ Comprehensive Quality Scoring")
    print("\nTo use this analyzer:")
    print("1. Set up Databento API key")
    print("2. Create analyzer: analyzer = create_analyzer_from_api_key(api_key, 'ES.c.0')")
    print("3. Track failures: analyzer.track_level_failure(price, time, 'SUP')")
    print("4. Process flips: analyzer.process_flip_signal(signal, time)")
    print("5. Generate report: analyzer.generate_summary_report()")
