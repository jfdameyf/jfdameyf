"""
Example: Integrating OrderBookFlipAnalyzer with Backtest Framework

This file shows how to integrate order book analysis into the existing
backtesting framework. Copy these patterns into your actual backtest files.
"""

from backtest_bot import TradingBotBacktester
from orderbook_flip_analyzer import OrderBookFlipAnalyzer, create_analyzer_from_api_key
from datetime import datetime, timedelta
import pytz

# ==============================================================================
# ENHANCED BACKTESTER WITH ORDER BOOK ANALYSIS
# ==============================================================================

class EnhancedBacktester(TradingBotBacktester):
    """
    Extended backtester that includes order book analysis for FLIP signals
    """

    def __init__(self, start_date, end_date, enable_poc_filter=False,
                 analyze_orderbook=False, databento_api_key=None):
        """
        Initialize enhanced backtester

        Args:
            start_date: Start of backtest period
            end_date: End of backtest period
            enable_poc_filter: Enable POC filtering
            analyze_orderbook: Enable order book analysis (requires API key)
            databento_api_key: Databento API key for order book data
        """
        # Initialize parent class
        super().__init__(start_date, end_date, enable_poc_filter)

        # Order book analysis
        self.analyze_orderbook = analyze_orderbook
        self.ob_analyzer = None

        if analyze_orderbook:
            if not databento_api_key:
                print("⚠️  Order book analysis enabled but no API key provided")
                print("   Set databento_api_key parameter to enable")
                self.analyze_orderbook = False
            else:
                print("📊 Initializing Order Book Analyzer...")
                self.ob_analyzer = create_analyzer_from_api_key(
                    databento_api_key,
                    symbol="ES.c.0"  # Adjust for NQ or GC as needed
                )
                print("✅ Order book analysis enabled")

    def _track_level_failure(self, level, timestamp):
        """
        Called when a level reaches FAILED state

        This hooks into the existing backtest to track failures
        for later flip analysis
        """
        if self.analyze_orderbook and self.ob_analyzer:
            self.ob_analyzer.track_level_failure(
                level_price=level['price'],
                fail_time=timestamp,
                original_type=level['type']
            )

    def _process_flip_signal(self, signal, timestamp):
        """
        Enhanced FLIP signal processing with order book analysis

        This is called when a FLIP_ENTRY action is detected
        """
        # Check if we have order book analysis enabled
        if self.analyze_orderbook and self.ob_analyzer:
            print(f"   🔍 Running order book analysis for FLIP @ {signal['price']:.2f}...")

            # Run the analysis
            ob_analysis = self.ob_analyzer.process_flip_signal(signal, timestamp)

            if ob_analysis:
                # Attach order book analysis to signal
                signal['orderbook'] = ob_analysis

                # Log quality assessment
                quality = ob_analysis['quality_rating']
                score = ob_analysis['quality_score']
                rec = ob_analysis['recommendation']

                print(f"      Quality: {quality} ({score:.1f}/100) → {rec}")

                # Optionally filter signals by quality
                if rec == 'SKIP':
                    print(f"      ⚠️  Low quality FLIP - consider skipping")
                    # You could return None here to skip the signal

        return signal


# ==============================================================================
# INTEGRATION POINTS FOR EXISTING BACKTEST FILES
# ==============================================================================

def integration_example_1_level_monitoring():
    """
    INTEGRATION POINT 1: Level Monitoring

    Add this to detect_level_recapture() in StrategyManager when a level
    reaches FAILED state (blowout threshold exceeded)
    """

    # In trading_bot_FIXED.py or backtest_bot.py
    # Inside StrategyManager.detect_level_recapture():

    """
    if violation_dist > BLOWOUT_THRESHOLD:
        monitor['state'] = 'FAILED'
        state_changed = True
        result_signal = "CANCEL"

        # ✅ NEW: Track for order book analysis
        if hasattr(self, 'ob_analyzer') and self.ob_analyzer:
            self.ob_analyzer.track_level_failure(
                level_price=level_price,
                fail_time=current_time,  # You need to pass timestamp
                original_type=monitor.get('original_type', 'RES')
            )

        # Create FLIP monitor...
        flip_key = f"{level_price:.2f}_SUP"
        ...
    """


