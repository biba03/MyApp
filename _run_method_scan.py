"""Offline method scan using a read-only SQLite connection."""
from pathlib import Path
import argparse, json, sqlite3, time
import pandas as pd
from readiness import readiness_report
from watchable import watchable_universe, refresh_market_caps
from method_scans import scan_methods, summarize_tags, MethodScanConfig, METHODS


def load_cached_market(db, asof=None):
    db=Path(db).resolve()
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as conn:
        latest=conn.execute('SELECT MAX(date) FROM prices').fetchone()[0]
        date=str(pd.Timestamp(asof or latest).date())
        # Preserve the full available historical dataset; never write to cache.
        frame=pd.read_sql_query('SELECT ticker,date,open,high,low,close,volume FROM prices WHERE date<=? ORDER BY ticker,date',conn,params=(date,))
    frame['date']=pd.to_datetime(frame['date'])
    market={}
    for tk,part in frame.groupby('ticker',sort=True):
        part=part.drop(columns='ticker').set_index('date')
        part.columns=['Open','High','Low','Close','Volume'];market[tk]=part
    return market,date


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',default=str(Path(__file__).resolve().parent/'cache/market_data.db'))
    p.add_argument('--asof');p.add_argument('--output',default='exports/method_scans');p.add_argument('--min-price',type=float,default=0)
    p.add_argument('--min-adv',type=float,default=0)
    p.add_argument('--caps',default=str(Path.home()/'Documents/Shoryuken_reports/market_caps.csv'))
    p.add_argument('--refresh-caps',action='store_true');a=p.parse_args()
    start=time.perf_counter(); market,date=load_cached_market(a.db,a.asof)
    if a.asof:
        raise ValueError('Watchable runner uses current cap snapshots; historical runs require point-in-time metadata.')
    if a.refresh_caps:
        refresh_market_caps(set(market)-{'SPY','QQQ','IWM'},a.caps)
    if not Path(a.caps).exists():
        raise FileNotFoundError('Missing market-cap CSV. Run with --refresh-caps or supply --caps with dated metadata.')
    watchable,audit,summary=watchable_universe(market,pd.read_csv(a.caps),Path(__file__).resolve().parent/'data/sector_industry.csv',date)
    results=scan_methods(market,date,MethodScanConfig(min_price=a.min_price,min_avg_dollar_volume=a.min_adv),candidate_tickers=set(watchable))
    results.attrs['watchable_summary']=summary
    output=Path(a.output);output.mkdir(parents=True,exist_ok=True)
    audit.to_csv(output/'watchable_audit.csv',index=False)
    results.to_csv(output/'method_results.csv',index=False);summarize_tags(results).to_csv(output/'ticker_tags.csv',index=False)
    readiness = readiness_report(results, market)
    readiness.to_csv(output/'readiness_report.csv',index=False)
    for status, group in readiness.groupby('Readiness',sort=False):
        group.to_csv(output/('readiness_'+status.lower()+'.csv'),index=False)
    for method in METHODS: results.loc[results.Method==method].to_csv(output/(method+'.csv'),index=False)
    meta=dict(results.attrs);meta['elapsed_seconds']=time.perf_counter()-start
    meta['readiness_counts'] = readiness.Readiness.value_counts().to_dict()
    meta['counts']={method:int((results.Method==method).sum()) for method in METHODS}
    (output/'scan_metadata.json').write_text(json.dumps(meta,indent=2))
    print(json.dumps({'asof':date,'counts':meta['counts'],'eligible_tickers':meta['eligible_tickers'],'elapsed_seconds':meta['elapsed_seconds']},indent=2))
if __name__=='__main__':main()
