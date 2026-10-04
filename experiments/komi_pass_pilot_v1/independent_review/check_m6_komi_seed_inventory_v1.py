"""Independent, stdlib-only historical seed-isolation audit. Executes no games."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
OLD_NAMES=('winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1',
           'winorlose_g1_pass8_v1','winorlose_g1_pass8_estimation_v1')
EXPECTED_NAMES={'batch_A_seed0','batch_B_shallow_seed0','batch_B_shallow_seed1','d0_g0_v1_seed0',
                'd1_g0_cost_v1','d1_g0_estimation_v1','g1_pass8_pilot_v1','g1_pass8_estimation_v1','smoke_random','smoke_mcts'}

def seed_hash(*parts):
    raw='|'.join(map(str,parts)).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:16],'big')

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def object_hash(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def run():
    current_seeds={seed_hash('game-seed',batch,idx) for batch in (14,15,16) for idx in range(8)}
    current_streams={seed_hash('agent-stream',seed_hash('game-seed',batch,i*2+o),color,pair[c])
                     for batch in (14,15,16) for i in range(4) for o,pair in enumerate(((1,2),(2,1)))
                     for c,color in enumerate(('black','white'))}
    # Additional conservative superset guards either orientation assigned to a block.
    conservative_streams={seed_hash('agent-stream',seed,color,agent)
                          for seed in current_seeds for color in ('black','white') for agent in (1,2)}
    historical_seeds=set();historical_streams=set();names=set();batch_labels=set();inventory=[];problems=[]
    for old_name in OLD_NAMES:
        old=ROOT.parent/old_name
        for seed_path in sorted((old/'outputs').glob('*/game_seeds.json')):
            d=seed_path.parent;names.add(d.name)
            seed_rows=json.loads(seed_path.read_text())
            seeds={row['game_seed'] for row in seed_rows}
            plan=d/'plan.json';manifest=d/'manifest.json'
            mf=json.loads(manifest.read_text())
            label=mf.get('batch_seed')
            if isinstance(label,int):batch_labels.add(label)
            elif isinstance(label,list):batch_labels.update(label)
            sources={str(seed_path.relative_to(old)):digest(seed_path),str(manifest.relative_to(old)):digest(manifest)}
            if plan.exists():
                jobs=json.loads(plan.read_text());sources[str(plan.relative_to(old))]=digest(plan);origin='plan.json'
            else:
                paths=sorted((d/'games').glob('*.json'));jobs=[json.loads(p.read_text()) for p in paths]
                sources.update({str(p.relative_to(old)):digest(p) for p in paths});origin='complete game JSONs because plan absent'
            streams={seed_hash('agent-stream',job['game_seed'],color,job[color]['seed']) for job in jobs for color in ('black','white')}
            if len(jobs)!=len(seed_rows) or {job['game_seed'] for job in jobs}!=seeds:
                problems.append('inventory seed/job mismatch '+str(d))
            overlaps={'game_seeds':sorted(current_seeds&seeds),'actual_streams':sorted(current_streams&streams),
                      'conservative_streams':sorted(conservative_streams&streams)}
            if any(overlaps.values()):problems.append('new-versus-historical overlap '+str(d))
            inventory.append({'worktree':old_name,'dataset':d.name,'rows':len(jobs),'distinct_seeds':len(seeds),
                              'distinct_streams':len(streams),'origin':origin,'source_file_count':len(sources),
                              'source_inventory_sha256':object_hash(sources),'overlap':overlaps,
                              'key_source_sha256':{k:v for k,v in sources.items() if '/games/' not in k}})
            historical_seeds.update(seeds);historical_streams.update(streams)
    if names!=EXPECTED_NAMES:problems.append('historical dataset-name coverage mismatch')
    if batch_labels != set(range(14)):problems.append('expected historical batch seed labels 0 through13')
    if len(current_seeds)!=24 or len(current_streams)!=48 or len(conservative_streams)!=96:problems.append('candidate cardinality mismatch')
    return {'purpose':'Independent prelaunch all-history seed audit, no gameplay or historical writes.',
            'utc':datetime.now(timezone.utc).isoformat(),'passed':not problems,'problems':problems,
            'candidate_batch_seeds':[14,15,16],'candidate_blocks':24,'candidate_actual_derived_streams':48,
            'candidate_conservative_derived_streams':96,'candidate_seed_sha256':object_hash(sorted(current_seeds)),
            'candidate_actual_stream_sha256':object_hash(sorted(current_streams)),
            'historical_worktrees':list(OLD_NAMES),'historical_output_directories':len(inventory),
            'historical_dataset_names':sorted(names),'historical_batch_seed_labels':sorted(batch_labels),
            'historical_distinct_seeds':len(historical_seeds),'historical_distinct_streams':len(historical_streams),
            'historical_record_rows_including_duplicate_worktree_copies':sum(x['rows'] for x in inventory),
            'comparisons':inventory,'checker_sha256':digest(Path(__file__)),
            'limitations':['Seed hashes establish collision/isolation checks, not statistical independence.',
                          'Four arms deliberately share block seeds and initial color/agent streams; subsequent RNG consumption can diverge.',
                          'Historical copies and deliberate old within-experiment pairing are deduplicated for unique counts.',
                          'This candidate check assumes block_index=identity_index*2+orientation_index; implemented schedule is audited separately.']}

if __name__=='__main__':
    result=run();out=Path(sys.argv[1]);
    if out.exists():raise SystemExit('Refusing existing output')
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='comparisons'},indent=2));raise SystemExit(int(bool(result['problems'])))
