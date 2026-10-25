"""
fundamentals.py

Fundamental leadership overlay (Minervini SEPA).

The trend template / pattern detectors find technical *candidates*;
Minervini's edge is that real leaders also show accelerating earnings and
sales. Those signals are ORTHOGONAL to the price/volume features the
backtest showed have near-zero cross-sectional predictive power, so a
fundamental gate is the most promising place to add genuinely new edge.

This is a scaffold: a local CSV-backed store (like sector_data.py) plus a
gate. Fundamentals are fetched on demand (yfinance) and cached; anything
missing FAILS OPEN (the stock passes) so a data outage never silently
empties the scan. Wire a better data vendor into `fetch_fn` for production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

import config


FUNDAMENTAL_COLUMNS = ["ticker", "eps_growth_yoy", "rev_growth_yoy",
                       "eps_accelerating", "updated_at"]


@dataclass(slots=True)
class Fundamentals:
    ticker: str
    eps_growth_yoy: float | None      # latest quarter YoY EPS growth (fraction)
    rev_growth_yoy: float | None      # latest quarter YoY revenue growth
    eps_accelerating: bool | None     # last YoY growth > prior YoY growth


class FundamentalStore:
    """Local CSV cache of per-ticker fundamental growth metrics."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else (config.DATA_DIR / "fundamentals.csv")
        self._data: dict[str, Fundamentals] = {}
        self._load()

    # --- persistence ------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        df = pd.read_csv(self.path)
        for _, r in df.iterrows():
            self._data[r["ticker"]] = Fundamentals(
                ticker=r["ticker"],
                eps_growth_yoy=_nan_to_none(r.get("eps_growth_yoy")),
                rev_growth_yoy=_nan_to_none(r.get("rev_growth_yoy")),
                eps_accelerating=_bool_or_none(r.get("eps_accelerating")),
            )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = [{
            "ticker": f.ticker, "eps_growth_yoy": f.eps_growth_yoy,
            "rev_growth_yoy": f.rev_growth_yoy, "eps_accelerating": f.eps_accelerating,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        } for f in self._data.values()]
        pd.DataFrame(rows, columns=FUNDAMENTAL_COLUMNS).to_csv(self.path, index=False)

    # --- lookup -----------------------------------------------------------
    def get(self, ticker: str) -> Fundamentals | None:
        return self._data.get(ticker)

    def missing(self, tickers) -> list[str]:
        return [t for t in tickers if t not in self._data]

    def __len__(self) -> int:
        return len(self._data)

    # --- fetching ---------------------------------------------------------
    def update_missing(self, tickers, fetch_fn=None) -> int:
        """
        Fetch fundamentals for any ticker not already cached, persist, and
        return how many were fetched. Individual failures are swallowed
        (recorded as all-None) so one bad symbol never aborts the batch.
        """
        missing = self.missing(tickers)
        if not missing:
            return 0
        fetch_fn = fetch_fn or self._fetch_from_yfinance
        for ticker in missing:
            try:
                self._data[ticker] = fetch_fn(ticker)
            except Exception:
                self._data[ticker] = Fundamentals(ticker, None, None, None)
        self._save()
        return len(missing)

    @staticmethod
    def _fetch_from_yfinance(ticker: str) -> Fundamentals:
        """
        Best-effort quarterly EPS / revenue YoY growth from yfinance. This
        is the swappable piece - a paid vendor gives cleaner point-in-time
        data (yfinance is latest-only, so LIVE screening only; do NOT use
        it for historical backtests, which would inject look-ahead bias).
        """
        import yfinance as yf

        tk = yf.Ticker(ticker)
        eps_yoy = rev_yoy = None
        accelerating = None

        fin = getattr(tk, "quarterly_income_stmt", None)
        if fin is None or fin.empty:
            return Fundamentals(ticker, None, None, None)

        # Columns are quarter-end dates; order newest -> oldest so iloc[0] is
        # the latest quarter and iloc[4] is the same quarter a year earlier.
        fin = fin.reindex(sorted(fin.columns, reverse=True), axis=1)

        if "Diluted EPS" in fin.index:
            eps = fin.loc["Diluted EPS"].dropna()
            if len(eps) >= 5:
                eps_yoy = _growth(eps.iloc[0], eps.iloc[4])
            if len(eps) >= 6:
                prior = _growth(eps.iloc[1], eps.iloc[5])
                if eps_yoy is not None and prior is not None:
                    accelerating = eps_yoy > prior

        if "Total Revenue" in fin.index:
            rev = fin.loc["Total Revenue"].dropna()
            if len(rev) >= 5:
                rev_yoy = _growth(rev.iloc[0], rev.iloc[4])

        return Fundamentals(ticker, eps_yoy, rev_yoy, accelerating)


class FundamentalGate:
    """Passes a ticker if it clears the SEPA growth thresholds (or is unknown)."""

    def __init__(self, store: FundamentalStore):
        self.store = store

    def passes(self, ticker: str) -> bool:
        f = self.store.get(ticker)
        # Fail open: no data -> do not exclude (avoids emptying the scan when
        # fundamentals aren't wired up). Flip REQUIRE_KNOWN to be strict.
        if f is None:
            return not getattr(config, "REQUIRE_KNOWN_FUNDAMENTALS", False)
        if f.eps_growth_yoy is not None and f.eps_growth_yoy < config.MIN_EPS_GROWTH:
            return False
        if f.rev_growth_yoy is not None and f.rev_growth_yoy < config.MIN_SALES_GROWTH:
            return False
        return True


# --- helpers ---------------------------------------------------------------
def _growth(latest, base) -> float | None:
    try:
        latest, base = float(latest), float(base)
    except (TypeError, ValueError):
        return None
    if base == 0:
        return None
    return (latest - base) / abs(base)


def _nan_to_none(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)


def _bool_or_none(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return bool(v)
