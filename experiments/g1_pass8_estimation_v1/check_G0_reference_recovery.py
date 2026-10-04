"""Regenerate three predesignated frozen D1-medium records under new-code G0."""
import sys,json
from pathlib import Path
r=Path(__file__).resolve().parents[2];sys.path.insert(0,str(r/'src'))
from winai_loseai.experiments import g1_pass8_estimation as g
from winai_loseai.spec import AgentSpec
from winai_loseai.league.runner import play_one
E=r/'experiments/g1_pass8_estimation_v1'
# Prespecified minimum-index D1medium perseed5/6/7 =240,320,400.
old=r/'outputs/d1_g0_estimation_v1';plan=json.loads((old/'plan.json').read_text());proof=[]
def normalized(rec):
 rec=g.strip_timing(rec)
 for key in ('schema_version','code_version','source_fingerprint','python_version','ruleset','pass_min_ply'):rec.pop(key,None)
 return json.loads(json.dumps(rec))
for idx in (240,320,400):
 j=plan[idx];job={'index':idx,'game_seed':j['game_seed'],'batch_id':'d1_g0_estimation_v1','black':AgentSpec.from_dict(j['black']),'white':AgentSpec.from_dict(j['white']),'pass_min_ply':0}
 before=json.loads((old/'games'/f'd1_g0_estimation_v1-g{idx:06d}.json').read_text());after=play_one(job)
 assert normalized(before)==normalized(after),idx
 proof.append({'game_index':idx,'source_game_sha256':g.sha256(old/'games'/f'd1_g0_estimation_v1-g{idx:06d}.json'),'same_complete_gameplay_excluding_timing_provenance_newrule':True,'budget':256,'moves':after['move_count']});print(proof[-1],flush=True)
g.atomic_json(E/'G0_regression_3_recovery.json',{'reference_commit':'c180d059eec5e9f36dfe9fef255275c585edb568','rules':'samecodepass0','source':g.experiment_lock(),'games':proof,'passed':3,'sample_increment':0})
