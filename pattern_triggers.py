"""Expose native detector references without changing scores or execution rules."""
import numpy as np


def pattern_trigger_info(detector, df, metadata):
    name=detector.name
    out={'PatternTriggerKind':'Unavailable','PatternTriggerPrice':None,
         'PatternTriggerSource':'No native price trigger exposed',
         'DetectorReferencePrice':None,'DetectorReferenceIncludesSignalBar':False}
    if len(df)<2:return out
    if name in ('Shoryuken','VCP'):
        value=df.LastPivotHigh.iloc[-2] if 'LastPivotHigh' in df else np.nan
        out.update(PatternTriggerPrice=float(value) if np.isfinite(value) else None,
                   PatternTriggerKind='Native prior pivot',PatternTriggerSource='Previous-bar LastPivotHigh used by PivotBreakout')
    elif name=='DTRP':
        out.update(PatternTriggerPrice=metadata.get('range_high'),PatternTriggerKind='Native prior range',PatternTriggerSource='Detector tight-window high; excludes signal bar')
    elif name=='DarvasBox':
        out.update(PatternTriggerPrice=metadata.get('box_top'),PatternTriggerKind='Native box reference',PatternTriggerSource='Detector confirmed box top')
    elif name in ('PocketPivot','EpisodicPivot'):
        out.update(PatternTriggerKind='Event signal',PatternTriggerSource='Volume/price event; no independent price breakout trigger')
    elif name in ('CupHandle','FlatBase','BaseOnBase','HighTightFlag'):
        attribute={'CupHandle':'HANDLE_LENGTH','FlatBase':'BASE_LENGTH','BaseOnBase':'BASE2_LENGTH','HighTightFlag':'FLAG_LOOKBACK'}[name]
        n=getattr(detector,attribute)
        current=float(df.High.iloc[-n:].max())
        prior=float(df.High.iloc[-n-1:-1].max())
        # Preserve and expose the actual detector condition. Several detectors
        # include today in the high, making Close > that high unreachable.
        out.update(DetectorReferencePrice=current*(.98 if name=='FlatBase' else 1),
                   DetectorReferenceIncludesSignalBar=True,
                   PatternTriggerPrice=prior,PatternTriggerKind='Prior-window reporting counterpart',
                   PatternTriggerSource=f'Prior {n}-bar high excluding signal bar; detector current-window reference retained')
    if out['PatternTriggerPrice'] is not None and not np.isfinite(out['PatternTriggerPrice']):out['PatternTriggerPrice']=None
    return out
