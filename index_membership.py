"""Dated index membership snapshots, isolated from stock price caches."""
from pathlib import Path
from io import StringIO
import csv
import json
import os
import re
import pandas as pd

INDEXES = {
    'SPY': ('S&P 500', 'Wikipedia constituent list (existing project loader)'),
    'QQQ': ('Nasdaq 100', 'Wikipedia constituent list (existing project loader)'),
    'IWM': ('Russell 2000', 'iShares IWM equity holdings proxy; not an official index constituent file'),
}
IWM_URL = 'https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/latest-holdings.csv'


def symbol(value):
    return str(value).strip().upper().replace('.', '-').replace(' ', '-')


def parse_iwm(text):
    lines = text.lstrip('\ufeff').splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith('Ticker,') and 'Asset Class' in line), None)
    if start is None:
        raise ValueError('No IWM holdings header; response may be an HTML error page')
    rows = csv.DictReader(lines[start:])
    tickers = sorted({symbol(r.get('Ticker','')) for r in rows
                      if r.get('Asset Class') == 'Equity' and re.fullmatch(r'[A-Z][A-Z0-9-]{0,14}', symbol(r.get('Ticker','')))})
    if not tickers:
        raise ValueError('No IWM equity holdings')
    date = None
    for line in lines[:start]:
        if line.startswith('Fund Holdings as of,'):
            date = pd.Timestamp(next(csv.reader([line]))[1]).date().isoformat()
    return {'Tickers': tickers, 'MembershipDate': date}


def fetch_members(key):
    if key in ('SPY','QQQ'):
        from downloader import get_sp500_tickers, get_nasdaq100_tickers
        tickers = (get_sp500_tickers if key == 'SPY' else get_nasdaq100_tickers)()
        return {'Tickers': tickers, 'MembershipDate': None}
    import requests
    response = requests.get(IWM_URL, timeout=25, headers={'User-Agent':'Mozilla/5.0'})
    response.raise_for_status()
    return parse_iwm(response.text)


def load_index_memberships(cache_dir, refresh=True, fetcher=None, today=None):
    """Reuse same-day snapshots; failed refresh preserves last good membership."""
    directory = Path(cache_dir); directory.mkdir(parents=True, exist_ok=True)
    today = str(pd.Timestamp(today or pd.Timestamp.now(tz='UTC')).date())
    fetcher = fetcher or fetch_members
    results = {}
    for key, (name, source) in INDEXES.items():
        path = directory / (key+'.json')
        cached = None; error = None
        if path.exists():
            try:
                cached = json.loads(path.read_text())
                if cached.get('Index') != key or not cached.get('Tickers'):
                    cached = None
            except (ValueError, OSError):
                pass
        status = 'Cached' if cached else 'Unavailable'
        if refresh and (cached is None or cached.get('FetchedDate') != today):
            try:
                raw = fetcher(key)
                tickers = sorted({symbol(t) for t in raw['Tickers'] if re.fullmatch(r'[A-Z][A-Z0-9-]{0,14}',symbol(t))})
                # Guard against accidentally accepting top-holdings tables or error pages.
                minimum = {'SPY':400,'QQQ':80,'IWM':1000}[key]
                if len(tickers) < minimum:
                    raise ValueError(f'Membership incomplete: {len(tickers)} tickers; minimum {minimum}')
                cached = dict(Index=key, Name=name, Source=source, FetchedDate=today,
                              MembershipDate=raw.get('MembershipDate'), Tickers=tickers)
                tmp = path.with_suffix('.json.tmp');tmp.write_text(json.dumps(cached));os.replace(tmp,path)
                status = 'Downloaded'
            except Exception as exc:
                error = type(exc).__name__+': '+str(exc)
                status = 'Cached fallback' if cached else 'Unavailable'
        results[key] = dict(cached or dict(Index=key,Name=name,Source=source,Tickers=[]),
                            Status=status, Error=error)
    return results
