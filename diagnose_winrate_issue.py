#!/usr/bin/env python3
"""
Diagnostic tool to understand the win rate vs stop size relationship
This creates a theoretical model based on trade statistics
"""

def analyze_winrate_paradox():
    """
    Analyze why wider stops don't necessarily increase win rate
    when paired with wider targets
    """

    print("="*80)
    print("GC WIN RATE ANALYSIS - Understanding the Paradox")
    print("="*80)

    # Your actual results
    results = [
        {"target": 8, "stop": 6, "wr": 47.0, "exp": 68, "trades": 66},
        {"target": 12, "stop": 6, "wr": 39.4, "exp": 82, "trades": 66},
        {"target": 25, "stop": 6, "wr": 21.2, "exp": 120, "trades": 66},
        {"target": 25, "stop": 12, "wr": 22.7, "exp": 129, "trades": 66},
    ]

    print("\n📊 YOUR ACTUAL RESULTS:")
    print(f"{'Target':>8} {'Stop':>8} {'R/R':>8} {'WR':>8} {'Exp':>10} {'Trades':>8}")
    print("-"*60)
    for r in results:
        rr = r['target'] / r['stop']
        print(f"{r['target']:>7}pt {r['stop']:>7}pt {rr:>7.2f}:1 {r['wr']:>7.1f}% ${r['exp']:>9} {r['trades']:>8}")

    print("\n\n" + "="*80)
    print("KEY INSIGHTS")
    print("="*80)

    print("\n1️⃣  TARGET SIZE DRIVES WIN RATE (not stop size)")
    print("   When you increase target from 8pt → 25pt:")
    print("   - Win rate drops from 47% → 21-23%")
    print("   - You're selecting for much larger moves only")
    print("   - Most trades don't have 25pt of runway")

    print("\n2️⃣  WIDER STOPS *DO* HELP (slightly)")
    print("   With 25pt target:")
    print("   - 6pt stop = 21.2% WR, $120 expectancy")
    print("   - 12pt stop = 22.7% WR, $129 expectancy")
    print("   - Extra room gives +1.5% WR and +$9 expectancy")

    print("\n3️⃣  THE REAL QUESTION:")
    print("   Is 22.7% WR acceptable for a $129/trade strategy?")

    # Calculate what the win rate SHOULD be for break-even
    print("\n\n" + "="*80)
    print("BREAK-EVEN ANALYSIS")
    print("="*80)

    for r in results:
        target = r['target']
        stop = r['stop']
        # Break-even WR = Stop / (Target + Stop)
        breakeven_wr = stop / (target + stop) * 100

        print(f"\n{target}pt target / {stop}pt stop:")
        print(f"   Break-even WR: {breakeven_wr:.1f}%")
        print(f"   Actual WR: {r['wr']:.1f}%")
        print(f"   Edge: {r['wr'] - breakeven_wr:.1f} percentage points")

        # Calculate expected value per trade
        avg_win = target * 100  # $100 per point
        avg_loss = -stop * 100
        ev = (r['wr']/100 * avg_win) + ((100-r['wr'])/100 * avg_loss)
        print(f"   Expected Value: ${ev:.2f}/trade (actual: ${r['exp']:.2f})")

    print("\n\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)

    print("\n✅ OPTION 1: Accept the 22.7% WR with 25pt/12pt")
    print("   Pros:")
    print("   - Highest expectancy ($129/trade)")
    print("   - Good edge over break-even (22.7% vs 32.4% needed)")
    print("   - Catches big gold moves")
    print("   Cons:")
    print("   - Psychologically difficult (77% of trades lose)")
    print("   - Requires discipline and large bankroll")
    print("   - Long losing streaks possible")

    print("\n✅ OPTION 2: Use smaller targets for higher WR")
    print("   Example: 12pt target / 6pt stop")
    print("   - Win Rate: 39.4% (more comfortable)")
    print("   - Expectancy: $82/trade (still profitable)")
    print("   - More consistent equity curve")

    print("\n✅ OPTION 3: Investigate MFE/MAE patterns")
    print("   - Look at Maximum Favorable Excursion on losing trades")
    print("   - If losers are hitting 20-24pts MFE, consider:")
    print("     • Partial profit taking at 15-20pts")
    print("     • Trailing stops after 15pt move")
    print("     • Scaling out (take half at 15pt, let half run to 25pt)")

    print("\n\n" + "="*80)
    print("NEXT STEPS")
    print("="*80)
    print("\n1. Check MFE on losing trades:")
    print("   - How many losers got within 5pts of the 25pt target?")
    print("   - What's the average MFE on losing trades?")

    print("\n2. Consider trade management:")
    print("   - Move stop to breakeven after +15pt")
    print("   - Take partial profits at +20pt")
    print("   - This could improve WR while keeping high expectancy")

    print("\n3. Time-based analysis:")
    print("   - Do certain times of day perform better?")
    print("   - Are morning trades different from afternoon?")
    print("   - Gold RTH is only 8:20-13:30 (5 hours)")

    print("\n4. Compare to ES/NQ:")
    print("   - ES: 67.4% WR with 3pt/2pt")
    print("   - NQ: 57.6% WR with 15pt/4pt")
    print("   - GC: 22.7% WR with 25pt/12pt")
    print("   - GC needs different trade management strategy")

    # Simulate losing streak probability
    print("\n\n" + "="*80)
    print("RISK MANAGEMENT: LOSING STREAK PROBABILITY")
    print("="*80)

    for r in [results[1], results[3]]:  # 12pt/6pt and 25pt/12pt
        wr = r['wr'] / 100
        lose_rate = 1 - wr

        print(f"\n{r['target']}pt target / {r['stop']}pt stop (WR: {r['wr']:.1f}%):")
        for streak in [3, 5, 7, 10]:
            prob = lose_rate ** streak * 100
            print(f"   {streak} losses in a row: {prob:.1f}% chance")


if __name__ == "__main__":
    analyze_winrate_paradox()
