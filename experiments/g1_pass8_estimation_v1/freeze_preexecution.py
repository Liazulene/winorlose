"""Freeze reviewed production inputs once, before any formal game exists."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re,sys
r=Path(__file__).resolve().parents[2];sys.path.insert(0,str(r/'src'))
from winai_loseai.experiments import g1_pass8_estimation as g
from winai_loseai.provenance import source_lock
E=r/'experiments/g1_pass8_estimation_v1';I=E/'independent_review'
assert not (r/'outputs/g1_pass8_estimation_v1').exists(),'Freeze must precede all formal games'
text=(E/'full_tests_final_prelaunch.txt').read_text();last=text.strip().splitlines()[-1];assert 'failed' not in last and 'passed' in last,last
match=re.search(r'(\d+) passed.*in ([\d.]+)s',last);assert match,last
current=g.experiment_lock();reg=json.loads((E/'G0_regression_3_recovery.json').read_text());assert reg['source']==current and reg['passed']==3
review=json.loads((I/'resume20261004_launch_safety_summary.json').read_text());assert review['reviewed_experiment_lock']==current and not review['code_or_design_launch_blockers_found']
statreview=json.loads((I/'recovery_statistics_review_v1.json').read_text());assert all(g.sha256(r/p)==v for p,v in statreview['source_sha256'].items())
assert not json.loads((I/'resume20261004_delivery_result.json').read_text())['problems']
assert json.loads((E/'frozen_plan.json').read_text())==[g.job_to_entry(j) for j in g.jobs()]
for name in ('pre_execution_source_lock.json','pre_execution_lock.json','pre_execution_preservation.json','ledger.json'):
 assert not (E/name).exists(),name
preservation=json.loads((I/'resume20261004_historical_preservation.json').read_text())
lock=current|{'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'test_files_sha256':{p.relative_to(r).as_posix():g.sha256(p) for p in sorted((r/'tests').glob('*.py'))},'full_suite':{'passed':int(match[1]),'seconds':float(match[2]),'summary':last,'log_sha256':g.sha256(E/'full_tests_final_prelaunch.txt')},'baseline_delivery':'problems=[]','independent_review_sha256':g.sha256(I/'resume20261004_launch_safety_summary.json'),'independent_statistics_review_sha256':g.sha256(I/'recovery_statistics_review_v1.json'),'historical_preservation_sha256':g.sha256(I/'resume20261004_historical_preservation.json'),'frozen_plan_sha256':g.sha256(E/'frozen_plan.json'),'G0_regression_games':3,'G0_regression_sha256':g.sha256(E/'G0_regression_3_recovery.json'),'statistics_precision_final_sha256':g.sha256(E/'statistics_method_precision_final.json'),'scientific_plan_change':False,'formal_games_before_freeze':0}
g.atomic_json(E/'pre_execution_preservation.json',preservation)
g.atomic_json(E/'pre_execution_source_lock.json',source_lock())
g.atomic_json(E/'pre_execution_lock.json',lock)
g.atomic_json(E/'ledger.json',{'experiment_id':g.protocol()['experiment_id'],'phase':'pre_execution_freeze','decision':'Fixed480 paired rule estimation only; M4 and all history excluded','completed':0,'planned':480,'gates':{'full_suite':True,'G0_exact_regression3':True,'independent_code_and_statistics_review':True,'all_history_unchanged':True},'7x7':'NO-GO','next_phase_started':False,'next':'Verify complete remote freeze, then20 fixed24-game checkpoints at concurrency1. Full-sample inference only.'})
print(json.dumps(lock,indent=2))
