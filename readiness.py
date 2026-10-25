"""Reporting-only readiness diagnostics. No screening or execution rules change."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from method_scans import summarize_tags


@dataclass(frozen=True)
class ReadinessConfig:
    ready_distance_pct: float = 3.0
    extended_distance_pct: float = 5.0
    extended_atr: float = 0.5
    breakout_rvol: float = 1.0
    max_base_width: float = 0.20
    base_lengths: tuple = (10, 20, 30, 40)
    min_price: float = 10.0
    min_avg_volume: float = 500_000.0
    min_avg_dollar_volume: float = 20_000_000.0


def _base(df, n):
    b = df.iloc[-n-1:-1]
    if len(b) != n:
        return None
    first, second = b.iloc[:n//2], b.iloc[n//2:]
    width = float(b.High.max()/b.Low.min()-1)
    contraction = float((second.High.max()-second.Low.min()) / max(first.High.max()-first.Low.min(), 1e-12))
    return b, width, contraction, bool(second.Low.min() > first.Low.min())


def readiness_report(results, market, cfg=None):
    """One row per matched ticker. Thresholds are diagnostic defaults, not buy rules.

    Existing Qullamaggie triggers take precedence; other methods need a qualifying
    prior base proxy. Missing bases never produce an invented entry trigger.
    """
    cfg = cfg or ReadinessConfig()
    tags = summarize_tags(results)
    rows = []
    for _, tag in tags.iterrows():
        row = tag.to_dict()
        row.update(Readiness='Unavailable', TriggerPrice=np.nan, TriggerSource='',
                   DistanceToTriggerPct=np.nan, ExtensionATR=np.nan, ATR14=np.nan,
                   InvalidationLevel=np.nan, RiskToInvalidationPct=np.nan,
                   VolumeDryUpRatio=np.nan, LiquidityCheck='Unavailable',
                   TradeEligibility='Not assessed', ReadinessReasons='')
        date = pd.Timestamp(tag.AsOf)
        raw = market.get(tag.Ticker)
        if raw is None:
            row['ReadinessReasons'] = 'Missing price data'; rows.append(row); continue
        df = raw.sort_index().loc[:date, ['Open','High','Low','Close','Volume']].copy()
        values = df.to_numpy(dtype=float)
        if len(df) < 21 or df.index[-1] != date or not np.isfinite(values).all() or (df[['Open','High','Low','Close']] <= 0).any().any() or (df.Volume < 0).any():
            row['ReadinessReasons'] = 'Insufficient, stale, or invalid price data'; rows.append(row); continue
        close = float(df.Close.iloc[-1])
        tr = pd.concat([df.High-df.Low, (df.High-df.Close.shift()).abs(), (df.Low-df.Close.shift()).abs()],axis=1).max(axis=1)
        atr = float(tr.ewm(alpha=1/14,adjust=False).mean().iloc[-1])
        row['ATR14'] = atr
        prior_volume = float(df.Volume.iloc[-21:-1].mean())
        rvol = float(df.Volume.iloc[-1]/prior_volume) if prior_volume else np.nan
        row['RVOL20'] = rvol
        row['VolumeDryUpRatio'] = float(df.Volume.iloc[-6:-1].mean()/prior_volume) if prior_volume else np.nan
        liquid = close >= cfg.min_price and df.Volume.tail(20).mean() >= cfg.min_avg_volume and (df.Close*df.Volume).tail(20).mean() >= cfg.min_avg_dollar_volume
        row['LiquidityCheck'] = 'Pass' if liquid else 'Below existing liquidity floors'
        selected = None
        original = results.loc[(results.Ticker==tag.Ticker) & (results.Method=='Qullamaggie_Breakout')]
        # Momentum candidates supply no confirmed base/trigger. Use the existing
        # generic reporting proxy instead of converting missing BaseDays to int.
        if not original.empty and 'Status' in original:
            original = original.loc[original['Status'].ne('Momentum candidate')]
        if not original.empty:
            q = original.iloc[0]
            selected = _base(df, int(q.BaseDays))
            trigger = float(q.BreakoutLevel)
            source = 'Qullamaggie scan base'
        else:
            for n in cfg.base_lengths:
                candidate = _base(df, n)
                if candidate and candidate[1] <= cfg.max_base_width and candidate[2] <= 1 and candidate[3]:
                    selected = candidate; break
            trigger = float(selected[0].High.max()) if selected else np.nan
            source = 'Prior contracting base proxy' if selected else ''
        reasons = []
        if not liquid:
            reasons.append('Below existing liquidity floors; discovery match retained')
        if selected is None:
            row['Readiness'] = 'Forming'; reasons.append('No qualifying prior contracting base; trigger unavailable')
        else:
            b, width, contraction, higher = selected
            invalidation = float(b.Low.min())
            distance = (close/trigger-1)*100
            extension = (close-trigger)/atr if atr > 0 else np.nan
            row.update(TriggerPrice=trigger, TriggerSource=source, DistanceToTriggerPct=distance,
                       ExtensionATR=extension, InvalidationLevel=invalidation,
                       RiskToInvalidationPct=(close-invalidation)/close*100,
                       ReadinessBaseDays=len(b), ReadinessBaseWidthPct=width*100,
                       ContractionRatio=contraction, HigherLows=higher)
            if close < invalidation:
                status = 'Forming'; reasons.append('Price below base invalidation reference')
            elif distance > cfg.extended_distance_pct or extension > cfg.extended_atr:
                status = 'Extended'; reasons.append('Above diagnostic distance or ATR extension limit')
            elif distance > 0 and np.isfinite(rvol) and rvol >= cfg.breakout_rvol:
                status = 'Breakout'; reasons.append('Close above prior trigger with volume confirmation')
            elif distance > 0:
                status = 'Forming'; reasons.append('Above trigger without volume confirmation')
            elif distance >= -cfg.ready_distance_pct:
                status = 'Ready'; reasons.append('Within diagnostic distance below prior trigger; breakout not confirmed')
            else:
                status = 'Forming'; reasons.append('Below diagnostic ready zone')
            row['Readiness'] = status
        reasons.append('Trade eligibility, earnings, sector and portfolio controls not assessed')
        row['ReadinessReasons'] = '; '.join(reasons)
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=list(tags.columns)+['Readiness','RankWithinStatus','ReadinessReasons'])
    out = pd.DataFrame(rows)
    order = {'Ready':0,'Breakout':1,'Forming':2,'Extended':3,'Unavailable':4}
    out['_status'] = out.Readiness.map(order)
    out['_distance'] = out.DistanceToTriggerPct.abs().fillna(np.inf)
    out = out.sort_values(['_status','_distance','Ticker'],kind='stable').drop(columns=['_status','_distance']).reset_index(drop=True)
    out['RankWithinStatus'] = out.groupby('Readiness',sort=False).cumcount()+1
    return out


def assess_shoryuken_report(report, market, asof=None, cfg=None):
    """Reporting proxy only: detector Entry is current close, not a breakout level.

    Preserve every original pattern row and trading field. Assess a prior-base
    proxy per ticker, explicitly identifying its source; never reinterpret Entry.
    """
    cfg = cfg or ReadinessConfig()
    out = report.copy(deep=True)
    if out.empty:
        return out
    if 'Ticker' not in out.columns:
        raise ValueError('Shoryuken report must contain Ticker')
    if asof is None:
        dates = [df.index.max() for df in market.values() if not df.empty]
        if not dates:
            out['Readiness'] = 'Unavailable'
            out['ReadinessReasons'] = 'No market data available'
            return out
        asof = max(dates)
    asof = pd.Timestamp(asof)
    discovery = []
    for ticker in out.Ticker.unique():
        raw = market.get(ticker)
        df = raw.sort_index().loc[:asof] if raw is not None else None
        close = float(df.Close.iloc[-1]) if df is not None and not df.empty else np.nan
        discovery.append(dict(AsOf=str(asof.date()),Ticker=ticker,
                              Method='Shoryuken_Scanner',Status='Pattern qualified',
                              Close=close,DailyPct=np.nan,WeeklyPct=np.nan,Volume=np.nan))
    diagnostic = readiness_report(pd.DataFrame(discovery), market, cfg)
    diagnostic = diagnostic.set_index('Ticker')
    fields = ['Readiness','TriggerPrice','TriggerSource','DistanceToTriggerPct',
              'ExtensionATR','ATR14','InvalidationLevel','RiskToInvalidationPct',
              'VolumeDryUpRatio','LiquidityCheck','TradeEligibility','ReadinessReasons',
              'RVOL20']
    for field in fields:
        out[field] = out.Ticker.map(diagnostic[field]) if field in diagnostic else np.nan
    out['ReadinessBasis'] = 'Prior-base reporting proxy; detector Entry is current close'
    for i, row in out.iterrows():
        kind = row.get('PatternTriggerKind')
        if kind == 'Event signal':
            out.loc[i,'Readiness'] = 'Signal-qualified'
            out.loc[i,'ReadinessBasis'] = 'Detected event; not a price-breakout classification'
            out.loc[i,'TriggerPrice'] = np.nan
            out.loc[i,'TriggerSource'] = row.get('PatternTriggerSource')
            out.loc[i,'DistanceToTriggerPct'] = np.nan
            out.loc[i,'ExtensionATR'] = np.nan
            out.loc[i,'InvalidationLevel'] = np.nan
            out.loc[i,'RiskToInvalidationPct'] = np.nan
            out.loc[i,'ReadinessReasons'] = 'Original detector qualified an event signal; no price trigger inferred; trade eligibility not assessed'
            continue
        trigger = pd.to_numeric(row.get('PatternTriggerPrice'), errors='coerce')
        raw = market.get(row.Ticker)
        if raw is None or not np.isfinite(trigger) or trigger <= 0:
            continue
        df = raw.sort_index().loc[:asof]
        if len(df)<21 or df.index[-1]!=asof:
            continue
        close = float(df.Close.iloc[-1]);atr = out.loc[i,'ATR14'];rvol=out.loc[i,'RVOL20']
        distance=(close/trigger-1)*100
        extension=(close-trigger)/atr if pd.notna(atr) and atr>0 else np.nan
        if distance>cfg.extended_distance_pct or extension>cfg.extended_atr:status='Extended'
        elif distance>0 and pd.notna(rvol) and rvol>=cfg.breakout_rvol:status='Breakout'
        elif distance>0:status='Forming'
        elif distance>=-cfg.ready_distance_pct:status='Ready'
        else:status='Forming'
        source=row.get('PatternTriggerSource') or str(kind)
        out.loc[i,'Readiness']=status
        out.loc[i,'TriggerPrice']=trigger
        out.loc[i,'TriggerSource']=source
        out.loc[i,'DistanceToTriggerPct']=distance
        out.loc[i,'ExtensionATR']=extension
        out.loc[i,'ReadinessBasis']=kind
        # A generic base low cannot be attached to a different pattern trigger.
        out.loc[i,'InvalidationLevel']=np.nan
        out.loc[i,'RiskToInvalidationPct']=np.nan
        out.loc[i,'ReadinessReasons']=f'{status}: {source}; distance {distance:.2f}%; RVOL {rvol:.2f}; existing Stop and Target retained; trade eligibility not assessed'

    out['ReadinessAsOf'] = str(asof.date())
    out['ReadinessReasons'] = out.ReadinessReasons.fillna('Missing diagnostic data') + '; Entry, Stop and Target preserved'
    return out
