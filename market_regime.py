"""
market_regime.py

Determine whether market conditions favor
long, short, or neutral trading.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MarketRegime:

    trend: str          # Bull / Bear / Neutral

    score: float        # 0-100

    risk_multiplier: float

    long_allowed: bool

    short_allowed: bool

    exposure: float

    distribution_days: int

    reasons: list[str]

import pandas as pd

from trend_quality import DistributionDayCounter


class MarketRegimeEngine:

    def __init__(self):

        self.distribution_counter = DistributionDayCounter()

    def analyze(

        self,

        spy: pd.DataFrame,

        qqq: pd.DataFrame,

        iwm: pd.DataFrame,

    ) -> MarketRegime:

        score = 0

        reasons = []

        score += self.market_score(spy, "SPY", reasons)
        score += self.market_score(qqq, "QQQ", reasons)
        score += self.market_score(iwm, "IWM", reasons)

        score /= 3

        # O'Neil-style distribution day count on the primary index:
        # 5+ distribution days in a rolling ~25-session window is the
        # classic signal that a bull market is losing institutional
        # support, even while price is still holding up technically.
        distribution_days = self.distribution_counter.evaluate(spy).distribution_days

        if distribution_days >= 5:

            penalty = min(distribution_days, 10) * 4

            score = max(0, score - penalty)

            reasons.append(
                f"{distribution_days} distribution days on SPY in the last "
                f"{self.distribution_counter.lookback} sessions (-{penalty} pts)"
            )

        return self.build(score, reasons, distribution_days)
    def market_score(

        self,

        df,

        name,

        reasons,

    ):

        latest = df.iloc[-1]

        score = 0

        if latest.Close > latest.EMA20:

            score += 20

            reasons.append(f"{name} above EMA20")

        if latest.Close > latest.EMA50:

            score += 20

        if latest.Close > latest.EMA200:

            score += 30

        if latest.EMA50 > latest.EMA200:

            score += 15

        if latest.RVOL > 1:

            score += 15

        return score
    def build(

        self,

        score,

        reasons,

        distribution_days=0,

    ):

        if score >= 80:

            return MarketRegime(

                trend="Bull",

                score=score,

                risk_multiplier=1.0,

                exposure=1.00,

                long_allowed=True,

                short_allowed=False,

                distribution_days=distribution_days,

                reasons=reasons,

            )

        if score >= 60:

            return MarketRegime(

                trend="Bull",

                score=score,

                risk_multiplier=0.75,

                exposure=0.60,

                long_allowed=True,

                short_allowed=False,

                distribution_days=distribution_days,

                reasons=reasons,

            )

        if score >= 40:

            return MarketRegime(

                trend="Neutral",

                score=score,

                risk_multiplier=0.50,

                exposure=0.30,

                long_allowed=False,

                short_allowed=False,

                distribution_days=distribution_days,

                reasons=reasons,

            )

        return MarketRegime(

            trend="Bear",

            score=score,

            risk_multiplier=0.30,

            exposure=0.10,

            long_allowed=False,

            short_allowed=True,

            distribution_days=distribution_days,

            reasons=reasons,

        )
