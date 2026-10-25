"""Live discovery prefilter. Never used by research/backtesting automatically."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import os
import tempfile
import numpy as np
import pandas as pd
from relative_strength import RelativeStrengthEngine
from trend_quality import StageAnalyzer
from sector_data import SectorIndustryMap


@dataclass(frozen=True)
class WatchableConfig:
    min_atr_pct: float = 3.
    min_dollar_volume: float = 50_000_000.
    min_rs: float = 70.
    min_sector_rank: float = 70.
    min_industry_rank: float = 70.
    min_market_cap: float = 500_000_000.
    max_cap_age_days: int = 7


def refresh_market_caps(tickers, path, fetch=None):
    """Explicit current snapshot refresh, no writes to price/research databases."""
    if fetch is None:
        import yfinance as yf
        fetch = lambda ticker: yf.Ticker(ticker).fast_info['market_cap']
    rows=[]
    ordered=sorted(tickers)
    print(f"Refreshing market-cap snapshots for {len(ordered)} tickers",flush=True)
    for position,ticker in enumerate(ordered,1):
        try:
            cap=float(fetch(ticker))
            rows.append(dict(Ticker=ticker,MarketCapUSD=cap,SnapshotDate=str(date.today())))
        except Exception as error:
            rows.append(dict(Ticker=ticker,MarketCapUSD=np.nan,SnapshotDate=str(date.today()),Error=type(error).__name__))
        if position % 25 == 0 or position == len(ordered):
            print(f'Market caps: {position}/{len(ordered)} processed',flush=True)
    frame=pd.DataFrame(rows);path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    frame.to_csv(path,index=False)
    return frame


def ensure_market_caps(tickers, path, max_age_days=7, fetch=None, today=None):
    """Refresh only missing/invalid/expired Yahoo caps; preserve failed snapshots.

    Retained expired snapshots still fail the existing Watchable freshness gate.
    """
    current = pd.Timestamp(today if today is not None else date.today()).normalize()
    path = Path(path)
    columns = ['Ticker', 'MarketCapUSD', 'SnapshotDate']
    cached = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=columns)
    if not set(columns).issubset(cached.columns):
        raise ValueError('Market-cap CSV requires Ticker, MarketCapUSD, SnapshotDate')
    rows = cached.drop_duplicates('Ticker', keep='last').set_index('Ticker').to_dict('index')
    pending = []
    for ticker in sorted(set(tickers)):
        row = rows.get(ticker, {})
        value = pd.to_numeric(row.get('MarketCapUSD'), errors='coerce')
        stamp = pd.to_datetime(row.get('SnapshotDate'), errors='coerce', utc=True)
        age = (current - stamp.tz_convert(None).normalize()).days if pd.notna(stamp) else -1
        if not (pd.notna(value) and np.isfinite(value) and value > 0 and 0 <= age <= max_age_days):
            pending.append(ticker)
    print(f'Market caps: {len(set(tickers))-len(pending)} fresh; {len(pending)} need refresh', flush=True)
    if not pending:
        return cached
    if fetch is None:
        import yfinance as yf
        fetch = lambda ticker: yf.Ticker(ticker).fast_info['market_cap']
    failed = 0
    for position, ticker in enumerate(pending, 1):
        try:
            value = float(fetch(ticker))
            if not np.isfinite(value) or value <= 0:
                raise ValueError('Invalid market cap')
            rows[ticker] = dict(MarketCapUSD=value, SnapshotDate=str(current.date()))
        except Exception as error:
            failed += 1
            row = rows.setdefault(ticker, dict(MarketCapUSD=np.nan, SnapshotDate=''))
            row['Error'] = type(error).__name__
        if position % 25 == 0 or position == len(pending):
            print(f'Market caps: {position}/{len(pending)} processed; {failed} failed', flush=True)
    frame = pd.DataFrame.from_dict(rows, orient='index').rename_axis('Ticker').reset_index()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            frame.to_csv(stream, index=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f'Market caps: {len(pending)-failed} refreshed; {failed} unavailable/retained (freshness rules unchanged)', flush=True)
    return frame


def watchable_universe(market, caps, sector_path, asof=None, cfg=None, snapshot_date=None):
    """Ranks use full valid universe BEFORE filtering. Unknown values fail closed.

    Market-cap snapshots are current metadata, not point-in-time historical data.
    snapshot_date is the date of this live report, separately from price asof.
    """
    cfg=cfg or WatchableConfig();snapshot_date=pd.Timestamp(snapshot_date or date.today())
    latest=[d.index.max() for d in market.values() if len(d)]
    asof=pd.Timestamp(asof or max(latest)) if latest else pd.Timestamp(asof or snapshot_date)
    engine=RelativeStrengthEngine();groups=SectorIndustryMap(Path(sector_path))
    valid={};returns={};failures={}
    for ticker,raw in market.items():
        if ticker in ('SPY','QQQ','IWM'):continue
        df=raw.sort_index().loc[:asof].copy()
        if len(df)<253 or df.index[-1]!=asof:
            failures[ticker]='Insufficient or stale price history';continue
        values=df[['Open','High','Low','Close','Volume']].to_numpy(dtype=float)
        tolerance=np.max(np.abs(values[:,:4]),axis=1)*1e-10
        invalid_ohlc=(df.High.to_numpy()+tolerance<np.maximum.reduce([df.Open.to_numpy(),df.Low.to_numpy(),df.Close.to_numpy()])).any() or (df.Low.to_numpy()-tolerance>np.minimum.reduce([df.Open.to_numpy(),df.High.to_numpy(),df.Close.to_numpy()])).any()
        if not np.isfinite(values).all() or (values[:,:4]<=0).any() or (values[:,4]<0).any() or invalid_ohlc:
            failures[ticker]='Invalid price/volume data';continue
        valid[ticker]=df;returns[ticker]=engine.weighted_return(df.Close)
    universe=np.array(list(returns.values()),dtype=float)
    # Unknown groups cannot count as a leading sector/industry.
    known={t:v for t,v in returns.items() if all(g not in ('Unknown','',None) for g in groups.get(t))}
    sectors=engine.group_rank(known,groups,'sector');industries=engine.group_rank(known,groups,'industry')
    cap_map={}
    if not caps.empty:
        required={'Ticker','MarketCapUSD','SnapshotDate'}
        if not required.issubset(caps.columns):raise ValueError('Market-cap CSV requires Ticker, MarketCapUSD, SnapshotDate')
        if caps.Ticker.duplicated().any():raise ValueError('Duplicate tickers in market-cap snapshot')
        cap_map=caps.set_index('Ticker').to_dict('index')
    rows=[]
    for ticker in sorted(set(valid)|set(failures)):
        row=dict(Ticker=ticker,AsOf=str(asof.date()),Watchable=False,PassHistory=ticker in valid)
        if ticker in failures:
            raw=market[ticker].sort_index().loc[:asof]
            row['PriceDate']=str(raw.index[-1].date()) if len(raw) else ''
            row['PriceAgeCalendarDays']=(snapshot_date-raw.index[-1]).days if len(raw) else np.nan
            row['ExclusionReasons']=failures[ticker];rows.append(row);continue
        df=valid[ticker];df['SMA150']=df.Close.rolling(150).mean()
        stage=StageAnalyzer().evaluate(df).stage
        tr=pd.concat([df.High-df.Low,(df.High-df.Close.shift()).abs(),(df.Low-df.Close.shift()).abs()],axis=1).max(axis=1)
        atrpct=float(tr.ewm(alpha=1/14,adjust=False).mean().iloc[-1]/df.Close.iloc[-1]*100)
        adv=float((df.Close*df.Volume).tail(20).mean());rs=engine.rating(returns[ticker],universe)
        sector,industry=groups.get(ticker);cap=cap_map.get(ticker,{})
        capvalue=pd.to_numeric(cap.get('MarketCapUSD'),errors='coerce');capdate=pd.to_datetime(cap.get('SnapshotDate'),errors='coerce')
        cap_valid=pd.notna(capdate) and 0<=(snapshot_date-capdate).days<=cfg.max_cap_age_days and pd.notna(capvalue) and capvalue>0
        reasons=[]
        checks=[('Stage 1–2 proxy',stage in ('Stage 1','Stage 2')),('ATR below 3%',atrpct>=cfg.min_atr_pct),('Dollar volume below $50M',adv>=cfg.min_dollar_volume),('Stock RS below 70',rs>=cfg.min_rs),('Sector missing or rank below 70',sectors.get(ticker,0)>=cfg.min_sector_rank),('Industry missing or rank below 70',industries.get(ticker,0)>=cfg.min_industry_rank),('Missing/stale/invalid market cap',cap_valid),('Market cap below $500M',bool(cap_valid and capvalue>=cfg.min_market_cap))]
        reasons=[label for label,passed in checks if not passed]
        for field,(_,passed) in zip(('PassStage','PassATR','PassDollarVolume','PassRS','PassSector','PassIndustry','PassCapData','PassMarketCap'),checks):
            row[field]=bool(passed)
        row.update(PriceDate=str(df.index[-1].date()),PriceAgeCalendarDays=(snapshot_date-pd.Timestamp(df.index[-1])).days,Stage=stage,StageBasis='Stage 1–2 proxy; no 1A/2B subdivisions',ATRPct=atrpct,AvgDollarVolume20=adv,RS=rs,Sector=sector,Industry=industry,SectorRank=sectors.get(ticker),IndustryRank=industries.get(ticker),MarketCapUSD=capvalue,MarketCapSnapshotDate=str(capdate.date()) if pd.notna(capdate) else '',Watchable=not reasons,ExclusionReasons='; '.join(reasons))
        rows.append(row)
    audit=pd.DataFrame(rows) if rows else pd.DataFrame(columns=['Ticker','Watchable','ExclusionReasons'])
    allowed=set(audit.loc[audit.Watchable,'Ticker']) if not audit.empty else set()
    summary={'price_asof':str(asof.date()),'metadata_report_date':str(snapshot_date.date()),'universe_stocks':len(rows),'watchable':len(allowed),'excluded':len(rows)-len(allowed),'ranking_universe':'Full valid universe before filtering','market_cap_note':'Current dated snapshot, not historical point-in-time data'}
    funnel=[];mask=pd.Series(True,index=audit.index)
    for field in ('PassHistory','PassStage','PassATR','PassDollarVolume','PassRS','PassSector','PassIndustry','PassCapData','PassMarketCap'):
        passed=audit[field].astype('boolean').fillna(False).astype(bool) if field in audit else pd.Series(False,index=audit.index)
        before=int(mask.sum());mask &= passed
        funnel.append({'rule':field,'before':before,'remaining':int(mask.sum()),'removed_here':before-int(mask.sum())})
    summary['funnel']=funnel
    summary['coverage']={'valid_price_histories':len(valid),'known_classifications':len(known),
                         'supplied_cap_rows':len(caps),'valid_cap_snapshots':int(audit['PassCapData'].astype('boolean').fillna(False).astype(bool).sum()) if 'PassCapData' in audit else 0,'price_age_calendar_days':(snapshot_date-asof).days,
                         'benchmark_dates':{t:str(market[t].index.max().date()) if t in market and len(market[t]) else 'Missing' for t in ('SPY','QQQ','IWM')}}
    return {t:market[t] for t in market if t in allowed},audit,summary
