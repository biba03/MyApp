"""Compact standalone scan board. Presentation only; original values retained."""
from pathlib import Path
import json
import os
from html import escape
import pandas as pd
from readiness import assess_shoryuken_report
from scan_context import funnel_fields, market_breadth
from market_view import sector_relative_strength
from stock_bubbles import build_stock_bubbles
from leaders import build_leaders


def _ticker_frame(frame, name):
    """Keep empty scan outputs valid; reject malformed populated inputs clearly."""
    out = frame.copy()
    if 'Ticker' not in out:
        if out.index.name == 'Ticker':
            out = out.reset_index()
        elif out.empty:
            out['Ticker'] = pd.Series(index=out.index, dtype='object')
        else:
            raise ValueError(f"{name} must contain a 'Ticker' column or an index named 'Ticker'")
    return out


def _build_scan_payload(method_results, readiness, shoryuken=None):
    def records(frame):
        return json.loads(frame.to_json(orient='records',date_format='iso'))
    method = method_results.copy()
    for column in ("Ticker", "Method"):
        if column not in method:
            method[column] = pd.Series(dtype="object")
    if not readiness.empty:
        extra = [c for c in readiness.columns if c not in method.columns and c not in ('Method','Status')]
        method = method.merge(readiness[['Ticker']+extra],on='Ticker',how='left',validate='many_to_one')
    original = shoryuken.copy() if shoryuken is not None else pd.DataFrame()
    original['Method'] = 'Shoryuken_Scanner'
    method['ScanType'] = 'Method scan'
    original['ScanType'] = 'Shoryuken'
    combined = pd.concat([original,method],ignore_index=True,sort=False)
    data = {'rows':records(combined),'readiness':records(readiness),
            'original_available':shoryuken is not None,
            'watchable_summary':method_results.attrs.get('watchable_summary'),
            'asof':str(method_results.attrs.get('asof','Unknown')),
            'method_counts':{str(m):int(n) for m,n in method.groupby('Method').size().items()}}
    return data


def _static_results(data):
    """Readable results even when the browser blocks or fails JavaScript."""
    parts = ['<section id="static-fallback" style="padding:20px"><h2>Scan Board</h2>',
             '<p>Static results are shown until interactive rendering completes.</p>']
    for title, rows, columns in (
        ('Scan results', data['rows'], ['Ticker','Method','Pattern','Score','FunnelStage','Readiness','TriggerPrice','FunnelReason']),
        ('Market View', data.get('market_view', []), ['Ticker','Name','WeekRSPct','MonthRSPct','RSStatus','DayPct','WeekPct','MonthPct','ThreeMonthPct','SixMonthPct','YearPct','YTDPct','PriceDate','DataStatus']),
    ):
        parts.append('<h3>'+title+'</h3>')
        if not rows:
            parts.append('<p>No results supplied. Run the notebook loading and scan cells, then section 6b.</p>')
            continue
        parts.append('<div style="overflow:auto"><table style="width:100%;border-collapse:collapse"><thead><tr>')
        for column in columns:
            parts.append('<th style="padding:8px;text-align:left">'+escape(column)+'</th>')
        parts.append('</tr></thead><tbody>')
        for row in rows:
            parts.append('<tr>')
            for column in columns:
                value = row.get(column)
                if value is None:
                    text = '—'
                elif column.endswith('Pct') and isinstance(value,(int,float)):
                    text = f'{value:+.2f}%'
                else:
                    text = str(value)
                parts.append('<td style="padding:8px;border-bottom:1px solid #293648">'+escape(text)+'</td>')
            parts.append('</tr>')
        parts.append('</tbody></table></div>')
    if data.get('market_breadth'):
        parts.append('<h3>Stock breadth</h3><pre>'+escape(json.dumps(data['market_breadth'], indent=2))+'</pre>')
    parts.append('</section>')
    return ''.join(parts)


def export_scan_board(method_results, readiness, shoryuken=None, market=None,
                      output='all_scan_results.html', watchable_audit=None, history_dir=None, market_view=None, breadth_market=None, index_memberships=None, market_caps=None, sector_data=None):
    method_results = _ticker_frame(method_results, 'method_results')
    readiness = _ticker_frame(readiness, 'readiness')
    if shoryuken is not None:
        shoryuken = _ticker_frame(shoryuken, 'shoryuken')
        shoryuken = assess_shoryuken_report(
            shoryuken, market or {}, asof=method_results.attrs.get('asof'))
    method_results = method_results.copy()
    for i, row in method_results.iterrows():
        raw = (market or {}).get(row.Ticker)
        if raw is None:
            continue
        df = raw.sort_index().loc[:pd.Timestamp(row.AsOf)].copy()
        if df.empty:
            continue
        if len(df) >= 252:
            high = float(df.High.tail(252).max())
            method_results.loc[i, 'From52WeekHighPct'] = (float(df.Close.iloc[-1])/high-1)*100
        if len(df) >= 171:
            # Same SMA150-based StageAnalyzer as the existing scanner.
            from trend_quality import StageAnalyzer
            df['SMA150'] = df.Close.rolling(150).mean()
            method_results.loc[i, 'Stage'] = StageAnalyzer().evaluate(df).stage
    if watchable_audit is not None and not watchable_audit.empty:
        info = _ticker_frame(watchable_audit, 'watchable_audit').set_index('Ticker')
        for frame in (method_results, shoryuken):
            if frame is not None:
                for field in ('Watchable','ATRPct','MarketCapUSD','MarketCapSnapshotDate','Sector','Industry','SectorRank','IndustryRank','PriceDate','PriceAgeCalendarDays'):
                    if field in info and field not in frame:
                        frame[field] = frame.Ticker.map(info[field])
                if 'RS' in info:
                    frame['WatchableRS'] = frame.Ticker.map(info['RS'])
    path = Path(output)
    data = _build_scan_payload(method_results, readiness, shoryuken)
    leaders_market = breadth_market if breadth_market is not None else market
    data['leaders'] = build_leaders(leaders_market or {},
        asof=None if data['asof'] in ('Unknown', 'None') else data['asof'])
    for row in data['rows']:
        row.update(funnel_fields(row))
    if breadth_market is not None and data['asof'] != 'Unknown':
        data['market_breadth'] = market_breadth(breadth_market, data['asof'])
    if index_memberships is not None and breadth_market is not None:
        data['stock_bubbles'] = build_stock_bubbles(breadth_market, index_memberships, data['asof'],
            audit=watchable_audit, caps=market_caps, sectors=sector_data,
            matched={row['Ticker'] for row in data['rows']})
    data["market_view"] = json.loads(sector_relative_strength(market_view).to_json(orient="records")) if market_view is not None else []
    if history_dir is not None:
        from scan_history import record_scan_snapshot
        data['scan_changes']=record_scan_snapshot(data['rows'],data['asof'],history_dir,
            context={'schema':2,'original_available':data['original_available'],
                     'coverage':method_results.attrs.get('watchable_summary',{}).get('coverage'),
                     'watchable_rules':method_results.attrs.get('watchable_config'),
                     'universe':method_results.attrs.get('discovery_universe')})
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', chr(92) + 'u003c').replace('>', chr(92) + 'u003e').replace('&', chr(92) + 'u0026')
    path.parent.mkdir(parents=True, exist_ok=True)
    page = BOARD.replace('__DATA__', payload).replace('__STATIC_RESULTS__', _static_results(data))
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(page, encoding='utf-8')
    os.replace(temporary, path)
    return path


