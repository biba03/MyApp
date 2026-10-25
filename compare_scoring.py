"""Fixed-candidate OOS ranking comparison. Requires saved canonical research artifact.

Replays existing trades only: cannot validate newly admitted candidate signals.
No threshold fitting, bootstrap changes, RNG calls or historical scan relaunch.
"""
from pathlib import Path
from copy import deepcopy
from dataclasses import replace,asdict
import argparse,hashlib,json,pickle
import numpy as np
import pandas as pd
from _run_method_scan import load_cached_market
from indicators import compute_all
from patterns.shoryuken import Shoryuken
from experimental_scoring import PreBreakoutShoryuken


def compare_saved_candidates(artifact_path, db, sector_path, output, folds=None):
    artifact_path=Path(artifact_path).resolve();db=Path(db).resolve();output=Path(output).resolve()
    if not artifact_path.exists():raise FileNotFoundError('Canonical candidate_trades.pkl missing; provide the original saved research artifact. No new research scan will be launched.')
    if output==artifact_path.parent or output in artifact_path.parents:raise ValueError('Output must be outside canonical artifact directory')
    from research.validation import make_folds
    from backtest import PortfolioSimulator,PerformanceStats,_apply_regime_gate,_classify_regime
    from sector_data import SectorIndustryMap
    before=hashlib.file_digest(artifact_path.open('rb'),'sha256').hexdigest()
    # Load only an artifact you trust from your own research run.
    with artifact_path.open('rb') as stream:art=pickle.load(stream)
    trades=art['trades'];cfg=art['config'];benchmark=art.get('benchmark_close')
    if benchmark is None and (cfg.block_entry_regimes or cfg.regime_position_scale):raise ValueError('Saved benchmark required to preserve regime risk controls')
    market,_=load_cached_market(db);close={t:df.Close for t,df in market.items()};sm=SectorIndustryMap(sector_path)
    baseline=np.array([t.score for t in trades],dtype=float);candidate=baseline.copy();details=[]
    cache={}
    for i,t in enumerate(trades):
        if t.pattern!='Shoryuken':continue
        key=(t.ticker,str(t.signal_date))
        if key not in cache:
            raw=market.get(t.ticker)
            if raw is None:raise ValueError(f'Missing original price history: {key}')
            window=raw.loc[:pd.Timestamp(t.signal_date)].iloc[-cfg.indicator_window:].copy()
            if window.empty or window.index[-1]!=pd.Timestamp(t.signal_date):raise ValueError(f'Missing signal date: {key}')
            compute_all(window,lite=cfg.lite_indicators)
            old=Shoryuken().detect(window);new=PreBreakoutShoryuken().detect(window)
            # A changed cache/implementation must not silently masquerade as
            # the exact baseline artifact used in the original experiment.
            if abs(old.score-t.score)>1e-8:raise ValueError(f'Baseline score does not match saved artifact: {key}')
            cache[key]=(old,new)
        old,new=cache[key];candidate[i]=new.score
        details.append(dict(trade_index=i,ticker=t.ticker,signal_date=str(t.signal_date),baseline_score=old.score,candidate_score=new.score,candidate_detected=new.detected,net_return=t.net_return))
    entry=pd.Series([pd.Timestamp(t.entry_date) for t in trades])
    # Reuse stored folds if present, otherwise the existing research default.
    boundaries=folds or art.get('folds') or make_folds(entry,3)
    rows=[]
    for number,(start,train_end,test_end) in enumerate(boundaries,1):
        test=(entry>pd.Timestamp(train_end))&(entry<=pd.Timestamp(test_end))
        indexes=np.flatnonzero(test.to_numpy());foldcfg=replace(cfg,start_date=pd.Timestamp(train_end).normalize()+pd.Timedelta(days=1),end_date=pd.Timestamp(test_end).normalize(),show_progress=False)
        for name,scores in [('baseline',baseline),('candidate',candidate)]:
            copies=deepcopy([trades[j] for j in indexes])
            for trade,j in zip(copies,indexes):trade.score=float(scores[j])
            # Candidate rescoring keeps EVERY original candidate and entry/exit;
            # candidate_detected is audited, not used as a new entry gate.
            copies=_apply_regime_gate(copies,benchmark,foldcfg.block_entry_regimes)
            regimes=_classify_regime(benchmark) if benchmark is not None and foldcfg.regime_position_scale else None
            curve,accepted,daily,ps=PortfolioSimulator(foldcfg,sm).run(copies,close,regimes)
            stats=PerformanceStats.from_trades_and_curve(accepted,curve,foldcfg.initial_capital,ps)
            rows.append(dict(fold=number,variant=name,test_start=str(pd.Timestamp(train_end).normalize()+pd.Timedelta(days=1)),test_end=str(test_end),candidate_count=len(indexes),taken=len(accepted),**stats))
    output.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(rows).to_csv(output/'fold_comparison.csv',index=False)
    pd.DataFrame(details).to_csv(output/'shoryuken_rescoring.csv',index=False)
    summary={'status':'Fixed-candidate ranking comparison only; not a production promotion decision',
             'limitation':'Does not evaluate new signals admitted by the candidate or changed candidate thresholds; no production weights changed',
             'artifact_sha256':before,'trade_count':len(trades),'rescored_shoryuken_trades':len(details),
             'folds':[[str(x) for x in f] for f in boundaries],'original_config':asdict(cfg),
             'rng_used':False,'bootstrap_samples_changed':False}
    if hashlib.file_digest(artifact_path.open('rb'),'sha256').hexdigest()!=before:raise AssertionError('Canonical artifact changed')
    (output/'comparison_summary.json').write_text(json.dumps(summary,default=str,indent=2))
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--artifact',required=True);p.add_argument('--db',required=True);p.add_argument('--sector-map',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(compare_saved_candidates(a.artifact,a.db,a.sector_map,a.output),indent=2,default=str))
if __name__=='__main__':main()
