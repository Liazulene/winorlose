"""Read-only final independent fixed-design audit; produces new JSON evidence."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
from itertools import permutations
import json
from pathlib import Path
import random
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.experiments import komi_pass_pilot as pilot
from winai_loseai.league.runstore import job_to_entry


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def seed_hash(*parts):return int.from_bytes(hashlib.sha256('|'.join(map(str,parts)).encode()).digest()[:16],'big')

def run():
    p=pilot.protocol();actual=[job_to_entry(j) for j in pilot.jobs()]
    plan_path=ROOT/'experiments/komi_pass_pilot_v1/frozen_plan.json';frozen=json.loads(plan_path.read_text())
    blocks=[(s,i,o) for s in (14,15,16) for i in range(4) for o in range(2)]
    arms=((0,2.5),(8,2.5),(0,0.0),(8,0.0));identities=(('WIN','WIN'),('LOSE','LOSE'),('WIN','LOSE'),('LOSE','WIN'))
    scheduler=random.Random(2026100403);scheduler.shuffle(blocks)
    orders=list(permutations(arms));scheduler.shuffle(orders)
    problems=[];expected=[];strata=Counter();positions=Counter()
    for block_idx,((seed,i,o),order) in enumerate(zip(blocks,orders)):
        sb,sw=((1,2),(2,1))[o];ib,iw=identities[i]
        for pos,(rule,komi) in enumerate(order):
            spec=lambda identity,aseed:{'agent_id':f'{identity}-medium-s{aseed}','identity':identity,'algorithm':'vector_mcts','compute_level':'medium','seed':aseed}
            expected.append({'index':block_idx*4+pos,'game_seed':seed_hash('game-seed',seed,i*2+o),
                'black':spec(ib,sb),'white':spec(iw,sw),'pass_min_ply':rule,'komi':komi})
            strata[(seed,ib,iw,rule,komi)]+=1;positions[(rule,komi,pos)]+=1
    if expected!=actual:problems.append('production plan differs from independent reconstruction')
    if frozen!=expected:problems.append('frozen plan differs from independent reconstruction')
    if len(expected)!=96 or len(strata)!=48 or set(strata.values())!={2}:problems.append('fixed strata mismatch')
    if set(positions.values())!={6}:problems.append('position balance mismatch')
    new_output=ROOT/'outputs/komi_pass_pilot_v1'
    existing=len(list((new_output/'games').glob('*.json'))) if new_output.exists() else 0
    if existing:problems.append('prelaunch design review occurred after pilot games existed')
    scope=ROOT/'experiments/komi_pass_pilot_v1/independent_review'
    log=(scope/'independent_tests_final_v1.txt').read_text()
    if '134 passed' not in log or 'failed' in log.lower():problems.append('independent tests did not fully pass')
    seed=json.loads((scope/'seed_inventory_before_v1.json').read_text())
    lineage=json.loads((scope/'preservation_lineage_v1.json').read_text())
    if not seed['passed'] or not lineage['passed']:problems.append('seed/preservation prerequisite failed')
    source_lock=ROOT/'experiments/komi_pass_pilot_v1/pre_execution_source_lock.json'
    if json.loads(source_lock.read_text())!=pilot.source_lock():problems.append('pre-execution source lock differs')
    paths=[pilot.PROTOCOL,plan_path,source_lock,ROOT/'src/winai_loseai/experiments/komi_pass_pilot.py',
           ROOT/'scripts/verify_komi_pass_reproduction.py',scope/'test_m6_komi_independent_design_v1.py',
           scope/'independent_tests_final_v1.txt']
    return {'utc':datetime.now(timezone.utc).isoformat(),'passed':not problems,'problems':problems,
       'purpose':'Independent fixed design, seed, draw, preservation boundary and regression-harness review; no sampled experiment games generated.',
       'pilot_games_at_review':existing,'planned_games':96,'four_arm_blocks':24,'blocks_per_identity_direction':6,
       'arm_games':24,'arm_by_direction_games':6,'seed_by_arm_by_direction_games':2,
       'all24_arm_permutations_used_once':len(set(orders))==24,'each_arm_in_each_position':6,
       'checkpoints':{'games':24,'complete_blocks':6,'games_per_arm':6,'seed_direction_position_balance_within_checkpoint':'not guaranteed'},
       'distinct_game_seeds':24,'distinct_actual_color_agent_streams':48,
       'historical_isolation':{k:seed[k] for k in ('historical_worktrees','historical_output_directories','historical_dataset_names','historical_batch_seed_labels','historical_distinct_seeds','historical_distinct_streams')},
       'draw_semantics':'Exact zero margin is draw; each utility0; neither identity goal succeeds; denominators retain draws; mixed joint goal counted once.',
       'paired_contrasts':'komi0-minus2.5 atp0/p8; pass8-minus0 atk2.5/k0; interaction komi contrast atp8 minusatp0; never across identity.',
       'extra_delta':'pass contrast extra=raw-8; komi contrasts and interaction extra=raw.',
       'original_formal_game_count':15600,'M5_fixed_estimation_games':480,'M5_base_commit':p['parent_commit'],
       'historical_regression_indices':{'pass0_seed11_12_13':[0,5,13],'pass8_seed11_12_13':[1,4,12]},
       'regeneration_exclusions':{'historical':['code_version','source_fingerprint','game_wall_ms','search_time_ms'],'pilot':['game_wall_ms','search_time_ms']},
       'independent_tests':{'passed':134,'seconds':0.62,'artifact':'independent_tests_final_v1.txt','initial_run':'122 passed; four pending per-job serialization integration failures retained in independent_tests_initial_v1.txt; resolved after engine update'},
       'resolved_review_findings':['Nested inherited historical directories now rejected by output guard.',
         'Per-arm game/search cost distinguished from mixed-arm per-chunk child wall/CPU/RSS.',
         'Extra delta minus8 restricted to pass contrast.',
         'Structural short-route exclusion restricted to pass8 arms; komi0/pass0 still permits routes.',
         'Per-job komi round-trip serialization independently verified after engine integration.'],
       'reviewed_file_sha256':{str(path.relative_to(ROOT)):digest(path) for path in paths},
       'source_fingerprint_at_review':pilot.current_provenance()['source_fingerprint'],
       'remaining_release_gates':['Complete default inherited+new test suite on final source/test bytes.',
         'Six historical behavioral regressions with source lock unchanged.',
         'Before/after historical preservation after tests and before first game.',
         'Complete pre-execution lock including final test evidence; verified remote source/plan checkpoint before first game.'],
       'limitations':['Descriptive costpilot only; no intervals, p-values, rare-failure/efficacy claim or7x7GO.',
         'Hash isolation is not statistical independence; paired streams can consume different randomness.',
         'This review does not replace independent final actual/root/scoring audit or prove internal UCT execution.',
         'Old data are not pooled; all four cells are new game records.']}

if __name__=='__main__':
    result=run();out=Path(sys.argv[1]);
    if out.exists():raise SystemExit('Refusing to replace evidence')
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(json.dumps(result,indent=2));raise SystemExit(int(bool(result['problems'])))
