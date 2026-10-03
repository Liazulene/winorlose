"""Recompute selected saved games in memory, never rewriting their run."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.league.runner import run_jobs
from winai_loseai.league.runstore import entry_to_job


def semantic(value):
    if isinstance(value,dict):
        return {str(k):semantic(v) for k,v in value.items()
                if k not in ('search_time_ms','game_wall_ms')}
    if isinstance(value,list):return [semantic(v) for v in value]
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('indexes',nargs='+',type=int)
    p.add_argument('--concurrency',type=int,default=2);a=p.parse_args()
    out=Path(a.run)
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    plan=json.loads((out/'plan.json').read_text(encoding='utf-8'))
    jobs=[entry_to_job(plan[i],manifest['batch_id']) for i in a.indexes]
    results=run_jobs(jobs,concurrency=a.concurrency,board_size=manifest['board_size'],komi=manifest['komi'])
    checks=[]
    for rec in results:
        path=out/'games'/(rec['game_id']+'.json')
        original=json.loads(path.read_text(encoding='utf-8'))
        checks.append({'game_id':rec['game_id'],'equal_except_timing':semantic(rec)==semantic(original),
                       'original_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    result={'run':a.run,'concurrency':a.concurrency,'checks':checks,
            'excluded_fields':['search_time_ms','game_wall_ms']}
    target=ROOT/'reports/validation'/(out.name+'_reproducibility.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    raise SystemExit(not all(c['equal_except_timing'] for c in checks))
