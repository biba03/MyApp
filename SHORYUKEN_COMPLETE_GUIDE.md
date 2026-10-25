# Shoryuken Scanner — Complete Guide

Consolidated edition • Updated 17 October 2026

This guide replaces the separate README, user manual, loading notes, scan-context notes, sector-RS notes, stock-bubble notes and cleanup report supplied for this edition. It describes the cleaned project with the Yahoo-loading, scan-context, sector-RS and three-index bubble updates applied. This edition also documents the empty-result export fix, chart zoom, automatic cap refresh, Qullamaggie candidate changes, expanded notebook universe and S&P 600 parser fix. Documentation alone does not install these updates.

Shoryuken is a Python research and scanning project for U.S. equities. It downloads daily OHLCV histories, calculates indicators, detects patterns and ranks matches. Its standalone HTML report has two tabs: **Scan Board** and **Market View**. It does not place orders; portfolio sizing and backtests are research functions.

## Contents

1. [Installation and update order](#installation-and-update-order)
2. [Daily workflow and data refresh](#daily-workflow-and-data-refresh)
3. [Watchable universe and Scan Board](#watchable-universe-and-scan-board)
4. [Market View](#market-view)
5. [Reading scan results](#reading-scan-results)
6. [Common tasks](#common-tasks)
7. [Pattern detectors](#pattern-detectors)
8. [Backtesting](#backtesting)
9. [Troubleshooting](#troubleshooting)
10. [Technical reference](#technical-reference)
11. [Project cleanup and validation history](#project-cleanup-and-validation-history)
12. [Glossary](#glossary)

## Installation and update order

### Install the cleaned base project

1. Extract the full cleaned ZIP into a new folder, keeping its folder structure and supplied data intact.
2. From that folder, install the dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Open `shoryuken_scanner.ipynb` in Jupyter, JupyterLab or VS Code.
4. In the project-directory setup cell (section 2), set `PROJECT_DIR` to the actual extracted folder. For example:

   ```python
   PROJECT_DIR = Path(r"C:\Jupyter_project\shoryuken_project\shoryuken")
   ```

5. Check the report and market-cap paths before running the notebook.

### Apply the feature updates, if not already installed

The cleaned base ZIP predates the latest dashboard features. Apply patches in this order, replacing the included files:

| Order | Update ZIP | Purpose |
|---|---|---|
| 1 | `shoryuken_scan_context_update.zip` | Readiness funnel, breadth, RSP/QQQE and the previous Yahoo-only loading changes |
| 2 | `shoryuken_sector_rs_update.zip` | Sector week/month RS chart and aligned-period metadata |
| 3 | `shoryuken_three_index_bubbles.zip` | Individual-stock bubble chart and three membership selectors |
| 4 | Latest `scan_board.py` (zoom update) | Includes the earlier missing-Ticker/empty-result fix and zoom controls |
| 5 | `shoryuken_qullamaggie_coverage.zip` | Notebook, independent Qullamaggie gate, automatic cap refresh and WAL-aware cache reader |
| 6 | Latest `downloader.py` (S&P 600 parser fix) | Accepts valid constituent tables without mistaking metadata for change logs |

The Qullamaggie coverage ZIP includes the preceding `shoryuken_auto_market_caps.zip` changes; do not overlay the older notebook afterward. Keep the zoom-enabled `scan_board.py`: the coverage patch does not replace it. These patches do not implement the discussed third ETF Groups tab or Yahoo top-holdings downloads; the HTML still has two tabs.

The standalone `shoryuken_yahoo_loading.zip` is an earlier loading-only patch. It is already included in the scan-context update; do not apply it after newer patches, because it could overwrite newer files.

Restart the Jupyter kernel after replacing Python modules or the notebook. Run cells from the top, then stock loading through the final HTML export. The feature patches contain changed/new files, not replacement price caches or historical research outputs.

## Daily workflow and data refresh

1. Run the project setup and imports.
2. Run section 4 to refresh/read stocks and load ETF histories.
3. Run the Watchable gate, original scanner and method scans in notebook order.
4. Review diagnostics/readiness if needed.
5. Run the standalone HTML export cell (section 6b in the supplied notebook).
6. Open the generated `all_scan_results.html` and select Scan Board or Market View.

The report folder defaults to:

```python
HTML_OUTPUT_DIR = Path.home() / "Documents" / "Shoryuken_reports"
```

This is separate from the project folder. The Watchable market-cap file is also configured under `Documents/Shoryuken_reports/market_caps.csv`; inspect `CAP_FILE` in the notebook.

### Refresh controls

| Control | Meaning |
|---|---|
| `REFRESH_PRICES = True` | Use the existing Yahoo stock refresh/cache workflow, refresh ETFs, and check membership snapshots |
| `REFRESH_PRICES = False` | Read existing stock/ETF histories and membership snapshots without those refresh requests |
| `ensure_market_caps(...)` | Automatically refresh missing, invalid or expired market-cap snapshots in section 4c; reuse fresh rows |
| `update_sector_data=False` | Prevent the original scanner from fetching missing sector/industry metadata |

`REFRESH_PRICES=False` does not disable automatic cap refresh. The latest notebook has no single fully-offline switch: for a deliberate offline run, replace the `ensure_market_caps(...)` call with `market_caps = pd.read_csv(CAP_FILE)` and keep `update_sector_data=False`. Expired caps still fail validity checks. The original scanner can otherwise make classification requests independently of `REFRESH_PRICES`.

### Automatic market-cap maintenance

Section 4c calls `ensure_market_caps` from `watchable.py`. A snapshot is reused if its value is finite and positive and its date is between today and seven calendar days ago (inclusive). The age limit comes from `WATCHABLE_CONFIG.max_cap_age_days`. Missing, invalid, future-dated or expired rows are fetched from Yahoo `fast_info['market_cap']` when the notebook runs. This is not a background scheduler.

Successful requests receive the current retrieval date. Failed requests retain the previous cap and its original date, record an error, and are retried on the next run; an expired retained cap is not silently accepted. Other cached ticker rows are preserved, and the CSV is replaced atomically. The notebook prints fresh/requested/success/failure counts. A large first refresh can take time because cap requests run sequentially. No trading thresholds were relaxed.

Stock prices remain Yahoo-only through `yfinance`. Membership lists are separate metadata: the existing Wikipedia loaders for S&P 500 and Nasdaq 100, and iShares equity holdings for the Russell 2000 proxy.

### Cache locations

| Location | Contents |
|---|---|
| `cache/market_data.db` | Stock OHLCV histories |
| `cache/market_view/` | Separate ETF price CSVs and source metadata |
| `cache/index_membership/` | Dated membership JSON snapshots |
| `data/sector_industry.csv` | Local ticker-to-sector/industry classifications |
| Configured `CAP_FILE` | `Ticker`, `MarketCapUSD`, `SnapshotDate` |
| Report folder `history/` | Reporting snapshots used for scan-change comparisons |

The latest notebook constructs an explicit union of S&P 500, S&P 400, S&P 600 and Nasdaq 100 plus SPY/QQQ/IWM, calls `download_universe`, reads the complete discovery cache, then calculates indicators once. It no longer computes a preparation result that is discarded before another indicator pass. Script/dashboard callers of `load_universe()` retain their own preparation behavior.

Section 4 prints separate price-refresh, cache-read, indicator and ETF-loading times. Membership loading happens afterward; those four timings do not measure membership fetching.

ETF histories use Yahoo `auto_adjust=True`. Failed ETF refreshes may use clearly labelled Yahoo cached history. Non-Yahoo or unlabelled ETF caches stay on disk but are not used; a successful Yahoo refresh is needed. This update does not introduce an ETF freshness scheduler or an indicator-cache layer.

Membership snapshots are reused on the same UTC fetch date. A failed refresh retains the last good snapshot with a visible fallback/error status. Without an initial snapshot, offline membership is unavailable.

## Watchable universe and Scan Board

### Watchable gate

The supplied Watchable defaults require:

| Requirement | Default |
|---|---|
| Stock RS | ≥70 |
| Sector rank | ≥70 |
| Industry rank | ≥70 |
| Market capitalization | ≥$500 million, with a valid dated snapshot |
| ATR14 / close | ≥3% |
| Average 20-session dollar volume | ≥$50 million |
| Stage | Existing Stage 1–2 proxy |

The gate also checks valid, sufficient, same-date price history. Missing metadata fails closed. Ranks are calculated from the full valid discovery universe before the gate filters it. Inspect `WatchableConfig` for current settings, including the accepted market-cap age.

The update does not change the gate to $1 billion, exclude REITs, introduce exact 1A–2B stage subdivisions, or reproduce Steve Jacobs's proprietary/discretionary formulas. Stage badges use the existing stage analysis; proxy fields are labelled.

`watchable_audit` and its exported CSV list pass/fail conditions and exclusion reasons. The summary shows the number remaining after each gate and data coverage. No thresholds are relaxed when zero stocks pass.

### Qullamaggie exception to the Watchable gate

The latest notebook keeps the Watchable gate for the original scanner and other method scans. **Qullamaggie alone uses ATR14/close ≥3% and a valid market cap ≥$500M**, plus its existing daily-bar pattern rules. It does not additionally require Watchable stage, stock RS≥70, sector rank≥70, industry rank≥70 or $50M average dollar volume. Data preparation still rejects insufficient, stale or invalid histories.

`qullamaggie_candidates.py` builds `qull_candidates` from the audit's ATR, cap and `PassCapData`. `scan_methods` runs once on the full prepared universe; the notebook retains Qullamaggie rows belonging to `qull_candidates`, and other method rows belonging to `watchable_tickers`. Momentum ranks are therefore based on the full prepared universe. `all_method_results` holds the method matches before these candidate gates; it is not automatically exported separately.

The detector itself remains an inspired implementation, not a verified reproduction of another public screener: at least 127 bars; top 2% momentum over at least one of 21/63/126 sessions; close above rising 10/20-session averages; a prior ≥30% advance; a 10/20/30/40-session base of width ≤20% with contraction and higher lows; then price within 3% below the base high, or above it with relative volume ≥1. These pattern requirements are unchanged by the candidate-gate update.

A Qullamaggie match can legitimately show **Outside Watchable** on the board. That label describes the separate stricter Watchable assessment; it does not cancel the Qullamaggie match. Clear the board's funnel filter to see such matches.

### Readiness and funnel labels

| Funnel label | Implemented meaning |
|---|---|
| Watchable | Explicit Watchable pass, without an existing Ready/Breakout classification and valid price trigger |
| Tradable | Watchable pass + existing `Ready` diagnostic + valid trigger |
| Actionable | Watchable pass + existing `Breakout` diagnostic + valid trigger |
| Outside Watchable | Explicit gate failure |
| Not assessed | No Watchable assessment supplied |

Underlying diagnostics retain `Ready`, `Breakout`, `Forming`, `Extended`, `Unavailable` and event-signal classifications. A stock can qualify for a method or event without a confirmed price breakout. Missing triggers are not invented.

Trigger prices and reasons are visible; expandable sections retain the per-pattern fields and the trigger's native/proxy basis. The detector's `Entry` is not automatically the breakout trigger. Original Entry, Stop and Target fields are preserved by reporting.

**Actionable is a diagnostic label, not an order or complete eligibility decision.** Earnings, portfolio holdings, live execution checks and position-sizing controls are not assessed by this funnel.

### Reading the board

Use ticker/information search, readiness and funnel filters, sorting, expandable details and CSV export. Multiple matches for one ticker are grouped into a card within each method column, with pattern/method badges. A ticker can still appear in more than one method column. Grouping does not delete underlying matches.

“Market cap updated” (previously “Cap date”) is the snapshot date for market capitalization. “Price age” is separate: calendar days since the last price bar relative to the report's reference date. Current price data does not imply current market-cap metadata.

Method badges include KQ (Qullamaggie), MM (Minervini), SB4 (4% daily), SBW (20% weekly), SB9 (9-month movers), SH and DB where applicable. The broader strategy vocabulary also includes ON, TML, 97C, earnings, stage, trend-strength and strike-zone badges; a label's presence does not establish that the exact named trading system or all required fundamental inputs are implemented. Inspect the associated method and proxy labels.

## Market View

### ETF performance table

Market ETFs: **SPY, QQQ, IWM, RSP and QQQE**. Sector ETFs: **XLK, XLF, XLE, XLI, XLV, XLY, XLP, XLU, XLB, XLRE and XLC**.

| Column | Calculation window |
|---|---|
| Day | 1 trading session |
| Week | 5 sessions |
| Month | 21 sessions |
| 3 months | 63 sessions |
| 6 months | 126 sessions |
| 1 year | 252 sessions |
| YTD | Last close versus the last available close before the year of the latest price date |

Returns are percent changes in the provider's adjusted price series, not certified dividend-reinvested total returns. Missing history shows an unavailable value. Price date, calendar age, source and download/cache status are visible. Cached fallback means the refresh failed and usable saved Yahoo prices were used.

SPY tracks S&P 500 exposure, QQQ Nasdaq 100, and IWM Russell 2000. ETF price histories alone do not identify index members.

### Stock breadth

Breadth uses the full cached stock universe, equal-weighted:

- Percent above SMA50.
- Percent above SMA200.
- Percent with a higher close than the previous session.
- Percent within 3% of the trailing 252-session high.

Each metric has its own denominator of eligible histories. Stale and invalid histories are counted separately. Data after the scan reference date is excluded. Breadth is as of the stock scan date; ETF price dates can differ. This is coverage of the cache, not every exchange-listed stock. The near-high definition is a reporting choice, not Steve's one-ATR rule. The calculation does not detect incomplete intraday bars.

### Sector relative strength chart

The scatter chart plots the 11 sector ETFs:

- **X:** month RS versus SPY, 21 sessions.
- **Y:** week RS versus SPY, 5 sessions.

```text
RS (%) = ((1 + sector return / 100) / (1 + SPY return / 100) - 1) * 100
```

This is the change in the sector/SPY price ratio. It is not a subtraction of percentage returns, a percentile RS rating or a standardized RRG indicator. Positive values mean outperformance over that horizon.

Both period start and end dates must match SPY. Missing or mismatched histories remain visible in the table but are not plotted. Hover/focus a point for values and date. Table/CSV fields include `WeekRSPct`, `MonthRSPct`, `RSBenchmark` and `RSStatus`.

### Zoom and pan

Both the sector RS scatter and individual-stock performance bubbles have **Zoom in**, **Zoom out** and **Reset zoom** controls. Zoom ranges from 100% to 800%. Drag to pan after zooming; Ctrl + mouse wheel also zooms. The full SVG view is magnified, including labels and axes. Regenerating a chart after a filter/axis change resets its zoom. These are presentation controls; returns and scan rules are unchanged.

### Individual-stock performance bubbles

| Selector | Membership source |
|---|---|
| S&P 500 | Existing Wikipedia constituent loader |
| Nasdaq 100 | Existing Wikipedia constituent loader |
| Russell 2000 | Published iShares IWM equity holdings proxy, explicitly labelled; not an official licensed constituent file |

The bubble chart shows **ordinary price performance**, unlike the sector chart's RS calculation. Default X is month (21 sessions), Y is week (5). Axes can use Day, Week, Month, 3 Months, 6 Months or Year.

Bubble color is sector. Area scales with market cap, with a minimum 2-pixel radius for visibility. Unknown caps use hollow circles. Hover or click shows values, classifications, volume and price/cap dates. The thirty largest-cap names are labelled by default; “All labels” labels every displayed ticker.

Filters include Full index / Watchable / Scan Matches, sector, industry, minimum market cap, minimum 20-session average share volume, ticker search and comma-separated exclusions. Reset clears the filters. Export displayed stocks saves the filtered rows as CSV.

Coverage displays membership count, members present in the cache, usable same-date histories, missing market caps and displayed count. Missing/stale prices and insufficient selected-period histories are not plotted. Changing the chart filter does not change the scanner's selection rules.

**The bubble module itself does not download missing member histories.** The later notebook coverage update separately adds S&P 600 to its requested stock universe; this still does not fetch every IWM holding. A Russell 2000 selection can be incomplete if those stocks are absent from the cache. Current membership and cap snapshots are for live reporting, not point-in-time backtesting. Unknown classifications remain Unknown.



## Reading scan results

| Column | What it means |
|---|---|
| `Ticker` | The stock. |
| `Pattern` | Which of the 10 detectors fired (see Pattern detectors). |
| `Score` | Original Shoryuken report: composite ranking score. Detector diagnostics: raw rule score. Method rows may have different score definitions; compare like-for-like. |
| `Quality` | 0-100, a separate score for geometry/trend/volume/breakout/risk quality of the setup, independent of which pattern found it. |
| `Confidence` | Rule-coverage percentage for the pattern, not an estimated probability of a profitable trade. HTML may label this RuleCoveragePct (legacy Confidence). |
| `RS` | Relative Strength rating, 1-99, percentile-ranked against every other ticker in *this scan*. 99 = strongest mover in the universe you scanned; 1 = weakest. Not comparable across different scans of different universes. |
| `SectorRank` / `IndustryRank` | Same 1-99 percentile idea, but for the stock's *sector* and *industry* as a group, ranked against every other sector/industry present in this scan. A stock in a strong sector but showing individually weak RS might still be worth a second look (rising tide); the reverse (strong stock, weak sector) is a common way a leader eventually rolls over. |
| `Liquidity` | 0-100. 100 once dollar volume reaches 3x `config.MIN_DOLLAR_VOLUME`, scaling down linearly below that. |
| `Regime` | The market regime score (0-100) at the time of the scan, same value on every row (it's a market-wide condition, not stock-specific) - included so you can see what regime conditions the ranking accounted for. |
| `TrendTemplate` | `x/8` - how many of Minervini's 8 trend-quality criteria this stock passes (price vs. 50/150/200-day MA, MA stacking order, position within its 52-week range). This is a quality gate, not a pattern - a stock can have a great pattern score and a weak trend template, which is a warning sign. |
| `Stage` | Weinstein's stage classification: `Stage 2` (advancing, the buy zone) is what you want to see alongside a pattern hit. `Stage 1` (basing) means the setup may be premature. `Stage 3` (topping) and `Stage 4` (declining) are warning signs regardless of pattern score. |
| `AccumDays` / `DistDays` | Accumulation/distribution days in roughly the last 25 sessions - higher `AccumDays` relative to `DistDays` suggests institutional buying pressure; the reverse suggests selling pressure. |
| `Entry` / `Stop` / `Target` | Suggested trade levels. Inspect the relevant detector and `config.ATR_STOP_MULTIPLIER` for the stop convention; the HTML reporting layer preserves these values. |
| `RR` | Reward-to-risk ratio of Target vs. Stop. |



The RS rank depends on the ranked universe; it is not comparable across materially different universes. Sector/industry data are local snapshots. Pattern qualification, ranking and entry readiness are separate concepts.


## Common tasks

Configuration examples below describe available controls; changing thresholds, weights, stop multipliers or worker settings is separate from installing the reporting updates. Preserve your existing research settings unless you deliberately design and validate a change.

### Scan a different universe

For script/dashboard loaders, edit `config.py`:
```python
UNIVERSE = "SP500"   # or "SP400", "SP600", "NASDAQ100", "COMBINED" (default), "CUSTOM"
```
For `"CUSTOM"`, also set `CUSTOM_TICKERS = ["AAPL", "MSFT", ...]` in the same
file. Custom lists are good for quick tests - they skip the slow universe
download entirely.

The latest notebook's explicit index union overrides this configuration for its price-refresh cell. Editing `UNIVERSE` alone will not change that cell. Legacy `COMBINED` means S&P 500 + S&P 400 + Nasdaq 100 and omits S&P 600. The updated notebook adds S&P 600 without changing that legacy config option.

Coverage output reports expected symbols, cached symbols, missing histories and non-current histories, plus the discovery database path. It reads all cached symbols, including older symbols outside the new requested union. This is index-based coverage, not all US exchange listings; a reference ticker can still be absent. A wider universe can change cross-sectional ranks and consequently matches.

### Make stops tighter or looser

Edit `config.py`:
```python
ATR_STOP_MULTIPLIER = 1.0   # inspect each detector's stop construction
```
Raise it (e.g. to 1.5) if you're getting stopped out on normal noise; lower
it for tighter risk (and correspondingly tighter targets, since targets are
a multiple of the stop distance).

### Change how strict a pattern is

Edit `config.py`:
```python
MIN_PATTERN_SCORE = 70   # applies to VCP, DTRP, PocketPivot, FlatBase, CupHandle, EpisodicPivot, DarvasBox, HighTightFlag, BaseOnBase
SHORYUKEN_MIN_SCORE = 75  # Shoryuken has its own, stricter threshold
```

### Size a position for a specific signal

```python
from portfolio import PositionSizer

sizer = PositionSizer(account_size=100_000, risk_per_trade=0.01)
shares = sizer.shares_for(entry=result.iloc[0].Entry, stop=result.iloc[0].Stop)
```

### Get notified about new setups instead of re-reading the table

```python
from alerts import AlertManager, ConsoleBackend, FileBackend

manager = AlertManager(backends=[ConsoleBackend(), FileBackend()])
manager.notify(results)  # `results` is the list Scanner.scan() returned
```
Re-running `manager.notify(results)` with the same results won't re-alert -
it's deduplicated by (ticker, pattern). See `alerts.py` for the disabled
`EmailBackend` if you want real email notifications (you'll need to fill in
SMTP credentials yourself).

### Browse results without the notebook

```bash
streamlit run dashboard.py
```
Opens a filterable web UI in your browser - sliders for min score/RR/RS, a
"re-run scan" button, charts, and a per-ticker drill-down.

### Speed up (or quiet down) a scan

`scanner.scan()` shows a progress bar by default (`Computing RS` then
`Scanning`) and auto-picks a thread count based on your CPU. You normally
don't need to touch this, but:
```python
results = scanner.scan(market, quality, benchmark=benchmark, workers=16)       # more threads
results = scanner.scan(market, quality, benchmark=benchmark, show_progress=False)  # quiet, e.g. for a scripted/logged run
```
Profile the slow step before tuning workers. Network requests, cache access, indicators and scanning have different costs; more threads are not a guaranteed speed improvement.

### Check that the code itself still works after an edit

```bash
pytest tests/
```
This isn't for trading signals - it's a sanity check that the modules behave
correctly. Run it after you or I change any `.py` file.

---


## Pattern detectors

| Pattern | The idea |
|---|---|
| **Shoryuken** | A custom, strict breakout combining trend, volume dry-up, pivot breakout, and candle quality. The strictest detector (threshold 75 vs. 70 for the others). |
| **VCP** | Volatility Contraction Pattern (Minervini) - a series of pullbacks, each shallower than the last, on shrinking volume, resolving in a breakout. |
| **DTRP** | Daily Tight Range Pattern - several very tight, low-volatility days near highs, then a breakout out of that tight range. |
| **Pocket Pivot** | An up day whose volume exceeds the biggest down-volume day of the last 10 sessions - an early institutional-buying signal that doesn't require a new high. |
| **Flat Base** | A shallow (≤15%), multi-week consolidation after a real prior uptrend, breaking out on volume. |
| **Cup & Handle** | The classic U-shaped decline-and-recovery followed by a small handle pullback, breaking out above the handle. |
| **Episodic Pivot** | A news/earnings-driven gap up on very heavy volume - the catalyst itself is the setup, no prior base required. |
| **Darvas Box** | The most recent price high that hasn't been exceeded since defines a "box"; buy the breakout above the box top on volume. |
| **High Tight Flag** | A 90%+ explosive run followed by a brief, shallow pullback. A rare momentum continuation pattern; its configured target convention can differ from other detectors. |
| **Base-on-Base** | A second, higher, tighter base forming right on top of a first breakout without ever retesting it - a continuation structure used by the detector. |

---

Additional method scans include Qullamaggie, Minervini Trend Template and Stockbee variants. These method rows and the original detector rows share the board but retain their own definitions.


## Backtesting

The backtester (`backtest.py`) answers: *does this screening algorithm
actually have predictive power?* It uses a walk-forward simulation -
at every historical day, it recomputes every indicator from scratch using
only data up to that day, then checks whether any pattern would have fired,
then simulates the trade forward to see what actually happened.

### Running it

```python
from backtest import BacktestConfig, BacktestEngine

cfg = BacktestConfig(
    start_date="2023-01-01",
    end_date="2023-12-31",
    initial_capital=100_000,
    position_sizing="fixed_percent",   # "fixed_dollar" | "fixed_percent" | "atr_risk"
    risk_per_trade=0.01,
    max_open_positions=10,
    target_type="2R",                  # "2R" | "3R" | "trailing"
    entry_method="close",              # "close" | "next_open"
    step=5,                            # check every 5th day - see "speed" below
    use_multiprocessing=True,
)

result = BacktestEngine(scanner.detectors, cfg).run(market, benchmark=benchmark)
```

`market` and `benchmark` are the same dicts/dataframes you already loaded in
section 4 of the notebook - no separate data loading needed.

### Reading the output

- **`result.summary`** — the headline numbers: win rate, profit factor,
  expectancy (in R), Sharpe/Sortino/Calmar ratios, max drawdown, CAGR, and
  more. `expectancy_R > 0` is the single most important sign the system has
  edge; a high win rate with negative expectancy is still a losing system.
- **`result.pattern_stats`** — the same core numbers broken out per pattern.
  Some patterns will have very few trades in a given window - don't trust a
  pattern's numbers until it has a reasonable trade count (dozens, not a
  handful).
- **`result.score_buckets` / `result.confidence_buckets`** — groups trades
  by score/confidence range (90-100, 80-89, etc.) and shows win rate/avg
  return/profit factor per bucket. If higher scores don't correspond to
  better outcomes here, that's a sign the scoring weights need rethinking,
  not just the patterns themselves.
- **`result.time_breakdown`** — a dict of dataframes: `by_year`,
  `by_quarter`, `by_month`, `by_dow`, `by_regime` (bull/bear/sideways, using
  the benchmark's price vs. its 200-day EMA).
- **`result.equity_curve`** — a `pandas.Series` you can `.plot()` directly.

### Exporting everything to disk

```python
result.export("backtest_results")
```
Writes `signals.csv` (every single detection, unfiltered), `trades.csv`
(one row per simulated trade), `summary.csv`, `pattern_statistics.csv`, and
8 PNG charts (equity curve, drawdown, monthly returns heatmap, returns
distribution, win/loss histogram, score-vs-win-rate, score-vs-avg-return,
confidence-vs-win-rate).

### Speed

Recomputing indicators on trailing data supports causal evaluation, but does not by itself prove that all execution assumptions are realistic. It can be slow across a large universe and long period. The legacy documentation offers these exploration settings:

- Exploring/iterating: small universe (`CUSTOM_TICKERS` with 5-20 names),
  `step=5` or higher.
- Final validation: full universe, `step=1`, `use_multiprocessing=True` if
  you have multiple CPU cores.

### What this backtest can't tell you (read this before trusting the numbers)

- **Survivorship bias.** The universe is *today's* index membership. A stock
  that got delisted or dropped from the index during your backtest window
  simply isn't in the data at all - this tilts results optimistic versus
  what really happened live.
- **Costs are approximated** as flat percentages, not a model of real
  slippage under different volatility/liquidity conditions.
- **Fill assumptions.** The equity curve enforces `max_open_positions` and
  marks positions to daily closes, but doesn't check whether a position of
  that size could actually have been filled without moving the price.

Treat backtest outputs as estimates subject to these assumptions. Test counts establish software behavior, not predictive performance.

---

The example retains the legacy `entry_method="close"`. If a signal requires the completed daily close, same-close execution needs an explicit assumption; `next_open` is available for next-session entry modelling. Current membership/cap snapshots are not historical membership/cap data. Do not reduce data length, bootstrap samples, seeds, folds or other research settings merely to obtain a faster comparison.


## Troubleshooting

**A scan prints "N ticker(s) failed during scanning and were skipped."**
This is expected, not a crash - one bad ticker (missing data, a weird edge
case) used to be able to take down the *entire* scan and lose every other
ticker's results with it. Now it's isolated: the scan finishes normally,
and the failing tickers/reasons are both printed and available afterward:
```python
print(scanner.last_scan_errors)  # {ticker: "ExceptionType: message"}
```
If the same ticker keeps failing across runs, that's worth investigating
(bad cached data for that ticker, maybe) - but a handful of one-off
failures in a large universe scan is normal.

**A stock I expected to see isn't in the results at all, even before pattern
scoring.** For script/dashboard loading, check `config.MIN_PRICE`/`MAX_PRICE` - `DataLoader.load_universe()`
filters out any ticker whose latest close falls outside that range before it
ever reaches the scanner, and prints how many tickers got dropped this way.

**"Loaded 0 tickers" or a scan returns way fewer results than expected.**
Inspect download errors, cache coverage and the Watchable audit; rate limiting is one possible cause, not a diagnosis from the count alone. The
downloader now prints the real underlying error when this happens instead
of failing silently - check the console output. Try: `pip install -U
yfinance`, wait a while and retry, or use a different network.

**It re-downloads everything every time instead of just new days.**
Check that you're launching Jupyter from a consistent location - the cache
lives at an absolute path (`config.CACHE_DIR`), but if you want to confirm
it's actually being reused, run this:
```python
from cache import cache
print(cache.path, cache.path.exists())
```
The universe-loading cell also prints a `Cache usage: X fresh, Y
incremental, Z full downloads` line every run - "fresh"/"incremental"
dominating on a second run confirms it's working.

**`scan()` returns 0 setups.**
Run `scanner.diagnostics(market)` - it reports, per ticker, whether a trend
could even be computed and every detector's raw score whether or not it
cleared the detection threshold. If most tickers show `TrendOK=False`,
something's wrong upstream. If scores just cluster a bit under each
threshold, that's a genuinely quiet day for setups, not a bug.

**pytest shows a coverage percentage under 100%.**
That's code coverage (how many lines got exercised), not test pass/fail
rate - a different metric entirely. Check the actual pass/fail count
(`X passed`, `0 failed`) instead; coverage under 100% is normal and expected
unless you specifically write tests to hit every conditional branch.

**The Nasdaq-100 universe fetch fails.**
`downloader.py` scrapes `List_of_NASDAQ-100_companies` on Wikipedia
specifically (not the main "Nasdaq-100" article, which has extra
tables that used to confuse the parser). If Wikipedia reshuffles that page
again, the fallback matcher in `downloader.py` tries several strategies
before giving up - if it still fails, the error message dumps every table
found so the cause is diagnosable.

---

In the updated notebook, raw refresh is followed by complete cache discovery and a separate Watchable gate. Inspect that audit before assuming script-loader price filtering explains a missing notebook result.


### Zero matches: find the failing stage

Inspect `len(market)`, `len(watchable_tickers)`, `len(qull_candidates)`, `len(report)` and `len(method_results)`. Review `watchable_summary['funnel']` and `watchable_audit['ExclusionReasons']`. The Watchable audit is before pattern detection; it does not contain scores for every rejected pattern.

In the October 17 investigation, 76 stocks passed the non-cap Watchable checks, then all failed cap validation. Sample caps were dated October 5, beyond the seven-day maximum. Automatic refresh addresses that blocker. The legacy exclusion text also reports “Market cap below $500M” when cap data are invalid/stale; it does not establish that those companies are actually smaller than $500M. That wording has not been corrected in code.

For comparison with an external screener, verify the same scan date, loaded ticker coverage, price basis, liquidity definition and exact pattern rules. Six of seven supplied comparison symbols were missing from the 932-symbol cache; ANF failed the prior sector/industry gate. The new Qullamaggie exception removes those leadership exclusions, but does not guarantee any reference stock passes the unchanged pattern detector.

### Export fails with missing Ticker

The corrected `scan_board.py` normalizes empty inputs by adding a Ticker column, accepts an index named Ticker, and raises a clear ValueError for a populated input with neither. It normalizes method results, readiness, original results and supplied audit inputs before enrichment. Restart the kernel after installation; then rerun and regenerate the HTML.

### S&P 600 table-selection error

An error listing a 603-row symbol/security table can arise when the old parser mistakes short sector or SEC-link values for a second ticker column. The corrected downloader identifies historical change logs from Reason or addition/removal headers rather than arbitrary ticker-like values. It still rejects historical changes tables. Install the corrected downloader.py and restart the kernel.

### Cache coverage unexpectedly incomplete

The updated `_run_method_scan.py` reads SQLite with `mode=ro`, without `immutable=1`, so committed records in an active WAL can be visible. It does not change the database or remove any journal files. Check the printed database path and the downloader's cache path if coverage remains unexpected.

### HTML looks blank or old

Verify you opened the latest file in the configured report folder. Restart the kernel after installing Python updates and regenerate the HTML. The generator includes a readable static fallback if JavaScript fails and an error banner for interactive-render errors. Earlier blank output was caused by a missing closing style tag; use the corrected generator. Installing code does not update an already-exported HTML file.

### Missing PivotHigh / PivotLow in diagnostics

The corrected diagnostics routine calculates missing pivot indicators on a copy. If the old KeyError persists, check which scanner.py Jupyter imported, restart the kernel and rerun imports. Insufficient or invalid histories should produce diagnostic errors rather than an invented setup.

### Sector RS chart is empty

Rerun ETF loading with the updated market_view.py. Sector/SPY price dates and period start dates must align, with usable weekly/monthly returns. Older in-memory result frames may lack the new start-date fields. Check RSStatus, PriceDate and DataStatus.

### Stock bubbles are empty or show fewer members than expected

Check membership status and refresh errors. On a first run, REFRESH_PRICES=False cannot populate missing membership snapshots. Check cache coverage, report-date alignment, selected period and filters. Missing member prices are not fetched by the bubble reporting module. The Russell view is an IWM equity-holdings proxy.

### Cached data show an older date

A successful report export does not establish a successful download. Read each price date and fallback status. Do not delete usable cache history just because a refresh failed or yfinance printed “possibly delisted”; that wording alone does not confirm delisting.

### Jupyter prints pending-task / never-awaited warnings

Save the notebook and fully restart Jupyter. Capture the active Python executable and installed ipykernel/yfinance versions if it recurs. A warning printed next to pandas SQL code does not by itself establish a corrupt database. Investigate the kernel warning separately from an individual Yahoo download failure.

### Duplicate ticker cards

The same ticker can match several patterns and method columns. The board groups pattern matches within a column and retains all underlying records. CSV exports can therefore contain multiple rows for one ticker.


## Technical reference

### Indicator library

`indicators.py` covers four categories, computed once per ticker in
`compute_all()`:

- **Trend**: EMA/SMA (any period), WMA, VWMA.
- **Momentum**: RSI (Wilder-smoothed), Stochastic %K/%D, MACD, PPO, ROC.
- **Volatility**: ATR/ATR%/True Range, rolling standard deviation, Bollinger
  Bands (mid/upper/lower/width/%B), Keltner Channels.
- **Volume**: relative volume, OBV, the real Accumulation/Distribution line
  (Chaikin - not to be confused with `AccumulationScore`, a different custom
  0-4 composite used elsewhere), Chaikin Money Flow, rolling VWAP (true VWAP
  resets intraday; this project only has daily bars, so it's a rolling
  N-day variant - documented as such, not silently mislabeled).
- **Price structure**: pivots, swing highs/lows, compression, breakout
  scoring, distance-to-EMA/52-week-high/pivot.

`compute_all()` inserts roughly 120 columns one at a time, which pandas warns
about as a `PerformanceWarning` (a memory-layout efficiency note, not a
correctness issue) - suppressed deliberately rather than left to spam every
scan/backtest run. If this becomes an actual bottleneck at very large scale,
the real fix is batching every new column into one `pd.concat()` instead of
~120 individual assignments - a bigger refactor than was justified for now.


### Composite ranking

`ranking.py` combines seven factors into one score, weighted via
`config.RANKING_WEIGHTS` (must sum to 1.0 - `RankingEngine` raises rather
than silently renormalizing if it doesn't):

| Factor | Default weight | Source |
|---|---|---|
| Quality | 0.30 | `quality.py`'s 0-100 overall score |
| Confidence | 0.18 | Pattern's own confidence (score / max possible score) |
| Risk/Reward | 0.12 | Capped at 4:1 |
| Relative Strength | 0.15 | RS rating (1-99) vs. the scanned universe |
| Sector strength | 0.10 | Sector RS rank (1-99) vs. the scanned universe |
| Liquidity | 0.05 | Dollar volume vs. `config.MIN_DOLLAR_VOLUME` |
| Market Regime | 0.10 | `MarketRegimeEngine`'s 0-100 score |

RS/liquidity/regime **used to be computed and attached to each result for
display only** - they're now genuine inputs to `score`, which determines
sort order. If a benchmark/regime isn't supplied to `Scanner.scan()`, those
factors fall back to a neutral 50 rather than crashing or skewing results.


### Ranking configuration example

```python
RANKING_WEIGHTS = dict(
    quality=0.30, confidence=0.18, rr=0.12,
    rs=0.15, sector=0.10, liquidity=0.05, regime=0.10,
)
```

Weights must sum to 1.0. Inspect config.py for the installed values; these are the defaults documented in the supplied reference. ACCOUNT_SIZE and RISK_PER_TRADE configure research sizing, while ATR_STOP_MULTIPLIER and pattern thresholds control their respective rules. None are changed by the dashboard patches.

### Classifications

`sector_data.py`'s `SectorIndustryMap` is a local, CSV-backed lookup
(`data/sector_industry.csv`) - sector/industry classification doesn't change
often, so rather than hitting a network endpoint on every scan, it loads the
CSV once and only fetches (via `yfinance`) tickers it hasn't seen before,
persisting them for next time. `Scanner.scan(..., update_sector_data=True)`
(the default) does this automatically; set it `False` to skip (useful for
tests, or fully offline runs).

`RelativeStrengthEngine.group_rank()` uses this map to rank every sector and
every industry against each other (same 1-99 percentile method as
individual-stock RS ratings), which is what makes `SectorRank`/`IndustryRank`
real numbers now instead of the always-0 stub they used to be.


To inspect local classification coverage:

```python
from sector_data import SectorIndustryMap
sm = SectorIndustryMap()
print(len(sm), "tickers cached")
print(sm.get("AAPL"))
```

### Modules and folders

| Module or folder | Role |
|---|---|
| config.py | Universe settings, thresholds, ranking weights and risk controls |
| downloader.py / data.py / cache.py | Membership/universe construction, Yahoo price download, preparation and SQLite cache |
| indicators.py / structure.py / trendlines.py | Indicators, pivot extraction and fitted structure |
| patterns/ | Original detector implementations and rule scorecards |
| quality.py / ranking.py | Setup quality and composite ranking |
| relative_strength.py / sector_data.py | Stock/group RS and classification lookup |
| trend_quality.py / market_regime.py | Trend template, stage, accumulation/distribution and benchmark regime |
| scanner.py / report.py | Scan execution, diagnostics and report rows |
| method_scans.py / readiness.py / scan_context.py | Additional methods, reporting readiness and breadth/funnel context |
| scan_board.py | Single standalone HTML report generator |
| market_view.py | Yahoo ETF histories, period performance and sector RS |
| watchable.py / qullamaggie_candidates.py | Automatic cap maintenance, Watchable audit and independent Qullamaggie candidate gate |
| index_membership.py / stock_bubbles.py | Dated membership metadata and individual-stock bubble payload |
| portfolio.py / backtest.py | Research sizing, portfolio tracking and historical simulation |
| main.py / dashboard.py / alerts.py | Optional script pipeline, Streamlit view and notifications |
| research/ | Research analysis, exits and validation |
| tests/ / verification/ | Automated checks, evidence and benchmark support |
| data/ / cache/ | Metadata and cached histories |
| docs/ | Historical technical documentation |
| shoryuken_scanner.ipynb | Recommended unified notebook workflow |
| requirements.txt / LICENSE | Dependencies and MIT project license |

The deleted legacy universe.py is not part of the cleaned project. Keep core modules and notebook at the root to preserve imports and saved-object compatibility.

### Trend-quality context

`trend_quality.py` supplies:

- **TrendTemplate** (`x/8`) — Minervini's 8-criteria trend filter (price vs.
  50/150/200-day MA, MA stacking, 52-week high/low position). Not a pattern
  itself - a quality gate on the underlying trend.
- **Stage** — Weinstein's 4-stage classification (`Stage 1` basing / `Stage 2`
  advancing-buy zone / `Stage 3` topping / `Stage 4` declining-avoid), off the
  30-week (150-day) MA.
- **AccumDays / DistDays** — O'Neil-style accumulation/distribution day counts
  over the last ~25 sessions (a decline or advance on higher volume than the
  prior day). Also feeds `market_regime.py`: 5+ distribution days on SPY
  triggers a score penalty, the classic signal that a bull market is losing
  institutional support even while price still looks fine technically.

None of these three replace the pattern detectors - they're context columns
to help you filter *which* of the pattern hits are worth taking (e.g. a VCP
breakout with `TrendTemplate=8/8` and `Stage 2` is a different trend-context classification than the same VCP breakout on a `TrendTemplate=3/8`, `Stage 3` stock).




### How additional indicators are used



Adding an indicator to `indicators.py` doesn't automatically make it useful -
it has to be wired into scoring somewhere, deliberately:

- **`quality.py`'s momentum score** now blends RSI14 with raw rate-of-change
  (60/40) instead of raw ROC alone. RSI adds "is this move healthy or
  already extended" context: a stock up 20% with RSI 60 scores higher than
  one up 20% with RSI 95, even though raw ROC is identical.
- **`macd_bullish`** (MACD line above its signal line) is a scoring criterion
  in Shoryuken, VCP, FlatBase, CupHandle, DarvasBox, HighTightFlag, and
  BaseOnBase - the trend-following/breakout family.
- **`ttm_squeeze`** (Bollinger Bands sitting entirely inside Keltner
  Channels - a well-known volatility-compression signal) is a scoring
  criterion in VCP, DTRP, FlatBase, and DarvasBox - the contraction/breakout
  family, as a second, independent confirmation alongside the existing
  ATRCompression/RangeCompression checks.
- **`money_flow_positive`** (Chaikin Money Flow > 0) is a scoring criterion
  in PocketPivot, EpisodicPivot, and BaseOnBase - the institutional-
  accumulation family.

Stochastic, OBV, the A/D line, VWAP, WMA, and VWMA are computed but
deliberately not wired into any pattern's scoring yet - CMF already covers
the "does volume confirm the move" question those would otherwise
duplicate, and adding all of them everywhere would mostly add noise rather
than signal. They're available on every dataframe if you want to build
something with them.


### Optional entry points

```bash
python main.py
streamlit run dashboard.py
pytest tests/
```

main.py runs the script pipeline and reports/notifications/sizing configured there. dashboard.py is an optional Streamlit browser. The notebook is the integration point for the new standalone Market View and bubble charts; do not assume those HTML additions also modify Streamlit.

### Performance evidence

Legacy vectorization work replaced row iteration in pivot/contraction calculations and avoided unused RS calculations. The older README reported a 150-ticker synthetic, single-threaded scan benchmark of approximately 10.8 seconds to 1.4 seconds. Treat this as a historical benchmark, not an expected runtime for your machine or live downloads.

The Yahoo-loading change measured 32 evenly selected real cached histories, retaining full history, with simulated download results and three alternating-order repeats:

| Measure | Result |
|---|---|
| Baseline median | 2.319 seconds |
| Candidate median | 1.072 seconds |
| Tested-step reduction | 53.7% |
| Speedup | 2.16× |
| Indicator equality | Exact DataFrame equality |
| Scanner equality | 17 identical matches, including score, quality, confidence and trade levels |

This measured the tested price-return/indicator portion, not live Yahoo download speed or full-universe runtime. Changes to research methodology, history length and bootstrap counts were not used to obtain this result.

### Interpretation limits

- Rule confidence is not a calibrated win probability.
- Stock/group RS depends on its comparison universe; RS proxies retain their labels.
- Daily rolling VWAP is not intraday session-reset VWAP.
- Adaptive pivots use a centered window; recent swings need later confirmation. Historical evaluation must use only information available at each simulated date.
- Recomputed historical indicators do not eliminate survivorship, execution or cost assumptions.
- Yahoo refresh failures can produce stale or unavailable observations.
- Software checks and UI smoke tests do not establish trading profitability.

## Project cleanup and validation history

### Cleaned base project

The cleaned full archive retained supplied price/ETF caches, classifications/fundamentals, research artifacts, exports and historical outputs. It removed:

| Item | Reason/count |
|---|---|
| universe.py | Unused alternate CSV loader; active loading uses downloader.py |
| research_output/multiyear/_exit_oos.py | Unreferenced hardcoded experiment with malformed Windows path |
| Four bytecode-cache folders | 118 generated files |
| Two notebook checkpoint folders | 5 generated files |
| Pytest cache | 5 generated files |

Total removed: 130 files, including two program files. Research exit/validation functionality remains in the retained research modules. Optional dashboard, alerts, fundamentals and research entry points were retained deliberately.

Historical technical documents were grouped under docs/. Core modules, notebook, entry points and tests stayed at the root. Data paths were preserved. The original uploaded ZIP was not changed.

Cleanup verification recorded 546 protected data/output files byte-identical to the uploaded archive, and 696 retained original files byte-identical except the two stated documentation-reference edits. Executable method_scans.py AST and notebook code cells were unchanged at that cleanup stage. These integrity counts describe the cleaned base archive, not an assertion that later feature patches made no code changes.

### Validation by update

| Stage | Recorded verification |
|---|---|
| Full cleanup | 275 offline harness checks passed; data/output integrity verified |
| Yahoo-only loading | 277 offline checks; cached-data benchmark and exact-result comparison |
| Scan context | 280 offline checks passed; 1 skipped; compilation and simulated DOM checks |
| Sector RS | 14 focused offline checks; JS syntax and simulated DOM |
| Three-index bubbles | 289 offline checks passed; 1 skipped; compilation, JS and simulated DOM |

Counts are per run, not additive. The supplied offline pytest-compatible harness was used for these recorded runs; they are not claims of installed pytest execution. Data tests/benchmarks ran on isolated copies. Live Yahoo connectivity and actual browser layout were not verified in those feature checks.

Live membership source responses were separately parsed: S&P 500 503 tickers, Nasdaq 100 101 tickers, and IWM 1,976 equities with effective date 2026-10-08. These are dated source checks, not guaranteed current counts or a guarantee of local cached price coverage.

Evidence files are in the verification directories of the relevant delivered archives; the cleanup manifest records removals and moves. No code or data was changed by consolidating this guide.

### Current output locations and optional cleanup

| Item | Current role / guidance |
|---|---|
| `exports/method_scans/method_results.csv` | Current retained method matches, before readiness classification |
| `exports/method_scans/Qullamaggie_Breakout.csv` | Current Qullamaggie matches |
| `exports/method_scans/readiness_report.csv` | Reporting readiness |
| `scan_results.csv` | Original scanner export; relative to notebook working directory |
| `Documents/Shoryuken_reports/` | HTML, `watchable_audit.csv`, market-cap CSV and configured reporting history |
| Legacy `results/` | Old method CSV exports; current notebook does not use this folder |
| `verification/`, `evidence/`, `verification.json` | Optional historical validation, benchmarks and backtest evidence; removal loses those records |
| Old files inside `logs/` and `charts/` | Optional runtime logs and generated charts; keep configured folders |
| `research_output/` | Historical research databases/results; archive or remove only if no longer needed; removal may prevent resuming/comparing research runs |
| Old HTML, `scan_out.txt`, `cleanup_manifest.json` | Optional report snapshots, console output and cleanup record |
| `docs/` | Optional documentation; not needed to execute scans |
| `cache/`, `data/`, `patterns/`, `research/`, `tests/`, core Python files | Keep: histories, metadata, implementations, research tools and tests |

Exports update only when their notebook export cells run. An old CSV is not evidence of the current in-memory scan. The current notebook does not save an unrestricted full-universe scan by default; `all_method_results` is in memory, while `method_results` is the retained per-method selection. Deleting historical files is optional and was not performed by these updates. Cleanup guidance was checked against the supplied project copy; inspect any locally added files or integrations before removing them.

### October 13–17 update checks

The Ticker fix passed isolated empty-result, populated-result, indexed-Ticker, input-preservation and malformed-input checks. Zoom passed scripted zoom/pan/reset/Ctrl-wheel/bounds checks and JavaScript syntax validation; actual browser layout was not verified. Automatic cap maintenance passed simulated fetch tests for selective refresh, failed-snapshot preservation, fresh reuse and first-run creation. Qullamaggie candidate checks covered cap/ATR gates and stale/missing validity; the SQLite reader passed a committed-WAL visibility check; edited notebook cells compiled. The S&P 600 parser passed synthetic constituent/change-log and reordered-table cases. These checks did not perform live Yahoo downloads, verify the user's latest local coverage, or establish identical results to an external screener.

## Glossary

- **ATR** — Average True Range, a volatility measure. `ATR14` = 14-day ATR.
- **R / R-multiple** — Return measured in units of initial risk. "2R" means
  a gain of twice what you risked.
- **RR** — Reward-to-risk ratio (Target distance ÷ Stop distance).
- **RS rating** — Relative Strength rating, 1-99 percentile vs. the scanned
  universe.
- **Distribution day** — A decline of ≥0.2% on higher volume than the prior
  day; a sign of institutional selling. Mirror concept: accumulation day.
- **Stage (Weinstein)** — 1 (basing) / 2 (advancing, buy zone) / 3 (topping)
  / 4 (declining).
- **Trend Template (Minervini)** — An 8-criteria checklist for whether a
  stock's underlying trend is strong enough to be worth trading at all,
  independent of any specific pattern.
- **Look-ahead bias** — Accidentally using information that wouldn't have
  been available at the time being simulated. The single most common way a
  backtest lies to you.
- **Survivorship bias** — Only testing on securities that still exist
  today, which excludes the ones that failed/got delisted along the way and
  makes historical results look better than they really were.


## Document sources

This guide consolidates the seven uploaded documents: README(1).md, USER_MANUAL(1).md, LOADING_README(1).md, IMPLEMENTATION_README(1).md, SECTOR_RS_README(1).md, BUBBLES_README(1).md and PROJECT_CLEANUP(1).md. Later update notes take precedence over older workflow descriptions. The source documents remain unchanged. Project code and config.py are authoritative for installed settings.
