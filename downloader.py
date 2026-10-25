"""
downloader.py
=============

Universe management + Yahoo Finance downloader with local cache.

Author: Your Name
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from io import StringIO
from typing import Dict, List

import pandas as pd
import requests
import yfinance as yf
from tqdm.auto import tqdm

from cache import cache
from config import (
    BENCHMARK,
    CUSTOM_TICKERS,
    DOWNLOAD_RETRIES,
    MAX_DOWNLOAD_THREADS,
    REQUEST_TIMEOUT,
    START_DATE,
    UNIVERSE,
)

logger = logging.getLogger(__name__)

###############################################################################
# HTTP HEADERS
###############################################################################

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/120 Safari/537.36"
    )
}

###############################################################################
# WIKIPEDIA HELPERS
###############################################################################


def _read_wikipedia_table(url: str):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return pd.read_html(StringIO(response.text), flavor="lxml")


def _clean_symbols(series) -> List[str]:

    return (
        series.astype(str)
        .str.strip()
        .str.replace(".", "-", regex=False)
        .str.upper()
        .tolist()
    )


def _flatten_columns(columns) -> List[str]:
    """
    pd.read_html can return either flat columns or a MultiIndex (when a
    table has nested/multi-row headers, e.g. a "grouped" header row).
    Flatten either shape down to a single lowercase string per column
    so we can search them consistently.
    """

    flat = []

    for col in columns:

        if isinstance(col, tuple):

            parts = [
                str(p) for p in col
                if str(p) and not str(p).lower().startswith("unnamed")
            ]

            flat.append(" ".join(parts).strip().lower())

        else:

            flat.append(str(col).strip().lower())

    return flat


def _is_changes_log_table(table) -> bool:
    """
    Wikipedia's "annual changes" / "historical changes" tables (as
    opposed to the actual constituent list) reliably have a "Reason"
    column, and two ticker-like columns (one for the security added,
    one for the security removed) rather than one. Both are strong,
    Wikipedia-convention-specific tells that this is NOT the
    constituent list, even if it also happens to contain a column
    whose header/values look ticker-like.
    """

    flat_cols = _flatten_columns(table.columns)

    if any("reason" in c for c in flat_cols):

        return True

    # Short sector names or SEC-link labels can look like tickers too.
    # Identify additions/removals from headers, not arbitrary column values.
    has_added = any('added' in c or 'addition' in c for c in flat_cols)
    has_removed = any('removed' in c or 'deletion' in c for c in flat_cols)
    return has_added and has_removed


def _find_ticker_column(tables, keywords=("symbol", "ticker"), min_rows=50, min_ratio=0.5):
    """
    Wikipedia occasionally reorders/adds tables on these pages (extra
    milestone tables, historical-changes tables with nested headers,
    etc.), so picking "the first table" or an exact column name match
    is fragile. A header match alone isn't enough either - a
    changes-history table can have a nested ('Added', 'Ticker')
    column that matches the keyword but isn't the constituent list.

    So: exclude changes-log-shaped tables outright, then require BOTH
    a header containing a ticker/symbol-like keyword AND values that
    actually look like tickers, preferring a plain (non-nested) header
    match over one buried in a MultiIndex, and more rows as a
    tiebreaker.
    """

    candidates = []  # (table, col, is_flat_header, row_count)

    for table in tables:

        if len(table) < min_rows:

            continue

        if _is_changes_log_table(table):

            continue

        flat_cols = _flatten_columns(table.columns)

        for original_col, flat_col in zip(table.columns, flat_cols):

            if not any(keyword in flat_col for keyword in keywords):

                continue

            try:

                ratio = _looks_like_ticker_series(table[original_col])

            except Exception:

                continue

            if ratio < min_ratio:

                continue

            is_flat_header = not isinstance(original_col, tuple)

            candidates.append((table, original_col, is_flat_header, len(table)))

    if not candidates:

        return None, None

    candidates.sort(key=lambda c: (not c[2], -c[3]))

    best = candidates[0]

    return best[0], best[1]


def _looks_like_ticker_series(series, min_ratio=0.85) -> float:
    """
    What fraction of values in this column look like a stock ticker
    (1-6 uppercase letters, optionally with a .X/-X share-class
    suffix), ignoring header text entirely. Lets us find the right
    column even if the header text itself is malformed/unparseable.
    """

    values = series.astype(str).str.strip()

    if len(values) == 0:

        return 0.0

    matches = values.str.match(r"^[A-Za-z]{1,6}([.\-][A-Za-z]{1,2})?$")

    return float(matches.mean())


def _find_ticker_like_column(tables, min_rows=50, min_ratio=0.85):
    """
    Fallback for when header-based matching fails (e.g. the header
    text isn't what we expect, or lxml folded it into something we
    don't recognize). Scans every column of every large-enough table
    and picks the one whose *values* look like tickers, preferring
    the largest matching table.
    """

    best = None  # (table, col, row_count)

    for table in tables:

        if len(table) < min_rows:

            continue

        if _is_changes_log_table(table):

            continue

        for col in table.columns:

            try:

                ratio = _looks_like_ticker_series(table[col])

            except Exception:

                continue

            if ratio >= min_ratio and (best is None or len(table) > best[2]):

                best = (table, col, len(table))

    if best is None:

        return None, None

    return best[0], best[1]


def _describe_tables(tables) -> str:
    """
    Human-readable dump of every table's shape/columns, used in the
    error message if neither matcher finds anything - so a failure
    is diagnosable from the traceback alone instead of a bare
    "not found".
    """

    lines = []

    for i, table in enumerate(tables):

        cols = _flatten_columns(table.columns)

        lines.append(f"  table[{i}]: {len(table)} rows, columns={cols}")

    return "\n".join(lines)


def _find_ticker_table(tables, min_rows=50):
    """
    Try header-name matching first, then fall back to value-shape
    matching. Raises with a full dump of what was actually found if
    both fail, so the error is actionable.
    """

    table, col = _find_ticker_column(tables, min_rows=min_rows)

    if table is not None:

        return table, col

    table, col = _find_ticker_like_column(tables, min_rows=min_rows)

    if table is not None:

        return table, col

    raise RuntimeError(
        "Could not find a ticker/symbol column in any table on this "
        "page. Tables found:\n" + _describe_tables(tables)
    )


###############################################################################
# UNIVERSE FETCHERS
###############################################################################


def get_sp500_tickers() -> List[str]:

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

    tables = _read_wikipedia_table(url)

    table, col = _find_ticker_table(tables, min_rows=50)

    return _clean_symbols(table[col])


def get_sp400_tickers() -> List[str]:

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"

    tables = _read_wikipedia_table(url)

    table, col = _find_ticker_table(tables, min_rows=50)

    return _clean_symbols(table[col])


def get_sp600_tickers() -> List[str]:

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"

    tables = _read_wikipedia_table(url)

    table, col = _find_ticker_table(tables, min_rows=50)

    return _clean_symbols(table[col])


def get_nasdaq100_tickers() -> List[str]:

    url = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"

    tables = _read_wikipedia_table(url)

    table, col = _find_ticker_table(tables, min_rows=50)

    return _clean_symbols(table[col])


def get_combined_tickers() -> List[str]:
    """
    Union of SP500 + SP400 + NASDAQ100, deduplicated. NASDAQ100 overlaps
    heavily with SP500, so this is a set union rather than a
    concatenation.
    """

    tickers: set[str] = set()

    tickers.update(get_sp500_tickers())

    tickers.update(get_sp400_tickers())

    tickers.update(get_nasdaq100_tickers())

    return sorted(tickers)


UNIVERSE_FETCHERS = {
    "SP500": get_sp500_tickers,
    "SP400": get_sp400_tickers,
    "SP600": get_sp600_tickers,
    "NASDAQ100": get_nasdaq100_tickers,
    "COMBINED": get_combined_tickers,
}


###############################################################################
# BUILD UNIVERSE
###############################################################################


def build_universe() -> List[str]:

    if UNIVERSE == "CUSTOM":

        tickers = sorted(set(t.upper() for t in CUSTOM_TICKERS))

    else:

        tickers = UNIVERSE_FETCHERS[UNIVERSE]()

    tickers = [t for t in tickers if t != BENCHMARK]

    return sorted(set(tickers))


###############################################################################
# YAHOO DOWNLOAD
###############################################################################


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    yfinance can return either a flat column index or a MultiIndex
    (Price, Ticker) even for a single symbol. Either way, normalize to
    Title Case ("Open", "High", "Low", "Close", "Volume") to match what
    indicators.py's REQUIRED_COLUMNS and every df["Open"]-style access
    throughout the rest of the project expect.
    """

    if isinstance(df.columns, pd.MultiIndex):

        df.columns = [str(c[0]).capitalize() for c in df.columns]

    else:

        df.columns = [str(c).capitalize() for c in df.columns]

    return df


def _validate(df: pd.DataFrame, min_rows: int = 50) -> bool:
    """
    min_rows defaults to 50, appropriate for a FULL historical
    download (there should be a substantial amount of history).

    An INCREMENTAL update is a different case entirely: by design it
    only requests a handful of new days since the last cached date, so
    requiring >50 rows there would reject every legitimate incremental
    update whenever the gap since the last cache refresh is under
    roughly 10 weeks - which is nearly always, since that's the whole
    point of incremental updates. Callers doing an incremental update
    should pass a much smaller min_rows (see _download_one below).
    """

    required = {"Open", "High", "Low", "Close", "Volume"}

    return required.issubset(df.columns) and len(df) >= min_rows


def _download_one(ticker: str):

    # Fresh cache? No network call needed at all.
    if cache.is_fresh(ticker):

        cached = cache.load(ticker)

        if cached is not None:

            return ticker, cached, None, "fresh"

    # Incremental update: only request the days since what's already cached
    last = cache.last_date(ticker)

    start = START_DATE if last is None else (last - pd.Timedelta(days=5)).strftime("%Y-%m-%d")

    mode = "full" if last is None else "incremental"

    # A full download should have substantial history; an incremental
    # update legitimately might only be a single new trading day.
    min_rows = 50 if last is None else 1

    last_error = None

    for attempt in range(DOWNLOAD_RETRIES):

        try:

            df = yf.download(
                ticker,
                start=start,
                auto_adjust=True,
                progress=False,
                threads=False,
            )

            if df.empty:

                raise RuntimeError("Empty download (often Yahoo rate-limiting - see below)")

            df = _normalize_columns(df)

            df.index = pd.to_datetime(df.index)

            df.sort_index(inplace=True)

            if not _validate(df, min_rows=min_rows):

                raise RuntimeError("Invalid OHLCV structure")

            if last is None:

                cache.save(ticker, df)

            else:

                cache.update(ticker, df)

            return ticker, cache.load(ticker), None, mode

        except Exception as exc:

            last_error = f"{type(exc).__name__}: {exc}"

            if attempt + 1 == DOWNLOAD_RETRIES:

                logger.warning("Failed to download %s: %s", ticker, last_error)

                return ticker, None, last_error, mode

            time.sleep(1.5 * (attempt + 1))

    return ticker, None, last_error, mode


###############################################################################
# PUBLIC API
###############################################################################


def download_universe(tickers: List[str]) -> Dict[str, pd.DataFrame]:

    output: Dict[str, pd.DataFrame] = {}

    errors: Dict[str, str] = {}

    mode_counts = {"fresh": 0, "incremental": 0, "full": 0}

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_DOWNLOAD_THREADS
    ) as executor:

        futures = {
            executor.submit(_download_one, ticker): ticker
            for ticker in tickers
        }

        for future in tqdm(
            concurrent.futures.as_completed(futures),
            total=len(futures),
            desc="Downloading",
            unit="ticker",
        ):

            ticker, df, error, mode = future.result()

            mode_counts[mode] = mode_counts.get(mode, 0) + 1

            if df is not None:

                output[ticker] = df

            elif error is not None:

                errors[ticker] = error

    print(
        f"\nCache usage: {mode_counts['fresh']} already fresh (no request sent), "
        f"{mode_counts['incremental']} incremental (only new days fetched), "
        f"{mode_counts['full']} full history downloads."
    )

    if mode_counts["full"] > len(tickers) * 0.5 and mode_counts["fresh"] == 0:

        print(
            "Almost everything did a full download - if you expected most of "
            "these to already be cached from a prior run, see cache.path "
            f"below and confirm it's the same file each time: {cache.path}"
        )

    if errors and not output:

        # Every ticker failed - almost always Yahoo rate-limiting/blocking
        # rather than a real per-ticker problem. Surface one example so the
        # cause is visible instead of a silent "Loaded 0 tickers".
        sample_ticker, sample_error = next(iter(errors.items()))

        print(
            f"\nAll {len(errors)} downloads failed. Example ({sample_ticker}): "
            f"{sample_error}\n"
            "This is almost always Yahoo Finance rate-limiting yfinance, not a "
            "bug in this code. Try: pip install -U yfinance, wait a bit and "
            "retry, or use a different network. See the troubleshooting notes "
            "in the notebook."
        )

    elif errors:

        print(f"\n{len(errors)} of {len(tickers)} tickers failed to download.")

    return output


def download_benchmark() -> pd.DataFrame:

    ticker, df, error, mode = _download_one(BENCHMARK)

    if df is None:

        raise RuntimeError(
            f"Failed to download benchmark: {BENCHMARK} ({error})"
        )

    return df


###############################################################################
# TEST
###############################################################################

if __name__ == "__main__":

    universe = build_universe()

    print(f"Universe size: {len(universe)}")

    sample = universe[:10]

    data = download_universe(sample)

    print(f"Downloaded: {len(data)} tickers")

    for t, df in list(data.items())[:3]:

        print(t, df.tail(2))
