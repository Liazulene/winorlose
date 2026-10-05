"""Read-only exact M6 regression or M7 regeneration with create-only evidence.

Historical selection is the lowest index per M6 arm and seed14/15/16 plus
all observed draws, deduplicated. Final M7 uses lowest index per arm and
seed17/18/19. No saved source is rewritten and sample increment is zero.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.experiments import komi_pass_estimation as g
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


def select_rows(rows,seeds,include_draws=False):
    """Preregistered index-based selection, with all historical draw probes."""
    selected={}
    for pass_min,komi in g.arms():
        for seed in seeds:
            eligible=[r for r in rows if (r['pass_min_ply'],r['komi'],r['batch_seed'])==(pass_min,komi,seed)]
            row=min(eligible,key=lambda r:r['game_index'])
            selected[row['game_id']]=row
    if include_draws:
        for row in rows:
            if row['winner']=='draw':selected[row['game_id']]=row
    return sorted(selected.values(),key=lambda r:r['game_index'])


def reproduce(mode,dest):
    dest=g.assert_output_allowed(dest)
    if dest.exists():raise FileExistsError('Evidence path must be new; never overwrite an attempt')
    start=time.perf_counter();locked=g.experiment_lock()
    if mode=='historical':
        out=ROOT.parent/'winorlose_komi_pass_pilot_v1/outputs/komi_pass_pilot_v1'
        rows=json.loads((out/'analysis.json').read_text(encoding='utf-8'))['rows']
        seeds=[14,15,16];excluded={'search_time_ms','game_wall_ms','code_version','source_fingerprint'}
    elif mode=='estimation':
        out=ROOT/'outputs/komi_pass_estimation_v1'
        checked=g.validate(out)
        if checked['problems'] or not checked['complete'] or checked['manifest_status']!='completed':
            raise ValueError('Full validated 960-game sample is required')
        rows=json.loads((out/'analysis.json').read_text(encoding='utf-8'))['rows']
        seeds=[17,18,19];excluded={'search_time_ms','game_wall_ms'}
    else:raise ValueError('unknown reproduction mode')
    selected=select_rows(rows,seeds,include_draws=mode=='historical')
    inputs={str(path.relative_to(out)):g.sha256(path) for path in (out/'analysis.json',*(out/'games'/(r['game_id']+'.json') for r in selected))}
    checks=[]
    for row in selected:
        path=out/'games'/(row['game_id']+'.json');saved=json.loads(path.read_text(encoding='utf-8'));before=g.sha256(path)
        job={'index':saved['game_index'],'batch_id':saved['batch_id'],'game_seed':saved['game_seed'],
            'black':AgentSpec.from_dict(saved['black']),'white':AgentSpec.from_dict(saved['white']),
            'pass_min_ply':saved['pass_min_ply'],'komi':saved['komi']}
        regenerated=play_one(job,board_size=saved['board_size'])
        equal=exact(canonical(saved,excluded),canonical(regenerated,excluded))
        check={'game_id':saved['game_id'],'batch_seed':row['batch_seed'],'pass_min_ply':saved['pass_min_ply'],'komi':saved['komi'],
            'winner':saved['winner'],'move_count':saved['move_count'],'exact_except_excluded':equal,
            'original_sha256':before,'original_unchanged':before==g.sha256(path)}
        checks.append(check);print(json.dumps(check),flush=True)
        if not equal:break
    result={'mode':mode,'source':str(out),'planned_regenerations':len(selected),'regenerations':len(checks),'sample_increment':0,
        'selection_rule':'lowest game index per arm and batch seed, plus all historical observed draws, deduplicated' if mode=='historical' else 'lowest game index per arm and batch seed',
        'selected_game_ids':[r['game_id'] for r in selected],'excluded_fields':sorted(excluded),'checks':checks,
        'passed':len(checks)==len(selected) and all(c['exact_except_excluded'] and c['original_unchanged'] for c in checks),
        'source_inputs_sha256':inputs,'all_inputs_unchanged':all(g.sha256(out/key)==value for key,value in inputs.items()),
        'source_lock_unchanged':locked==g.experiment_lock(),'experiment_lock':locked,
        'elapsed_seconds':time.perf_counter()-start,'completed_utc':datetime.now(timezone.utc).isoformat()}
    result['passed']=result['passed'] and result['all_inputs_unchanged'] and result['source_lock_unchanged']
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2));return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode',choices=['historical','estimation']);ap.add_argument('--evidence',required=True)
    args=ap.parse_args();return int(not reproduce(args.mode,args.evidence)['passed'])

if __name__=='__main__':raise SystemExit(main())
