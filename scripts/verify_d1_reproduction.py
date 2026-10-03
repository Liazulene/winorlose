"""Regenerate the first predesignated full game of each budget, at one worker.

Verification only: generated records are compared in memory, never added as
new formal observations and never overwrite any saved game.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from winai_loseai.experiments.d1 import jobs,cells,play_one,strip_timing,atomic_json,experiment_lock

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--dest',required=True);args=ap.parse_args()
    locked=experiment_lock();plan=jobs();cc=cells();seen=set();results=[];start=time.perf_counter()
    for j,c in zip(plan,cc):
        if c['budget'] in seen:continue
        seen.add(c['budget']);t=time.perf_counter();fresh=play_one(j)
        saved=json.loads((Path(args.out)/'games'/f"{fresh['game_id']}.json").read_text())
        same=strip_timing(fresh)==strip_timing(saved)
        results.append({'game_id':fresh['game_id'],'budget':c['budget'],'game_index':j['index'],'matches_except_timing':same,'wall_seconds':time.perf_counter()-t})
        print(json.dumps(results[-1]),flush=True)
    result={'experiment_lock':locked,'predesignated_selection':'Lowest game_index in each budget, one worker; supplementary index-based verification planned during execution','results':results,'wall_seconds':time.perf_counter()-start,
        'problems':[] if all(r['matches_except_timing'] for r in results) else ['regeneration mismatch'],
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    atomic_json(args.dest,result);return bool(result['problems'])
if __name__=='__main__':raise SystemExit(main())