def integration_example_2_flip_signal():
    """
    INTEGRATION POINT 2: FLIP Signal Detection

    Add this to _check_signal() in backtester when FLIP_ENTRY detected
    """

    # In backtest_bot.py
    # Inside TradingBotBacktester._check_signal():

    """
    elif action == "FLIP_ENTRY":
        signal = {
            'time': timestamp,
            'type': 'FLIP',
            'direction': 'LONG' if level['type'] == 'SUP' else 'SHORT',
            'price': current_price,
            'zone': strategy.get_zone_number(level),
            'size_mod': modifier,
            'message': message
        }

        # ✅ NEW: Run order book analysis
        if self.analyze_orderbook and self.ob_analyzer:
            ob_result = self.ob_analyzer.process_flip_signal(signal, timestamp)
            if ob_result:
                signal['orderbook'] = ob_result

                # Optional: Filter by quality
                if ob_result['recommendation'] == 'SKIP':
                    logging.info(f"   ⚠️  Skipping low-quality FLIP (score: {ob_result['quality_score']:.1f})")
                    return None  # Skip this signal

        return signal
    """


def integration_example_3_backtest_init():
    """
    INTEGRATION POINT 3: Backtester Initialization

    Add this to __init__ of TradingBotBacktester
    """

    # In backtest_bot.py
    # Inside TradingBotBacktester.__init__():

    """
    def __init__(self, start_date, end_date, enable_poc_filter=False,
                 analyze_orderbook=False, databento_api_key=None):

        # ... existing code ...

        # ✅ NEW: Order book analysis setup
        self.analyze_orderbook = analyze_orderbook
        self.ob_analyzer = None

        if analyze_orderbook:
            if databento_api_key:
                from orderbook_flip_analyzer import create_analyzer_from_api_key
                self.ob_analyzer = create_analyzer_from_api_key(databento_api_key, SYMBOL)
                print(f"✅ Order book analysis enabled")
            else:
                print(f"⚠️  Order book analysis requested but no API key provided")
                self.analyze_orderbook = False
    """


def integration_example_4_final_report():
    """
    INTEGRATION POINT 4: Final Report Generation

    Add this to generate_report() to show order book insights
    """

    # In backtest_bot.py
    # At end of TradingBotBacktester.generate_report():

    """
    def generate_report(self):
        # ... existing report code ...

        # ✅ NEW: Order book analysis report
        if self.analyze_orderbook and self.ob_analyzer:
            print("\n" + "="*60)
            print("📊 ORDER BOOK ANALYSIS")
            print("="*60)

            df_ob = self.ob_analyzer.generate_summary_report()

            if not df_ob.empty:
                # Export detailed results
                self.ob_analyzer.export_to_csv(
                    f'{BACKTEST_OUTPUT}/flip_orderbook_{self.start_date}_to_{self.end_date}.csv'
                )

                # Generate quality chart
                self.ob_analyzer.plot_quality_distribution(
                    f'{BACKTEST_OUTPUT}/flip_quality_{self.start_date}_to_{self.end_date}.png'
                )
    """


# ==============================================================================
# USAGE EXAMPLES
# ==============================================================================

def example_basic_usage():
    """
    Example 1: Basic backtest WITH order book analysis
    """
    from datetime import datetime
    import pytz

    NY_TZ = pytz.timezone('America/New_York')
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=7)

    # Your Databento API key
    DATABENTO_KEY = "YOUR_API_KEY_HERE"  # Replace with actual key

    # Create enhanced backtester
    backtester = EnhancedBacktester(
        start_date=start_date,
        end_date=end_date,
        enable_poc_filter=False,
        analyze_orderbook=True,  # ✅ Enable order book analysis
        databento_api_key=DATABENTO_KEY
    )

    # Run backtest
    backtester.generate_historical_plans()
    backtester.run_backtest()
    backtester.generate_report()


