"""Read-only independent prospective seed and historical stream audit.
No package RNG helpers or game generation are imported. New writes: report only.
"""
from collections import Counter
import datetime,hashlib,json,pathlib
HERE=pathlib.Path(__file__).resolve().parent
BASE=HERE.parents[3]
ROOTS=['winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1','winorlose_g1_pass8_v1']
REQUIRED={'batch_A_seed0','batch_B_shallow_seed0','batch_B_shallow_seed1','smoke_mcts','smoke_random','d0_g0_v1_seed0','d1_g0_cost_v1','d1_g0_estimation_v1','g1_pass8_pilot_v1'}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def seed(*parts):return int.from_bytes(hashlib.sha256('|'.join(map(str,parts)).encode()).digest()[:16],'big')
def main():
    game_seeds={seed('game-seed',batch,index) for batch in (11,12,13) for index in range(80)}
    # Conservative superset avoids relying on the final orientation-index formula.
    streams={seed('agent-stream',gs,color,individual) for gs in game_seeds for color in ('black','white') for individual in (1,2)}
    errors=[]; comparisons=[]; found=set(); all_old_seeds=set();all_old_streams=set()
    for name in ROOTS:
        root=BASE/name
        for sp in sorted(root.glob('outputs/**/game_seeds.json')):
            folder=sp.parent;found.add(folder.name);seed_rows=json.loads(sp.read_text());old_seeds={r['game_seed'] for r in seed_rows}
            sources={str(sp):digest(sp)};plan=folder/'plan.json'
            if plan.exists():
                jobs=json.loads(plan.read_text());sources[str(plan)]=digest(plan);origin='plan.json'
            else:
                paths=sorted((folder/'games').glob('*.json'));jobs=[json.loads(p.read_text()) for p in paths];sources.update({str(p):digest(p) for p in paths});origin='complete game JSONs'
            if Counter(r['game_seed'] for r in seed_rows)!=Counter(j['game_seed'] for j in jobs):errors.append(f'{folder}: game seed multiset mismatch')
            old_streams={seed('agent-stream',j['game_seed'],color,j[color]['seed']) for j in jobs for color in ('black','white')}
            overlap=sorted(game_seeds&old_seeds);stream_overlap=sorted(streams&old_streams)
            if overlap or stream_overlap:errors.append(f'{folder}: new/historical RNG collision')
            all_old_seeds|=old_seeds;all_old_streams|=old_streams
            comparisons.append({'worktree':name,'directory':str(folder),'records':len(jobs),'seed_source':origin,'distinct_seeds':len(old_seeds),'distinct_derived_streams':len(old_streams),'game_seed_overlap':overlap,'conservative_derived_stream_overlap':stream_overlap,'source_sha256':sources})
    if REQUIRED-found:errors.append(f'Missing mandatory historical datasets: {sorted(REQUIRED-found)}')
    result={'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'purpose':'Independent prospective seed11/12/13, block0..79 isolation before formal games','new_batch_seeds':[11,12,13],'new_block_indexes_per_seed':[0,79],'new_distinct_game_seeds':len(game_seeds),'new_stream_candidate_superset_count':len(streams),'historical_worktrees':ROOTS,'historical_directories':len(comparisons),'historical_unique_dataset_names':sorted(found),'historical_distinct_game_seeds':len(all_old_seeds),'historical_distinct_derived_streams':len(all_old_streams),'comparisons':comparisons,'script_sha256':digest(pathlib.Path(__file__)),'problems':errors,'limitations':['Hashes check collision/isolation, not statistical independence.','The stream test conservatively checks both agent seeds1/2 for each colour and block; the actual formal plan must use a subset of these960 candidate streams.','Paired arms reuse initial stream seeds; random-number consumption diverges.','Historical duplicated copies across worktrees and deliberate historical budget/rule pairing are allowed.']}
    (HERE/'resume20261004_seed_isolation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='comparisons'},indent=2));return bool(errors)
if __name__=='__main__':raise SystemExit(main())
