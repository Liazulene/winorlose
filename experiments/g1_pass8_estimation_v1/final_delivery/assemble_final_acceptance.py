"""Seal completed M5 acceptance after the final default whole-repository tests.
Writes only new final_delivery evidence. Preserves all762 prior validation inputs.
"""
from pathlib import Path
from datetime import datetime,timezone
import importlib.util,json,re,sys
R=Path(__file__).resolve().parents[3];D=Path(__file__).resolve().parent;E=D.parent
spec=importlib.util.spec_from_file_location('m5_final_harness_acceptance',D/'run_final_validation.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
h.source_only_imports(R)
last=(D/'final_pytest_default_verified.txt').read_text().strip().splitlines()[-1]
m=re.match(r'^(\d+) passed, (\d+) subtests passed in ([\d.]+)s',last)
h.require(m is not None and 'failed' not in last and 'error' not in last.lower(),'Final full pytest must pass: '+last)
protocol,lock,source,plan,cells=h.frozen_guard(R)
audit=h.read(E/'final_audit/results_v1/report.json');regen=h.read(D/'results_v1/six_game_regeneration.json');v=h.read(D/'results_v1/final_validation_summary.json')
h.require(audit['passed'] and audit['complete'] and audit['n_records']==480 and audit['n_pairs']==240 and not audit['problems'],'independent audit failed')
h.require(audit['statistical_audit']['passed'],'independent interval audit failed')
h.require(v['passed'] and not v['problems'] and v['strict_complete_validation_passed'] and v['validation_inputs_unchanged'],'final verification failed')
h.require(regen['count']==regen['matching_count']==6 and regen['sample_increment']==0,'six exact regenerations missing')
before=h.read(D/'results_v1/validation_input_hashes_before.json');after=h.input_snapshot(R);preserved=h.compare_snapshots(before,after);h.require(preserved['unchanged'],'prior validation inputs changed')
history=h.historical_check(R);h.require(history['all_passed'],'historical protection failed')
sys.path.insert(0,str(R/'src'))
from winai_loseai.experiments import g1_pass8_estimation as g
validated=g.validate(R/'outputs/g1_pass8_estimation_v1');h.require(not validated['problems'] and validated['game_count']==validated['replay_and_search_ok']==480 and validated['manifest_status']=='completed','post-test strict validation failed')
cp=h.read(E/'checkpoints.json');h.require([x['checkpoint_games'] for x in cp]==list(range(0,481,24)),'checkpoint coverage mismatch')
summary={'command':'PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider','passed':int(m[1]),'subtests_passed':int(m[2]),'seconds':float(m[3]),'summary':last,'exit_code':0,'log_sha256':h.sha(D/'final_pytest_default_verified.txt'),'scope':'Default complete repository discovery, including inherited M4 audit27 plus unique M5 audit47 and M5 final-verification43. Original standalone files preserved; recursive adapters prevent import-name/global-state collisions without omitting assertions.','prior_attempts_preserved':['final_pytest.txt','final_pytest_main_isolated.txt','final_pytest_audit_isolated.txt'],'production_source_changes':False,'original_validation_inputs_unchanged':preserved}
for name,value in [('post_test_preservation.json',history),('post_test_validation_inputs.json',preserved),('post_test_strict_validation.json',validated),('final_test_summary.json',summary)]:h.write(D,name,value)
artifacts={p.relative_to(R).as_posix():{'sha256':h.sha(p),'bytes':p.stat().st_size} for folder in (E/'final_audit',D) for p in sorted(folder.rglob('*')) if p.is_file() and p.suffix!='.pyc' and '__pycache__' not in p.parts}
h.write(D,'final_evidence_inventory.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'files':artifacts,'scope':'Completed technical audit, validation, test and supplementary files before final acceptance/ledger; acceptance records this inventory digest.'})
acceptance={'experiment_id':protocol['experiment_id'],'phase':'completed_fixed480_estimation','recorded_at_utc':datetime.now(timezone.utc).isoformat(),'formal_sample_n':480,'paired_blocks':240,'source_fingerprint':source['source_fingerprint'],'protocol_sha256':lock['preregistration_sha256'],'strict_replay_search_passed':480,'independent_audit_passed':True,'independent_statistical_audit_passed':True,'exact_regenerations':6,'sample_increment_from_validation':0,'test_summary':summary,'historical_files_checked':sum(x['selected_files'] for x in history['checks']),'original_validation_inputs_preserved':preserved,'last_raw_backup':cp[-1],'all_21_checkpoint_proofs_verified':all(x['remote_fetch_and_tree_verified'] for x in cp),'evidence_inventory_sha256':h.sha(D/'final_evidence_inventory.json'),'production_manifest_status':validated['manifest_status'],'7x7':'NO-GO','next_phase_started':False,'scientific_scope':'Whole early-pass rule intervention atkomi2.5/budget256; point estimates do not establish equivalence or rare-failure reliability.','next_mechanism_recommendation':'Separately preregister a new-seed5x5komi/pass2x2engineering-cost probe with draw semantics, then decide formal precision; no newphase here.','problems':[]}
h.write(D,'final_acceptance.json',acceptance)
h.write(D,'final_ledger.json',{'experiment_id':protocol['experiment_id'],'phase':'completed_fixed480_estimation','completed':480,'planned':480,'validation_problems':[],'final_acceptance':'final_acceptance.json','last_production_checkpoint_ledger_preserved':'../ledger.json','source_fingerprint':source['source_fingerprint'],'7x7':'NO-GO','next_phase_started':False,'next':'Deliver M5 report; any nextkomi/passprobe requires a separate newversion, design, seeds and freeze.'})
print(json.dumps({'tests':summary['summary'],'formal_sample_n':480,'historical_files_checked':acceptance['historical_files_checked'],'validation_inputs':len(before),'problems':[],'acceptance_sha256':h.sha(D/'final_acceptance.json')},indent=2))
