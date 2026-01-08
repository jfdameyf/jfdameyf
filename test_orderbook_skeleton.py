"""
Test script for OrderBookFlipAnalyzer skeleton class
Verifies the class structure works without real data
"""

from datetime import datetime, timedelta

try:
    import pytz
    NY_TZ = pytz.timezone('America/New_York')
except ImportError:
    print("⚠️  pytz not available, using UTC for testing")
    pytz = None
    NY_TZ = None

# Mock Databento client for testing
class MockDatabento:
    """Mock Databento client for testing without API key"""
    def __init__(self):
        pass

# Import the analyzer
try:
    from orderbook_flip_analyzer import OrderBookFlipAnalyzer
except ImportError as e:
    print(f"❌ Failed to import OrderBookFlipAnalyzer: {e}")
    exit(1)

def test_initialization():
    """Test analyzer initialization"""
    print("\n" + "="*60)
    print("TEST 1: Initialization")
    print("="*60)

    mock_client = MockDatabento()
    analyzer = OrderBookFlipAnalyzer(
        databento_client=mock_client,
        symbol="ES.c.0",
        tick_proximity=5
    )

    print("✅ Analyzer initialized successfully")
    print(f"   Symbol: {analyzer.symbol}")
    print(f"   Tick size: {analyzer.tick_size}")
    print(f"   Large order threshold: {analyzer.large_order_threshold}")
    print(f"   Tick proximity: {analyzer.tick_proximity}")

    return analyzer


def test_level_tracking(analyzer):
    """Test level failure tracking"""
    print("\n" + "="*60)
    print("TEST 2: Level Failure Tracking")
    print("="*60)

    fail_time = datetime.now(NY_TZ) if NY_TZ else datetime.now()

    # Track a failed resistance
    analyzer.track_level_failure(
        level_price=5925.50,
        fail_time=fail_time,
        original_type='RES'
    )

    print(f"✅ Tracked failed RES @ 5925.50")
    print(f"   Pending flips: {len(analyzer.pending_flips)}")
    print(f"   Keys: {list(analyzer.pending_flips.keys())}")

    # Track another
    analyzer.track_level_failure(
        level_price=5930.25,
        fail_time=fail_time + timedelta(minutes=10),
        original_type='SUP'
    )

    print(f"✅ Tracked failed SUP @ 5930.25")
    print(f"   Pending flips: {len(analyzer.pending_flips)}")


def test_flip_analysis(analyzer):
    """Test FLIP analysis with mock signal"""
    print("\n" + "="*60)
    print("TEST 3: FLIP Signal Analysis")
    print("="*60)

    fail_time = datetime.now(NY_TZ) if NY_TZ else datetime.now()
    flip_time = fail_time + timedelta(minutes=30)

    # First track a failure
    analyzer.track_level_failure(
        level_price=5928.00,
        fail_time=fail_time,
        original_type='RES'
    )

    # Create mock signal
    mock_signal = {
        'price': 5928.00,
        'type': 'FLIP',
        'direction': 'LONG',
        'zone': 2
    }

    # Process flip signal
    result = analyzer.process_flip_signal(mock_signal, flip_time)

    if result:
        print(f"✅ FLIP analysis completed")
        print(f"   Level: {result['level_price']:.2f}")
        print(f"   Type: {result['original_type']} → {result['flip_type']}")
        print(f"   Quality: {result['quality_rating']}")
        print(f"   Score: {result['quality_score']:.1f}/100")
        print(f"   Recommendation: {result['recommendation']}")
    else:
        print(f"⚠️  Analysis returned None (expected with no real data)")


