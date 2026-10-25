"""Transparent score accounting and timing-correct diagnostics, not a new model."""
import numpy as np
import pandas as pd
import config


def ranking_breakdown(result):
    """Use unrounded RankedStock values and the existing production weights."""
    w=config.RANKING_WEIGHTS
    inputs={'quality':result.quality,'confidence':result.confidence*100,
            'rr':min(result.rr,4)/4*100,
            'rs':result.rs_rating if result.rs_rating is not None else 50.,
            'sector':result.sector_rank if result.sector_rank is not None else 50.,
            'liquidity':result.liquidity_score if result.liquidity_score is not None else 50.,
            'regime':result.regime_score if result.regime_score is not None else 50.}
    labels={'quality':'QualityPoints','confidence':'RuleCoveragePoints','rr':'PlannedRRPoints',
            'rs':'RSPoints','sector':'SectorPoints','liquidity':'LiquidityPoints','regime':'RegimePoints'}
    out={labels[k]:float(v*w.get(k,0)) for k,v in inputs.items()}
    out['ScoreBreakdownTotal']=sum(out.values())
    out['ScoreBreakdownResidual']=result.score-out['ScoreBreakdownTotal']
    out['ScoreBasis']='Existing production ranking; breakdown uses current default weights'
    out['NeutralFallbacks']=' | '.join(k for k,v in [('RS',result.rs_rating),('Sector',result.sector_rank),('Liquidity',result.liquidity_score),('Regime',result.regime_score)] if v is None)
    metadata=result.metadata or {}
    out['DetectorRawScore']=metadata.get('score',np.nan)
    out['DetectorMaxScore']=metadata.get('max_score',np.nan)
    out['RuleCoveragePct']=result.confidence*100
    out['RulesPassed']=' | '.join(metadata.get('passed',[]))
    out['RulesFailed']=' | '.join(metadata.get('failed',[]))
    return out


def timing_diagnostics(raw, asof=None):
    """Pre-signal diagnostics exclude the signal day and every future bar.

    Prior20High is a diagnostic reference, never a pattern-specific trigger.
    No composite score or research claim is generated.
    """
    if raw is None or raw.empty:return {'ScoreDiagnosticsStatus':'Unavailable: no price data'}
    df=raw.sort_index().loc[:pd.Timestamp(asof)] if asof is not None else raw.sort_index()
    if len(df)<22:return {'ScoreDiagnosticsStatus':'Unavailable: need 22 bars'}
    if asof is not None and df.index[-1]!=pd.Timestamp(asof):
        return {'ScoreDiagnosticsStatus':'Unavailable: stale prices'}
    values=df[['High','Low','Close','Volume']].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:,:3]<=0).any() or (values[:,3]<0).any():
        return {'ScoreDiagnosticsStatus':'Unavailable: invalid prices/volume'}
    tr=pd.concat([df.High-df.Low,(df.High-df.Close.shift()).abs(),(df.Low-df.Close.shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False).mean()
    prior=df.iloc[:-1];ranges=prior.High-prior.Low
    range_mean=ranges.rolling(10).mean();volume_mean=float(prior.Volume.tail(20).mean())
    prior_high=float(prior.High.tail(20).max());last=df.iloc[-1]
    denom=float(last.High-last.Low)
    return {'ScoreDiagnosticsStatus':'Available; reporting only',
            'DiagnosticsAsOf':str(df.index[-1].date()),
            'SetupATRCompressionPct':(1-float(atr.iloc[-2]/atr.iloc[-12]))*100 if atr.iloc[-12]>0 else np.nan,
            'SetupRangeCompressionPct':(1-float(range_mean.iloc[-1]/range_mean.iloc[-11]))*100 if range_mean.iloc[-11]>0 else np.nan,
            'SetupVolumeDryUpRatio':float(prior.Volume.tail(5).mean()/volume_mean) if volume_mean>0 else np.nan,
            'SignalRVOLPrior20':float(last.Volume/volume_mean) if volume_mean>0 else np.nan,
            'SignalCloseLocationPct':float((last.Close-last.Low)/denom*100) if denom>0 else np.nan,
            'Prior20HighReference':prior_high,
            'SignalDistancePriorHighPct':float((last.Close/prior_high-1)*100),
            'DiagnosticBasis':'Setup excludes signal day; prior high is generic reference, not detector trigger'}
