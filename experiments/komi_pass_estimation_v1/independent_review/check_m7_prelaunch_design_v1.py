"""Final read-only M7 prelaunch design review. No games are generated."""
from collections import Counter
from datetime import datetime,timezone
import hashlib,importlib.util,json,math,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.experiments import komi_pass_estimation as production
from winai_loseai.league.runstore import job_to_entry
AUDIT_PATH=ROOT/'experiments/komi_pass_estimation_v1/independent_audit/komi960_independent_audit.py'
spec=importlib.util.spec_from_file_location('m7_independent_final_review_audit',AUDIT_PATH)
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
EXP=ROOT/'experiments/komi_pass_estimation_v1'
SCOPE=EXP/'independent_review'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def run():
    problems=[];p=production.protocol();cells,expected=audit.design(p)
    actual=[job_to_entry(j) for j in production.jobs(p)]
    problems.extend(audit.differences(expected,actual,'production_plan'))
    problems.extend(audit.differences(cells,production.cells(p),'production_cells'))
    for name,value in (('frozen_plan.json',expected),('pre_execution_source_lock.json',production.source_lock())):
        path=EXP/name
        if not path.is_file():problems.append('missing '+name)
        else:problems.extend(audit.differences(value,json.loads(path.read_text()),name))
    if sha(EXP/'preregistration.json')!=audit.PROTOCOL_SHA:problems.append('independent protocol pin changed')
    adapter=json.loads((SCOPE/'legacy_version_adapter_proof_v1.json').read_text())
    if not adapter['passed'] or adapter['problems']:problems.append('legacy version adapter proof failed')
    if '2 passed' not in (SCOPE/'legacy_golden_adapter_focused_v1.txt').read_text():problems.append('focused rewritten golden tests failed')
    games=len(list((ROOT/'outputs/komi_pass_estimation_v1/games').glob('*.json')))
    if games:problems.append('review is not before first formal game')
    log=SCOPE/'independent_final_tests_v1.txt';exitfile=SCOPE/'independent_final_tests_v1.exit.txt'
    if not log.is_file() or not exitfile.is_file() or exitfile.read_text().strip()!='0':problems.append('independent final tests unavailable or failed')
    elif '1043 passed' not in log.read_text() or 'failed' in log.read_text().lower():problems.append('expected independent test coverage missing')
    for name in ('final_runner_schema_compatibility_v1.txt','final_freeze_schema_compatibility_v1.txt'):
        if not (SCOPE/name).is_file() or '1 passed' not in (SCOPE/name).read_text():problems.append('final schema compatibility proof missing: '+name)
    seed=json.loads((SCOPE/'seed_inventory_before_v1.json').read_text())
    preservation=json.loads((SCOPE/'preservation_before_verified_v1.json').read_text())
    if not seed['passed'] or not preservation['passed']:problems.append('seed/preservation prerequisite failure')
    n=60;cp=[audit.independent_cp(k,n,.95) for k in range(n+1)]
    maxdistance=max(max(k/n-lo,hi-k/n) for k,(lo,hi) in enumerate(cp))
    component=1-.05/6;limits=[audit.independent_cp(k,n,component) for k in range(n+1)]
    pairdist=max(max((plus-minus)/n-(limits[plus][0]-limits[minus][1]),(limits[plus][1]-limits[minus][0])-(plus-minus)/n) for plus in range(n+1) for minus in range(n-plus+1))
    radius=4*math.sqrt(math.log(120)/120)
    paths=[AUDIT_PATH,EXP/'preregistration.json',EXP/'frozen_plan.json',EXP/'pre_execution_source_lock.json',log,exitfile,ROOT/'src/winai_loseai/experiments/komi_pass_estimation.py',ROOT/'src/winai_loseai/experiments/komi_pass_estimation_stats.py',ROOT/'scripts/verify_komi_pass_estimation_reproduction.py',SCOPE/'test_m7_independent_design_v1.py',EXP/'independent_audit/test_komi960_independent_audit.py',SCOPE/'seed_inventory_before_v1.json',SCOPE/'preservation_before_verified_v1.json',SCOPE/'final_runner_schema_compatibility_v1.txt',SCOPE/'final_freeze_schema_compatibility_v1.txt',SCOPE/'legacy_version_adapter_proof_v1.json',SCOPE/'legacy_golden_adapter_focused_v1.txt',ROOT/'conftest.py']
    return {'utc':datetime.now(timezone.utc).isoformat(),'passed':not problems,'problems':problems,'formal_games_at_review':games,'planned_games':960,'quartets':240,'arm_by_direction_n':60,'seed_by_arm_by_direction_n':20,'seed_orientation_replicates':10,'seed_mapping':'(identity_index*2+orientation_index)*10+replicate','schedule_seed':2026100501,'orders':{'all24_permutations_repetitions':10,'each_arm_each_position':60,'checkpoint_games':48,'checkpoint_quartets':12,'checkpoint_per_arm':12},'seed_isolation':{k:seed[k] for k in ('historical_output_directories','historical_distinct_seeds','historical_distinct_streams','candidate_blocks','candidate_actual_derived_streams')},'draw_semantics':'Draw exactly zero margin; both utility0; neither goal succeeds; denominator retains every draw; white goal independently counted; mixed joint goal once. All history excluded from inference.','primary_family':{'members':['LL_komi_at_p0','LL_komi_at_p8','LL_interaction'],'size':3,'family_alpha':.05,'per_estimand_alpha':.05/3,'CP_component_alpha':.05/6,'interaction_support':[-2,2],'interaction_radius_n60':radius,'paired_construction':'Two two-sided CP intervals with component confidence1-alpha/2; project discordance rectangle using union bound; nonidentical-independent Bernoulli interpretation.','CP_primary_source_checked':'https://arxiv.org/pdf/1403.0229 Theorem1.12, arXivv3 page5, confidence>=.5. One-sided robustness is explicitly not claimed.','sensitivity':'Six fixed strata; sample variance within each ten-replicate cell; sum variance components / H^2, Satterthwaite df; nonconfirmatory only; zero empirical variance yields null CI.'},'independent_outcome_free_precision':{'marginal_CP_max_endpoint_distance':maxdistance,'family_CP_pair_max_endpoint_distance':pairdist,'interaction_radius':radius},'resource_choice':'960 largest balanced allocation with M6 measured child-wall cost plus50% inside360min;1056 exceeds. Costs only, no effect/power selection; no data-dependent expansion.','legacy_version_adapter':{'passed':adapter['passed'],'inherited_test_files_changed':adapter['inherited_test_files_changed'],'exact_target_nodes':len(adapter['exact_nodes']),'other_code_attributes_changed':[], 'disk_test_bytes':'unchanged; only exact expected-version constant changes in memory and is restored'},'historical_regression':{'selected_indices':[0,1,2,3,16,17,18,19,30,32,33,34,35,51],'selected_games':14,'all_M6_draw_indices':[3,30,51],'komi2p5_records':6,'exclusions':['game_wall_ms','search_time_ms','code_version','source_fingerprint'],'sample_increment':0},'reviewed_file_sha256':{str(x.relative_to(ROOT)):sha(x) for x in paths if x.is_file()},'source_fingerprint_at_review':production.current_provenance()['source_fingerprint'],'remaining_release_gates':['Complete stable-source default full pytest with inherited tests unchanged except reviewed exact-path version adapter.','All14 selected M6 exact behavioral regressions; all3 historical draws included.','Preservation after all tests/regenerations and final source/runtime/test/review locks.','Verified prelaunch remote source/plan checkpoint before first formal game.'],'limitations':['No proof of PRNG independence or numerical correctness of every internal UCT/tree/rollout step.','Interaction precision is coarse; crossingzero cannot establish equivalence or absence.','No automatic7x7 or further experiment launch; finish fixed960 or explicit safety pause and report.']}
if __name__=='__main__':
    dest=Path(sys.argv[1])
    if dest.exists():raise SystemExit('Refusing existing evidence')
    r=run();dest.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps(r,indent=2));raise SystemExit(int(not r['passed']))
