"""Opt-in candidate only. Never enabled in Scanner or BacktestEngine by default."""
from patterns.shoryuken import Shoryuken
from score_diagnostics import timing_diagnostics
import config


class PreBreakoutShoryuken(Shoryuken):
    """Same rules/weights/threshold: shift only contraction and dry-up timing."""
    name='Shoryuken'
    def detect(self,df):
        work=df.copy(deep=True)
        diagnostic=timing_diagnostics(df)
        if 'SetupATRCompressionPct' not in diagnostic:
            raise ValueError('Candidate needs valid pre-signal history')
        last=work.index[-1]
        work.loc[last,'ATRCompression']=diagnostic['SetupATRCompressionPct']/100
        work.loc[last,'RangeCompression']=diagnostic['SetupRangeCompressionPct']/100
        work.loc[last,'IsDryUp']=diagnostic['SetupVolumeDryUpRatio']<config.VOLUME_DRYUP_THRESHOLD
        result=super().detect(work)
        result.metadata['experimental_variant']='Pre-breakout compression + prior5/prior20 volume dry-up'
        return result
