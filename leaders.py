"""EMA100/EMA200 leadership, computed solely from supplied cached closes."""
import numpy as np
import pandas as pd


def build_leaders(market, asof=None, top_n=20, window=252):
    """Full-universe rolling score and historical membership; no I/O/mutation.

    EMAs use all available past data, adjust=False and 200-session warm-up.
    Three rankings: 252-session mean, 20-session change, and current ratio.
    Historical ranks use today's cached universe, not point-in-time constituents.
    """
    excluded = {'SPY', 'QQQ', 'IWM', 'RSP', 'QQQE', 'XLK', 'XLF', 'XLE',
                'XLI', 'XLV', 'XLY', 'XLP', 'XLU', 'XLB', 'XLRE', 'XLC'}
    histories, errors = {}, {}
    for ticker, frame in market.items():
        if ticker in excluded:
            continue
        try:
            if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.has_duplicates:
                raise ValueError('invalid/duplicate dates')
            close = pd.to_numeric(frame['Close'], errors='coerce').copy()
            close.index = close.index.tz_localize(None).normalize()
            if close.index.has_duplicates:
                raise ValueError('duplicate sessions')
            close = close.sort_index()
            if asof is not None:
                close = close.loc[:pd.Timestamp(asof).tz_localize(None).normalize()]
            if close.empty:
                raise ValueError('no history before report date')
            histories[ticker] = close.where(np.isfinite(close) & close.gt(0))
        except (ValueError, KeyError, TypeError) as error:
            errors[ticker] = str(error)
    reference = market.get('SPY')
    if reference is not None and not reference.empty:
        calendar = pd.DatetimeIndex(reference.index).tz_localize(None).normalize().unique().sort_values()
        calendar_basis = 'Cached SPY trading dates'
    else:
        calendar = pd.DatetimeIndex(sorted(set().union(*(set(s.index) for s in histories.values()))))
        calendar_basis = 'Union of cached stock dates; SPY unavailable'
    if asof is not None:
        calendar = calendar[calendar <= pd.Timestamp(asof).tz_localize(None).normalize()]
    base = dict(AsOf=str(calendar[-1].date()) if len(calendar) else None,
                Window=window, TopN=top_n, CalendarBasis=calendar_basis,
                UniverseCount=len(set(market)-excluded), PreparedCount=len(histories),
                EligibleCount=0, Dates=[], Top=[], HeatRows=[], Exclusions=errors,
                Basis='EMA100/EMA200 leadership; no Watchable, price, ADR, cap or liquidity gate. Historical ranks use the current cached universe.')
    if not len(calendar) or not histories:
        return base
    ratios = {}
    for ticker in sorted(histories):
        c = histories[ticker].reindex(calendar)
        ema100 = c.ewm(span=100, adjust=False, min_periods=100).mean()
        ema200 = c.ewm(span=200, adjust=False, min_periods=200).mean()
        # Never fill prices or pretend a missing session was observed.
        valid = c.notna().rolling(200, min_periods=200).sum().eq(200)
        ratio = (ema100 / ema200).where(valid)
        ratios[ticker] = ratio
    ratio_frame = pd.DataFrame(ratios, index=calendar)
    changes = {n: (ratio_frame / ratio_frame.shift(n) - 1) * 100 for n in (5, 20, 60)}
    valid20 = ratio_frame.notna().rolling(21, min_periods=21).sum().eq(21)
    changes[20] = changes[20].where(valid20)
    averages = ratio_frame.rolling(window, min_periods=window).mean()
    visible_dates = calendar[-window:]
    modes = {}
    definitions = {
        'year': ('Year Mean', '252-session mean EMA ratio', averages,
                 averages.notna()),
        'emerging': ('Emerging', '20-session ratio change (%)', changes[20],
                     ratio_frame.gt(1) & changes[20].gt(0)),
        'current': ('High Current Ratio', 'Current EMA ratio', ratio_frame,
                    ratio_frame.gt(1)),
    }
    def number(value):
        return float(value) if pd.notna(value) and np.isfinite(value) else None
    def values(series):
        return [number(x) for x in series]
    for key, (label, score_label, metric, eligible) in definitions.items():
        result = dict(base, Mode=key, Label=label, ScoreLabel=score_label,
                      Top=[], HeatRows=[], Exclusions=dict(errors))
        score_frame = metric.where(eligible)
        ranks = score_frame.rank(axis=1, ascending=False, method='first')
        latest = score_frame.iloc[-1].dropna().sort_values(ascending=False, kind='stable')
        selected = (latest if key == 'current' else latest.head(top_n)).index.tolist()
        heat_selected = latest.head(top_n).index.tolist()
        result['EligibleCount'] = len(latest)
        for ticker in ratio_frame:
            if pd.isna(score_frame[ticker].iloc[-1]):
                result['Exclusions'][ticker] = (
                    'Missing/stale/insufficient ratio history' if not valid20[ticker].iloc[-1]
                    else 'Insufficient yearly mean history' if key == 'year' else 'Does not meet this view: ratio >1, and positive 20-session change for Emerging')
        for position, ticker in enumerate(selected, 1):
            ratio = ratio_frame[ticker].iloc[-1]
            crossed = len(calendar) >= 21 and ratio > 1 and ratio_frame[ticker].iloc[-21] <= 1
            change = changes[20][ticker].iloc[-1]
            flag = 'Fading' if pd.notna(change) and change < 0 else 'Emerging · crossed above 1 in last 20 sessions' if crossed else 'Accelerating' if pd.notna(change) and change > 0 else 'Flat / insufficient change history'
            result['Top'].append(dict(Rank=position, Ticker=ticker,
                Score=number(latest[ticker]), AverageRatio=number(averages[ticker].iloc[-1]),
                CurrentRatio=number(ratio), Change5Pct=number(changes[5][ticker].iloc[-1]),
                Change20Pct=number(changes[20][ticker].iloc[-1]),
                Change60Pct=number(changes[60][ticker].iloc[-1]), Flag=flag,
                Close=number(histories[ticker].loc[calendar[-1]])))
        membership = ranks.loc[visible_dates].le(top_n)
        ever = membership.any(axis=0)
        others = sorted(set(ever[ever].index)-set(heat_selected))
        result['Dates'] = [str(d.date()) for d in visible_dates]
        for ticker in heat_selected + others:
            result['HeatRows'].append(dict(Ticker=ticker, Current=ticker in heat_selected,
                Ratios=values(ratio_frame.loc[visible_dates, ticker]),
                Scores=values(score_frame.loc[visible_dates, ticker]),
                Ranks=values(ranks.loc[visible_dates, ticker])))
        modes[key] = result
    return dict(modes['year'], Modes=modes)
