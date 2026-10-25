"""Local atomic snapshots and comparison with prior data-date scan."""
from pathlib import Path
import json
import os
import tempfile


def record_scan_snapshot(rows, asof, folder, context=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    day=str(asof)[:10]
    if len(day)!=10 or any(c not in '0123456789-' for c in day):raise ValueError('Snapshot requires ISO data date')
    target=folder/(day+'.json')
    earlier=sorted(p for p in folder.glob('????-??-??.json') if p.name<target.name)
    previous=json.loads(earlier[-1].read_text()) if earlier else None
    def grouped(items):
        groups={}
        for row in items:
            key=(row.get('Method'),row.get('Ticker'))
            groups.setdefault(key,[]).append(row)
        return groups
    current=grouped(rows);old=grouped(previous['rows']) if previous else {}
    changes=[]
    if previous:
        for key in sorted(set(current)|set(old),key=str):
            now=current.get(key,[]);before=old.get(key,[])
            patterns=lambda rs:sorted(set(r.get('Pattern') or '' for r in rs))
            status=lambda rs:sorted(set(r.get('Readiness') or 'Not assessed' for r in rs))
            if not before:change='New match'
            elif not now:change='No longer matched'
            elif patterns(now)!=patterns(before):change='Pattern matches changed'
            elif status(now)!=status(before):change='Readiness changed'
            else:continue
            changes.append({'Method':key[0],'Ticker':key[1],'Change':change,
                            'BeforePatterns':patterns(before),'AfterPatterns':patterns(now),
                            'BeforeReadiness':status(before),'AfterReadiness':status(now)})
    snapshot={'asof':day,'rows':rows,'context':context or {}}
    fd,temp=tempfile.mkstemp(prefix='.scan-',suffix='.tmp',dir=folder)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(snapshot,stream,ensure_ascii=False,allow_nan=False)
        os.replace(temp,target)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    comparable=previous is not None and previous.get('context',{})==snapshot['context']
    return {'current_data_date':day,'previous_data_date':previous.get('asof') if previous else None,
            'context_comparable':comparable,'note':('Scan context unchanged' if comparable else 'First snapshot or changed scan context; disappearing matches can reflect coverage/universe changes'),
            'changes':changes}