BOARD = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shoryuken Scan Board</title>
<style>
:root{color-scheme:dark;font-family:Arial,sans-serif;background:#0c0e16;color:#e8edf6}body{margin:0}header{padding:18px 20px;border-bottom:1px solid #292e40;background:#10131d}h1{font-size:20px;margin:0 0 8px}.sub{color:#a3adc0;font-size:12px;line-height:1.5}.tools{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}input,select,button{background:#1c2231;color:#e8edf6;border:1px solid #3b445a;border-radius:5px;padding:8px;font:inherit;font-size:12px}input{min-width:220px}button{cursor:pointer}.board{display:grid;grid-template-columns:repeat(6,minmax(240px,1fr));gap:10px;padding:14px;align-items:start;overflow-x:auto}.column{min-width:0}.cap{border-radius:4px;padding:10px;text-align:center;background:var(--accent);color:#07141b;font-weight:bold;position:sticky;top:0;z-index:2}.cap b{display:block;font-size:18px;margin-bottom:4px}.cap span{font-size:11px}.stocks{padding-top:6px;display:flex;flex-direction:column;gap:5px}.stock{background:#1c2230;border-left:3px solid #526b82;border-radius:3px;padding:9px}.stock.Ready{border-left-color:#19d992}.stock.Breakout{border-left-color:#45b6ff}.stock.Extended{border-left-color:#efaa40}.top{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.ticker{font-size:13px;font-weight:bold;color:white}.change{font-size:11px;font-weight:bold}.up{color:#20d994}.down{color:#ff697a}.badges{display:flex;gap:4px;flex-wrap:wrap;margin-top:7px}.badge{border:1px solid #60718e;border-radius:4px;color:#b7d7ef;font-size:10px;padding:3px 5px;line-height:1.2}.method{border-color:#9765e5;color:#c39afc}.stage{border-color:#3dc7b1;color:#70ddc6}.square{border-radius:2px;border-color:#cfb652;color:#e4cf79}.status{border-color:#4c80bd;color:#93c4ff}.circle{border-radius:50%;min-width:20px;height:20px;display:inline-flex;align-items:center;justify-content:center;padding:1px}.detail{margin-top:8px;color:#aab5c9;font-size:11px}summary{cursor:pointer;color:#a5bad8}.all{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.all .badge{overflow-wrap:anywhere;max-width:100%}.empty{padding:18px;color:#8490a6;font-size:12px;text-align:center}.legend{padding:0 20px 18px;font-size:12px;line-height:1.8;color:#a5b1c5}.warn{color:#e3bc73}a{color:#93c4ff}.count{font-size:12px;color:#a5b1c5;margin-top:10px}@media(max-width:900px){.board{grid-template-columns:repeat(6,260px)}}
[hidden]{display:none!important}.tabs{display:flex;gap:10px;margin:16px 0}.tabs button[aria-pressed="true"]{background:#70b6ee;color:#101827}#market-panel{padding:20px}.market-table{overflow:auto;margin-top:15px}#market-panel table{border-collapse:collapse;width:100%;font-size:13px}#market-panel th,#market-panel td{padding:12px;border-bottom:1px solid #293648;text-align:right;white-space:nowrap}#market-panel th{cursor:pointer;background:#172232}#market-panel td:first-child,#market-panel td:nth-child(2){text-align:left}.positive{color:#33d69f}.negative{color:#ff828e}</style></head><body><div id="render-error" role="alert" style="padding:12px;background:#412934" hidden></div><header><h1>SHORYUKEN · Market Dashboard</h1><nav class="tabs" aria-label="Dashboard views"><button id="scan-tab" aria-pressed="true">Scan Board</button><button id="market-tab" aria-pressed="false">Market View</button><button id="leaders-tab" aria-pressed="false">Leaders</button></nav><div id="scan-header"><div class="sub" id="date"></div><div class="sub warn" id="notice"></div><div class="tools"><input id="search" type="search" placeholder="Search ticker or any information" aria-label="Search"><select id="status" aria-label="Readiness"><option value="">All readiness</option><option>Ready</option><option>Breakout</option><option>Forming</option><option>Extended</option><option>Unavailable</option><option>Signal-qualified</option><option value="unassessed">Not assessed</option></select><select id="funnel" aria-label="Funnel stage"><option value="">All funnel stages</option><option>Watchable</option><option>Tradable</option><option>Actionable</option><option>Outside Watchable</option><option>Not assessed</option></select><select id="sort" aria-label="Sort"><option value="daily">Daily change ↓</option><option value="ticker">Ticker A–Z</option><option value="rank">Readiness rank ↑</option></select><button id="expand">Expand all information</button><button id="csv">Export visible matches</button></div><div class="sub">Funnel: Watchable = gate passed; Tradable = near an existing trigger; Actionable = diagnostic breakout confirmed. Earnings and portfolio controls are not assessed. Stages are reporting labels, not orders.</div><div id="count" class="count"></div></div></header><section id="scan-panel"><details style="margin:12px 20px"><summary>Watchable funnel, coverage and scan changes</summary><div id="audit-summary" class="sub"></div></details><main id="board" class="board"></main>
<div class="legend"><b>Badge key:</b> KQ · Qullamaggie | MM · Minervini Trend Template | SB4 · Stockbee 4% daily | SBW · Stockbee 20% weekly | SB9 · Stockbee 9M mover | SH · original Shoryuken scanner | DB · existing DarvasBox pattern.<br>Square <b>RS~</b> = cross-sectional RS proxy for method screens; square <b>RS</b> = the existing scanner’s RS value. Neither is renamed Relative Trend Strength. <b>52H</b> = signed percentage distance from the trailing 252-session high. <b>S1–S4</b> = existing SMA150-based stage classification; Stage 2A/2B is not inferred. Score is the unchanged final ranking. Rule Coverage is weighted rule completion, not a win probability. PlannedRRPoints reflect a constructed target. Setup metrics exclude the signal day; signal metrics assess that day separately. Each column shows one card per ticker; its header counts unique tickers. Pattern badges summarize all matches. Expand a stock for separate per-pattern scores, stops, targets and every supplied field. CSV exports preserve every pattern row.<br>Readiness is a reporting diagnostic, not trade approval. Missing values are omitted, never treated as zero. TML, 97 Club, earnings countdown and Strike Zone are not invented when absent. Methods and original scan fields retain their existing definitions. Pattern trigger sources are labeled. Native prior pivots/ranges/boxes are distinguished from reporting counterparts. Some legacy detector windows include today in their high, making strict Close > high impossible; their production rules remain unchanged. Event patterns are Signal-qualified, not breakout-confirmed.</div>
</section><section id="market-panel" hidden><h2>Market View</h2><p class="sub">Daily ETF prices · Day: 1 session · Week: 5 · Month: 21 · 3 months: 63 · 6 months: 126 · 1 year: 252. YTD uses the last close before the price-date year. Returns use provider prices; dividend-reinvested total returns are not certified. Missing history displays —.</p><div id="breadth" class="sub"></div><h3>Index Stocks – Performance Bubbles</h3><p class="sub">Price performance, not RS versus SPY. Bubble area scales with market cap, with a minimum visible size; unknown caps use hollow circles. Current membership snapshots are for live reporting, not historical backtests.</p><div class="tools"><label>Index <select id="bubble-index"><option value="SPY">S&amp;P 500</option><option value="QQQ">Nasdaq 100</option><option value="IWM">Russell 2000 (IWM holdings proxy)</option></select></label><label>Universe <select id="bubble-universe"><option value="all">Full index</option><option value="watchable">Watchable</option><option value="matches">Scan Matches</option></select></label><label>X axis <select id="bubble-x"></select></label><label>Y axis <select id="bubble-y"></select></label><label>Sector <select id="bubble-sector"><option value="">Any</option></select></label><label>Industry <select id="bubble-industry"><option value="">Any</option></select></label><label>Min cap <select id="bubble-cap"><option value="">Any</option><option value="500000000">$500M</option><option value="1000000000">$1B</option><option value="10000000000">$10B</option></select></label><label>Min 20D avg volume <select id="bubble-volume"><option value="">Any</option><option value="500000">500K</option><option value="1000000">1M</option></select></label><input id="bubble-search" placeholder="Find ticker" aria-label="Find ticker"><input id="bubble-exclude" placeholder="Exclude tickers, comma separated" aria-label="Exclude tickers"><label><input id="bubble-labels" type="checkbox" style="min-width:0">All labels</label><button id="bubble-reset">Reset filters</button><button id="bubble-export">Export displayed stocks</button></div><p id="bubble-coverage" class="sub"></p><div id="bubble-chart"></div><div id="bubble-legend" class="badges"></div><p id="bubble-detail" class="sub"></p><h3>Market Metrics – Sector Relative Strength</h3><p class="sub">X: month RS (21 sessions) · Y: week RS (5 sessions), versus SPY. RS = change in the sector/SPY price ratio, in %. Positive means outperformance. Both period endpoints must match SPY. This is a relative-return comparison, not a standardized RRG or percentile rank.</p><div id="sector-rs-chart" style="max-width:900px"></div><p id="sector-rs-note" class="sub"></p><button id="market-csv">Export ETF performance</button><div class="market-table"><table><thead id="market-head"></thead><tbody id="market-body"></tbody></table></div></section><section id="leaders-panel" hidden style="padding:20px"><h2>Leaders · EMA100 / EMA200</h2><nav class="tabs" aria-label="Leaders rankings"><button id="leaders-year" aria-pressed="true">Year Mean</button><button id="leaders-emerging" aria-pressed="false">Emerging · 20 sessions</button><button id="leaders-current" aria-pressed="false">High Current Ratio</button></nav><p id="leaders-summary" class="sub"></p><p class="sub">Year Mean: top 20 by the average daily EMA100/EMA200 over 252 sessions. Emerging: top 20 by 20-session ratio change, requiring ratio >1 and positive change. High Current Ratio: all stocks with ratio >1, sorted highest first, including fading stocks. Changes are ratio changes, not stock returns. The graph shows the current top 20 or historical top-20 membership for the active subtab.</p><button id="leaders-csv">Export active list</button><div class="market-table"><table style="width:100%;text-align:left;border-spacing:12px"><thead><tr><th>Rank</th><th>Ticker</th><th id="leaders-score-heading">20-session ratio change (%)</th><th>Year mean ratio</th><th>Current ratio</th><th>5-session change %</th><th>20-session change %</th><th>60-session change %</th><th>Flag</th><th>Close</th></tr></thead><tbody id="leaders-body"></tbody></table></div><h3>Leadership history</h3><label>View <select id="leaders-mode"><option value="current">Today's top 20 · full ratio history</option><option value="historical">Historical top 20 · membership heatmap</option></select></label><p class="sub">X: last 252 cached trading sessions · Y: ticker. Teal → green → yellow → red indicates increasing EMA ratio. Historical mode shows every stock that reached the daily top 20; blank = eligible but outside top 20, gray = unavailable or does not meet the selected view. Current mode plots today's selected stocks even when they were outside the historical top 20.</p><p id="leaders-scale" class="sub"></p><div style="overflow:auto"><canvas id="leaders-heat" role="img" aria-label="Historical EMA leadership heatmap" style="max-width:100%;height:auto"></canvas></div><p id="leaders-hover" class="sub" aria-live="polite">Hover over a cell for ticker, date, ratio, score and rank.</p><details><summary>Excluded stocks / coverage</summary><pre id="leaders-exclusions" style="white-space:pre-wrap"></pre></details></section>__STATIC_RESULTS__<script id="scan-data" type="application/json">__DATA__</script><script>
'use strict';window.addEventListener('error',function(event){const box=document.getElementById('render-error');box.hidden=false;box.textContent='Interactive report could not render: '+event.message+'. Static scan and ETF results are below.';document.getElementById('static-fallback').hidden=false;});const D=JSON.parse(document.getElementById('scan-data').textContent),$=x=>document.getElementById(x);const defs=[['Shoryuken_Scanner','Shoryuken','#70b6ee','SH'],['Qullamaggie_Breakout','Qullamaggie','#ffd500','KQ'],['Minervini_Trend_Template','Minervini','#ffd500','MM'],['Stockbee_9M_Movers','SB 9M Movers','#20c89f','SB9'],['Stockbee_4pct_Daily','SB 4% Daily','#20c89f','SB4'],['Stockbee_20pct_Weekly','SB 20% Weekly','#20c89f','SBW']];let visible=[],expanded=false;const tags={};for(const r of D.rows){if(!tags[r.Ticker])tags[r.Ticker]=new Set();const code=defs.find(d=>d[0]===r.Method)?.[3];if(code)tags[r.Ticker].add(code);if(r.Pattern==='DarvasBox')tags[r.Ticker].add('DB')}
$('date').textContent='Method data as of '+D.asof+' · Standalone offline page · Hover a badge for its definition';$('notice').textContent=D.original_available?'Original and method results included. Original trading fields are preserved; Shoryuken readiness uses per-pattern native levels where available; reporting counterparts and event signals are labeled.':'Original Shoryuken results not supplied. Run its notebook scan and report cells, then regenerate this page.';
if(D.watchable_summary){const w=D.watchable_summary;$('notice').textContent+=' Watchable: '+w.watchable+' / '+w.universe_stocks+' stocks; excluded '+w.excluded+'. Gates: Stage 1–2 proxy, ATR ≥3%, D$V ≥$50M, RS/sector/industry ≥70, cap ≥$500M. Current cap snapshots; audit CSV contains exclusion reasons.';}
const audit=document.getElementById('audit-summary');if(audit){const lines=[];if(D.watchable_summary){const w=D.watchable_summary;lines.push('Coverage: '+JSON.stringify(w.coverage||{}));for(const x of w.funnel||[])lines.push(x.rule+': '+x.before+' → '+x.remaining+' (removed '+x.removed_here+')');}if(D.scan_changes){const h=D.scan_changes;lines.push('Compared with '+(h.previous_data_date||'no prior data-date snapshot')+' · '+h.note);for(const x of h.changes)lines.push(x.Ticker+' / '+x.Method+': '+x.Change+'; '+x.BeforeReadiness.join(', ')+' → '+x.AfterReadiness.join(', '));}for(const line of lines){const p=document.createElement('p');p.textContent=line;audit.append(p)}}
const fmt=v=>typeof v==='number'?v.toLocaleString('en-US',{maximumFractionDigits:2}):String(v);function badge(parent,label,value,cls='',tip=''){if(value==null||value==='')return;const s=document.createElement('span');s.className='badge '+cls;s.textContent=label+(value===true?'':': '+fmt(value));s.title=tip||label+': '+fmt(value);parent.append(s)}
function render(){const query=$('search').value.toLowerCase(),status=$('status').value;visible=D.rows.filter(r=>(!$('funnel').value||r.FunnelStage===$('funnel').value)&&(!query||Object.values(r).some(v=>v!=null&&String(v).toLowerCase().includes(query))||Array.from(tags[r.Ticker]||[]).some(v=>v.toLowerCase().includes(query)))&&(!status||(status==='unassessed'?!r.Readiness:r.Readiness===status)));$('board').replaceChildren();for(const [method,name,color]of defs){const matches=visible.filter(r=>r.Method===method);matches.sort((a,b)=>$('sort').value==='ticker'?String(a.Ticker).localeCompare(String(b.Ticker)):$('sort').value==='rank'?(a.RankWithinStatus??Infinity)-(b.RankWithinStatus??Infinity):(b.DailyPct??-Infinity)-(a.DailyPct??-Infinity));const col=document.createElement('section');col.className='column';const cap=document.createElement('div');cap.className='cap';cap.style.setProperty('--accent',color);const grouped=new Map();for(const row of matches){if(!grouped.has(row.Ticker))grouped.set(row.Ticker,[]);grouped.get(row.Ticker).push(row)}const b=document.createElement('b');b.textContent=grouped.size;b.title=grouped.size+' unique tickers / '+matches.length+' scan matches';const label=document.createElement('span');label.textContent=name;cap.append(b,label);col.append(cap);const stocks=document.createElement('div');stocks.className='stocks';for(const [tickerKey, patternRows] of grouped){const r=patternRows[0];const card=document.createElement('article');card.className='stock '+(r.Readiness||'');const top=document.createElement('div');top.className='top';const ticker=document.createElement('span');ticker.className='ticker';ticker.textContent=r.Ticker;top.append(ticker);if(r.DailyPct!=null){const c=document.createElement('span');c.className='change '+(r.DailyPct>=0?'up':'down');c.textContent=(r.DailyPct>=0?'+':'')+fmt(r.DailyPct)+'%';c.title='Daily price change';top.append(c)}card.append(top);const chips=document.createElement('div');chips.className='badges';for(const tag of tags[r.Ticker]||[])badge(chips,tag,true,'method','Matched method: '+tag);for(const pattern of new Set(patternRows.map(x=>x.Pattern).filter(Boolean)))badge(chips,pattern,true,'method','Detected pattern: '+pattern);if(r.Stage)badge(chips,r.Stage.replace('Stage ','S'),true,'stage','Stage: '+r.Stage+' — existing stage analysis');if(r.RSProxy!=null)badge(chips,'RS~',r.RSProxy,'square','Cross-sectional RS proxy; not official IBD RS or Relative Trend Strength');else if(r.RS!=null)badge(chips,'RS',r.RS,'square','Original scanner relative strength value');if(r.From52WeekHighPct!=null)badge(chips,'52H',fmt(r.From52WeekHighPct)+'%','','Distance from trailing 252-session high');if(r.PriceAgeCalendarDays!=null)badge(chips,'Price age',r.PriceAgeCalendarDays+'d','','Calendar days since last price bar');if(r.MarketCapSnapshotDate)badge(chips,'Market cap updated',r.MarketCapSnapshotDate);for(const kind of new Set(patternRows.map(x=>x.PatternTriggerKind).filter(Boolean)))badge(chips,'Trigger',kind,'',patternRows.filter(x=>x.PatternTriggerKind===kind).map(x=>(x.Pattern||x.Method)+': '+x.PatternTriggerSource).join(' | '));for(const statusValue of new Set(patternRows.map(x=>x.Readiness).filter(Boolean)))badge(chips,statusValue,true,'status',patternRows.filter(x=>x.Readiness===statusValue).map(x=>(x.Pattern||x.Method)+': '+x.ReadinessReasons).join(' | '));if(r.LiquidityCheck&&r.LiquidityCheck!=='Pass')badge(chips,'Liquidity warning',true,'','Below existing liquidity floors; discovery match retained');badge(chips,r.FunnelStage,true,'status',r.FunnelBasis);card.append(chips);const explanation=document.createElement('div');explanation.className='detail';explanation.textContent=(r.TriggerPrice!=null?'Trigger: '+fmt(r.TriggerPrice)+' · ':'')+(r.FunnelReason||'');card.append(explanation);const details=document.createElement('details');details.className='detail';details.open=expanded;const summary=document.createElement('summary');summary.textContent=patternRows.length>1?patternRows.length+' pattern matches · All information':'All information';details.append(summary);for(const result of patternRows){const section=document.createElement('div');const title=document.createElement('strong');title.textContent=result.Pattern||result.Method;section.append(title);const all=document.createElement('div');all.className='all';for(const [k,v]of Object.entries(result))if(v!=null&&v!==''&&k!=='Ticker')badge(all,k==='Confidence'?'RuleCoveragePct (legacy Confidence)':k,v);section.append(all);details.append(section)}card.append(details);stocks.append(card)}if(!matches.length){const e=document.createElement('div');e.className='empty';e.textContent=method==='Shoryuken_Scanner'&&!D.original_available?'Not run':'No matches';stocks.append(e)}col.append(stocks);$('board').append(col)}$('count').textContent=visible.length+' matches · '+new Set(visible.map(r=>r.Ticker)).size+' unique stocks · All matches preserved; one card per ticker per column';}
for(const id of ['search','status','sort'])$(id).addEventListener(id==='search'?'input':'change',render);$('expand').onclick=()=>{expanded=!expanded;$('expand').textContent=expanded?'Collapse information':'Expand all information';render()};$('csv').onclick=()=>{const keys=Array.from(new Set(visible.flatMap(r=>Object.keys(r))));function f(v){let s=v==null?'':String(v);if(typeof v!=='number'&&/^[=+@-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"'}const csv=[keys.map(f).join(','),...visible.map(r=>keys.map(k=>f(r[k])).join(','))].join('\r\n');const u=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download='scan_board_matches.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};render();

const marketColumns=[['Ticker','ETF'],['Name','Market / Sector'],['DayPct','Day'],['WeekPct','Week'],['MonthPct','Month'],['ThreeMonthPct','3 Months'],['SixMonthPct','6 Months'],['YearPct','1 Year'],['YTDPct','YTD'],['WeekRSPct','Week RS vs SPY'],['MonthRSPct','Month RS vs SPY'],['RSStatus','RS status'],['LastClose','Close'],['Source','Source'],['PriceDate','Price Date'],['PriceAgeCalendarDays','Age (days)'],['DataStatus','Data Status']];
let marketSort='WeekPct',marketDesc=true;
function chartZoom(box,svg,width,height){
 const controls=document.createElement('div');controls.className='tools';
 let scale=1,cx=width/2,cy=height/2,drag=null;
 const status=document.createElement('span');status.className='sub';
 function draw(){const w=width/scale,h=height/scale;cx=Math.max(w/2,Math.min(width-w/2,cx));cy=Math.max(h/2,Math.min(height-h/2,cy));svg.setAttribute('viewBox',[cx-w/2,cy-h/2,w,h].join(' '));status.textContent=Math.round(scale*100)+'%';svg.style.cursor=scale>1?'grab':'default'}
 function zoom(factor){scale=Math.max(1,Math.min(8,scale*factor));draw()}
 for(const [label,action]of [['Zoom in',()=>zoom(1.5)],['Zoom out',()=>zoom(1/1.5)],['Reset zoom',()=>{scale=1;cx=width/2;cy=height/2;draw()}]]){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=action;controls.append(b)}
 controls.append(status);const hint=document.createElement('span');hint.className='sub';hint.textContent='Drag to pan when zoomed · Ctrl + wheel to zoom';controls.append(hint);box.append(controls,svg);
 svg.style.touchAction='pan-y';
 svg.addEventListener('wheel',e=>{if(!e.ctrlKey)return;e.preventDefault();zoom(e.deltaY<0?1.2:1/1.2)},{passive:false});
 svg.addEventListener('pointerdown',e=>{if(scale<=1||e.button!==0)return;const rect=svg.getBoundingClientRect();if(!rect.width||!rect.height)return;drag={id:e.pointerId,x:e.clientX,y:e.clientY,cx,cy,moved:false,unit:Math.max(width/scale/rect.width,height/scale/rect.height)};svg.setPointerCapture(e.pointerId);svg.style.touchAction='none';svg.style.cursor='grabbing'});
 svg.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true;cx=drag.cx-dx*drag.unit;cy=drag.cy-dy*drag.unit;draw()});
 let suppressClick=false;
 function end(e){if(!drag||drag.id!==e.pointerId)return;suppressClick=drag.moved;drag=null;svg.style.touchAction='pan-y';draw()}
 svg.addEventListener('pointerup',end);svg.addEventListener('pointercancel',end);
 svg.addEventListener('click',e=>{if(suppressClick){e.stopImmediatePropagation();suppressClick=false}},true);draw();
}
function sectorRSRender(){
 const box=$('sector-rs-chart');box.replaceChildren();const sectors=(D.market_view||[]).filter(r=>r.Group==='Sector');const valid=sectors.filter(r=>Number.isFinite(r.WeekRSPct)&&Number.isFinite(r.MonthRSPct));$('sector-rs-note').textContent=valid.length+' of '+sectors.length+' sectors plotted. Missing or mismatched histories remain visible in the table.';
 if(!valid.length){box.textContent='Aligned sector and SPY history unavailable. Rerun stock loading and regenerate the report.';return}
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 800 460');svg.setAttribute('role','img');svg.setAttribute('aria-label','Sector weekly versus monthly relative returns against SPY');svg.style.width='100%';svg.style.background='#111827';
 function add(tag,attrs,text){const e=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,String(v));if(text!=null)e.textContent=text;svg.append(e);return e}
 const limit=Math.max(1,...valid.flatMap(r=>[Math.abs(r.WeekRSPct),Math.abs(r.MonthRSPct)]))*1.2;const x=v=>400+v/limit*310,y=v=>215-v/limit*165;
 for(const [px,py,w,h,color]of [[90,50,310,165,'#253323'],[400,50,310,165,'#16382e'],[90,215,310,165,'#34202b'],[400,215,310,165,'#3b3021']])add('rect',{x:px,y:py,width:w,height:h,fill:color});
 for(const [v,label]of [[-limit,-limit.toFixed(1)+'%'],[0,'0%'],[limit,limit.toFixed(1)+'%']]){add('text',{x:x(v),y:405,fill:'#b7c5d9','text-anchor':'middle','font-size':12},label);add('text',{x:80,y:y(v)+4,fill:'#b7c5d9','text-anchor':'end','font-size':12},label)}
 add('line',{x1:90,y1:215,x2:710,y2:215,stroke:'#8495ac'});add('line',{x1:400,y1:50,x2:400,y2:380,stroke:'#8495ac'});
 for(const [px,py,text]of [[100,70,'Month lagging / Week leading'],[420,70,'Both leading'],[100,370,'Both lagging'],[420,370,'Month leading / Week lagging']])add('text',{x:px,y:py,fill:'#b7c5d9','font-size':12},text);
 add('text',{x:400,y:440,fill:'white','text-anchor':'middle','font-size':14},'Month RS vs SPY (%)');add('text',{x:90,y:25,fill:'white','font-size':14},'Week RS vs SPY (%)');
 valid.forEach((r,i)=>{const px=x(r.MonthRSPct),py=y(r.WeekRSPct);const dot=add('circle',{cx:px,cy:py,r:6,fill:r.WeekRSPct>=0?'#38dca1':'#ff8294',tabindex:0});const title=document.createElementNS(ns,'title');title.textContent=r.Ticker+' · '+r.Name+' · Week RS '+r.WeekRSPct.toFixed(2)+'% · Month RS '+r.MonthRSPct.toFixed(2)+'% · '+r.PriceDate;dot.append(title);add('text',{x:px+9,y:py+(i%2?14:-8),fill:'white','font-size':12},r.Ticker)});chartZoom(box,svg,800,460);
}
function marketRender(){sectorRSRender();const breadth=D.market_breadth;const box=$('breadth');if(breadth){box.textContent='Stock breadth as of '+breadth.AsOf+' · '+breadth.CurrentCount+'/'+breadth.UniverseCount+' current · '+breadth.StaleCount+' stale · '+breadth.InvalidCount+' invalid. '+Object.entries(breadth.Metrics).map(([k,v])=>k+': '+(v.Pct==null?'—':Number(v.Pct).toFixed(1)+'%')+' ('+v.Count+'/'+v.Eligible+')').join(' · ');box.title=breadth.Basis}else{box.textContent='Stock breadth unavailable: supply the full cached universe.'}const head=$('market-head'),body=$('market-body');head.replaceChildren();body.replaceChildren();const h=document.createElement('tr');for(const [key,label] of marketColumns){const th=document.createElement('th');th.textContent=label+(key===marketSort?(marketDesc?' ↓':' ↑'):'');th.onclick=()=>{marketDesc=key===marketSort?!marketDesc:true;marketSort=key;marketRender()};h.append(th)}head.append(h);const rows=[...(D.market_view||[])].sort((a,b)=>{const x=a[marketSort],y=b[marketSort];if(x==null)return y==null?0:1;if(y==null)return -1;return (typeof x==='number'?x-y:String(x).localeCompare(String(y)))*(marketDesc?-1:1)});for(const r of rows){const tr=document.createElement('tr');for(const [key]of marketColumns){const td=document.createElement('td'),v=r[key];td.textContent=v==null?'—':key.endsWith('Pct')?(v>0?'+':'')+Number(v).toFixed(2)+'%':typeof v==='number'?Number(v).toFixed(key==='LastClose'?2:0):String(v);if(key.endsWith('Pct')&&v!=null)td.className=v>=0?'positive':'negative';if(key==='DataStatus')td.title=(r.Error||r.DownloadNote||'')+' | '+(r.PriceBasis||'')+' | Fetched UTC: '+(r.FetchedUTC||'unknown');tr.append(td)}body.append(tr)}if(!rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=marketColumns.length;td.textContent='No ETF data supplied. Run the stock-loading section, then regenerate this report.';tr.append(td);body.append(tr)}}
function switchTab(market,leaders=false){$('scan-panel').hidden=market||leaders;$('scan-header').hidden=market||leaders;$('market-panel').hidden=!market||leaders;$('leaders-panel').hidden=!leaders;$('scan-tab').setAttribute('aria-pressed',String(!market&&!leaders));$('market-tab').setAttribute('aria-pressed',String(market&&!leaders));$('leaders-tab').setAttribute('aria-pressed',String(leaders))}
$('scan-tab').onclick=()=>switchTab(false);$('market-tab').onclick=()=>switchTab(true);$('leaders-tab').onclick=()=>switchTab(false,true);
$('funnel').onchange=render;
$('market-csv').onclick=()=>{const keys=Array.from(new Set((D.market_view||[]).flatMap(r=>Object.keys(r))));const esc=v=>{let s=v==null?'':String(v);if(typeof v!=='number'&&/^[=+@-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"'};const csv=[keys.map(esc).join(','),...(D.market_view||[]).map(r=>keys.map(k=>esc(r[k])).join(','))].join('\r\n');const u=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download='etf_performance.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};
marketRender();
const bubblePeriods=[['DayPct','1 Day'],['WeekPct','1 Week'],['MonthPct','1 Month'],['ThreeMonthPct','3 Months'],['SixMonthPct','6 Months'],['YearPct','1 Year']];
let bubbleVisible=[];
function bubbleSetup(){
 for(const id of ['bubble-x','bubble-y'])for(const [v,t]of bubblePeriods){const o=document.createElement('option');o.value=v;o.textContent=t;$(id).append(o)}
 $('bubble-x').value='MonthPct';$('bubble-y').value='WeekPct';
 const rows=D.stock_bubbles?.Rows||[];
 for(const [id,key]of [['bubble-sector','Sector'],['bubble-industry','Industry']])for(const v of [...new Set(rows.map(r=>r[key]))].sort()){const o=document.createElement('option');o.value=v;o.textContent=v;$(id).append(o)}
 for(const id of ['bubble-index','bubble-universe','bubble-x','bubble-y','bubble-sector','bubble-industry','bubble-cap','bubble-volume','bubble-search','bubble-exclude','bubble-labels'])$(id).addEventListener('input',bubbleRender);
 $('bubble-reset').onclick=()=>{for(const id of ['bubble-sector','bubble-industry','bubble-cap','bubble-volume','bubble-search','bubble-exclude'])$(id).value='';$('bubble-universe').value='all';bubbleRender()};
 $('bubble-export').onclick=()=>{const keys=['Ticker','Sector','Industry','MarketCapUSD','MarketCapSnapshotDate','AvgVolume20','PriceDate',...bubblePeriods.map(p=>p[0])];const esc=v=>'"'+String(v??'').replaceAll('"','""')+'"';const csv=[keys.join(','),...bubbleVisible.map(r=>keys.map(k=>esc(typeof r[k]==='string'&&/^[=+@-]/.test(r[k])?"'"+r[k]:r[k])).join(','))].join('\r\n');const u=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download='stock_bubbles_'+$('bubble-index').value+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};
 bubbleRender();
}
function bubbleRender(){
 const key=$('bubble-index').value||'SPY',data=D.stock_bubbles,info=data?.Coverage?.[key],box=$('bubble-chart');box.replaceChildren();$('bubble-detail').textContent='Click a bubble for details.';
 const exclusions=new Set($('bubble-exclude').value.toUpperCase().split(/[\s,;]+/).filter(Boolean)),query=$('bubble-search').value.toUpperCase().trim(),xk=$('bubble-x').value,yk=$('bubble-y').value;
 bubbleVisible=(data?.Rows||[]).filter(r=>r.Indexes.includes(key)&&Number.isFinite(r[xk])&&Number.isFinite(r[yk])&&($('bubble-universe').value==='all'||($('bubble-universe').value==='watchable'?r.Watchable:r.ScanMatch))&&(!$('bubble-sector').value||r.Sector===$('bubble-sector').value)&&(!$('bubble-industry').value||r.Industry===$('bubble-industry').value)&&(!$('bubble-cap').value||(r.MarketCapUSD!=null&&r.MarketCapUSD>=Number($('bubble-cap').value)))&&(!$('bubble-volume').value||(r.AvgVolume20!=null&&r.AvgVolume20>=Number($('bubble-volume').value)))&&(!query||r.Ticker.includes(query))&&!exclusions.has(r.Ticker));
 $('bubble-coverage').textContent=info?info.Name+' · Prices as of '+data.AsOf+' · Membership '+info.Status+' · '+info.Members+' members / '+info.Cached+' cached / '+info.Plottable+' usable / '+bubbleVisible.length+' displayed · '+info.MissingCap+' usable stocks missing cap · Snapshot fetched '+(info.FetchedDate||'unknown')+'; effective date '+(info.MembershipDate||'not provided')+' · '+info.Source+(info.Error?' · Refresh error: '+info.Error:''):'Membership unavailable. Run stock loading and regenerate the report.';
 if(!bubbleVisible.length){box.textContent='No stocks available for this index and filter selection. Check membership status, cached price coverage, and filters.';return}
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1100 650');svg.setAttribute('role','img');svg.setAttribute('aria-label',info.Name+' stock performance bubble chart');svg.style.width='100%';svg.style.background='#191e29';
 function add(tag,attrs,text){const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,String(v));if(text!=null)e.textContent=text;svg.append(e);return e}
 const loX=Math.min(0,...bubbleVisible.map(r=>r[xk])),hiX=Math.max(0,...bubbleVisible.map(r=>r[xk])),loY=Math.min(0,...bubbleVisible.map(r=>r[yk])),hiY=Math.max(0,...bubbleVisible.map(r=>r[yk]));
 const padX=Math.max(1,(hiX-loX)*.08),padY=Math.max(1,(hiY-loY)*.08),xmin=loX-padX,xmax=hiX+padX,ymin=loY-padY,ymax=hiY+padY,x=v=>90+(v-xmin)/(xmax-xmin)*940,y=v=>570-(v-ymin)/(ymax-ymin)*510;
 for(let i=0;i<=5;i++){const a=xmin+(xmax-xmin)*i/5,b=ymin+(ymax-ymin)*i/5;add('line',{x1:x(a),y1:60,x2:x(a),y2:570,stroke:'#333b4b'});add('text',{x:x(a),y:595,fill:'#a9b6c9','text-anchor':'middle','font-size':12},a.toFixed(1)+'%');add('line',{x1:90,y1:y(b),x2:1030,y2:y(b),stroke:'#333b4b'});add('text',{x:80,y:y(b)+4,fill:'#a9b6c9','text-anchor':'end','font-size':12},b.toFixed(1)+'%')}
 add('line',{x1:x(0),y1:60,x2:x(0),y2:570,stroke:'#8793aa'});add('line',{x1:90,y1:y(0),x2:1030,y2:y(0),stroke:'#8793aa'});
 const xl=bubblePeriods.find(p=>p[0]===xk)[1],yl=bubblePeriods.find(p=>p[0]===yk)[1];add('text',{x:560,y:630,fill:'white','text-anchor':'middle','font-size':15},xl+' Performance (%)');add('text',{x:90,y:30,fill:'white','font-size':15},yl+' Performance (%)');
 const palette=['#f35764','#ff9b42','#efcb4b','#8fcc4f','#3bd99c','#24c7d9','#5894fa','#a384ff','#cc69ec','#c2b891','#719ca4','#9ca3af'];const sectors=[...new Set((data.Rows||[]).map(r=>r.Sector))].sort();const color=s=>palette[sectors.indexOf(s)%palette.length];
 $('bubble-legend').replaceChildren();for(const sector of [...new Set(bubbleVisible.map(r=>r.Sector))].sort()){const e=document.createElement('span');e.className='badge';e.style.color=color(sector);e.textContent=sector;$('bubble-legend').append(e)}
 const maxCap=Math.max(1,...bubbleVisible.map(r=>r.MarketCapUSD||0));const labelled=new Set([...bubbleVisible].sort((a,b)=>(b.MarketCapUSD||0)-(a.MarketCapUSD||0)).slice(0,30).map(r=>r.Ticker));
 // Draw larger circles first so small caps remain selectable.
 for(const r of [...bubbleVisible].sort((a,b)=>(b.MarketCapUSD||0)-(a.MarketCapUSD||0))){const radius=r.MarketCapUSD?Math.max(2,26*Math.sqrt(r.MarketCapUSD/maxCap)):3;const dot=add('circle',{cx:x(r[xk]),cy:y(r[yk]),r:radius,fill:r.MarketCapUSD?color(r.Sector):'none',stroke:color(r.Sector),'fill-opacity':.65,tabindex:0,role:'button','aria-label':r.Ticker});
 const describe=()=>r.Ticker+' · '+r.Sector+' / '+r.Industry+' · '+xl+' '+r[xk].toFixed(2)+'% · '+yl+' '+r[yk].toFixed(2)+'% · Cap '+(r.MarketCapUSD?'$'+r.MarketCapUSD.toLocaleString('en-US'):'unknown')+' (snapshot '+(r.MarketCapSnapshotDate||'unknown')+') · Avg volume '+(r.AvgVolume20==null?'unknown':r.AvgVolume20.toLocaleString('en-US'))+' · Price '+r.PriceDate;
 const title=document.createElementNS(ns,'title');title.textContent=describe();dot.append(title);dot.style.cursor='pointer';dot.onclick=()=>{$('bubble-detail').textContent=describe()};dot.onkeydown=e=>{if(e.key==='Enter'||e.key===' ')dot.onclick()};
 if($('bubble-labels').checked||labelled.has(r.Ticker))add('text',{x:x(r[xk])+radius+3,y:y(r[yk])+3,fill:'#e8edf6','font-size':10,'pointer-events':'none'},r.Ticker);
 }chartZoom(box,svg,1100,650);
}
bubbleSetup();

let leadersRanking='year';
function leadersRender(){
 const root=D.leaders||{},data=root.Modes?.[leadersRanking]||root,top=data.Top||[],body=$('leaders-body');body.replaceChildren();$('leaders-score-heading').textContent=data.ScoreLabel||'252-session mean EMA ratio';
 $('leaders-summary').textContent='As of '+(data.AsOf||'unavailable')+' · '+(data.UniverseCount||0)+' cached stock symbols · '+(data.EligibleCount||0)+' eligible · '+top.length+' selected · '+(data.CalendarBasis||'')+'. '+(data.Basis||'');
 for(const r of top){const tr=document.createElement('tr');for(const k of ['Rank','Ticker','Score','AverageRatio','CurrentRatio','Change5Pct','Change20Pct','Change60Pct','Flag','Close']){const td=document.createElement('td');td.textContent=r[k]==null?'—':typeof r[k]==='number'?r[k].toFixed(k==='Rank'?0:k==='Close'?2:4):r[k];tr.append(td)}body.append(tr)}
 if(!top.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=10;td.textContent='No eligible stocks. No stocks meet this view. Year Mean needs at least 451 consecutive sessions, Emerging 220, and High Current Ratio 200. Check exclusions below.';tr.append(td);body.append(tr)}
 $('leaders-exclusions').textContent=Object.entries(data.Exclusions||{}).map(([k,v])=>k+': '+v).join('\n')||'None';
 const historical=$('leaders-mode').value==='historical',rows=(data.HeatRows||[]).filter(r=>historical||r.Current),dates=data.Dates||[],canvas=$('leaders-heat');
 const left=85,right=20,plotWidth=1000,rowHeight=24,topY=32,height=Math.max(120,topY+rows.length*rowHeight+45);canvas.width=left+plotWidth+right;canvas.height=height;
 const ctx=canvas.getContext('2d');ctx.fillStyle='#111827';ctx.fillRect(0,0,canvas.width,height);ctx.font='12px Arial';
 let low=Infinity,high=-Infinity;for(const r of rows)for(let i=0;i<dates.length;i++){const v=r.Ratios[i];if(Number.isFinite(v)&&(!historical||(r.Ranks[i]!=null&&r.Ranks[i]<=20))){low=Math.min(low,v);high=Math.max(high,v)}}
 function color(v){const limits=[.9,1,1.2,1.3],stops=[[69,165,190],[139,255,116],[239,239,65],[226,45,28]];let j=0;while(j<2&&v>limits[j+1])j++;const a=Math.max(0,Math.min(1,(v-limits[j])/(limits[j+1]-limits[j])));return 'rgb('+stops[j].map((x,k)=>Math.round(x+(stops[j+1][k]-x)*a)).join(',')+')'}
 $('leaders-scale').textContent='Fixed ratio colors: ≤0.90 teal · 1.00 green · 1.20 yellow · ≥1.30 red. '+rows.length+' rows. Values between thresholds blend; hover for exact values.';
 rows.forEach((r,y)=>{ctx.fillStyle='#e8edf6';ctx.fillText(r.Ticker,5,topY+y*rowHeight+16);for(let i=0;i<dates.length;i++){const v=r.Ratios[i],rank=r.Ranks[i],missing=!Number.isFinite(v)||(historical&&rank==null);ctx.fillStyle=missing?'#354052':historical&&rank>20?'#111827':color(v);ctx.fillRect(left+i*plotWidth/dates.length,topY+y*rowHeight,plotWidth/dates.length+.2,rowHeight-2)}});
 ctx.fillStyle='#b7c5d9';if(dates.length){for(const fraction of [0,.25,.5,.75,1]){const i=Math.round((dates.length-1)*fraction);ctx.fillText(dates[i],left+fraction*(plotWidth-75),height-15)}}
 canvas.onmousemove=e=>{const rect=canvas.getBoundingClientRect(),x=(e.clientX-rect.left)*canvas.width/rect.width,y=(e.clientY-rect.top)*canvas.height/rect.height,i=Math.floor((x-left)/plotWidth*dates.length),j=Math.floor((y-topY)/rowHeight);if(i<0||i>=dates.length||j<0||j>=rows.length)return;const r=rows[j],rank=r.Ranks[i],ratio=r.Ratios[i],score=r.Scores[i];$('leaders-hover').textContent=r.Ticker+' · '+dates[i]+' · Ratio '+(ratio==null?'unavailable':ratio.toFixed(4))+' · Score '+(score==null?'unavailable':score.toFixed(4))+' · Rank '+(rank==null?'unavailable':rank)+(historical&&rank>20?' · outside top 20':'')};
}
$('leaders-mode').onchange=leadersRender;for(const key of ['year','emerging','current'])$('leaders-'+key).onclick=()=>{leadersRanking=key;for(const k of ['year','emerging','current'])$('leaders-'+k).setAttribute('aria-pressed',String(k===key));leadersRender()};
$('leaders-csv').onclick=()=>{const keys=['Rank','Ticker','Score','AverageRatio','CurrentRatio','Change5Pct','Change20Pct','Change60Pct','Flag','Close'];const esc=v=>'"'+String(v??'').replaceAll('"','""')+'"';const csv=[keys.join(','),...((D.leaders?.Modes?.[leadersRanking]||D.leaders)?.Top||[]).map(r=>keys.map(k=>esc(typeof r[k]==='string'&&/^[=+@-]/.test(r[k])?"'"+r[k]:r[k])).join(','))].join('\r\n');const u=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download='leaders_'+leadersRanking+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};
leadersRender();

document.getElementById('static-fallback').hidden=true;

</script></body></html>'''
