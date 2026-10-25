"""
data.py

Thin orchestration layer that main.py actually imports.

Wires together:
  - downloader.py  (universe construction + Yahoo Finance download/cache)
  - indicators.py  (feature engineering, run once per ticker)

so the rest of the pipeline (scanner, quality, ranking) always receives
dataframes that already have every indicator column attached.
"""

from __future__ import annotations

from typing import Dict

import pandas as pd

import indicators
import config
from downloader import (
    build_universe,
    download_benchmark,
    download_universe,
)


class DataLoader:

    def refresh_prices(self) -> Dict[str, pd.DataFrame]:
        """Refresh the configured universe without computing discarded indicators.

        The notebook subsequently reads the complete shared discovery cache
        and computes indicators once. Main/dashboard load_universe behavior
        remains unchanged.
        """
        return download_universe(build_universe())

    def load_universe(self) -> Dict[str, pd.DataFrame]:
        """
        Build the ticker universe (per config.UNIVERSE), download/cache
        OHLCV for each ticker, and run the full indicator pipeline on
        every dataframe before handing them to the scanner.

        Also enforces config.MIN_PRICE/MAX_PRICE here - a universe-
        level liquidity/quality filter, not something any individual
        pattern detector should be responsible for re-checking.
        """

        tickers = build_universe()

        raw = download_universe(tickers)

        data: Dict[str, pd.DataFrame] = {}

        skipped_history: Dict[str, str] = {}

        skipped_price: Dict[str, float] = {}

        for ticker, df in raw.items():

            try:

                indicators.compute_all(df)

            except ValueError as exc:

                # Not enough history / bad OHLC — skip this ticker
                # rather than letting one bad symbol kill the scan.
                skipped_history[ticker] = str(exc)

                continue

            latest_close = float(df["Close"].iloc[-1])

            if not (config.MIN_PRICE <= latest_close <= config.MAX_PRICE):

                skipped_price[ticker] = latest_close

                continue

            data[ticker] = df

        total_skipped = len(skipped_history) + len(skipped_price)

        if total_skipped and not data:

            print(
                f"\n{total_skipped} of {len(raw)} downloaded tickers were dropped "
                f"({len(skipped_history)} for insufficient/invalid history, "
                f"{len(skipped_price)} for price outside "
                f"[{config.MIN_PRICE}, {config.MAX_PRICE}]) - and none made it "
                "through. If every ticker is failing, check downloader.py's "
                "_normalize_columns() or your MIN_PRICE/MAX_PRICE settings."
            )

        else:

            if skipped_history:

                print(f"\n{len(skipped_history)} of {len(raw)} tickers skipped (insufficient/invalid history).")

            if skipped_price:

                print(
                    f"{len(skipped_price)} of {len(raw)} tickers skipped "
                    f"(price outside [{config.MIN_PRICE}, {config.MAX_PRICE}])."
                )

        return data

    def load_benchmark(self) -> pd.DataFrame:

        df = download_benchmark()

        indicators.compute_all(df)

        return df
