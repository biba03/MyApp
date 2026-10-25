"""
indicators.py
=============

Technical Indicator Engine for Momentum Pro Scanner.

This module computes all indicators only once so every pattern
shares the same dataframe.

Author: ChatGPT
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
import warnings

import numpy as np
import pandas as pd

import config


###############################################################################
# Dataclass
###############################################################################

@dataclass(slots=True)
class IndicatorResult:

    ticker: str

    data: pd.DataFrame


###############################################################################
# Validation
###############################################################################

REQUIRED_COLUMNS = [
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
]


def validate_dataframe(df: pd.DataFrame) -> None:
    """
    Validate OHLCV dataframe.

    Raises
    ------
    ValueError
    """

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]

    if missing:

        raise ValueError(
            f"Missing columns: {missing}"
        )

    if len(df) < 250:

        raise ValueError(
            "Need at least 250 trading days."
        )

    if df.isna().all().any():

        raise ValueError(
            "One or more columns are empty."
        )

    if (df["High"] < df["Low"]).any():

        raise ValueError(
            "Invalid OHLC bars."
        )


###############################################################################
# EMA
###############################################################################

def add_ema(
    df: pd.DataFrame,
    period: int
) -> None:

    df[f"EMA{period}"] = (
        df["Close"]
        .ewm(
            span=period,
            adjust=False
        )
        .mean()
    )


def add_all_ema(
    df: pd.DataFrame
) -> None:

    for period in config.EMA_PERIODS:

        add_ema(df, period)
###############################################################################
# SMA
###############################################################################

def add_sma(
    df: pd.DataFrame,
    period: int
) -> None:
    """
    Add Simple Moving Average.
    """
    df[f"SMA{period}"] = (
        df["Close"]
        .rolling(period)
        .mean()
    )


def add_all_sma(df: pd.DataFrame) -> None:
    """
    Common SMAs.
    """
    for period in (10, 20, 50, 100, 150, 200):
        add_sma(df, period)


###############################################################################
# TRUE RANGE
###############################################################################

def add_true_range(df: pd.DataFrame) -> None:
    """
    Wilder True Range.
    """

    prev_close = df["Close"].shift(1)

    tr1 = df["High"] - df["Low"]

    tr2 = (df["High"] - prev_close).abs()

    tr3 = (df["Low"] - prev_close).abs()

    df["TR"] = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)


###############################################################################
# ATR
###############################################################################

def add_atr(
    df: pd.DataFrame,
    period: int = config.ATR_PERIOD
) -> None:
    """
    Average True Range using Wilder smoothing.
    """

    if "TR" not in df.columns:
        add_true_range(df)

    df[f"ATR{period}"] = (
        df["TR"]
        .ewm(
            alpha=1 / period,
            adjust=False
        )
        .mean()
    )


###############################################################################
# NORMALIZED ATR
###############################################################################

def add_natr(
    df: pd.DataFrame,
    period: int = config.ATR_PERIOD
) -> None:
    """
    ATR as percentage of Close.
    """

    atr_col = f"ATR{period}"

    if atr_col not in df.columns:
        add_atr(df, period)

    df["NATR"] = (
        df[atr_col]
        / df["Close"]
        * 100
    )


###############################################################################
# DAILY RANGE
###############################################################################

def add_daily_range(df: pd.DataFrame) -> None:
    """
    Daily range in percent.
    """

    df["DailyRange"] = (
        (df["High"] - df["Low"])
        / df["Close"]
        * 100
    )


###############################################################################
# ADR
###############################################################################

def add_adr(
    df: pd.DataFrame,
    period: int = 20
) -> None:
    """
    Average Daily Range (%).

    Used heavily by momentum traders.
    """

    if "DailyRange" not in df.columns:
        add_daily_range(df)

    df[f"ADR{period}"] = (
        df["DailyRange"]
        .rolling(period)
        .mean()
    )


###############################################################################
# ATR COMPRESSION
###############################################################################

def add_atr_compression(
    df: pd.DataFrame,
    period: int = config.ATR_PERIOD,
    lookback: int = 10
) -> None:
    """
    Measures ATR contraction.

    Positive values indicate volatility is contracting.
    """

    atr_col = f"ATR{period}"

    if atr_col not in df.columns:
        add_atr(df, period)

    df["ATRCompression"] = (
        1
        - df[atr_col]
        / df[atr_col].shift(lookback)
    )


###############################################################################
# RANGE COMPRESSION
###############################################################################

def add_range_compression(
    df: pd.DataFrame,
    lookback: int = 10
) -> None:
    """
    Measures contraction in candle size.
    """

    if "DailyRange" not in df.columns:
        add_daily_range(df)

    rolling = (
        df["DailyRange"]
        .rolling(lookback)
        .mean()
    )

    df["RangeCompression"] = (
        1
        - rolling
        / rolling.shift(lookback)
    )
###############################################################################
# VOLUME INDICATORS
###############################################################################

def add_average_volume(
    df: pd.DataFrame,
    period: int = 20
) -> None:
    """
    Average trading volume.
    """

    df[f"AvgVolume{period}"] = (
        df["Volume"]
        .rolling(period)
        .mean()
    )


###############################################################################
# RELATIVE VOLUME (RVOL)
###############################################################################

def add_rvol(
    df: pd.DataFrame,
    period: int = config.RVOL_PERIOD
) -> None:
    """
    Relative Volume.

    RVOL = Today's Volume / Average Volume
    """

    avg_col = f"AvgVolume{period}"

    if avg_col not in df.columns:
        add_average_volume(df, period)

    df["RVOL"] = (
        df["Volume"]
        / df[avg_col]
    )


###############################################################################
# DOLLAR VOLUME
###############################################################################

def add_dollar_volume(df: pd.DataFrame) -> None:
    """
    Dollar Volume.

    Used to remove illiquid stocks.
    """

    df["DollarVolume"] = (
        df["Close"]
        * df["Volume"]
    )


###############################################################################
# AVERAGE DOLLAR VOLUME
###############################################################################

def add_average_dollar_volume(
    df: pd.DataFrame,
    period: int = 20
) -> None:
    """
    Average Dollar Volume.
    """

    if "DollarVolume" not in df.columns:
        add_dollar_volume(df)

    df[f"AvgDollarVolume{period}"] = (
        df["DollarVolume"]
        .rolling(period)
        .mean()
    )


###############################################################################
# VOLUME SPIKE
###############################################################################

def add_volume_spike(
    df: pd.DataFrame,
    period: int = 20
) -> None:
    """
    Volume Spike Ratio.
    """

    avg_col = f"AvgVolume{period}"

    if avg_col not in df.columns:
        add_average_volume(df, period)

    df["VolumeSpike"] = (
        df["Volume"]
        / df[avg_col]
    )


###############################################################################
# VOLUME DRY-UP
###############################################################################

def add_volume_dryup(
    df: pd.DataFrame,
    period: int = 20
) -> None:
    """
    Volume Dry-Up.

    Values below 1 indicate
    lower-than-average volume.
    """

    avg_col = f"AvgVolume{period}"

    if avg_col not in df.columns:
        add_average_volume(df, period)

    df["VolumeDryUp"] = (
        df["Volume"]
        / df[avg_col]
    )

    df["IsDryUp"] = (
        df["VolumeDryUp"]
        < config.VOLUME_DRYUP_THRESHOLD
    )


###############################################################################
# TURNOVER
###############################################################################

def add_turnover(
    df: pd.DataFrame,
    shares_outstanding: float | None = None
) -> None:
    """
    Daily Turnover.

    Requires shares outstanding.
    """

    if shares_outstanding is None:

        df["Turnover"] = np.nan

        return

    df["Turnover"] = (
        df["Volume"]
        / shares_outstanding
    )


###############################################################################
# UP/DOWN VOLUME
###############################################################################

def add_up_down_volume(df: pd.DataFrame) -> None:
    """
    Split volume into Up and Down volume.
    """

    up = df["Close"] >= df["Close"].shift()

    df["UpVolume"] = np.where(
        up,
        df["Volume"],
        0
    )

    df["DownVolume"] = np.where(
        up,
        0,
        df["Volume"]
    )


###############################################################################
# UP/DOWN VOLUME RATIO
###############################################################################

def add_up_down_ratio(
    df: pd.DataFrame,
    period: int = 20
) -> None:
    """
    Buying pressure vs selling pressure.
    """

    if "UpVolume" not in df.columns:
        add_up_down_volume(df)

    up = (
        df["UpVolume"]
        .rolling(period)
        .sum()
    )

    down = (
        df["DownVolume"]
        .rolling(period)
        .sum()
    )

    df["UpDownVolumeRatio"] = (
        up
        / down.replace(0, np.nan)
    )


###############################################################################
# ACCUMULATION SCORE
###############################################################################

def add_accumulation_score(
    df: pd.DataFrame,
    period: int = 20
) -> None:
    """
    Simple accumulation score.

    Positive = institutions likely accumulating.
    """

    if "UpDownVolumeRatio" not in df.columns:
        add_up_down_ratio(df, period)

    score = np.zeros(len(df))

    score += (df["RVOL"] > 1.5).astype(int)

    score += (df["UpDownVolumeRatio"] > 1).astype(int)

    score += (
        df["Close"] > df["Open"]
    ).astype(int)

    score += (
        df["Close"] > df["EMA20"]
    ).astype(int)

    df["AccumulationScore"] = score


###############################################################################
# VOLUME TREND
###############################################################################

def add_volume_trend(
    df: pd.DataFrame,
    period: int = 20
) -> None:
    """
    Rising average volume.

    Positive values indicate increasing participation.
    """

    avg_col = f"AvgVolume{period}"

    if avg_col not in df.columns:
        add_average_volume(df, period)

    df["VolumeTrend"] = (
        df[avg_col]
        .pct_change(period)
    )
###############################################################################
# GAP ANALYSIS
###############################################################################

def add_gap(df: pd.DataFrame) -> None:
    """
    Gap % from previous close.
    """

    prev_close = df["Close"].shift(1)

    df["GapPct"] = (
        (df["Open"] - prev_close)
        / prev_close
        * 100
    )


def add_gap_type(df: pd.DataFrame) -> None:
    """
    Gap direction.
    """

    df["GapUp"] = df["GapPct"] > 0

    df["GapDown"] = df["GapPct"] < 0

    df["ValidGap"] = (
        (df["GapPct"] >= config.MIN_GAP * 100)
        &
        (df["GapPct"] <= config.MAX_GAP * 100)
    )


###############################################################################
# CANDLE BODY
###############################################################################

def add_body(df: pd.DataFrame) -> None:

    df["Body"] = (
        df["Close"] - df["Open"]
    ).abs()

    df["BodyPct"] = (
        df["Body"]
        /
        (df["High"] - df["Low"]).replace(0, np.nan)
    )


###############################################################################
# UPPER / LOWER SHADOW
###############################################################################

def add_wicks(df: pd.DataFrame) -> None:

    upper = np.maximum(
        df["Open"],
        df["Close"]
    )

    lower = np.minimum(
        df["Open"],
        df["Close"]
    )

    df["UpperShadow"] = (
        df["High"] - upper
    )

    df["LowerShadow"] = (
        lower - df["Low"]
    )

    rng = (
        df["High"] - df["Low"]
    ).replace(0, np.nan)

    df["UpperShadowPct"] = (
        df["UpperShadow"] / rng
    )

    df["LowerShadowPct"] = (
        df["LowerShadow"] / rng
    )


###############################################################################
# CLOSE LOCATION VALUE
###############################################################################

def add_clv(df: pd.DataFrame) -> None:
    """
    Close Location Value

    +1 = close at high

    -1 = close at low
    """

    rng = (
        df["High"] - df["Low"]
    ).replace(0, np.nan)

    df["CLV"] = (
        (
            (df["Close"] - df["Low"])
            -
            (df["High"] - df["Close"])
        )
        /
        rng
    )


###############################################################################
# CANDLE CLASSIFICATION
###############################################################################

def add_candle_flags(df: pd.DataFrame) -> None:

    if "BodyPct" not in df.columns:
        add_body(df)

    if "UpperShadowPct" not in df.columns:
        add_wicks(df)

    df["Bullish"] = (
        df["Close"] > df["Open"]
    )

    df["Bearish"] = (
        df["Close"] < df["Open"]
    )

    df["Doji"] = (
        df["BodyPct"] < 0.10
    )

    df["StrongBull"] = (
        (df["Bullish"])
        &
        (df["BodyPct"] > 0.65)
    )

    df["StrongBear"] = (
        (df["Bearish"])
        &
        (df["BodyPct"] > 0.65)
    )


###############################################################################
# MARUBOZU
###############################################################################

def add_marubozu(df: pd.DataFrame) -> None:

    if "UpperShadowPct" not in df.columns:
        add_wicks(df)

    if "BodyPct" not in df.columns:
        add_body(df)

    df["BullMarubozu"] = (

        df["Bullish"]

        &

        (df["BodyPct"] > 0.90)

        &

        (df["UpperShadowPct"] < 0.05)

        &

        (df["LowerShadowPct"] < 0.05)

    )

    df["BearMarubozu"] = (

        df["Bearish"]

        &

        (df["BodyPct"] > 0.90)

        &

        (df["UpperShadowPct"] < 0.05)

        &

        (df["LowerShadowPct"] < 0.05)

    )


###############################################################################
# INSIDE / OUTSIDE BAR
###############################################################################

def add_inside_outside_bar(df: pd.DataFrame) -> None:

    prev_high = df["High"].shift()

    prev_low = df["Low"].shift()

    df["InsideBar"] = (

        (df["High"] <= prev_high)

        &

        (df["Low"] >= prev_low)

    )

    df["OutsideBar"] = (

        (df["High"] >= prev_high)

        &

        (df["Low"] <= prev_low)

    )


###############################################################################
# NR7
###############################################################################

def add_nr7(df: pd.DataFrame) -> None:
    """
    Narrowest range in last 7 bars.
    """

    rng = (
        df["High"] - df["Low"]
    )

    df["NR7"] = (

        rng

        ==

        rng.rolling(7).min()

    )


###############################################################################
# TIGHT CLOSE
###############################################################################

def add_tight_close(df: pd.DataFrame) -> None:
    """
    Close in top 20% of candle.
    """

    rng = (
        df["High"] - df["Low"]
    ).replace(0, np.nan)

    close_pos = (

        (df["Close"] - df["Low"])

        / rng

    )

    df["TightClose"] = (

        close_pos > 0.80

    )


###############################################################################
# BREAKOUT CANDLE SCORE
###############################################################################

def add_breakout_quality(df: pd.DataFrame) -> None:
    """
    0-100 breakout candle quality.
    """

    if "BodyPct" not in df.columns:
        add_body(df)

    if "CLV" not in df.columns:
        add_clv(df)

    score = np.zeros(len(df))

    score += (df["BodyPct"] > 0.60) * 25

    score += (df["BodyPct"] > 0.75) * 20

    score += (df["CLV"] > 0.70) * 25

    score += (df["GapPct"] > 2) * 10

    score += (df["GapPct"] > 4) * 10

    score += (df["BullMarubozu"]) * 10

    df["BreakoutScore"] = score.clip(0, 100)
###############################################################################
# ROLLING HIGHS / LOWS
###############################################################################

def add_rolling_high_low(
    df: pd.DataFrame,
    period: int = 20
) -> None:
    """
    Rolling highest high and lowest low.
    """

    df[f"High{period}"] = (
        df["High"]
        .rolling(period)
        .max()
    )

    df[f"Low{period}"] = (
        df["Low"]
        .rolling(period)
        .min()
    )


###############################################################################
# 52-WEEK HIGH / LOW
###############################################################################

def add_52_week_levels(df: pd.DataFrame) -> None:
    """
    252 trading days ≈ 52 weeks.
    """

    df["High52W"] = (
        df["High"]
        .rolling(252)
        .max()
    )

    df["Low52W"] = (
        df["Low"]
        .rolling(252)
        .min()
    )


###############################################################################
# DISTANCE TO 52W HIGH
###############################################################################

def add_distance_to_high(df: pd.DataFrame) -> None:

    if "High52W" not in df.columns:
        add_52_week_levels(df)

    df["PctFrom52High"] = (

        (df["Close"] - df["High52W"])

        /

        df["High52W"]

        * 100

    )


###############################################################################
# DISTANCE TO 52W LOW
###############################################################################

def add_distance_to_low(df: pd.DataFrame) -> None:

    if "Low52W" not in df.columns:
        add_52_week_levels(df)

    df["PctAbove52Low"] = (

        (df["Close"] - df["Low52W"])

        /

        df["Low52W"]

        * 100

    )


###############################################################################
# HIGHEST CLOSE
###############################################################################

def add_highest_close(
    df: pd.DataFrame,
    period: int = 20
) -> None:

    df[f"HighestClose{period}"] = (

        df["Close"]

        .rolling(period)

        .max()

    )


###############################################################################
# LOWEST CLOSE
###############################################################################

def add_lowest_close(
    df: pd.DataFrame,
    period: int = 20
) -> None:

    df[f"LowestClose{period}"] = (

        df["Close"]

        .rolling(period)

        .min()

    )


###############################################################################
# PRICE POSITION
###############################################################################

def add_price_position(
    df: pd.DataFrame,
    period: int = 20
) -> None:
    """
    Position inside recent range.

    1.0 = top

    0.0 = bottom
    """

    high = (

        df["High"]

        .rolling(period)

        .max()

    )

    low = (

        df["Low"]

        .rolling(period)

        .min()

    )

    df["PricePosition"] = (

        (df["Close"] - low)

        /

        (high - low).replace(0, np.nan)

    )


###############################################################################
# RANGE WIDTH
###############################################################################

def add_range_width(
    df: pd.DataFrame,
    period: int = 20
) -> None:

    high = (

        df["High"]

        .rolling(period)

        .max()

    )

    low = (

        df["Low"]

        .rolling(period)

        .min()

    )

    df["RangeWidth"] = (

        (high - low)

        /

        high

        * 100

    )


###############################################################################
# RANGE COMPRESSION SCORE
###############################################################################

def add_range_score(
    df: pd.DataFrame,
    lookback: int = 20
) -> None:
    """
    Higher score = tighter base.
    """

    if "RangeWidth" not in df.columns:
        add_range_width(df, lookback)

    width = df["RangeWidth"]

    rolling_max = width.rolling(lookback).max()

    df["RangeScore"] = (

        100

        *

        (

            1

            -

            width

            /

            rolling_max

        )

    ).clip(0, 100)


###############################################################################
# HIGHER HIGH / LOWER HIGH
###############################################################################

def add_price_structure(df: pd.DataFrame) -> None:
    """
    Simple daily price structure.
    """

    prev_high = df["High"].shift()

    prev_low = df["Low"].shift()

    df["HigherHigh"] = (

        df["High"] > prev_high

    )

    df["LowerHigh"] = (

        df["High"] < prev_high

    )

    df["HigherLow"] = (

        df["Low"] > prev_low

    )

    df["LowerLow"] = (

        df["Low"] < prev_low

    )


###############################################################################
# EXPANSION DAY
###############################################################################

def add_expansion_day(df: pd.DataFrame) -> None:
    """
    Wide-range expansion day.
    """

    if "DailyRange" not in df.columns:
        add_daily_range(df)

    avg = (

        df["DailyRange"]

        .rolling(20)

        .mean()

    )

    df["ExpansionDay"] = (

        df["DailyRange"]

        >

        avg * 1.5

    )


###############################################################################
# COMPRESSION DAY
###############################################################################

def add_compression_day(df: pd.DataFrame) -> None:
    """
    Very tight trading day.
    """

    if "DailyRange" not in df.columns:
        add_daily_range(df)

    avg = (

        df["DailyRange"]

        .rolling(20)

        .mean()

    )

    df["CompressionDay"] = (

        df["DailyRange"]

        <

        avg * 0.6

    )
###############################################################################
# PIVOT DETECTION
###############################################################################

def add_pivot_highs(
    df: pd.DataFrame,
    left: int = config.PIVOT_LEFT,
    right: int = config.PIVOT_RIGHT,
) -> None:
    """
    Detect swing highs.

    A pivot high must be higher than the bars
    immediately to its left and right.
    """

    highs = df["High"].values

    pivot = np.zeros(len(df), dtype=bool)

    for i in range(left, len(df) - right):

        window = highs[i-left:i+right+1]

        if highs[i] == np.max(window):

            if np.sum(window == highs[i]) == 1:

                pivot[i] = True

    df["PivotHigh"] = pivot


###############################################################################
# PIVOT LOW
###############################################################################

def add_pivot_lows(
    df: pd.DataFrame,
    left: int = config.PIVOT_LEFT,
    right: int = config.PIVOT_RIGHT,
) -> None:
    """
    Detect swing lows.
    """

    lows = df["Low"].values

    pivot = np.zeros(len(df), dtype=bool)

    for i in range(left, len(df)-right):

        window = lows[i-left:i+right+1]

        if lows[i] == np.min(window):

            if np.sum(window == lows[i]) == 1:

                pivot[i] = True

    df["PivotLow"] = pivot


###############################################################################
# PIVOT PRICE
###############################################################################

def add_pivot_prices(df: pd.DataFrame) -> None:
    """
    Store pivot prices.

    Easier for plotting.
    """

    if "PivotHigh" not in df.columns:
        add_pivot_highs(df)

    if "PivotLow" not in df.columns:
        add_pivot_lows(df)

    df["PivotHighPrice"] = np.where(
        df["PivotHigh"],
        df["High"],
        np.nan,
    )

    df["PivotLowPrice"] = np.where(
        df["PivotLow"],
        df["Low"],
        np.nan,
    )


###############################################################################
# PIVOT INDEX
###############################################################################

def add_pivot_index(df: pd.DataFrame) -> None:
    """
    Integer IDs for pivots.

    Vectorized via cumsum+masking instead of a Python loop that
    re-fetched df["PivotHigh"]/df["PivotLow"] via __getitem__ on every
    row. Verified identical output to the original loop across 32
    test cases (random patterns plus no-pivot/all-pivot edge cases).
    Skipped under lite=True (see LITE_SKIP) but still runs during live
    scanning, which always uses the full (non-lite) path.
    """

    if "PivotHigh" not in df.columns:
        add_pivot_highs(df)

    if "PivotLow" not in df.columns:
        add_pivot_lows(df)

    ph = np.full(len(df), np.nan)
    pl = np.full(len(df), np.nan)

    high_mask = df["PivotHigh"].to_numpy()
    low_mask = df["PivotLow"].to_numpy()

    if high_mask.any():
        ph[high_mask] = np.cumsum(high_mask)[high_mask]

    if low_mask.any():
        pl[low_mask] = np.cumsum(low_mask)[low_mask]

    df["PivotHighID"] = ph

    df["PivotLowID"] = pl


###############################################################################
# LAST PIVOT HIGH
###############################################################################

def add_last_pivot_high(df: pd.DataFrame) -> None:
    """
    Forward-fill previous pivot high.
    """

    if "PivotHighPrice" not in df.columns:
        add_pivot_prices(df)

    df["LastPivotHigh"] = (
        df["PivotHighPrice"]
        .ffill()
    )


###############################################################################
# LAST PIVOT LOW
###############################################################################

def add_last_pivot_low(df: pd.DataFrame) -> None:

    if "PivotLowPrice" not in df.columns:
        add_pivot_prices(df)

    df["LastPivotLow"] = (
        df["PivotLowPrice"]
        .ffill()
    )


###############################################################################
# PIVOT DISTANCE
###############################################################################

def add_pivot_distance(df: pd.DataFrame) -> None:
    """
    Distance to most recent pivots.
    """

    if "LastPivotHigh" not in df.columns:
        add_last_pivot_high(df)

    if "LastPivotLow" not in df.columns:
        add_last_pivot_low(df)

    df["PctBelowPivotHigh"] = (

        (df["Close"] - df["LastPivotHigh"])

        /

        df["LastPivotHigh"]

        * 100

    )

    df["PctAbovePivotLow"] = (

        (df["Close"] - df["LastPivotLow"])

        /

        df["LastPivotLow"]

        * 100

    )


###############################################################################
# BREAKOUT ABOVE LAST PIVOT
###############################################################################

def add_pivot_breakout(df: pd.DataFrame) -> None:
    """
    Break above previous swing high.
    """

    if "LastPivotHigh" not in df.columns:
        add_last_pivot_high(df)

    previous = df["LastPivotHigh"].shift(1)

    df["PivotBreakout"] = (

        (df["Close"] > previous)

        &

        (df["Open"] < previous)

    )


###############################################################################
# BREAKDOWN BELOW LAST PIVOT
###############################################################################

def add_pivot_breakdown(df: pd.DataFrame) -> None:

    if "LastPivotLow" not in df.columns:
        add_last_pivot_low(df)

    previous = df["LastPivotLow"].shift(1)

    df["PivotBreakdown"] = (

        (df["Close"] < previous)

        &

        (df["Open"] > previous)

    )
###############################################################################
# ADAPTIVE PIVOT ENGINE
###############################################################################

def add_pivot_strength(df: pd.DataFrame) -> None:
    """
    Estimate market noise using ATR.

    Higher ATR -> larger pivot window.
    """

    if "NATR" not in df.columns:
        add_natr(df)

    strength = np.select(
        [
            df["NATR"] < 2,
            df["NATR"] < 4,
            df["NATR"] < 6,
        ],
        [
            2,
            3,
            4,
        ],
        default=5,
    )

    df["PivotStrength"] = strength.astype(int)


###############################################################################
# VECTORIZED PIVOT HIGH
###############################################################################

def add_vector_pivot_high(df: pd.DataFrame) -> None:
    """
    Fast pivot high detection.

    Uses centered rolling windows.
    """

    if "PivotStrength" not in df.columns:
        add_pivot_strength(df)

    pivot = np.zeros(len(df), dtype=bool)

    highs = df["High"]

    for window in (5, 7, 9, 11):

        local = (
            highs
            ==
            highs.rolling(
                window,
                center=True
            ).max()
        )

        mask = df["PivotStrength"] == ((window - 1) // 2)

        pivot |= (local & mask).fillna(False)

    df["PivotHigh"] = pivot


###############################################################################
# VECTORIZED PIVOT LOW
###############################################################################

def add_vector_pivot_low(df: pd.DataFrame) -> None:

    if "PivotStrength" not in df.columns:
        add_pivot_strength(df)

    pivot = np.zeros(len(df), dtype=bool)

    lows = df["Low"]

    for window in (5, 7, 9, 11):

        local = (
            lows
            ==
            lows.rolling(
                window,
                center=True
            ).min()
        )

        mask = df["PivotStrength"] == ((window - 1) // 2)

        pivot |= (local & mask).fillna(False)

    df["PivotLow"] = pivot


###############################################################################
# PIVOT COUNT
###############################################################################

def add_pivot_count(
    df: pd.DataFrame,
    period: int = 60
) -> None:
    """
    Number of pivots in recent history.
    """

    if "PivotHigh" not in df.columns:
        add_vector_pivot_high(df)

    if "PivotLow" not in df.columns:
        add_vector_pivot_low(df)

    df["PivotHighCount"] = (
        df["PivotHigh"]
        .rolling(period)
        .sum()
    )

    df["PivotLowCount"] = (
        df["PivotLow"]
        .rolling(period)
        .sum()
    )


###############################################################################
# RECENT PIVOT INDEX
###############################################################################

def add_recent_pivot_index(df: pd.DataFrame) -> None:
    """
    Distance (bars) from latest pivot.

    Vectorized via np.maximum.accumulate (a running "last index where
    True" carry-forward) instead of a Python loop that re-fetched
    df["PivotHigh"]/df["PivotLow"] via __getitem__ on every single
    row. Verified to produce identical output to the original
    row-by-row loop across 32 test cases (random patterns plus
    no-pivot/all-pivot edge cases) - this function alone accounted
    for ~24% of the entire compute_all() cost per bar in profiling.
    """

    if "PivotHigh" not in df.columns:
        add_vector_pivot_high(df)

    if "PivotLow" not in df.columns:
        add_vector_pivot_low(df)

    n = len(df)
    idx = np.arange(n)

    high_mask = df["PivotHigh"].to_numpy()
    low_mask = df["PivotLow"].to_numpy()

    high_positions = np.where(high_mask, idx, -1)
    low_positions = np.where(low_mask, idx, -1)

    last_high_idx = np.maximum.accumulate(high_positions)
    last_low_idx = np.maximum.accumulate(low_positions)

    last_high = np.where(last_high_idx >= 0, idx - last_high_idx, np.nan)
    last_low = np.where(last_low_idx >= 0, idx - last_low_idx, np.nan)

    df["BarsSincePivotHigh"] = last_high
    df["BarsSincePivotLow"] = last_low


###############################################################################
# PIVOT DENSITY
###############################################################################

def add_pivot_density(
    df: pd.DataFrame,
    period: int = 60
) -> None:
    """
    Too many pivots usually means
    choppy price action.
    """

    if "PivotHighCount" not in df.columns:
        add_pivot_count(df, period)

    total = (
        df["PivotHighCount"]
        +
        df["PivotLowCount"]
    )

    df["PivotDensity"] = total / period


###############################################################################
# CLEAN STRUCTURE
###############################################################################

def add_clean_structure(df: pd.DataFrame) -> None:
    """
    Strong trends produce fewer pivots.
    """

    if "PivotDensity" not in df.columns:
        add_pivot_density(df)

    df["CleanStructure"] = (

        df["PivotDensity"]

        <

        0.12

    )


###############################################################################
# WMA (Weighted Moving Average)
###############################################################################

def add_wma(
    df: pd.DataFrame,
    period: int,
) -> None:
    """
    Weighted Moving Average: more recent bars get linearly higher
    weight than older ones, unlike SMA (equal weight) or EMA
    (exponential decay).

    Implemented as a sum of `period` shifted, scalar-weighted Close
    series rather than a rolling .apply(), so every step stays a
    vectorized pandas operation.
    """

    weights = np.arange(1, period + 1)

    weighted_sum = sum(
        df["Close"].shift(period - 1 - i) * w
        for i, w in enumerate(weights)
    )

    df[f"WMA{period}"] = weighted_sum / weights.sum()


###############################################################################
# VWMA (Volume Weighted Moving Average)
###############################################################################

def add_vwma(
    df: pd.DataFrame,
    period: int,
) -> None:
    """
    Volume Weighted Moving Average: price average weighted by volume
    over the window, rather than by time.
    """

    price_volume = df["Close"] * df["Volume"]

    df[f"VWMA{period}"] = (
        price_volume.rolling(period).sum()
        / df["Volume"].rolling(period).sum()
    )


###############################################################################
# RSI
###############################################################################

def add_rsi(
    df: pd.DataFrame,
    period: int = 14,
) -> None:
    """
    Relative Strength Index, using Wilder's smoothing (an EMA with
    alpha = 1/period, the original definition) rather than a plain
    SMA of gains/losses.

    Handles the zero-losses edge case explicitly: a pure uptrend with
    no down days at all gives avg_loss == 0 exactly, and naively
    dividing by that (even after replacing 0 with NaN to avoid a
    divide-by-zero) makes the whole RSI value NaN instead of the
    correct answer of 100.
    """

    delta = df["Close"].diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()

    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    rsi = 100 - (100 / (1 + rs))

    # avg_loss == 0: RSI is 100 (all gains) unless avg_gain is also 0
    # (no movement at all), in which case 50 (neutral) is the
    # conventional value.
    rsi = np.where(
        avg_loss == 0,
        np.where(avg_gain == 0, 50.0, 100.0),
        rsi,
    )

    df[f"RSI{period}"] = rsi


###############################################################################
# STOCHASTIC OSCILLATOR
###############################################################################

def add_stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
) -> None:
    """
    Stochastic %K and %D (%K's own moving average).
    """

    low_min = df["Low"].rolling(k_period).min()

    high_max = df["High"].rolling(k_period).max()

    percent_k = (
        100 * (df["Close"] - low_min)
        / (high_max - low_min).replace(0, np.nan)
    )

    df["StochK"] = percent_k

    df["StochD"] = percent_k.rolling(d_period).mean()


###############################################################################
# MACD
###############################################################################

def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> None:
    """
    Moving Average Convergence/Divergence: fast EMA minus slow EMA,
    plus a signal line (EMA of that difference) and the histogram
    (their spread).
    """

    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()

    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()

    macd_line = ema_fast - ema_slow

    signal_line = macd_line.ewm(span=signal, adjust=False).mean()

    df["MACD"] = macd_line

    df["MACDSignal"] = signal_line

    df["MACDHist"] = macd_line - signal_line


###############################################################################
# PPO (Percentage Price Oscillator)
###############################################################################

def add_ppo(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> None:
    """
    Percentage Price Oscillator: like MACD, but expressed as a
    percentage of the slow EMA rather than a raw price difference -
    makes it comparable across stocks at very different price levels.
    """

    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()

    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()

    ppo_line = (ema_fast - ema_slow) / ema_slow.replace(0, np.nan) * 100

    signal_line = ppo_line.ewm(span=signal, adjust=False).mean()

    df["PPO"] = ppo_line

    df["PPOSignal"] = signal_line

    df["PPOHist"] = ppo_line - signal_line


###############################################################################
# ROC (Rate of Change)
###############################################################################

def add_roc(
    df: pd.DataFrame,
    period: int = 12,
) -> None:
    """
    Rate of Change: percentage price change over `period` bars.
    """

    df[f"ROC{period}"] = df["Close"].pct_change(period, fill_method=None) * 100


###############################################################################
# STANDARD DEVIATION
###############################################################################

def add_stddev(
    df: pd.DataFrame,
    period: int = 20,
) -> None:
    """
    Rolling standard deviation of Close - the volatility measure
    Bollinger Bands are built on.
    """

    df[f"StdDev{period}"] = df["Close"].rolling(period).std()


###############################################################################
# BOLLINGER BANDS
###############################################################################

def add_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    num_std: float = 2.0,
) -> None:
    """
    Bollinger Bands: an SMA midline with upper/lower bands at
    `num_std` standard deviations, plus %B (where Close sits within
    the bands, 0=lower band, 1=upper band) and bandwidth (how wide the
    bands are, as a % of the midline - a volatility-contraction tell
    in its own right, alongside ATRCompression/RangeCompression).
    """

    if f"StdDev{period}" not in df.columns:

        add_stddev(df, period)

    if f"SMA{period}" not in df.columns:

        add_sma(df, period)

    mid = df[f"SMA{period}"]

    std = df[f"StdDev{period}"]

    upper = mid + num_std * std

    lower = mid - num_std * std

    df["BollingerMid"] = mid

    df["BollingerUpper"] = upper

    df["BollingerLower"] = lower

    df["BollingerWidth"] = (upper - lower) / mid.replace(0, np.nan) * 100

    df["BollingerPercentB"] = (
        (df["Close"] - lower) / (upper - lower).replace(0, np.nan)
    )


###############################################################################
# KELTNER CHANNELS
###############################################################################

def add_keltner_channels(
    df: pd.DataFrame,
    period: int = 20,
    atr_multiplier: float = 2.0,
    atr_period: int = config.ATR_PERIOD,
) -> None:
    """
    Keltner Channels: an EMA midline with bands at
    `atr_multiplier` * ATR - a volatility-adaptive alternative to
    Bollinger Bands (which use standard deviation instead of ATR).
    """

    atr_col = f"ATR{atr_period}"

    if atr_col not in df.columns:

        add_atr(df, atr_period)

    if f"EMA{period}" not in df.columns:

        add_ema(df, period)

    mid = df[f"EMA{period}"]

    df["KeltnerMid"] = mid

    df["KeltnerUpper"] = mid + atr_multiplier * df[atr_col]

    df["KeltnerLower"] = mid - atr_multiplier * df[atr_col]


###############################################################################
# VOLUME EMA
###############################################################################

def add_volume_ema(
    df: pd.DataFrame,
    period: int = 20,
) -> None:
    """
    Exponential moving average of volume, alongside the existing
    simple AvgVolume{period}.
    """

    df[f"VolumeEMA{period}"] = df["Volume"].ewm(span=period, adjust=False).mean()


###############################################################################
# OBV (On-Balance Volume)
###############################################################################

def add_obv(df: pd.DataFrame) -> None:
    """
    On-Balance Volume: running total of volume, added on up days and
    subtracted on down days. A rising OBV alongside a rising price
    supports the move; a flat/falling OBV during a price rise is a
    classic divergence warning.
    """

    direction = np.sign(df["Close"].diff()).fillna(0)

    df["OBV"] = (direction * df["Volume"]).cumsum()


###############################################################################
# ACCUMULATION / DISTRIBUTION LINE
###############################################################################

def add_accumulation_distribution(df: pd.DataFrame) -> None:
    """
    The real Accumulation/Distribution line (Chaikin), not to be
    confused with AccumulationScore elsewhere in this file (a
    different, custom 0-4 composite score). Running total of
    Close-Location-Value-weighted volume.
    """

    if "CLV" not in df.columns:

        add_clv(df)

    df["ADLine"] = (df["CLV"] * df["Volume"]).cumsum()


###############################################################################
# CHAIKIN MONEY FLOW
###############################################################################

def add_chaikin_money_flow(
    df: pd.DataFrame,
    period: int = 20,
) -> None:
    """
    Chaikin Money Flow: CLV-weighted volume, summed over a rolling
    window and normalized by total volume in that window - a bounded
    (~-1 to 1) money-flow oscillator built on the same CLV concept as
    the Accumulation/Distribution line above.
    """

    if "CLV" not in df.columns:

        add_clv(df)

    money_flow_volume = df["CLV"] * df["Volume"]

    df[f"CMF{period}"] = (
        money_flow_volume.rolling(period).sum()
        / df["Volume"].rolling(period).sum()
    )


###############################################################################
# VWAP (rolling)
###############################################################################

def add_vwap(
    df: pd.DataFrame,
    period: int = 20,
) -> None:
    """
    Rolling Volume-Weighted Average Price over `period` bars.

    NOTE: true VWAP is normally computed intraday, resetting every
    session - this project only has daily bars, so this is a rolling
    N-day variant rather than a true session VWAP. Documented here
    rather than silently mislabeled.
    """

    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3

    price_volume = typical_price * df["Volume"]

    df[f"VWAP{period}"] = (
        price_volume.rolling(period).sum()
        / df["Volume"].rolling(period).sum()
    )


###############################################################################
# DISTANCE TO EMA (generic)
###############################################################################

def add_distance_to_ema(
    df: pd.DataFrame,
    period: int,
) -> None:
    """
    Close's distance from EMA{period}, as a percentage. Generalizes
    the existing distance-to-52w-high/low and distance-to-pivot
    columns to any EMA.
    """

    ema_col = f"EMA{period}"

    if ema_col not in df.columns:

        add_ema(df, period)

    df[f"DistanceToEMA{period}"] = (
        (df["Close"] - df[ema_col]) / df[ema_col].replace(0, np.nan) * 100
    )


###############################################################################
# COMPUTE ALL
###############################################################################
#
# NOTE: add_pivot_highs()/add_pivot_lows() (fixed left/right window) and
# add_vector_pivot_high()/add_vector_pivot_low() (adaptive, ATR-driven
# window via PivotStrength) both write to the same "PivotHigh"/"PivotLow"
# columns. They are NOT the same algorithm and will disagree on where
# pivots fall. compute_all() below intentionally calls only the adaptive
# vectorized version, since add_pivot_strength/add_pivot_density/
# add_clean_structure are all built on top of it. If the fixed-window
# version is what patterns are actually meant to use, call
# add_pivot_highs()/add_pivot_lows() explicitly afterward instead.

# Ordered indicator pipeline as a (name, callable) registry. The full path
# runs every step; the "lite" path (used only by the backtest for speed)
# skips LITE_SKIP. Correctness of the lite path is NOT assumed - it is
# guaranteed by tests/test_indicators_lite.py, which asserts every detector
# and the feature extractor produce byte-identical output under lite vs full.
PIPELINE_STEPS: list[tuple[str, object]] = [
    ("all_ema", add_all_ema),
    ("all_sma", add_all_sma),
    ("true_range", add_true_range),
    ("atr", add_atr),
    ("natr", add_natr),
    ("daily_range", add_daily_range),
    ("adr", add_adr),
    ("atr_compression", add_atr_compression),
    ("range_compression", add_range_compression),
    ("average_volume", add_average_volume),
    ("rvol", add_rvol),
    ("dollar_volume", add_dollar_volume),
    ("average_dollar_volume", add_average_dollar_volume),
    ("volume_spike", add_volume_spike),
    ("volume_dryup", add_volume_dryup),
    ("up_down_volume", add_up_down_volume),
    ("up_down_ratio", add_up_down_ratio),
    ("accumulation_score", add_accumulation_score),
    ("volume_trend", add_volume_trend),
    ("gap", add_gap),
    ("gap_type", add_gap_type),
    ("body", add_body),
    ("wicks", add_wicks),
    ("clv", add_clv),
    ("candle_flags", add_candle_flags),
    ("marubozu", add_marubozu),
    ("inside_outside_bar", add_inside_outside_bar),
    ("nr7", add_nr7),
    ("tight_close", add_tight_close),
    ("breakout_quality", add_breakout_quality),
    ("rolling_high_low", add_rolling_high_low),
    ("week_levels_52", add_52_week_levels),
    ("distance_to_high", add_distance_to_high),
    ("distance_to_low", add_distance_to_low),
    ("highest_close", add_highest_close),
    ("lowest_close", add_lowest_close),
    ("price_position", add_price_position),
    ("range_width", add_range_width),
    ("range_score", add_range_score),
    ("price_structure", add_price_structure),
    ("expansion_day", add_expansion_day),
    ("compression_day", add_compression_day),
    ("pivot_strength", add_pivot_strength),
    ("vector_pivot_high", add_vector_pivot_high),
    ("vector_pivot_low", add_vector_pivot_low),
    ("pivot_prices", add_pivot_prices),
    ("pivot_index", add_pivot_index),
    ("last_pivot_high", add_last_pivot_high),
    ("last_pivot_low", add_last_pivot_low),
    ("pivot_distance", add_pivot_distance),
    ("pivot_breakout", add_pivot_breakout),
    ("pivot_breakdown", add_pivot_breakdown),
    ("pivot_count", add_pivot_count),
    ("recent_pivot_index", add_recent_pivot_index),
    ("pivot_density", add_pivot_density),
    ("clean_structure", add_clean_structure),
    ("rsi", add_rsi),
    ("stochastic", add_stochastic),
    ("macd", add_macd),
    ("ppo", add_ppo),
    ("roc", add_roc),
    ("stddev", add_stddev),
    ("bollinger_bands", add_bollinger_bands),
    ("keltner_channels", add_keltner_channels),
    ("wma20", lambda df: add_wma(df, 20)),
    ("vwma20", lambda df: add_vwma(df, 20)),
    ("volume_ema", add_volume_ema),
    ("obv", add_obv),
    ("accumulation_distribution", add_accumulation_distribution),
    ("chaikin_money_flow", add_chaikin_money_flow),
    ("vwap", add_vwap),
    ("distance_to_ema20", lambda df: add_distance_to_ema(df, 20)),
    ("distance_to_ema50", lambda df: add_distance_to_ema(df, 50)),
]

# Steps the backtest's lite path may skip - empirically proven not to change
# any detector or feature output (see tests/test_indicators_lite.py). Empty
# means "no reduction yet".
# Derived by research/derive_lite_skip.py (greedy output-equivalence) and
# guarded by tests/test_indicators_lite.py: every step here is proven not to
# change any detector or feature output when skipped. Empty = no reduction
# (lite == full), the safe default until a set is derived and verified.
LITE_SKIP: frozenset[str] = frozenset({
    "accumulation_distribution", "adr", "all_sma", "atr", "average_dollar_volume",
    "average_volume", "body", "clv", "compression_day", "daily_range",
    "distance_to_ema20", "distance_to_ema50", "distance_to_low", "highest_close",
    "inside_outside_bar", "last_pivot_high", "last_pivot_low", "lowest_close",
    "natr", "nr7", "obv", "pivot_breakdown", "pivot_count", "pivot_density",
    "pivot_distance", "pivot_index", "pivot_prices", "pivot_strength", "ppo",
    "price_structure", "range_width", "roc", "rolling_high_low", "stddev",
    "stochastic", "true_range", "up_down_ratio", "up_down_volume", "volume_ema",
    "volume_spike", "vwap", "vwma20", "week_levels_52", "wicks", "wma20",
})


def compute_all(df: pd.DataFrame, lite: bool = False) -> None:
    """
    Run the indicator pipeline once, in place, so every pattern detector
    and the quality/ranking engines can share one dataframe.

    lite=True skips indicators no detector or feature reads (LITE_SKIP) - a
    speed option for the walk-forward backtest that recomputes indicators at
    every bar. It is correctness-guarded by tests/test_indicators_lite.py;
    the live scanner always uses the full path.

    NOTE: this inserts many columns one at a time, which pandas warns about
    as a PerformanceWarning (DataFrame fragmentation) - a memory-layout
    warning, not a correctness one - so it is suppressed here.
    """

    with warnings.catch_warnings():

        warnings.simplefilter("ignore", pd.errors.PerformanceWarning)

        _compute_all_impl(df, LITE_SKIP if lite else frozenset())


def _compute_all_impl(df: pd.DataFrame, skip: "frozenset[str]" = frozenset()) -> None:

    validate_dataframe(df)

    for name, fn in PIPELINE_STEPS:

        if name in skip:

            continue

        fn(df)