def example_without_orderbook():
    """
    Example 2: Standard backtest WITHOUT order book analysis
    (Same as before, no changes needed)
    """
    from datetime import datetime
    import pytz

    NY_TZ = pytz.timezone('America/New_York')
    end_date = datetime.now(NY_TZ).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=7)

    # Standard backtester (no order book)
    backtester = TradingBotBacktester(
        start_date=start_date,
        end_date=end_date,
        enable_poc_filter=False
    )

    backtester.generate_historical_plans()
    backtester.run_backtest()
    backtester.generate_report()


def example_flip_quality_filtering():
    """
    Example 3: Filter FLIP signals by order book quality

    Only take FLIP signals with GOOD or EXCELLENT quality ratings
    """

    # Inside your signal processing:
    """
    if signal['type'] == 'FLIP':
        if 'orderbook' in signal:
            ob = signal['orderbook']

            # Only take high-quality FLIPs
            if ob['quality_rating'] in ['GOOD', 'EXCELLENT']:
                print(f"✅ High-quality FLIP @ {signal['price']:.2f}")
                self.signals.append(signal)
            else:
                print(f"⚠️  Skipping low-quality FLIP @ {signal['price']:.2f}")
                # Don't add to signals
        else:
            # No order book data, use other criteria
            self.signals.append(signal)
    """


# ==============================================================================
# RECOMMENDED WORKFLOW
# ==============================================================================

def recommended_workflow():
    """
    Recommended workflow for implementing order book analysis:

    PHASE 1: Test Skeleton (Current)
    --------------------------------
    1. ✅ Create OrderBookFlipAnalyzer class (DONE)
    2. ⏳ Test class initialization and method structure
    3. ⏳ Verify integration points work with empty data

    PHASE 2: Implement Data Fetching
    ---------------------------------
    4. Implement _fetch_orderbook_snapshot() with Databento MBP-10
    5. Test data fetching on sample dates
    6. Verify order book data structure

    PHASE 3: Implement Calculations
    --------------------------------
    7. Implement _calculate_absorption_at_level()
    8. Implement _calculate_imbalance()
    9. Implement _count_large_orders()
    10. Implement _assess_depth_quality()

    PHASE 4: Integration Testing
    -----------------------------
    11. Add integration points to backtest_bot.py
    12. Run pilot backtest on 5-10 FLIP events
    13. Verify metrics make sense

    PHASE 5: Full Deployment
    -------------------------
    14. Run full backtest with order book analysis
    15. Generate quality distribution charts
    16. Use quality scores to filter signals

    PHASE 6: Optimization
    ---------------------
    17. Tune quality scoring weights
    18. Identify optimal quality threshold
    19. Backtest quality-filtered strategy vs unfiltered
    """
    pass


# ==============================================================================
# TESTING THE SKELETON
# ==============================================================================

if __name__ == "__main__":
    print("="*80)
    print("BACKTEST + ORDER BOOK INTEGRATION EXAMPLE")
    print("="*80)

    print("\n📋 This file demonstrates how to integrate OrderBookFlipAnalyzer")
    print("   with the existing backtest framework.")

    print("\n✅ Integration Points:")
    print("   1. Track level failures in detect_level_recapture()")
    print("   2. Analyze FLIPs in _check_signal()")
    print("   3. Initialize analyzer in __init__()")
    print("   4. Generate report in generate_report()")

    print("\n📖 See functions above for detailed code examples")

    print("\n🚀 Next Steps:")
    print("   1. Implement _fetch_orderbook_snapshot() with real Databento data")
    print("   2. Implement calculation methods")
    print("   3. Add integration hooks to backtest_bot.py")
    print("   4. Run pilot test on sample data")

    print("\n" + "="*80)
