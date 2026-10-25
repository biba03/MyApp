"""Yahoo-only daily ETF history, isolated cache and market performance."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
from threading import Lock
import numpy as np
import pandas as pd

_YAHOO_LOCK = Lock()

ETFS = {
    'SPY': ('S&P 500', 'Market'), 'QQQ': ('Nasdaq 100', 'Market'),
    'IWM': ('Russell 2000', 'Market'),
    'RSP': ('S&P 500 Equal Weight', 'Market'),
    'QQQE': ('Nasdaq 100 Equal Weight', 'Market'),
    'XLK': ('Technology', 'Sector'), 'XLF': ('Financials', 'Sector'),
    'XLE': ('Energy', 'Sector'), 'XLI': ('Industrials', 'Sector'),
    'XLV': ('Health Care', 'Sector'), 'XLY': ('Consumer Discretionary', 'Sector'),
    'XLP': ('Consumer Staples', 'Sector'), 'XLU': ('Utilities', 'Sector'),
    'XLB': ('Materials', 'Sector'), 'XLRE': ('Real Estate', 'Sector'),
    'XLC': ('Communication Services', 'Sector'),
}
PERIODS = {'DayPct': 1, 'WeekPct': 5, 'MonthPct': 21,
           'ThreeMonthPct': 63, 'SixMonthPct': 126, 'YearPct': 252}


def _history(frame, asof):
    frame = frame.copy()
    if 'Date' in frame:
        frame.index = pd.to_datetime(frame.pop('Date'), errors='raise')
    else:
        frame.index = pd.to_datetime(frame.index, errors='raise')
    if frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    if 'Close' not in frame:
        raise ValueError('Provider returned no Close column')
    frame['Close'] = pd.to_numeric(frame['Close'], errors='raise')
    if frame.index.hasnans or frame.empty or not (frame.Close.gt(0) & np.isfinite(frame.Close)).all():
        raise ValueError('Invalid price history')
    frame = frame.loc[~frame.index.duplicated(keep='last')].sort_index()
    frame = frame.loc[:pd.Timestamp(asof).normalize()]
    if frame.empty:
        raise ValueError('No history on or before the requested date')
    return frame


def fetch_free_history(ticker):
    """Yahoo Finance only; keep the existing auto-adjusted price convention."""
    import yfinance as yf
    with _YAHOO_LOCK:
        frame = yf.download(ticker, period='2y', interval='1d', auto_adjust=True,
                            progress=False, threads=False, timeout=15)
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    if frame.empty or 'Close' not in frame:
        raise ValueError('No Yahoo Finance prices returned')
    frame.attrs['Source'] = 'Yahoo Finance'
    frame.attrs['PriceBasis'] = 'Yahoo auto-adjusted close'
    return frame


def performance(frame, asof):
    frame = _history(frame, asof)
    close = frame.Close
    last = float(close.iloc[-1])
    row = {'LastClose':last, 'PriceDate':frame.index[-1].date().isoformat(),
           'PriceAgeCalendarDays':int((pd.Timestamp(asof).normalize()-frame.index[-1].normalize()).days)}
    for field, bars in PERIODS.items():
        row[field] = (last / float(close.iloc[-bars-1]) - 1) * 100 if len(close)>bars else None
    for period, bars in (('Week', 5), ('Month', 21)):
        row[period+'StartDate'] = frame.index[-bars-1].date().isoformat() if len(close)>bars else None
    baseline = close.loc[:pd.Timestamp(year=frame.index[-1].year-1, month=12, day=31)]
    row['YTDPct'] = (last / float(baseline.iloc[-1]) - 1) * 100 if len(baseline) else None
    return row


def load_market_view(cache_dir, refresh=True, asof=None, fetcher=None):
    """Refresh on stock-load; keep ETF data outside the discovery universe.

    Failed refreshes use clearly flagged cached history. Missing history is
    visible as an unavailable row. No credentials or paid subscription needed.
    Returns percent changes in provider closing-price series, not certified
    dividend-reinvested total returns. Windows use trading sessions.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    asof = pd.Timestamp(asof) if asof is not None else pd.Timestamp.now(tz='America/New_York').tz_localize(None).normalize()
    if asof.tzinfo is not None:
        asof = asof.tz_localize(None)
    fetcher = fetcher or fetch_free_history

    def load(item):
        ticker, (name, group) = item
        path = cache_dir / (ticker + '.csv')
        meta_path = cache_dir / (ticker + '.json')
        error = None
        frame = None
        refreshed = False
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except (ValueError, OSError):
                pass
        if refresh:
            try:
                frame = _history(fetcher(ticker), asof)
                temporary = path.with_suffix('.csv.tmp')
                frame.to_csv(temporary, index_label='Date')
                os.replace(temporary, path)
                meta = {'FetchedUTC':pd.Timestamp.now(tz='UTC').isoformat(),
                        'Source':frame.attrs.get('Source','Yahoo Finance'),
                        'PriceBasis':frame.attrs.get('PriceBasis','Provider closing-price series'),
                        'DownloadNote':frame.attrs.get('DownloadNote')}
                temporary_meta = meta_path.with_suffix('.json.tmp')
                temporary_meta.write_text(json.dumps(meta))
                os.replace(temporary_meta, meta_path)
                refreshed = True
            except Exception as exc:
                error = 'Refresh failed: ' + type(exc).__name__ + ': ' + str(exc)
        if frame is None and path.exists() and meta.get("Source") == "Yahoo Finance":
            try:
                frame = _history(pd.read_csv(path), asof)
            except Exception as exc:
                error = (error + '; ' if error else '') + 'Cache invalid: ' + str(exc)
        if frame is None and path.exists() and meta.get('Source') != 'Yahoo Finance':
            error = (error + '; ' if error else '') + 'Cached provider is not Yahoo Finance; refresh required'
        row = {'Ticker':ticker, 'Name':name, 'Group':group, 'Source':'Yahoo Finance',
               'PriceBasis':meta.get('PriceBasis','Provider closing-price series'),
               'DownloadNote':meta.get('DownloadNote'),
               'FetchedUTC':meta.get('FetchedUTC'), 'Error':error,
               'DataStatus':'Downloaded' if refreshed else ('Cached fallback' if frame is not None and refresh else 'Cached' if frame is not None else 'Unavailable')}
        if frame is not None:
            row.update(performance(frame, asof))
        else:
            row.update({field:None for field in ['LastClose','PriceDate','PriceAgeCalendarDays',*PERIODS,'YTDPct']})
        return row

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(load, ETFS.items()))
    result = sector_relative_strength(pd.DataFrame(rows))
    result.attrs['asof'] = asof.date().isoformat()
    return result


