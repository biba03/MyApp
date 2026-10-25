from data import DataLoader
from scanner import Scanner
from quality import PatternQuality
from report import Report
from market_regime import MarketRegimeEngine
from portfolio import Portfolio
from alerts import AlertManager

loader = DataLoader()

market = loader.load_universe()

benchmark = loader.load_benchmark()

# --- Market regime gate ---
# Only trade long setups when the broader market actually supports it,
# and size positions down (via risk_multiplier) when conditions are
# merely OK rather than strong. Needs SPY/QQQ/IWM specifically since
# MarketRegimeEngine.analyze() checks all three.
regime_engine = MarketRegimeEngine()

spy = market.get("SPY", benchmark)  # benchmark load already gives SPY by default
qqq = market.get("QQQ")
iwm = market.get("IWM")

regime = None

if qqq is not None and iwm is not None:

    regime = regime_engine.analyze(spy, qqq, iwm)

    print(f"Market regime: {regime.trend} (score={regime.score:.0f}), "
          f"long_allowed={regime.long_allowed}, risk_multiplier={regime.risk_multiplier}, "
          f"distribution_days={regime.distribution_days}")

    for reason in regime.reasons:

        print(f"  - {reason}")

else:

    print("Market regime: skipped (QQQ/IWM not in universe - add them to "
          "config.CUSTOM_TICKERS or scan a universe that includes them)")

quality = PatternQuality()

scanner = Scanner()

results = scanner.scan(

    market,

    quality,

    benchmark=benchmark,

    regime=regime,

)

if regime is not None and not regime.long_allowed:

    print(f"\nMarket regime does not favor long setups ({regime.trend}) - "
          "results are still reported below, but consider skipping new "
          "long entries or sizing down further.")

report = Report.dataframe(results)

print(report.head(50))

report.to_csv(

    "scan_results.csv",

    index=False,

)

# --- Alerts ---
alerts = AlertManager()

alerts.notify(results)

# --- Position sizing (informational - doesn't place real trades) ---
risk_multiplier = regime.risk_multiplier if regime is not None else 1.0

portfolio = Portfolio()

for ranked_stock in results[:10]:

    position = portfolio.open_position(ranked_stock, risk_multiplier=risk_multiplier)

    if position is not None:

        print(f"Would size {position.ticker}: {position.shares} shares "
              f"(risking ${position.dollar_risk:.0f})")
