"""
scanner.py

Main scanning engine.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import os

import numpy as np
from tqdm.auto import tqdm

import config
from patterns.shoryuken import Shoryuken
from patterns.vcp import VCP
from patterns.dtrp import DTRP
from patterns.pocket_pivot import PocketPivot
from patterns.flat_base import FlatBase
from patterns.cup_handle import CupHandle
from patterns.episodic_pivot import EpisodicPivot
from patterns.darvas_box import DarvasBox
from patterns.high_tight_flag import HighTightFlag
from patterns.base_on_base import BaseOnBase

from ranking import RankingEngine
from relative_strength import RelativeStrengthEngine
from sector_data import SectorIndustryMap
from structure import StructureAnalyzer
from trendlines import TrendlineAnalyzer
from trend_quality import MinerviniTrendTemplate, StageAnalyzer, DistributionDayCounter


class Scanner:

    def __init__(self):

        self.detectors = [

            Shoryuken(),

            VCP(),

            DTRP(),

            PocketPivot(),

            FlatBase(),

            CupHandle(),

            EpisodicPivot(),

            DarvasBox(),

            HighTightFlag(),

            BaseOnBase(),

        ]

        self.ranking = RankingEngine()

        self.structure = StructureAnalyzer()

        self.trendlines = TrendlineAnalyzer()

        self.rs_engine = RelativeStrengthEngine()

        self.trend_template = MinerviniTrendTemplate()

        self.stage_analyzer = StageAnalyzer()

        self.distribution_counter = DistributionDayCounter()

        self.sector_map = SectorIndustryMap()

        # Fundamental leadership overlay (Minervini SEPA). Off unless
        # config.REQUIRE_FUNDAMENTALS is set; missing data fails open.
        from fundamentals import FundamentalStore, FundamentalGate

        self.fundamentals = FundamentalStore()

        self.fundamental_gate = FundamentalGate(self.fundamentals)

        self.last_scan_errors = {}

    ###################################################################
    # Liquidity score (0-100), used both for display and in ranking
    ###################################################################

    @staticmethod
    def liquidity_score(df, cap_multiple: float = 3.0) -> float:
        """
        0-100 liquidity score: 100 once dollar volume reaches
        `cap_multiple` * config.MIN_DOLLAR_VOLUME, scaling linearly
        below that, 0 at or below 0 dollar volume.
        """

        dollar_volume = float(df["DollarVolume"].iloc[-1])

        cap = config.MIN_DOLLAR_VOLUME * cap_multiple

        if cap <= 0:

            return 0.0

        return float(np.clip(dollar_volume / cap, 0.0, 1.0) * 100)

    ###################################################################
    # Hard entry filters (screening gates)
    ###################################################################

    @staticmethod
    def passes_entry_filters(df, rs_rating=None, sector_rank=None) -> bool:
        """
        Institutional pre-screen applied BEFORE pattern detection. A stock
        failing any enabled gate is excluded outright:

          - strong relative strength   (RS rating >= MIN_RS_RATING)
          - strong group/sector        (sector rank >= MIN_SECTOR_RANK)
          - price above the 50 SMA
          - price above the 200 SMA    (exclude stocks below 200 SMA)
          - not overextended           (Close - SMA50 <= MAX_ATR_EXTENSION x ATR)
          - good dollar volume         (>= MIN_DOLLAR_VOLUME)

        RS/sector gates are only enforced when those values are available
        (i.e. a benchmark was supplied); missing OHLC-derived columns fail
        safe (the stock is skipped rather than crashing the scan).
        """

        try:

            last = df.iloc[-1]

            close = float(last["Close"])

            sma50 = float(last["SMA50"])

            sma200 = float(last["SMA200"])

            atr = float(last["ATR14"])

            dollar_volume = float(last["DollarVolume"])

        except (KeyError, IndexError, ValueError):

            return False

        if config.REQUIRE_ABOVE_SMA50 and not close > sma50:

            return False

        if config.REQUIRE_ABOVE_SMA200 and not close > sma200:

            return False

        if config.MAX_ATR_EXTENSION_FROM_SMA50 is not None and atr > 0:

            if (close - sma50) > config.MAX_ATR_EXTENSION_FROM_SMA50 * atr:

                return False

        if config.REQUIRE_MIN_DOLLAR_VOLUME and dollar_volume < config.MIN_DOLLAR_VOLUME:

            return False

        if rs_rating is not None and config.MIN_RS_RATING and rs_rating < config.MIN_RS_RATING:

            return False

        if sector_rank is not None and config.MIN_SECTOR_RANK and sector_rank < config.MIN_SECTOR_RANK:

            return False

        return True

    @staticmethod
    def atr_extension_50sma(df) -> float | None:
        """
        How many ATRs the latest close sits above the 50 SMA - a plain
        overextension read-out reported alongside every setup (not a gate).
        """

        try:

            last = df.iloc[-1]

            atr = float(last["ATR14"])

            if atr <= 0:

                return None

            return round((float(last["Close"]) - float(last["SMA50"])) / atr, 2)

        except (KeyError, IndexError, ValueError):

            return None

    ###################################################################

    def scan_stock(

        self,

        ticker,

        df,

        quality_engine,

        rs_rating=None,

        benchmark=None,

        regime_score=None,

        sector_rank=None,

        industry_rank=None,

        apply_filters=True,

    ):

        results = []

        # Hard pre-screen: drop the stock before any pattern work if it
        # fails the institutional entry filters (technical + optional
        # fundamental leadership gate).
        if apply_filters and not self.passes_entry_filters(df, rs_rating, sector_rank):

            return results

        if apply_filters and config.REQUIRE_FUNDAMENTALS and not self.fundamental_gate.passes(ticker):

            return results

        highs, lows = self.structure.pivots(df)

        trend = self.trendlines.analyze(highs, lows)

        if trend is None:

            return results

        # Quality-gate metrics: same for every pattern hit on this
        # ticker, so compute once rather than per-detector.
        trend_template_result = self.trend_template.evaluate(df)

        rs_line = None

        if benchmark is not None:

            try:

                rs_raw = self.rs_engine.rs_line(df, benchmark)

                rs_line = self.rs_engine.smooth(rs_raw)

            except Exception:

                rs_line = None

        stage_result = self.stage_analyzer.evaluate(df, rs_line=rs_line)

        accumulation_result = self.distribution_counter.evaluate(df)

        liquidity = self.liquidity_score(df)

        extension = self.atr_extension_50sma(df)

        for detector in self.detectors:

            try:

                pattern = detector.detect(df)

            except Exception:

                # One bad detector/ticker combination shouldn't take
                # down the whole scan.
                continue

            if not pattern.detected:

                continue

            # Keep detector points distinct from the live composite ranking.
            pattern.metadata["RawDetectorScore"] = float(pattern.score)

            from pattern_triggers import pattern_trigger_info
            pattern.metadata.update(pattern_trigger_info(detector, df, pattern.metadata))

            quality = quality_engine.evaluate(

                df,

                trend,

                pattern.entry,

                pattern.stop,

                pattern.target,

            )

            ranked = self.ranking.rank(

                ticker,

                pattern,

                quality,

                rs_rating,

                trend_template=str(trend_template_result),

                stage=stage_result.stage,

                accum_days=accumulation_result.accumulation_days,

                dist_days=accumulation_result.distribution_days,

                liquidity_score=liquidity,

                regime_score=regime_score,

                sector_rank=sector_rank,

                industry_rank=industry_rank,

                atr_extension_50sma=extension,

            )

            results.append(ranked)

        return results

    ###################################################################

    def compute_rs_ratings(

        self,

        data,

        benchmark,

        show_progress=True,

    ):
        """
        RS rating is a percentile rank against the rest of the
        universe, so it has to be computed once across every ticker
        before any individual stock's rating means anything. Also
        computes sector_rank/industry_rank the same way, by grouping
        each ticker's weighted_return via SectorIndustryMap.

        Returns (rs_ratings, sector_ranks, industry_ranks) - each a
        {ticker: value_or_None} dict.
        """

        weighted_returns = {}

        items = tqdm(
            data.items(),
            total=len(data),
            desc="Computing RS",
            unit="ticker",
            disable=not show_progress,
        )

        for ticker, df in items:

            try:

                weighted_returns[ticker] = self.rs_engine.weighted_return(df.Close)

            except Exception:

                continue

        universe = np.array(list(weighted_returns.values()), dtype=float)

        universe = universe[~np.isnan(universe)]

        ratings = {}

        if len(universe) == 0:

            empty = {t: None for t in data}

            return empty, empty, empty

        for ticker, wr in weighted_returns.items():

            try:

                ratings[ticker] = self.rs_engine.rating(wr, universe)

            except Exception:

                ratings[ticker] = None

        for ticker in data:

            ratings.setdefault(ticker, None)

        sector_ranks = self.rs_engine.group_rank(
            weighted_returns, self.sector_map, key="sector"
        )

        industry_ranks = self.rs_engine.group_rank(
            weighted_returns, self.sector_map, key="industry"
        )

        return ratings, sector_ranks, industry_ranks

    ###################################################################

    def diagnostics(
        self,

        data,

    ):
        """
        Debug helper - NOT used by scan(). For every ticker, reports
        whether a trend could even be computed, and the raw score
        every detector would give it regardless of whether it clears
        that detector's detection threshold.

        A normal "quiet market" day looks like: TrendOK mostly True,
        scores clustered a bit below each threshold.

        A bug upstream (bad data, broken indicators, etc.) looks like:
        TrendOK mostly False, or scores at/near 0 for every pattern.
        """

        import pandas as pd

        thresholds = {d.name: d.minimum_score for d in self.detectors}

        rows = []

        for ticker, source in data.items():
            row = {"Ticker": ticker, "TrendOK": False, "DiagnosticError": None,
                   **{detector.name: None for detector in self.detectors}}
            try:
                if source is None or source.empty:
                    raise ValueError("Empty price history")
                df = source.copy()
                if not {"PivotHigh", "PivotLow"}.issubset(df.columns):
                    import indicators
                    indicators.compute_all(df)
                highs, lows = self.structure.pivots(df)
                trend = self.trendlines.analyze(highs, lows)
                row["TrendOK"] = trend is not None
            except Exception as exc:
                row["DiagnosticError"] = f"{type(exc).__name__}: {exc}"
                rows.append(row)
                continue
            for detector in self.detectors:
                if trend is None:
                    continue
                try:
                    pattern = detector.detect(df)
                    row[detector.name] = round(pattern.score, 1)
                except Exception as exc:
                    row[detector.name] = f"ERROR: {exc}"
            rows.append(row)
        report = pd.DataFrame(rows, columns=["Ticker", "TrendOK", "DiagnosticError", *thresholds])

        print("Thresholds (minimum score to count as detected):", thresholds)

        print(f"TrendOK: {report['TrendOK'].sum()} / {len(report)} tickers")

        return report

    ###################################################################

    def scan_methods(self, market, asof=None, cfg=None):
        """Independent tagged method screens; existing scan() remains unchanged."""
        from method_scans import scan_methods
        return scan_methods(market, asof=asof, cfg=cfg)

    def scan(

        self,

        data,

        quality_engine,

        benchmark=None,

        regime=None,

        update_sector_data=True,

        workers=None,

        show_progress=True,

        apply_filters=True,

        update_fundamentals=False,

        candidate_tickers=None,

        leadership_snapshot=None,

    ):
        """
        regime: an optional market_regime.MarketRegime (from
        MarketRegimeEngine.analyze()) - its .score feeds into every
        result's ranking score. Pass None to skip (falls back to a
        neutral 50 in the ranking formula rather than crashing).

        update_sector_data: if True (default), fetches sector/industry
        for any ticker not already in the local
        data/sector_industry.csv before ranking - wrapped in a
        try/except so a network hiccup here doesn't abort the scan;
        those tickers just fall back to "Unknown"/no group rank for
        this run.

        workers: thread count for per-ticker scanning. Defaults to
        min(32, (cpu_count or 4) * 4) - each ticker's work is mostly
        vectorized pandas/numpy calls, which release the GIL during
        the actual computation, so a higher thread count than "one per
        CPU core" still gives a real speedup here, up to a point.

        show_progress: print a tqdm progress bar as tickers finish.
        """

        if workers is None:

            workers = min(32, (os.cpu_count() or 4) * 4)

        if update_sector_data:

            try:

                self.sector_map.update_missing(list(data.keys()))

            except Exception:

                pass

        if update_fundamentals and config.REQUIRE_FUNDAMENTALS:

            try:

                self.fundamentals.update_missing(list(data.keys()))

            except Exception:

                pass

        rs_ratings, sector_ranks, industry_ranks = {}, {}, {}

        if leadership_snapshot is not None:
            rs_ratings, sector_ranks, industry_ranks = leadership_snapshot
        elif benchmark is not None:

            rs_ratings, sector_ranks, industry_ranks = self.compute_rs_ratings(
                data, benchmark, show_progress=show_progress
            )

        regime_score = regime.score if regime is not None else None

        output = []

        errors = {}

        with ThreadPoolExecutor(max_workers=workers) as pool:

            futures = {

                pool.submit(

                    self.scan_stock,

                    ticker,

                    df,

                    quality_engine,

                    rs_ratings.get(ticker),

                    benchmark,

                    regime_score,

                    sector_ranks.get(ticker),

                    industry_ranks.get(ticker),

                    apply_filters,

                ): ticker

                for ticker, df in data.items()
                if candidate_tickers is None or ticker in candidate_tickers

            }

            progress = tqdm(

                as_completed(futures),

                total=len(futures),

                desc="Scanning",

                unit="ticker",

                disable=not show_progress,

            )

            for future in progress:

                ticker = futures[future]

                try:

                    output.extend(future.result())

                except Exception as exc:

                    errors[ticker] = f"{type(exc).__name__}: {exc}"

        self.last_scan_errors = errors

        if errors:

            sample = list(errors.items())[:10]

            print(f"\n{len(errors)} ticker(s) failed during scanning and were skipped:")

            for ticker, err in sample:

                print(f"  {ticker}: {err}")

            if len(errors) > 10:

                print(f"  ... and {len(errors) - 10} more (see scanner.last_scan_errors for all of them)")

        output.sort(

            key=lambda x: x.score,

            reverse=True,

        )

        return output