def sector_relative_strength(frame):
    """Relative return of each sector/SPY price ratio; require aligned endpoints."""
    out = frame.copy(deep=True)
    for key in ('WeekRSPct', 'MonthRSPct'):
        out[key] = np.nan
    out['RSBenchmark'] = 'SPY'
    out['RSStatus'] = 'Not a sector'
    benchmark = out.loc[out.Ticker.eq('SPY')] if 'Ticker' in out else pd.DataFrame()
    for i, row in out.iterrows():
        if row.get('Group') != 'Sector':
            continue
        out.loc[i, 'RSStatus'] = 'Benchmark or aligned history unavailable'
        if len(benchmark) != 1:
            continue
        b = benchmark.iloc[0]
        valid = []
        for period in ('Week', 'Month'):
            value = pd.to_numeric(row.get(period+'Pct'), errors='coerce')
            base = pd.to_numeric(b.get(period+'Pct'), errors='coerce')
            end = row.get('PriceDate')
            start = row.get(period+'StartDate')
            if (isinstance(end, str) and end == b.get('PriceDate') and
                    isinstance(start, str) and start == b.get(period+'StartDate') and
                    pd.notna(value) and pd.notna(base) and np.isfinite(value) and
                    np.isfinite(base) and base > -100 and value > -100):
                out.loc[i, period+'RSPct'] = ((1+value/100)/(1+base/100)-1)*100
                valid.append(period)
        out.loc[i, 'RSStatus'] = 'Available' if len(valid)==2 else 'Partial' if valid else 'Benchmark or aligned history unavailable'
    return out
