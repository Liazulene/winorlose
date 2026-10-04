"""Read-only saved-game regeneration, with isolated create-only evidence.

Historical six games prove komi2.5 behavioral regression under new code.
Final twelve games verify exact pilot regeneration; neither changes sample n.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.experiments import komi_pass_pilot as g
from winai_loseai.league.runner import play_one
from winai_loseai.spec import AgentSpec

def canonical(value,excluded):
    if isinstance(value,dict):return {str(k):canonical(v,excluded) for k,v in value.items() if k not in excluded}
    if isinstance(value,list):return [canonical(v,excluded) for v in value]
    return value

def exact(left,right):
    if type(left) is not type(right):return False
    if isinstance(left,dict):return left.keys()==right.keys() and all(exact(left[k],right[k]) for k in left)
    if isinstance(left,list):return len(left)==len(right) and all(exact(x,y) for x,y in zip(left,right))
    return left==right

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['historical','pilot']);ap.add_argument('--evidence',required=True);args=ap.parse_args()
    dest=g.assert_output_allowed(args.evidence)
    if dest.exists():raise FileExistsError('Evidence path must be new; never overwrite an attempt')
    dest.parent.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter();locked=g.experiment_lock()
    if args.mode=='historical':
        out=ROOT.parent/'winorlose_g1_pass8_estimation_v1/outputs/g1_pass8_estimation_v1'
        analysis=json.loads((out/'analysis.json').read_text());rows=analysis['rows'];seeds=[11,12,13];arms=[(0,2.5),(8,2.5)]
        excluded={'search_time_ms','game_wall_ms','code_version','source_fingerprint'}
    else:
        out=ROOT/'outputs/komi_pass_pilot_v1'
        checked=g.validate(out)
        if checked['problems'] or not checked['complete'] or checked['manifest_status']!='completed':raise ValueError('Full validated 96-game sample is required')
        rows=json.loads((out/'analysis.json').read_text())['rows'];seeds=[14,15,16];arms=g.arms()
        excluded={'search_time_ms','game_wall_ms'}
    selected=[]
    for pass_min,komi in arms:
        for seed in seeds:
            eligible=[r for r in rows if r['pass_min_ply']==pass_min and r.get('komi',2.5)==komi and r['batch_seed']==seed]
            selected.append(min(eligible,key=lambda r:r['game_index']))
    checks=[]
    for row in selected:
        path=out/'games'/(row['game_id']+'.json');saved=json.loads(path.read_text());before=g.sha256(path)
        job={'index':saved['game_index'],'batch_id':saved['batch_id'],'game_seed':saved['game_seed'],
            'black':AgentSpec.from_dict(saved['black']),'white':AgentSpec.from_dict(saved['white']),
            'pass_min_ply':saved['pass_min_ply'],'komi':saved['komi']}
        regenerated=play_one(job,board_size=saved['board_size'])
        equal=exact(canonical(saved,excluded),canonical(regenerated,excluded))
        check={'game_id':saved['game_id'],'batch_seed':row['batch_seed'],'pass_min_ply':saved['pass_min_ply'],'komi':saved['komi'],
            'exact_except_excluded':equal,'original_sha256':before,'original_unchanged':before==g.sha256(path)}
        checks.append(check);print(json.dumps(check),flush=True)
        if not equal:break
    result={'mode':args.mode,'source':str(out),'planned_regenerations':len(selected),'regenerations':len(checks),'sample_increment':0,
        'excluded_fields':sorted(excluded),'checks':checks,'passed':len(checks)==len(selected) and all(c['exact_except_excluded'] and c['original_unchanged'] for c in checks),
        'source_lock_unchanged':locked==g.experiment_lock(),'elapsed_seconds':time.perf_counter()-start,'completed_utc':datetime.now(timezone.utc).isoformat()}
    with dest.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2));return 0 if result['passed'] and result['source_lock_unchanged'] else 1
if __name__=='__main__':raise SystemExit(main())
