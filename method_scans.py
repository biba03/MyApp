"""Independent EOD method screens; never alter existing trading/risk rules.
See docs/METHOD_SCANS_README.md for source definitions and numerical approximations.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

METHODS = ('Qullamaggie_Breakout', 'Minervini_Trend_Template',
           'Stockbee_4pct_Daily', 'Stockbee_20pct_Weekly', 'Stockbee_9M_Movers')

@dataclass(frozen=True)
class MethodScanConfig:
    # Optional common liquidity gates, disabled by default to preserve raw screens.
    min_price: float = 0.
    min_avg_dollar_volume: float = 0.
    excluded_tickers: tuple = ('SPY','QQQ','IWM')
    minervini_rs_min: float = 70.
    minervini_low_multiple: float = 1.30
    q_top_percentile: float = 98.
    q_prior_move: float = .30
    q_base_lengths: tuple = (10,20,30,40)
    q_max_base_width: float = .20
    q_min_adr_pct: float = 0.  # No author-specified universal ADR cutoff.
    q_breakout_rvol: float = 1.
    stockbee_daily_pct: float = 4.
    stockbee_weekly_pct: float = 20.
    stockbee_volume: float = 9_000_000.
    stockbee_9m_require_expansion: bool = True

COLUMNS = ['AsOf','Ticker','Method','Status','Close','DailyPct','WeeklyPct','Volume',
           'AvgDollarVolume20','RVOL20','ADR20Pct','RSProxy','BreakoutLevel',
           'BaseDays','BaseWidthPct','PriorMovePct','Reason']


def _prepare(market, asof, cfg):
    valid, excluded = {}, {}
    for tk, raw in market.items():
        if tk in cfg.excluded_tickers:
            excluded[tk] = 'benchmark'; continue
        if not isinstance(raw.index, pd.DatetimeIndex) or raw.index.has_duplicates:
            excluded[tk] = 'invalid or duplicate dates'; continue
        df = raw.sort_index().loc[:asof, ['Open','High','Low','Close','Volume']].copy()
        if df.empty or df.index[-1] != asof:
            excluded[tk] = 'no bar on selected date'; continue
        vals = df.to_numpy(dtype=float)
        tolerance = df[["Open","High","Low","Close"]].abs().max(axis=1)*1e-10
        if (not np.isfinite(vals).all() or (vals[:,:4] <= 0).any()
                or (vals[:,4] < 0).any() or (df.High + tolerance < df.Low).any()
                or (df.High + tolerance < df[['Open','Close']].max(axis=1)).any()
                or (df.Low - tolerance > df[['Open','Close']].min(axis=1)).any()):
            excluded[tk] = 'invalid OHLCV'; continue
        adv = float((df.Close * df.Volume).tail(20).mean())
        if df.Close.iloc[-1] < cfg.min_price or adv < cfg.min_avg_dollar_volume:
            excluded[tk] = 'optional liquidity gate'; continue
        valid[tk] = df
    return valid, excluded


def scan_methods(market: dict[str,pd.DataFrame], asof=None,
                 cfg: MethodScanConfig | None = None, candidate_tickers=None) -> pd.DataFrame:
    """Return one row per ticker/method; no input mutation or network calls.

    Explicit asof truncates future bars before all calculations. Tickers without
    a bar on that common date are excluded, never scanned at stale dates.
    attrs contain configuration, exclusions, and per-method eligible counts.
    """
    from dataclasses import asdict
    cfg = cfg or MethodScanConfig()
    latest = [df.index.max() for df in market.values() if len(df)]
    if asof is None and not latest:
        out = pd.DataFrame(columns=COLUMNS)
        out.attrs.update({'asof':None,'eligible_tickers':0,'excluded':{},'config':asdict(cfg)})
        return out
    asof = pd.Timestamp(asof) if asof is not None else max(latest)
    data, exclusions = _prepare(market, asof, cfg)
    # Weighted 12-month return percentile: explicitly a proxy, not an IBD rating.
    scores = {}
    momentum = {n:{} for n in (21,63,126)}
    for tk,df in data.items():
        c = df.Close
        if len(c)>=253:
            scores[tk] = sum(w*(float(c.iloc[-1]/c.iloc[-1-n])-1.)
                             for n,w in [(63,.4),(126,.2),(189,.2),(252,.2)])
        for n in momentum:
            if len(c)>n: momentum[n][tk] = float(c.iloc[-1]/c.iloc[-1-n])-1.
    rs = pd.Series(scores,dtype=float).rank(pct=True,method='average')*99
    ranks = {n:pd.Series(v,dtype=float).rank(pct=True,method='average')*100 for n,v in momentum.items()}
    rows=[]; eligible={m:0 for m in METHODS}
    for tk,df in data.items():
        if candidate_tickers is not None and tk not in candidate_tickers:
            continue
        c,h,l,v = df.Close,df.High,df.Low,df.Volume
        price=float(c.iloc[-1]); volume=float(v.iloc[-1])
        daily=100*(price/float(c.iloc[-2])-1) if len(df)>=2 else np.nan
        weekly=100*(price/float(c.iloc[-6])-1) if len(df)>=6 else np.nan
        prior_v=float(v.iloc[-21:-1].mean()) if len(df)>=21 else np.nan
        rvol=volume/prior_v if prior_v>0 else np.nan
        adr=float(((h/l-1)*100).tail(20).mean()) if len(df)>=20 else np.nan
        common=dict(AsOf=str(asof.date()),Ticker=tk,Close=price,DailyPct=daily,
                    WeeklyPct=weekly,Volume=volume,AvgDollarVolume20=float((c*v).tail(20).mean()),
                    RVOL20=rvol,ADR20Pct=adr,RSProxy=float(rs.get(tk,np.nan)))
        def emit(method,status,reason,**extra):
            rows.append(dict(common,Method=method,Status=status,Reason=reason,**extra))
        if len(df)>=2:
            eligible[METHODS[2]]+=1
            if price/float(c.iloc[-2]) >= 1+cfg.stockbee_daily_pct/100:
                emit(METHODS[2],'Daily gainer','Close / previous close >= 1.04')
        if len(df)>=6:
            eligible[METHODS[3]]+=1
            if price/float(c.iloc[-6]) >= 1+cfg.stockbee_weekly_pct/100:
                emit(METHODS[3],'Weekly gainer','Close / close five sessions ago >= 1.20')
        if len(df)>=21:
            eligible[METHODS[4]]+=1
            if (volume>=cfg.stockbee_volume and daily>0
                    and (not cfg.stockbee_9m_require_expansion or rvol>1)):
                emit(METHODS[4],'High-volume up mover','>=9M shares; positive day; volume expansion against prior 20 sessions')
        if len(df)>=253:
            eligible[METHODS[1]]+=1
            ma50=c.rolling(50).mean(); ma150=c.rolling(150).mean(); ma200=c.rolling(200).mean()
            checks=[price>ma150.iloc[-1] and price>ma200.iloc[-1],
                    ma150.iloc[-1]>ma200.iloc[-1], ma200.iloc[-1]>ma200.iloc[-21],
                    ma50.iloc[-1]>ma150.iloc[-1] and ma50.iloc[-1]>ma200.iloc[-1],
                    price>ma50.iloc[-1],price>=cfg.minervini_low_multiple*l.tail(252).min(),
                    price>=.75*h.tail(252).max(),rs.get(tk,0)>=cfg.minervini_rs_min]
            if all(checks):
                emit(METHODS[1],'Trend qualified','7 trend/price rules + local 12-month RS proxy >=70')
        if len(df)<127: continue
        eligible[METHODS[0]]+=1
        leader=any(ranks[n].get(tk,0)>=cfg.q_top_percentile for n in ranks)
        ma10=c.rolling(10).mean(); ma20=c.rolling(20).mean()
        if not (leader and adr>=cfg.q_min_adr_pct and price>ma10.iloc[-1]
                and price>ma20.iloc[-1] and ma10.iloc[-1]>ma10.iloc[-6]
                and ma20.iloc[-1]>ma20.iloc[-6]): continue
        for n in cfg.q_base_lengths:
            if len(df)<n+64: continue
            base=df.iloc[-n-1:-1]; prior=df.iloc[-n-64:-n-1]
            prior_move=float((prior.Close/prior.Close.cummin()-1).max())
            level=float(base.High.max()); width=level/float(base.Low.min())-1
            half=n//2; first=base.iloc[:half]; last=base.iloc[half:]
            tightening=float(last.High.max()-last.Low.min()) <= float(first.High.max()-first.Low.min())
            higher_lows=float(last.Low.min())>float(first.Low.min())
            if not (prior_move>=cfg.q_prior_move and width<=cfg.q_max_base_width and tightening and higher_lows): continue
            breakout=price>level and rvol>=cfg.q_breakout_rvol
            ready=price<=level and price>=level*.97
            if breakout or ready:
                emit(METHODS[0], 'Breakout' if breakout else 'Watchlist',
                     'Daily-bar proxy: leader + prior advance + contracting higher-low base + rising MAs',
                     BreakoutLevel=level,BaseDays=n,BaseWidthPct=width*100,PriorMovePct=prior_move*100)
                break
    out=pd.DataFrame(rows,columns=COLUMNS)
    if len(out): out=out.sort_values(['Method','DailyPct','Ticker'],ascending=[True,False,True]).reset_index(drop=True)
    out.attrs.update({'asof':str(asof.date()),'eligible_tickers':len(data),'eligible_by_method':eligible,
                      'excluded':exclusions,'config':asdict(cfg),'rs_proxy_universe':len(scores)})
    return out


def summarize_tags(results):
    """One row per ticker preserving every matching method and status."""
    if results.empty: return pd.DataFrame(columns=['AsOf','Ticker','Tags','Statuses','Close','DailyPct','WeeklyPct','Volume'])
    return results.groupby(['AsOf','Ticker'],sort=True).agg(
        Tags=('Method',lambda x:' | '.join(sorted(set(x)))),
        Statuses=('Status',lambda x:' | '.join(sorted(set(x)))),
        Close=('Close','first'),DailyPct=('DailyPct','first'),WeeklyPct=('WeeklyPct','first'),Volume=('Volume','first')).reset_index()


def tag_existing_results(results):
    """Tag the unchanged scanner output before concatenating with method rows."""
    out=results.copy();out['Method']='Shoryuken_Scanner'
    return out
