"""Reporting context; never changes detector scores or execution rules."""
import numpy as np
import pandas as pd


def funnel_fields(row):
    """Map existing diagnostic states, without inventing missing eligibility."""
    state = row.get('Readiness')
    gate = row.get('Watchable')
    gate_pass = isinstance(gate, (bool, np.bool_)) and bool(gate)
    trigger = pd.to_numeric(row.get('TriggerPrice'), errors='coerce')
    has_trigger = pd.notna(trigger) and np.isfinite(trigger) and trigger > 0
    if not gate_pass:
        stage = 'Not assessed' if pd.isna(gate) else 'Outside Watchable'
    elif state == 'Breakout' and has_trigger:
        stage = 'Actionable'
    elif state == 'Ready' and has_trigger:
        stage = 'Tradable'
    else:
        stage = 'Watchable'
    return {'FunnelStage': stage,
            'FunnelReason': str(row.get('ReadinessReasons') or 'No readiness assessment'),
            'FunnelBasis': 'Existing diagnostic thresholds; not an order or complete trade eligibility check'}


def market_breadth(market, asof):
    """Equal-weight breadth. Each metric has its own valid-history denominator."""
    date = pd.Timestamp(asof).normalize()
    metrics = {k: [0, 0] for k in ('AboveSMA50', 'AboveSMA200', 'Advancing', 'Near52WeekHigh')}
    stale = invalid = current = 0
    for raw in market.values():
        if raw is None or raw.empty or 'Close' not in raw:
            invalid += 1; continue
        df = raw.sort_index().copy()
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df.loc[~df.index.duplicated(keep='last')].loc[:date]
        if df.empty:
            invalid += 1; continue
        if df.index[-1].normalize() != date:
            stale += 1; continue
        close = pd.to_numeric(df.Close, errors='coerce')
        if not np.isfinite(close.iloc[-1]) or close.iloc[-1] <= 0:
            invalid += 1; continue
        current += 1
        def record(key, values, length, condition):
            tail = values.tail(length)
            if len(tail) == length and (np.isfinite(tail) & tail.gt(0)).all():
                metrics[key][1] += 1
                metrics[key][0] += int(condition(tail))
        for n in (50, 200):
            record('AboveSMA'+str(n), close, n, lambda s: s.iloc[-1] > s.mean())
        record('Advancing', close, 2, lambda s: s.iloc[-1] > s.iloc[-2])
        if 'High' in df:
            high = pd.to_numeric(df.High, errors='coerce')
            record('Near52WeekHigh', high, 252, lambda s: close.iloc[-1] >= .97*s.max())
    return {'AsOf': date.date().isoformat(), 'UniverseCount': len(market),
            'CurrentCount': current, 'StaleCount': stale, 'InvalidCount': invalid,
            'Metrics': {k: {'Count': v[0], 'Eligible': v[1],
                           'Pct': 100*v[0]/v[1] if v[1] else None}
                        for k, v in metrics.items()},
            'Basis': 'Full cached stock universe; equal-weight; near high = within 3% of 252-session high. Latest incomplete daily bars are not detected.'}
