"""
quality.py

Universal pattern quality engine.

Every detector produces a normalized score (0-100)
based on geometry, trend, volume and breakout quality.
"""

from __future__ import annotations

import math

from dataclasses import dataclass


##############################################################################
# Quality Result
##############################################################################

@dataclass(slots=True)
class QualityResult:

    geometry: float

    trend: float

    volume: float

    momentum: float

    breakout: float

    risk: float

    overall: float
##############################################################################

class PatternQuality:

    """
    Converts raw metrics into normalized scores.
    """

    ##################################################################

    @staticmethod
    def normalize(

        value,

        low,

        high,

    ):

        if value <= low:

            return 0.0

        if value >= high:

            return 100.0

        return (

            (value-low)

            /

            (high-low)

        )*100
##############################################################################

    def geometry(

        self,

        trend,

    ):

        convergence = self.normalize(

            trend.convergence,

            0.10,

            0.60,

        )

        symmetry = trend.symmetry * 100

        upper_fit = trend.upper.r2 * 100

        lower_fit = trend.lower.r2 * 100

        return (

            convergence * 0.35

            +

            symmetry * 0.25

            +

            upper_fit * 0.20

            +

            lower_fit * 0.20

        )
##############################################################################

    def trend(

        self,

        df,

    ):

        score = 0

        latest = df.iloc[-1]

        if latest.Close > latest.EMA20:

            score += 20

        if latest.Close > latest.EMA50:

            score += 20

        if latest.Close > latest.EMA150:

            score += 20

        if latest.Close > latest.EMA200:

            score += 20

        if latest.EMA50 > latest.EMA150:

            score += 10

        if latest.EMA150 > latest.EMA200:

            score += 10

        return score
##############################################################################

    def volume(

        self,

        df,

    ):

        latest = df.iloc[-1]

        score = 0

        score += min(

            latest.RVOL,

            3

        ) * 20

        if latest.IsDryUp:

            score += 20

        if latest.VolumeTrend > 0:

            score += 20

        return min(

            score,

            100,

        )
##############################################################################

    @staticmethod
    def _rsi_momentum_score(rsi):
        """
        Triangular scoring: RSI in the 40-65 "healthy uptrend, not yet
        extended" zone scores highest, tapering to 0 both toward
        oversold (<=40) and toward overbought (>=90). Falls back to a
        neutral 50 if RSI isn't available (e.g. too little history).
        """

        if rsi is None or (isinstance(rsi, float) and math.isnan(rsi)):

            return 50.0

        if rsi <= 65:

            return max(0.0, min(100.0, (rsi - 40) / (65 - 40) * 100))

        return max(0.0, min(100.0, (90 - rsi) / (90 - 65) * 100))

    def momentum(

        self,

        df,

    ):

        roc = df.Close.pct_change(20).iloc[-1]

        roc_score = self.normalize(

            roc,

            -0.05,

            0.20,

        )

        rsi_value = df["RSI14"].iloc[-1] if "RSI14" in df.columns else None

        rsi_score = self._rsi_momentum_score(rsi_value)

        # 60% raw price rate-of-change, 40% RSI - RSI adds "is this move
        # healthy or already extended" context that raw ROC alone can't
        # distinguish (a stock up 20% with RSI 95 is a different
        # situation than one up 20% with RSI 60).
        return roc_score * 0.6 + rsi_score * 0.4
##############################################################################

    def breakout(

        self,

        df,

    ):

        latest = df.iloc[-1]

        score = latest.BreakoutScore

        if latest.ValidGap:

            score += 10

        if latest.BullMarubozu:

            score += 10

        if latest.TightClose:

            score += 10

        return min(

            score,

            100,

        )
##############################################################################

    def risk(

        self,

        entry,

        stop,

        target,

    ):

        risk = entry-stop

        reward = target-entry

        if risk <= 0:

            return 0

        rr = reward/risk

        return self.normalize(

            rr,

            1,

            3,

        )
##############################################################################

    def evaluate(

        self,

        df,

        trend,

        entry,

        stop,

        target,

    ):

        geometry = self.geometry(trend)

        trend_score = self.trend(df)

        volume = self.volume(df)

        momentum = self.momentum(df)

        breakout = self.breakout(df)

        risk = self.risk(

            entry,

            stop,

            target,

        )

        overall = (

            geometry * 0.25

            +

            trend_score * 0.15

            +

            volume * 0.15

            +

            momentum * 0.10

            +

            breakout * 0.20

            +

            risk * 0.15

        )

        return QualityResult(

            geometry,

            trend_score,

            volume,

            momentum,

            breakout,

            risk,

            overall,

        )
