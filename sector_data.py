"""
sector_data.py

Local, CSV-backed sector/industry lookup for tickers.

Sector/industry classification doesn't change often, so rather than
hitting a network endpoint for it on every single scan, this loads a
local CSV once (config.DATA_DIR/sector_industry.csv) and only fetches
tickers that aren't already in it - persisting them for next time.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import config


class SectorIndustryMap:

    UNKNOWN = "Unknown"

    def __init__(self, path: Path | None = None):

        self.path = Path(path) if path else (config.DATA_DIR / "sector_industry.csv")

        self._data: dict[str, dict[str, str]] = {}

        self._load()

    ####################################################################
    # Persistence
    ####################################################################

    def _load(self) -> None:

        if not self.path.exists():

            self._data = {}

            return

        df = pd.read_csv(self.path, dtype=str).fillna(self.UNKNOWN)

        self._data = {
            row["ticker"]: {"sector": row["sector"], "industry": row["industry"]}
            for _, row in df.iterrows()
        }

    def _save(self) -> None:

        self.path.parent.mkdir(parents=True, exist_ok=True)

        rows = [
            {"ticker": ticker, "sector": v["sector"], "industry": v["industry"]}
            for ticker, v in sorted(self._data.items())
        ]

        pd.DataFrame(rows, columns=["ticker", "sector", "industry"]).to_csv(
            self.path, index=False
        )

    ####################################################################
    # Lookup
    ####################################################################

    def get(self, ticker: str) -> tuple[str, str]:

        entry = self._data.get(ticker)

        if entry is None:

            return self.UNKNOWN, self.UNKNOWN

        return entry["sector"], entry["industry"]

    def missing(self, tickers) -> list[str]:

        return [t for t in tickers if t not in self._data]

    def __len__(self) -> int:

        return len(self._data)

    ####################################################################
    # Fetching missing tickers
    ####################################################################

    def update_missing(self, tickers, fetch_fn=None) -> int:
        """
        Fetches sector/industry for any ticker not already in the
        local CSV, appends it, and persists - so future runs don't
        need the network for tickers already seen.

        fetch_fn defaults to a yfinance lookup, but can be overridden
        (used by tests, or if you want a different data source) - it
        must be a callable(ticker: str) -> (sector: str, industry: str).

        Failures for an individual ticker are caught and recorded as
        "Unknown" rather than aborting the whole batch - one bad
        symbol shouldn't block everything else from being cached.
        """

        missing = self.missing(tickers)

        if not missing:

            return 0

        fetch_fn = fetch_fn or self._fetch_from_yfinance

        for ticker in missing:

            try:

                sector, industry = fetch_fn(ticker)

                sector = sector or self.UNKNOWN

                industry = industry or self.UNKNOWN

            except Exception:

                sector, industry = self.UNKNOWN, self.UNKNOWN

            self._data[ticker] = {"sector": sector, "industry": industry}

        self._save()

        return len(missing)

    @staticmethod
    def _fetch_from_yfinance(ticker: str) -> tuple[str, str]:

        import yfinance as yf

        info = yf.Ticker(ticker).info

        return info.get("sector", "Unknown"), info.get("industry", "Unknown")
