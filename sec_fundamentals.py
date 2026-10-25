"""
sec_fundamentals.py

POINT-IN-TIME fundamentals from SEC EDGAR's free XBRL API.

Unlike yfinance (latest-only, so backtest-unsafe), every SEC fact carries
its `filed` date - the day it became public. Querying "what was known as of
date D" means using only facts with filed <= D, which is genuinely
look-ahead-free and therefore usable in historical backtests.

Free, no key. SEC asks for a descriptive User-Agent and <=10 req/s.

Scope / honest limits:
- Covers companies that file with the SEC (US-listed). Foreign/ADR coverage
  is spotty; missing data fails open (see FundamentalGate).
- Quarterly figures are taken from ~90-day XBRL periods; issuers that report
  only cumulative periods may yield fewer clean quarters.
- This fixes LOOK-AHEAD for fundamentals. It does NOT fix survivorship - a
  delisted company still has no price data in the cache.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

import config
from timing import timer

_UA = {"User-Agent": "shoryuken-research contact: research@example.com"}
_EPS_CONCEPT = "EarningsPerShareDiluted"
_REV_CONCEPTS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")
_CACHE = config.DATA_DIR / "sec_cache"

# Facts are cached per ticker; as-of filtering still runs on every query.
_TICKER_MEMO: dict[str, dict] = {}
_GPA_MEMO: dict[str, dict] = {}


def clear_memo_cache() -> None:
    """Clear in-process facts after refreshing or redirecting the disk cache."""
    _TICKER_MEMO.clear()
    _GPA_MEMO.clear()


@dataclass(slots=True)
class PitFundamentals:
    """Fundamentals as known on a given as-of date (look-ahead-free)."""
    ticker: str
    asof: pd.Timestamp
    eps_growth_yoy: float | None
    rev_growth_yoy: float | None
    eps_accelerating: bool | None
    last_filed: pd.Timestamp | None


# ---------------------------------------------------------------------------
# ticker -> CIK
# ---------------------------------------------------------------------------
_TICKER_CIK: dict[str, int] | None = None


def _load_ticker_cik() -> dict[str, int]:
    global _TICKER_CIK
    if _TICKER_CIK is not None:
        return _TICKER_CIK
    path = _CACHE / "ticker_cik.json"
    if path.exists():
        _TICKER_CIK = {k: int(v) for k, v in json.loads(path.read_text()).items()}
        return _TICKER_CIK
    r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=_UA, timeout=20)
    r.raise_for_status()
    mapping = {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}
    _CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping))
    _TICKER_CIK = mapping
    return mapping


def cik_for(ticker: str) -> int | None:
    return _load_ticker_cik().get(ticker.upper())


# ---------------------------------------------------------------------------
# concept fetch (cached per ticker)
# ---------------------------------------------------------------------------
def _fetch_concept(cik: int, concept: str) -> list[dict]:
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{concept}.json"
    r = requests.get(url, headers=_UA, timeout=20)
    if r.status_code != 200:
        return []
    units = r.json().get("units", {})
    # EPS is USD/shares; revenue is USD.
    series = units.get("USD/shares") or units.get("USD") or []
    return series


def _quarterly(points: list[dict]) -> pd.DataFrame:
    """Keep ~90-day (quarterly) facts; one row per period end, columns end/val/filed."""
    rows = []
    for p in points:
        start, end, filed = p.get("start"), p.get("end"), p.get("filed")
        if not (start and end and filed):
            continue
        dur = (pd.Timestamp(end) - pd.Timestamp(start)).days
        if 80 <= dur <= 100:  # a single fiscal quarter
            rows.append({"end": pd.Timestamp(end), "val": float(p["val"]), "filed": pd.Timestamp(filed)})
    if not rows:
        return pd.DataFrame(columns=["end", "val", "filed"])
    df = pd.DataFrame(rows).sort_values(["end", "filed"])
    return df


def fetch_ticker(ticker: str, use_cache: bool = True) -> dict:
    """All quarterly EPS/revenue facts for a ticker (cached to disk)."""
    key = ticker.upper()
    if use_cache and key in _TICKER_MEMO:
        with timer("sec_fetch_ticker.memo_hit"):
            return _TICKER_MEMO[key]
    _CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = _CACHE / f"{ticker.upper()}.json"
    if use_cache and cache_path.exists():
        with timer("sec_fetch_ticker.disk_read"):
            raw = json.loads(cache_path.read_text())
            out = {k: _load_frame(v) for k, v in raw.items()}
        _TICKER_MEMO[key] = out
        return out

    with timer("sec_fetch_ticker.network"):
        cik = cik_for(ticker)
        out = {"eps": pd.DataFrame(), "rev": pd.DataFrame()}
        if cik is not None:
            out["eps"] = _quarterly(_fetch_concept(cik, _EPS_CONCEPT))
            time.sleep(0.12)
            for concept in _REV_CONCEPTS:
                rev = _quarterly(_fetch_concept(cik, concept))
                time.sleep(0.12)
                if not rev.empty:
                    out["rev"] = rev
                    break
        cache_path.write_text(json.dumps(
            {k: (v.assign(end=v["end"].astype(str), filed=v["filed"].astype(str)).to_dict("records")
                 if not v.empty else []) for k, v in out.items()}
        ))
        if use_cache:
            _TICKER_MEMO[key] = out
        return out


def _load_frame(records) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["end", "val", "filed"])
    df = pd.DataFrame(records)
    df["end"] = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    return df


# ---------------------------------------------------------------------------
# point-in-time query
# ---------------------------------------------------------------------------
def _yoy_asof(df: pd.DataFrame, asof: pd.Timestamp):
    """Latest-quarter YoY growth using only rows filed on/before `asof`."""
    known = df[df["filed"] <= asof]
    if known.empty:
        return None, None, None
    # value known as-of for each period end = latest filing <= asof.
    known = known.sort_values("filed").drop_duplicates("end", keep="last").sort_values("end")
    if len(known) < 5:
        return None, None, known["filed"].max()

    latest = known.iloc[-1]
    year_ago = known[known["end"] <= latest["end"] - pd.Timedelta(days=350)]
    if year_ago.empty:
        return None, None, latest["filed"]
    ya = year_ago.iloc[-1]
    growth = _growth(latest["val"], ya["val"])

    # acceleration: prior quarter's YoY vs this quarter's YoY
    accel = None
    if len(known) >= 6:
        prev = known.iloc[-2]
        prev_ya = known[known["end"] <= prev["end"] - pd.Timedelta(days=350)]
        if not prev_ya.empty:
            pg = _growth(prev["val"], prev_ya.iloc[-1]["val"])
            if growth is not None and pg is not None:
                accel = growth > pg
    return growth, accel, latest["filed"]


def point_in_time(ticker: str, asof, use_cache: bool = True) -> PitFundamentals:
    """EPS/revenue YoY growth as it was publicly known on `asof` (look-ahead-free)."""
    asof = pd.Timestamp(asof)
    data = fetch_ticker(ticker, use_cache=use_cache)
    eps_yoy, accel, eps_filed = _yoy_asof(data["eps"], asof) if not data["eps"].empty else (None, None, None)
    rev_yoy, _, rev_filed = _yoy_asof(data["rev"], asof) if not data["rev"].empty else (None, None, None)
    last_filed = max([f for f in (eps_filed, rev_filed) if f is not None], default=None)
    return PitFundamentals(ticker.upper(), asof, eps_yoy, rev_yoy, accel, last_filed)


def _growth(latest, base) -> float | None:
    try:
        latest, base = float(latest), float(base)
    except (TypeError, ValueError):
        return None
    if base == 0:
        return None
    return (latest - base) / abs(base)


# ---------------------------------------------------------------------------
# Gross profitability (Novy-Marx GP/A), point-in-time
# ---------------------------------------------------------------------------
_GP_CONCEPT = "GrossProfit"
_COST_CONCEPTS = ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")
_REV_ANNUAL = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet")
_ASSETS_CONCEPT = "Assets"


def _annual(points: list[dict]) -> pd.DataFrame:
    """~365-day (fiscal-year) duration facts: end/val/filed."""
    rows = []
    for p in points:
        start, end, filed = p.get("start"), p.get("end"), p.get("filed")
        if not (start and end and filed):
            continue
        dur = (pd.Timestamp(end) - pd.Timestamp(start)).days
        if 350 <= dur <= 380:
            rows.append({"end": pd.Timestamp(end), "val": float(p["val"]), "filed": pd.Timestamp(filed)})
    return pd.DataFrame(rows).sort_values(["end", "filed"]) if rows else pd.DataFrame(columns=["end", "val", "filed"])


def _instant(points: list[dict]) -> pd.DataFrame:
    """Balance-sheet instant facts (e.g. Assets): end/val/filed."""
    rows = []
    for p in points:
        end, filed = p.get("end"), p.get("filed")
        if not (end and filed):
            continue
        rows.append({"end": pd.Timestamp(end), "val": float(p["val"]), "filed": pd.Timestamp(filed)})
    return pd.DataFrame(rows).sort_values(["end", "filed"]) if rows else pd.DataFrame(columns=["end", "val", "filed"])


def fetch_gpa(ticker: str, use_cache: bool = True) -> dict:
    """Annual GrossProfit/Revenue/Cost + instant Assets facts (cached to disk)."""
    key = ticker.upper()
    if use_cache and key in _GPA_MEMO:
        with timer("sec_fetch_gpa.memo_hit"):
            return _GPA_MEMO[key]
    _CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = _CACHE / f"{ticker.upper()}_gpa.json"
    if use_cache and cache_path.exists():
        with timer("sec_fetch_gpa.disk_read"):
            raw = json.loads(cache_path.read_text())
            out = {k: _load_frame(v) for k, v in raw.items()}
        _GPA_MEMO[key] = out
        return out

    with timer("sec_fetch_gpa.network"):
        cik = cik_for(ticker)
        out = {"gp": pd.DataFrame(), "rev": pd.DataFrame(), "cost": pd.DataFrame(), "assets": pd.DataFrame()}
        if cik is not None:
            out["gp"] = _annual(_fetch_concept(cik, _GP_CONCEPT)); time.sleep(0.12)
            for c in _REV_ANNUAL:
                rev = _annual(_fetch_concept(cik, c)); time.sleep(0.12)
                if not rev.empty:
                    out["rev"] = rev; break
            for c in _COST_CONCEPTS:
                cost = _annual(_fetch_concept(cik, c)); time.sleep(0.12)
                if not cost.empty:
                    out["cost"] = cost; break
            out["assets"] = _instant(_fetch_concept(cik, _ASSETS_CONCEPT)); time.sleep(0.12)
        cache_path.write_text(json.dumps(
            {k: (v.assign(end=v["end"].astype(str), filed=v["filed"].astype(str)).to_dict("records")
                 if not v.empty else []) for k, v in out.items()}
        ))
        if use_cache:
            _GPA_MEMO[key] = out
        return out


def point_in_time_gpa(ticker: str, asof, use_cache: bool = True) -> dict:
    """
    Gross-profits-to-assets as known on `asof` (SEC facts filed <= asof).
    Uses annual GrossProfit; falls back to annual (Revenue - Cost) matched on
    the same fiscal period. Returns GP/A plus the raw components and their
    period-end/filed dates so every point-in-time join can be audited.
    """
    asof = pd.Timestamp(asof)
    d = fetch_gpa(ticker, use_cache=use_cache)

    def latest(df):
        if df.empty:
            return None
        k = df[df["filed"] <= asof]
        if k.empty:
            return None
        k = k.sort_values("filed").drop_duplicates("end", keep="last").sort_values("end")
        return k.iloc[-1]

    gp_val = gp_end = gp_filed = None
    source = "none"
    gp_row = latest(d["gp"])
    if gp_row is not None:
        gp_val, gp_end, gp_filed, source = gp_row["val"], gp_row["end"], gp_row["filed"], "GrossProfit"
    else:
        rev_row = latest(d["rev"])
        if rev_row is not None and not d["cost"].empty:
            ck = d["cost"][(d["cost"]["filed"] <= asof) & (d["cost"]["end"] == rev_row["end"])]
            if not ck.empty:
                c = ck.sort_values("filed").iloc[-1]
                gp_val = rev_row["val"] - c["val"]
                gp_end = rev_row["end"]
                gp_filed = max(rev_row["filed"], c["filed"])
                source = "Rev-Cost"

    a_row = latest(d["assets"])
    assets = a_end = a_filed = None
    if a_row is not None:
        assets, a_end, a_filed = a_row["val"], a_row["end"], a_row["filed"]

    gpa = (gp_val / assets) if (gp_val is not None and assets and assets > 0) else None
    return {
        "ticker": ticker.upper(), "asof": asof, "gpa": gpa, "source": source,
        "gross_profit": gp_val, "gp_period_end": gp_end, "gp_filed": gp_filed,
        "total_assets": assets, "assets_period_end": a_end, "assets_filed": a_filed,
    }
