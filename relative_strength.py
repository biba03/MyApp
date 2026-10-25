"""
relative_strength.py

Institutional Relative Strength Engine.

Computes:

- Relative Strength Line
- Relative Strength Rating (1-99)
- Relative Momentum
- Industry Relative Strength
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


##############################################################################

@dataclass(slots=True)
class RSResult:

    rs_line: float

    rs_rating: int

    rs_percentile: float

    momentum: float

    sector_rank: float

    industry_rank: float
##############################################################################

class RelativeStrengthEngine:

    def rs_line(

        self,

        stock: pd.DataFrame,

        benchmark: pd.DataFrame,

    ):

        """
        Relative Strength Line

        Stock / Index
        """

        rs = (

            stock["Close"]

            /

            benchmark["Close"]

        )

        return rs
##############################################################################

    def smooth(

        self,

        rs,

        period=20,

    ):

        return (

            rs

            .ewm(

                span=period,

                adjust=False,

            )

            .mean()

        )
##############################################################################

    def momentum(

        self,

        rs,

        period=20,

    ):

        return (

            rs

            -

            rs.shift(period)

        ) / rs.shift(period)
##############################################################################

    def weighted_return(

        self,

        prices,

    ):

        r3 = prices.pct_change(63, fill_method=None).iloc[-1]

        r6 = prices.pct_change(126, fill_method=None).iloc[-1]

        r9 = prices.pct_change(189, fill_method=None).iloc[-1]

        r12 = prices.pct_change(252, fill_method=None).iloc[-1]

        return (

            r3*0.40

            +

            r6*0.30

            +

            r9*0.20

            +

            r12*0.10

        )
##############################################################################

    @staticmethod

    def percentile(

        value,

        universe,

    ):

        rank = (

            np.sum(

                universe <= value

            )

            /

            len(universe)

        )

        return rank
##############################################################################

    def rating(

        self,

        value,

        universe,

    ):

        percentile = self.percentile(

            value,

            universe,

        )

        rating = max(

            1,

            min(

                99,

                round(percentile*99)

            )

        )

        return rating
##############################################################################

    def evaluate(

        self,

        stock,

        benchmark,

        universe_returns,

        sector_rank=0,

        industry_rank=0,

    ):

        rs = self.rs_line(

            stock,

            benchmark,

        )

        smoothed = self.smooth(rs)

        momentum = self.momentum(smoothed)

        weighted = self.weighted_return(

            stock.Close

        )

        percentile = self.percentile(

            weighted,

            universe_returns,

        )

        rating = self.rating(

            weighted,

            universe_returns,

        )

        return RSResult(

            rs_line=float(smoothed.iloc[-1]),

            rs_rating=rating,

            rs_percentile=percentile,

            momentum=float(momentum.iloc[-1]),

            sector_rank=sector_rank,

            industry_rank=industry_rank,

        )
##############################################################################

    def group_rank(

        self,

        weighted_returns: dict,

        sector_map,

        key: str = "sector",

    ) -> dict:
        """
        Groups every ticker's own weighted_return (from
        weighted_return() above) by sector or industry (via a
        SectorIndustryMap), ranks each GROUP's average return against
        every other group in the same universe using the same 1-99
        percentile method used for individual stock RS ratings, and
        returns {ticker: group_rank}.

        This is what makes sector_rank/industry_rank real numbers
        instead of the always-0 stub they used to be - it just needs
        to be called once per scan (not once per ticker), since group
        averages only mean something computed across the whole
        scanned universe at once.
        """

        ticker_group: dict[str, str] = {}

        groups: dict[str, list[float]] = {}

        for ticker, wr in weighted_returns.items():

            if wr is None or (isinstance(wr, float) and np.isnan(wr)):

                continue

            sector, industry = sector_map.get(ticker)

            group_name = sector if key == "sector" else industry

            ticker_group[ticker] = group_name

            groups.setdefault(group_name, []).append(wr)

        group_avg = {
            name: float(np.mean(values))
            for name, values in groups.items()
            if values
        }

        if not group_avg:

            return {ticker: None for ticker in weighted_returns}

        group_values = np.array(list(group_avg.values()))

        group_ratings = {
            name: self.rating(avg, group_values)
            for name, avg in group_avg.items()
        }

        return {
            ticker: group_ratings.get(ticker_group.get(ticker), None)
            for ticker in weighted_returns
        }
