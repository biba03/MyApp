"""
ranking.py

Institutional ranking engine.

Every detected setup receives a weighted score built from: pattern
quality, pattern confidence, risk/reward, relative strength,
liquidity, and market regime. The last three used to be computed and
attached to each result purely for display - they're now genuine
inputs to the score itself, which is what actually determines sort
order.
"""

from __future__ import annotations

from dataclasses import dataclass

import config
from patterns.base import PatternResult
from quality import QualityResult


##############################################################################

@dataclass(slots=True)
class RankedStock:

    ticker: str

    pattern: str

    score: float

    quality: float

    confidence: float

    entry: float

    stop: float

    target: float

    rr: float

    rs_rating: float | None

    trend_template: str | None

    stage: str | None

    accum_days: int | None

    dist_days: int | None

    liquidity_score: float | None

    regime_score: float | None

    sector_rank: float | None

    industry_rank: float | None

    metadata: dict

    # Distance of price above the 50 SMA in ATRs - reported for context
    # (an overextension read-out), not used to gate or score.
    atr_extension_50sma: float | None = None


##############################################################################

class RankingEngine:

    NEUTRAL_FALLBACK = 50.0  # used when rs/liquidity/regime aren't supplied

    def __init__(
        self,
        weights: dict | None = None,
    ):

        weights = weights or config.RANKING_WEIGHTS

        total = sum(weights.values())

        if abs(total - 1.0) > 1e-6:

            raise ValueError(
                f"RANKING_WEIGHTS must sum to 1.0, got {total:.4f}: {weights}"
            )

        self.quality_weight = weights["quality"]

        self.confidence_weight = weights["confidence"]

        self.rr_weight = weights["rr"]

        self.rs_weight = weights["rs"]

        # Sector strength: read defensively so callers passing the older
        # six-key weight dict (no "sector") still work - it just contributes
        # nothing in that case.
        self.sector_weight = weights.get("sector", 0.0)

        self.liquidity_weight = weights["liquidity"]

        self.regime_weight = weights["regime"]

    ##########################################################################

    @staticmethod
    def rr(
        entry,
        stop,
        target,
    ):

        risk = entry - stop

        reward = target - entry

        if risk <= 0:

            return 0

        return reward / risk

    ##########################################################################

    def score(
        self,
        pattern: PatternResult,
        quality: QualityResult,
        rs_rating: float | None = None,
        liquidity_score: float | None = None,
        regime_score: float | None = None,
        sector_rank: float | None = None,
    ):

        rr = self.rr(
            pattern.entry,
            pattern.stop,
            pattern.target,
        )

        rr_component = min(rr, 4) / 4 * 100

        rs_component = rs_rating if rs_rating is not None else self.NEUTRAL_FALLBACK

        sector_component = sector_rank if sector_rank is not None else self.NEUTRAL_FALLBACK

        liquidity_component = (
            liquidity_score if liquidity_score is not None else self.NEUTRAL_FALLBACK
        )

        regime_component = (
            regime_score if regime_score is not None else self.NEUTRAL_FALLBACK
        )

        score = (

            quality.overall * self.quality_weight

            + pattern.confidence * 100 * self.confidence_weight

            + rr_component * self.rr_weight

            + rs_component * self.rs_weight

            + sector_component * self.sector_weight

            + liquidity_component * self.liquidity_weight

            + regime_component * self.regime_weight

        )

        return score

    ##########################################################################

    def rank(
        self,
        ticker,
        pattern,
        quality,
        rs_rating=None,
        trend_template=None,
        stage=None,
        accum_days=None,
        dist_days=None,
        liquidity_score=None,
        regime_score=None,
        sector_rank=None,
        industry_rank=None,
        atr_extension_50sma=None,
    ):

        rr = self.rr(
            pattern.entry,
            pattern.stop,
            pattern.target,
        )

        return RankedStock(

            ticker=ticker,

            pattern=pattern.name,

            score=self.score(
                pattern,
                quality,
                rs_rating,
                liquidity_score,
                regime_score,
                sector_rank,
            ),

            quality=quality.overall,

            confidence=pattern.confidence,

            entry=pattern.entry,

            stop=pattern.stop,

            target=pattern.target,

            rr=rr,

            rs_rating=rs_rating,

            trend_template=trend_template,

            stage=stage,

            accum_days=accum_days,

            dist_days=dist_days,

            liquidity_score=liquidity_score,

            regime_score=regime_score,

            sector_rank=sector_rank,

            industry_rank=industry_rank,

            metadata=pattern.metadata,

            atr_extension_50sma=atr_extension_50sma,

        )


##############################################################################

def sort_results(results):

    return sorted(
        results,
        key=lambda x: x.score,
        reverse=True,
    )
