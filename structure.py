"""
Market Structure Engine

This module extracts swing structure from OHLC data.

Every pattern uses this instead of
recomputing pivots.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


##############################################################################
# Pivot
##############################################################################

@dataclass(slots=True)
class Pivot:

    index: int

    price: float

    kind: str


##############################################################################
# Structure
##############################################################################

@dataclass(slots=True)
class StructureResult:

    pivot_highs: list[Pivot]

    pivot_lows: list[Pivot]

    higher_highs: int

    lower_highs: int

    higher_lows: int

    lower_lows: int

    contraction: float

    convergence: float

    clean_score: float
class StructureAnalyzer:

    def __init__(

        self,

        lookback=120,

    ):

        self.lookback = lookback

    ###############################################################

    def pivots(

        self,

        df: pd.DataFrame,

    ):
        """
        Vectorized: uses numpy boolean masking to find pivot
        positions directly instead of iterating every row with
        .iterrows() (which builds a full pandas Series per row - by
        far the slowest way to do this). Produces identical output to
        that row-by-row approach, just much faster.
        """

        subset = df.iloc[-self.lookback:]

        high_mask = subset["PivotHigh"].to_numpy()

        low_mask = subset["PivotLow"].to_numpy()

        high_prices = subset["High"].to_numpy()

        low_prices = subset["Low"].to_numpy()

        highs = [
            Pivot(index=int(i), price=float(high_prices[i]), kind="H")
            for i in np.nonzero(high_mask)[0]
        ]

        lows = [
            Pivot(index=int(i), price=float(low_prices[i]), kind="L")
            for i in np.nonzero(low_mask)[0]
        ]

        return highs, lows
    ###############################################################

    def trend_statistics(

        self,

        pivots,

        higher=True,

    ):

        count = 0

        for a, b in zip(

            pivots,

            pivots[1:],

        ):

            if higher:

                if b.price > a.price:

                    count += 1

            else:

                if b.price < a.price:

                    count += 1

        return count
    ###############################################################

    def contraction(

        self,

        highs,

        lows,

    ):

        if len(highs) < 2:

            return 0

        if len(lows) < 2:

            return 0

        upper = abs(

            highs[-1].price

            -

            highs[0].price

        )

        lower = abs(

            lows[-1].price

            -

            lows[0].price

        )

        width = (

            highs[0].price

            -

            lows[0].price

        )

        if width <= 0:

            return 0

        return (

            upper

            +

            lower

        ) / width
    ###############################################################

    def analyze(

        self,

        df: pd.DataFrame,

    ) -> StructureResult:

        highs, lows = self.pivots(df)

        contraction = self.contraction(

            highs,

            lows,

        )

        total_pivots = len(highs) + len(lows)

        clean_score = max(

            0.0,

            1 - total_pivots / (2 * self.lookback),

        )

        result = StructureResult(

            pivot_highs=highs,

            pivot_lows=lows,

            higher_highs=self.trend_statistics(highs, higher=True),

            lower_highs=self.trend_statistics(highs, higher=False),

            higher_lows=self.trend_statistics(lows, higher=True),

            lower_lows=self.trend_statistics(lows, higher=False),

            contraction=contraction,

            convergence=contraction,

            clean_score=clean_score,

        )

        return result
    ###############################################################

    def score(

        self,

        result,

    ):

        score = 0

        score += min(

            result.higher_lows * 10,

            30,

        )

        score += min(

            result.lower_highs * 10,

            30,

        )

        score += (

            result.clean_score

            * 20

        )

        score += (

            result.contraction

            * 20

        )

        return min(

            score,

            100,

        )