def test_quality_assessment(analyzer):
    """Test quality assessment with direct call"""
    print("\n" + "="*60)
    print("TEST 4: Quality Assessment")
    print("="*60)

    # Create mock metrics
    fail_metrics = analyzer._empty_phase_metrics()
    fail_metrics['total_liquidity'] = 1000
    fail_metrics['absorption_at_level'] = 300
    fail_metrics['depth_quality'] = 'WEAK'

    flip_metrics = analyzer._empty_phase_metrics()
    flip_metrics['total_liquidity'] = 1500
    flip_metrics['absorption_at_level'] = 500
    flip_metrics['depth_quality'] = 'STRONG'
    flip_metrics['level_type'] = 'SUP'

    # Compare
    comparison = analyzer._compare_phases(fail_metrics, flip_metrics)

    print(f"✅ Comparison metrics calculated")
    print(f"   Liquidity shift: {comparison['liquidity_shift']:+.0f} contracts")
    print(f"   Absorption delta: {comparison['absorption_delta']:+.0f} contracts")
    print(f"   Depth improved: {comparison['depth_improved']}")

    # Assess quality
    quality = analyzer._assess_flip_quality(fail_metrics, flip_metrics, comparison)

    print(f"\n✅ Quality assessment completed")
    print(f"   Score: {quality['score']:.1f}/100")
    print(f"   Rating: {quality['rating']}")
    print(f"   Confidence: {quality['confidence']}")
    print(f"   Recommendation: {quality['recommendation']}")


def test_reporting(analyzer):
    """Test reporting with empty data"""
    print("\n" + "="*60)
    print("TEST 5: Summary Report")
    print("="*60)

    # Try report with no data
    df = analyzer.generate_summary_report()

    if df.empty:
        print("✅ Correctly handled empty dataset")

    # Add mock analysis
    now = datetime.now(NY_TZ) if NY_TZ else datetime.now()

    analyzer.flip_analyses.append({
        'level_price': 5925.50,
        'original_type': 'RES',
        'flip_type': 'SUP',
        'fail_time': now,
        'flip_time': now + timedelta(minutes=20),
        'time_between': 20,
        'quality_score': 75.0,
        'quality_rating': 'GOOD',
        'confidence': 'HIGH',
        'recommendation': 'TAKE',
        'liquidity_shift': 500,
        'absorption_delta': 200,
    })

    analyzer.flip_analyses.append({
        'level_price': 5930.00,
        'original_type': 'SUP',
        'flip_type': 'RES',
        'fail_time': now + timedelta(hours=1),
        'flip_time': now + timedelta(hours=1, minutes=15),
        'time_between': 15,
        'quality_score': 45.0,
        'quality_rating': 'FAIR',
        'confidence': 'MEDIUM',
        'recommendation': 'CONSIDER',
        'liquidity_shift': -100,
        'absorption_delta': 50,
    })

    # Generate report
    df = analyzer.generate_summary_report()

    print(f"\n✅ Generated report with {len(df)} analyses")


def test_export(analyzer):
    """Test CSV export"""
    print("\n" + "="*60)
    print("TEST 6: CSV Export")
    print("="*60)

    if analyzer.flip_analyses:
        analyzer.export_to_csv('test_flip_analysis.csv')
        print("✅ CSV export successful")
        print("   File: test_flip_analysis.csv")
    else:
        print("⚠️  No data to export")


def run_all_tests():
    """Run all skeleton tests"""
    print("\n" + "="*80)
    print("ORDERBOOK FLIP ANALYZER - SKELETON TEST SUITE")
    print("="*80)
    print("\nTesting class structure WITHOUT real order book data...")
    print("This verifies the skeleton is properly structured and ready for")
    print("implementation of actual Databento data fetching and calculations.")

    try:
        # Run tests
        analyzer = test_initialization()
        test_level_tracking(analyzer)
        test_flip_analysis(analyzer)
        test_quality_assessment(analyzer)
        test_reporting(analyzer)
        test_export(analyzer)

        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        print("\n📋 Next Steps:")
        print("   1. Implement _fetch_orderbook_snapshot() with Databento MBP-10 data")
        print("   2. Implement calculation methods (_calculate_absorption, etc.)")
        print("   3. Integrate with backtest_bot.py using patterns from")
        print("      backtest_with_orderbook_example.py")
        print("   4. Run pilot test on real market data")

        return True

    except Exception as e:
        print("\n" + "="*80)
        print("❌ TEST FAILED")
        print("="*80)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
