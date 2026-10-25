"""User-configured momentum candidate screen, not a confirmed breakout detector."""
import numpy as np
import pandas as pd
from method_scans import _prepare, MethodScanConfig, COLUMNS


def scan_qullamaggie_momentum(market, audit, asof):
    """Return candidates and per-rule diagnostics; no mutation, network or writes.

    ROC ranks describe the full valid universe with 127+ bars. No ROC cutoff.
    Cap validity is the existing dated Watchable audit check, not Watchable pass.
    """
    asof = pd.Timestamp(asof)
    data, excluded = _prepare(market, asof, MethodScanConfig())
    caps = audit.drop_duplicates('Ticker', keep='last').set_index('Ticker').to_dict('index')
    rows = []
    for ticker in sorted(set(market) - {'SPY', 'QQQ', 'IWM'}):
        row = dict(Ticker=ticker, AsOf=str(asof.date()), Matched=False)
        df = data.get(ticker)
        if df is None or len(df) < 127:
            row['ExclusionReasons'] = excluded.get(ticker, 'Need 127 daily bars for all ROC windows')
            rows.append(row)
            continue
        c, v = df.Close, df.Volume
        price = float(c.iloc[-1])
        adr = float(((df.High / df.Low - 1) * 100).tail(20).mean())
        sma10, sma20, sma50 = (float(c.tail(n).mean()) for n in (10, 20, 50))
        info = caps.get(ticker, {})
        cap = pd.to_numeric(info.get('MarketCapUSD'), errors='coerce')
        valid = info.get('PassCapData')
        valid = isinstance(valid, (bool, np.bool_)) and bool(valid)
        avg_volume = float(v.tail(20).mean())
        dollar_volume = price * float(v.iloc[-1])
        checks = dict(PassPrice=price > 8, PassADR=adr > 4,
                      PassCapData=valid,
                      PassMarketCap=bool(pd.notna(cap) and np.isfinite(cap) and cap >= 1_000_000_000),
                      PassLiquidity=dollar_volume > 20_000_000 or avg_volume > 300_000,
                      PassMAAlignment=sma10 > sma20 > sma50,
                      PassPriceAboveMA=price > sma10 or price > sma20 or price > sma50)
        prior_volume = float(v.iloc[-21:-1].mean())
        row.update(checks)
        row.update(Close=price, ADR20Pct=adr, MarketCapUSD=cap,
                   MarketCapSnapshotDate=info.get('MarketCapSnapshotDate'),
                   DollarVolume1D=dollar_volume, AvgVolume20=avg_volume,
                   SMA10=sma10, SMA20=sma20, SMA50=sma50,
                   DailyPct=(price / float(c.iloc[-2]) - 1) * 100,
                   WeeklyPct=(price / float(c.iloc[-6]) - 1) * 100,
                   Volume=float(v.iloc[-1]), AvgDollarVolume20=float((c*v).tail(20).mean()),
                   RVOL20=float(v.iloc[-1]) / prior_volume if prior_volume > 0 else np.nan,
                   Matched=all(checks.values()),
                   ExclusionReasons='; '.join(k for k, passed in checks.items() if not passed))
        for label, n in [('Month', 21), ('ThreeMonth', 63), ('SixMonth', 126)]:
            row[label+'Pct'] = (price / float(c.iloc[-n-1]) - 1) * 100
        rows.append(row)
    diagnostics = pd.DataFrame(rows)
    for label in ('Month', 'ThreeMonth', 'SixMonth'):
        col = label+'Pct'
        if col not in diagnostics:
            diagnostics[col] = pd.Series(index=diagnostics.index, dtype=float)
        diagnostics[label+'Rank'] = diagnostics[col].rank(ascending=False, method='min')
    if 'Matched' not in diagnostics:
        diagnostics['Matched'] = pd.Series(dtype=bool)
    matches = diagnostics.loc[diagnostics.Matched.eq(True)].copy()
    matches['Method'] = 'Qullamaggie_Breakout'  # Existing board/CSV compatibility.
    matches['Status'] = 'Momentum candidate'
    matches['Reason'] = 'Momentum candidate: price >$8, ADR20 >4%, valid cap >=$500M; liquidity and SMA alignment. Not a confirmed breakout.'
    for col in COLUMNS:
        if col not in matches:
            matches[col] = np.nan
    if not matches.empty:
        matches = matches.sort_values(['MonthRank', 'Ticker']).reset_index(drop=True)
    return matches, diagnostics
