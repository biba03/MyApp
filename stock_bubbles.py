"""Reporting-only stock bubble data using full cached price histories."""
import numpy as np
import pandas as pd


def build_stock_bubbles(market, memberships, asof, audit=None, caps=None, sectors=None, matched=()):
    def text(value, default=None):
        return str(value) if value is not None and pd.notna(value) and str(value) else default
    date = pd.Timestamp(asof).normalize()
    audit_map = audit.set_index('Ticker').to_dict('index') if audit is not None and not audit.empty else {}
    cap_map = caps.set_index('Ticker').to_dict('index') if caps is not None and not caps.empty else {}
    sector_map = sectors.set_index('ticker').to_dict('index') if sectors is not None and not sectors.empty else {}
    members = {k:set(v.get('Tickers',[])) for k,v in memberships.items()}
    wanted = set().union(*members.values()) if members else set()
    matched = set(matched);rows=[];excluded={}
    for ticker in sorted(wanted):
        raw = market.get(ticker)
        if raw is None or raw.empty or 'Close' not in raw:
            excluded[ticker]='No cached prices';continue
        df=raw.sort_index()
        index=pd.to_datetime(df.index)
        if index.tz is not None:index=index.tz_localize(None)
        df=df.copy();df.index=index;df=df.loc[~df.index.duplicated(keep='last')].loc[:date]
        if df.empty or df.index[-1].normalize()!=date:
            excluded[ticker]='Stale prices';continue
        close=pd.to_numeric(df.Close,errors='coerce').tail(253)
        if len(close)<22 or not (np.isfinite(close.tail(22)) & close.tail(22).gt(0)).all():
            excluded[ticker]='Insufficient or invalid prices';continue
        meta=audit_map.get(ticker,{});cap=cap_map.get(ticker,{});group=sector_map.get(ticker,{})
        value=pd.to_numeric(cap.get('MarketCapUSD',meta.get('MarketCapUSD')),errors='coerce')
        volume=pd.to_numeric(df.Volume.tail(20),errors='coerce') if 'Volume' in df else pd.Series(dtype=float)
        avg=float(volume.mean()) if len(volume)==20 and (np.isfinite(volume)&volume.ge(0)).all() else None
        returns={}
        for name,n in [('DayPct',1),('WeekPct',5),('MonthPct',21),('ThreeMonthPct',63),('SixMonthPct',126),('YearPct',252)]:
            window=close.tail(n+1)
            returns[name]=float((close.iloc[-1]/close.iloc[-n-1]-1)*100) if len(window)==n+1 and (np.isfinite(window)&window.gt(0)).all() else None
        rows.append(dict(Ticker=ticker,Indexes=[k for k,s in members.items() if ticker in s],PriceDate=date.date().isoformat(),
                         Close=float(close.iloc[-1]),Sector=text(group.get('sector'), text(meta.get('Sector'), 'Unknown')),
                         Industry=text(group.get('industry'), text(meta.get('Industry'), 'Unknown')),
                         MarketCapUSD=float(value) if pd.notna(value) and np.isfinite(value) and value>0 else None,
                         MarketCapSnapshotDate=text(cap.get('SnapshotDate'), text(meta.get('MarketCapSnapshotDate'))),
                         AvgVolume20=avg,Watchable=meta.get('Watchable') is True,ScanMatch=ticker in matched,**returns))
    coverage={k:dict(Name=v.get('Name',k),Source=v.get('Source'),Status=v.get('Status'),Error=v.get('Error'),
                    FetchedDate=v.get('FetchedDate'),MembershipDate=v.get('MembershipDate'),Members=len(members[k]),
                    Cached=sum(t in market for t in members[k]),Plottable=sum(k in r['Indexes'] for r in rows),
                    MissingCap=sum(k in r['Indexes'] and r['MarketCapUSD'] is None for r in rows)) for k,v in memberships.items()}
    return {'AsOf':date.date().isoformat(),'Rows':rows,'Coverage':coverage,'Excluded':excluded}
