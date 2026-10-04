"""Validate a registered 24-game checkpoint; never run extra games or infer early."""
import json,sys
from pathlib import Path
r=Path(__file__).resolve().parents[2];sys.path.insert(0,str(r/'src'))
from winai_loseai.experiments import g1_pass8_estimation as g
E=r/'experiments/g1_pass8_estimation_v1';out=r/'outputs/g1_pass8_estimation_v1'
v=g.validate(out,require_complete=False);assert not v['problems'],v['problems'];n=v['game_count'];assert 0<n<=480 and n%24==0
file=E/f'checkpoint_validation_{n:03d}.json'
if file.exists():
 assert json.loads(file.read_text())==v,'Never overwrite changed checkpoint evidence'
else:g.atomic_json(file,v)
costs=[json.loads(p.read_text()) for p in sorted((E/'cost').glob('chunk_*.json'))]
assert costs and all(c['exit_code'] in (0,75) for c in costs)
assert costs[-1]['completed_after']==n
summary={'completed':n,'planned':480,'child_wall_seconds':sum(c['wall_seconds'] for c in costs),'child_cpu_seconds':sum(c['cpu_user_seconds']+c['cpu_system_seconds'] for c in costs),'peak_process_rss_kib':max(c['peak_process_rss_kib'] for c in costs),'chunks':len(costs),'validation_problems':v['problems'],'formal_inference_available':n==480}
g.atomic_json(E/'execution_progress.json',summary)
g.atomic_json(E/'ledger.json',{'experiment_id':g.protocol()['experiment_id'],'phase':'fixed480_complete_pending_audit' if n==480 else 'fixed480_checkpoint','completed':n,'planned':480,'validation_problems':[],'7x7':'NO-GO','next_phase_started':False,'source_fingerprint':g.experiment_lock()['source_fingerprint']})
print(json.dumps(summary))
