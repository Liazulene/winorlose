"""Independent read-only freeze verification; no game run or production imports."""
import ast,datetime,hashlib,importlib.metadata,json,platform,re
from pathlib import Path
from verify_fixed_design import reconstruct
HERE=Path(__file__).resolve().parent;E=HERE.parent;ROOT=HERE.parents[2]
def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def sha(p):return sha_bytes(Path(p).read_bytes())
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def constants(p):
    result={}
    for node in ast.parse(Path(p).read_text()).body:
        if isinstance(node,ast.Assign):
            try:value=ast.literal_eval(node.value)
            except (ValueError,TypeError):continue
            for target in node.targets:
                if isinstance(target,ast.Name):result[target.id]=value
    return result

def main():
    problems=[];checks={};p=read(E/'preregistration.json');lock=read(E/'pre_execution_lock.json');source=read(E/'pre_execution_source_lock.json')
    def check(name,condition):
        checks[name]=bool(condition)
        if not condition:problems.append(name)
    package_constants=constants(ROOT/'src/winai_loseai/__init__.py');experiment_constants=constants(ROOT/'src/winai_loseai/experiments/g1_pass8_estimation.py');stats_constants=constants(ROOT/'src/winai_loseai/experiments/g1_pass8_estimation_stats.py')
    paths=[ROOT/'run.py',*sorted((ROOT/'src/winai_loseai').rglob('*.py'))]
    normalized={f.relative_to(ROOT).as_posix():sha_bytes(f.read_text(encoding='utf-8').encode('utf-8')) for f in paths}
    raw={f.relative_to(ROOT).as_posix():sha(f) for f in paths}
    fp=sha_bytes(json.dumps(normalized,sort_keys=True,separators=(',',':')).encode())
    expected_source={'code_version':package_constants['CODE_VERSION'],'schema_version':package_constants['SCHEMA_VERSION'],'source_fingerprint':fp,'python_version':platform.python_version(),'algorithm':'sha256-utf8-lf-path-map-v1','files':normalized}
    check('source_lock_complete_and_exact',source==expected_source)
    expected_inputs={'experiment_id':p['experiment_id'],**{k:v for k,v in expected_source.items() if k not in ('algorithm','files')},'preregistration_sha256':sha(E/'preregistration.json'),'entry_point_sha256':sha(ROOT/'scripts/run_g1_pass8_estimation.py'),'measurement_script_sha256':sha(ROOT/'scripts/measure_g1_pass8_estimation_chunk.py'),'scipy_version':importlib.metadata.version('scipy'),'numpy_version':importlib.metadata.version('numpy')}
    check('source_runtime_entry_protocol_measurement_exact',all(lock.get(k)==v for k,v in expected_inputs.items()))
    check('preregistration_sha_hardcoded_contract',experiment_constants['PREREGISTRATION_SHA256']==expected_inputs['preregistration_sha256'])
    check('registered_version_matches_runtime',p['code_version']==package_constants['CODE_VERSION'] and p['schema_version']==package_constants['SCHEMA_VERSION'])
    check('registered_emitted_analysis_label_matches',p['statistics']['analysis_version']==stats_constants['ANALYSIS_VERSION'])
    cells,plan=reconstruct(p);check('independent_frozen480_plan_exact',read(E/'frozen_plan.json')==plan and len(plan)==480)
    check('frozen_plan_raw_sha_matches_lock',sha(E/'frozen_plan.json')==lock['frozen_plan_sha256'])
    files={f.relative_to(ROOT).as_posix():sha(f) for f in sorted((ROOT/'tests').rglob('*.py'))}
    check('complete_test_raw_hash_map_matches',files==lock['test_files_sha256'])
    log=E/'full_tests_final_prelaunch.txt';text=log.read_text();m=re.search(r'(\d+) passed, (\d+) subtests passed in ([0-9.]+)s',text)
    check('final_suite_summary_and_hash_matches',bool(m) and int(m[1])==496 and int(m[2])==21 and float(m[3])==lock['full_suite']['seconds'] and int(m[1])==lock['full_suite']['passed'] and lock['full_suite']['summary'] in text and sha(log)==lock['full_suite']['log_sha256'])
    evidence={'independent_review_sha256':HERE/'resume20261004_launch_safety_summary.json','independent_statistics_review_sha256':HERE/'recovery_statistics_review_v1.json','historical_preservation_sha256':E/'pre_execution_preservation.json','G0_regression_sha256':E/'G0_regression_3_recovery.json','statistics_precision_final_sha256':E/'statistics_method_precision_final.json'}
    for key,path in evidence.items():check('evidence_hash_'+key,path.exists() and sha(path)==lock[key])
    check('preservation_copy_exact',sha(E/'pre_execution_preservation.json')==sha(HERE/'resume20261004_historical_preservation.json'))
    check('preservation_has_no_faults',read(E/'pre_execution_preservation.json')['all_passed'])
    check('baseline_delivery_has_no_faults',read(HERE/'resume20261004_delivery_result.json')['problems']==[])
    regression=read(E/'G0_regression_3_recovery.json')
    check('regression_current_locked_source',regression['source']==expected_inputs)
    check('three_prespecified_G0_regenerations_pass',regression['passed']==lock['G0_regression_games']==3 and regression['sample_increment']==0 and [r['game_index'] for r in regression['games']]==[240,320,400] and all(r['same_complete_gameplay_excluding_timing_provenance_newrule'] and r['budget']==256 for r in regression['games']))
    check('regression_historical_input_hashes_match',all(sha(ROOT/'outputs/d1_g0_estimation_v1/games'/f"d1_g0_estimation_v1-g{r['game_index']:06d}.json")==r['source_game_sha256'] for r in regression['games']))
    ledger=read(E/'ledger.json');check('ledger_pre_execution_not_launched',ledger['experiment_id']==p['experiment_id'] and ledger['planned']==480 and ledger['completed']==0 and ledger['phase']=='pre_execution_freeze' and ledger['next_phase_started'] is False and ledger['7x7']=='NO-GO' and all(ledger['gates'].values()))
    check('zero_formal_games_before_freeze',lock['formal_games_before_freeze']==0 and not (ROOT/'outputs/g1_pass8_estimation_v1').exists())
    result={'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'script_sha256':sha(__file__),'scope':'Exact independent recomputation from current files and runtime; package production modules and runner are not executed.','expected_experiment_inputs':expected_inputs,'checks':checks,'problems':problems,'passed':not problems,'source_file_count':len(normalized),'tests_file_count':len(files),'raw_source_files_sha256':raw,'freeze_artifact_sha256':{n:sha(E/n) for n in ('pre_execution_lock.json','pre_execution_source_lock.json','pre_execution_preservation.json','frozen_plan.json','ledger.json')},'remaining_external_launch_gate':'Parent must verify the complete remote freeze commit/tree before first measured formal chunk, then repeat raw checkpoint validation/sync every24games.','limitations':['Source lock intentionally uses the established UTF8/LF normalized map; raw physical byte hashes are additionally recorded here.','This verifies saved test/regeneration evidence and exact provenance; the496-test suite and three256-simulation games are not rerun redundantly in this check.','Historical-preservation audit is checked against its frozen copy; it remains the recorded08:49 byte audit, not a claim that no prior transient write occurred.']}
    dest=HERE/'resume20261004_freeze_verification.json';dest.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ('raw_source_files_sha256','checks')},indent=2));return bool(problems)
if __name__=='__main__':raise SystemExit(main())
