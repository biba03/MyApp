"""
trend_quality.py

Quality gates used by systematic traders to decide whether a stock is
even worth evaluating for a pattern trade, independent of any
specific chart pattern:

- MinerviniTrendTemplate: the 8-criteria trend filter Minervini uses
  as a hard gate before looking at any setup (VCP included).
- StageAnalyzer: Weinstein-style 4-stage classification (basing /
  advancing / topping / declining) off the ~30-week MA.
- DistributionDayCounter: O'Neil-style distribution/accumulation day
  counting - used at the index level as a market-health signal, and
  per-stock as a supporting signal.

None of these produce a trade (no entry/stop/target) - they're
filters and context, meant to sit alongside the pattern detectors in
patterns/, not replace them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


##############################################################################
# Minervini Trend Template
##############################################################################

@dataclass(slots=True)
class TrendTemplateResult:

    price_above_150: bool

    price_above_200: bool

    ma150_above_ma200: bool

    ma200_trending_up: bool

    ma50_above_150_200: bool

    price_above_50: bool

    above_52w_low_by_30pct: bool

    within_25pct_of_52w_high: bool

    @property
    def criteria(self) -> dict:

        return {
            "Price > 150-day MA": self.price_above_150,
            "Price > 200-day MA": self.price_above_200,
            "150-day MA > 200-day MA": self.ma150_above_ma200,
            "200-day MA trending up (1mo)": self.ma200_trending_up,
            "50-day MA > 150 & 200-day MA": self.ma50_above_150_200,
            "Price > 50-day MA": self.price_above_50,
            "Price >= 30% above 52w low": self.above_52w_low_by_30pct,
            "Price within 25% of 52w high": self.within_25pct_of_52w_high,
        }

    @property
    def passed_count(self) -> int:

        return sum(self.criteria.values())

    @property
    def total_count(self) -> int:

        return len(self.criteria)

    @property
    def passes_all(self) -> bool:

        return self.passed_count == self.total_count

    def __str__(self) -> str:

        return f"{self.passed_count}/{self.total_count}"


class MinerviniTrendTemplate:
    """
    Uses SMA150/SMA200 (already computed by indicators.py), matching
    the original definition, which is built on simple moving
    averages rather than exponential ones.
    """

    def evaluate(self, df: pd.DataFrame) -> TrendTemplateResult:

        latest = df.iloc[-1]

        ma200_month_ago = (
            df["SMA200"].iloc[-21] if len(df) > 21 else np.nan
        )

        return TrendTemplateResult(

            price_above_150=bool(latest.Close > latest.SMA150),

            price_above_200=bool(latest.Close > latest.SMA200),

            ma150_above_ma200=bool(latest.SMA150 > latest.SMA200),

            ma200_trending_up=bool(
                not np.isnan(ma200_month_ago) and latest.SMA200 > ma200_month_ago
            ),

            ma50_above_150_200=bool(
                latest.SMA50 > latest.SMA150 and latest.SMA50 > latest.SMA200
            ),

            price_above_50=bool(latest.Close > latest.SMA50),

            above_52w_low_by_30pct=bool(latest.Close >= latest.Low52W * 1.30),

            within_25pct_of_52w_high=bool(latest.Close >= latest.High52W * 0.75),

        )


##############################################################################
# Weinstein Stage Analysis
##############################################################################

@dataclass(slots=True)
class StageResult:

    stage: str          # "Stage 1" .. "Stage 4"

    label: str

    ma30w_rising: bool

    price_above_ma30w: bool

    rs_line_rising: bool | None  # None if no rs_line was provided


class StageAnalyzer:
    """
    Classifies a stock into Weinstein's 4 stages using the ~30-week
    (150 trading day) MA as the primary trend proxy - SMA150, already
    computed by indicators.py.

    Only Stage 2 is a "buy zone" in Weinstein's framework; Stage 1 is
    basing/not yet actionable, Stage 3 is topping/distribution risk,
    Stage 4 is a downtrend to avoid.
    """

    def evaluate(
        self,
        df: pd.DataFrame,
        rs_line: pd.Series | None = None,
    ) -> StageResult:

        latest = df.iloc[-1]

        ma_now = df["SMA150"].iloc[-1]

        ma_month_ago = df["SMA150"].iloc[-21] if len(df) > 21 else np.nan

        ma_rising = bool(not np.isnan(ma_month_ago) and ma_now > ma_month_ago)

        price_above_ma = bool(latest.Close > ma_now)

        rs_rising = None

        if rs_line is not None and len(rs_line) > 21:

            rs_rising = bool(rs_line.iloc[-1] > rs_line.iloc[-21])

        if price_above_ma and ma_rising:

            stage, label = "Stage 2", "Advancing (uptrend - buy zone)"

        elif not price_above_ma and not ma_rising:

            stage, label = "Stage 4", "Declining (downtrend - avoid)"

        elif price_above_ma and not ma_rising:

            stage, label = "Stage 3", "Topping (distribution risk)"

        else:

            stage, label = "Stage 1", "Basing (accumulation - not yet actionable)"

        return StageResult(

            stage=stage,

            label=label,

            ma30w_rising=ma_rising,

            price_above_ma30w=price_above_ma,

            rs_line_rising=rs_rising,

        )


##############################################################################
# Distribution days / institutional accumulation
##############################################################################

@dataclass(slots=True)
class AccumulationResult:

    accumulation_days: int

    distribution_days: int

    net_score: int  # accumulation_days - distribution_days


class DistributionDayCounter:
    """
    O'Neil-style distribution day counting. A "distribution day" is a
    decline of at least `decline_threshold` on volume higher than the
    prior day's - the classic institutional-selling tell. An
    "accumulation day" is the bullish mirror image.

    Used at the index level (SPY/QQQ/IWM) as a market-health signal -
    5+ distribution days in a rolling ~25-session window is O'Neil's
    standard warning that a bull market is losing institutional
    support - and per-stock as a supporting signal alongside the
    pattern detectors.
    """

    def __init__(self, lookback: int = 25, decline_threshold: float = 0.002):

        self.lookback = lookback

        self.decline_threshold = decline_threshold

    def evaluate(self, df: pd.DataFrame) -> AccumulationResult:

        window = df.iloc[-self.lookback:]

        pct_change = window["Close"].pct_change()

        vol_up = window["Volume"] > window["Volume"].shift(1)

        distribution = (pct_change <= -self.decline_threshold) & vol_up

        accumulation = (pct_change >= self.decline_threshold) & vol_up

        return AccumulationResult(

            accumulation_days=int(accumulation.sum()),

            distribution_days=int(distribution.sum()),

            net_score=int(accumulation.sum()) - int(distribution.sum()),

        )
