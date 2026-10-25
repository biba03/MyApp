"""
trendlines.py

Regression-based trendline engine.

Fits upper and lower trendlines using pivot highs/lows.

Every pattern uses this.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


##############################################################################
# TrendLine
##############################################################################

@dataclass(slots=True)
class TrendLine:

    slope: float

    intercept: float

    r2: float

    start_index: int

    end_index: int


##############################################################################
# Trend Result
##############################################################################

@dataclass(slots=True)
class TrendResult:

    upper: TrendLine

    lower: TrendLine

    convergence: float

    apex: float

    width_start: float

    width_end: float

    symmetry: float
##############################################################################

class TrendlineAnalyzer:

    ###############################################################

    @staticmethod
    def regression(points):

        if len(points) < 2:

            return None

        x = np.array([p.index for p in points])

        y = np.array([p.price for p in points])

        slope, intercept = np.polyfit(x, y, 1)

        fitted = slope * x + intercept

        ss_res = np.sum((y - fitted) ** 2)

        ss_tot = np.sum((y - y.mean()) ** 2)

        if ss_tot == 0:

            r2 = 1.0

        else:

            r2 = 1 - ss_res / ss_tot

        return TrendLine(

            slope=slope,

            intercept=intercept,

            r2=r2,

            start_index=int(x.min()),

            end_index=int(x.max()),

        )
##############################################################################

    @staticmethod
    def channel_width(

        upper,

        lower,

        x,

    ):

        top = (

            upper.slope * x

            +

            upper.intercept

        )

        bottom = (

            lower.slope * x

            +

            lower.intercept

        )

        return top - bottom
##############################################################################

    @staticmethod
    def convergence(

        upper,

        lower,

    ):

        start = min(

            upper.start_index,

            lower.start_index,

        )

        end = max(

            upper.end_index,

            lower.end_index,

        )

        width_start = TrendlineAnalyzer.channel_width(

            upper,

            lower,

            start,

        )

        width_end = TrendlineAnalyzer.channel_width(

            upper,

            lower,

            end,

        )

        if width_start <= 0:

            return 0, width_start, width_end

        contraction = (

            width_start

            -

            width_end

        ) / width_start

        return (

            contraction,

            width_start,

            width_end,

        )
##############################################################################

    @staticmethod
    def apex(

        upper,

        lower,

    ):

        denominator = (

            upper.slope

            -

            lower.slope

        )

        if abs(denominator) < 1e-8:

            return np.inf

        return (

            lower.intercept

            -

            upper.intercept

        ) / denominator
##############################################################################

    @staticmethod
    def symmetry(

        upper,

        lower,

    ):

        total = (

            abs(upper.slope)

            +

            abs(lower.slope)

        )

        if total == 0:

            return 1.0

        return (

            1

            -

            abs(

                abs(upper.slope)

                -

                abs(lower.slope)

            )

            / total

        )
##############################################################################

    def analyze(

        self,

        highs,

        lows,

    ):

        upper = self.regression(highs)

        lower = self.regression(lows)

        if upper is None or lower is None:

            return None

        contraction, start, end = self.convergence(

            upper,

            lower,

        )

        apex = self.apex(

            upper,

            lower,

        )

        symmetry = self.symmetry(

            upper,

            lower,

        )

        return TrendResult(

            upper=upper,

            lower=lower,

            convergence=contraction,

            apex=apex,

            width_start=start,

            width_end=end,

            symmetry=symmetry,

        )
