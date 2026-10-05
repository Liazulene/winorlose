"""Formal design, rule persistence, failclosed recovery, and descriptive statistics."""
import copy
import json
from pathlib import Path
import pytest
from winai_loseai.experiments import komi_pass_estimation as g
from winai_loseai.league.runstore import ConfigMismatch,MetadataCorrupt,job_to_entry,entry_to_job
from winai_loseai.game.state import NoLegalActionError
from winai_loseai.league.storage import _metadata_line

@pytest.fixture
def small(tmp_path,monkeypatch):
 p=g.protocol();p.update(budget=1,batch_seeds=[80],games_per_cell=1,planned_games=32);p['resource_policy']['concurrency']=2
 path=tmp_path/'protocol.json';path.write_text(json.dumps(p));monkeypatch.setattr(g,'PROTOCOL',path);monkeypatch.setattr(g,'PREREGISTRATION_SHA256',g.sha256(path));return p

def snapshot(out):return {str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}

def test_locked_plan():
 p=g.protocol();jj=g.jobs();cc=g.cells();assert len(jj)==len(cc)==960
 assert len({j['game_seed'] for j in jj})==240
 assert len({c['block_id'] for c in cc})==240
 from collections import Counter
 from itertools import permutations
 orders=[tuple((c['pass_min_ply'],c['komi']) for c in cc[i:i+4]) for i in range(0,960,4)]
 assert Counter(orders)==Counter({order:10 for order in permutations(g.arms())})
 for pos in range(4):assert set(Counter(order[pos] for order in orders).values())=={60}
 for i in range(0,960,4):
  assert len({c['block_id'] for c in cc[i:i+4]})==1 and len({j['game_seed'] for j in jj[i:i+4]})==1
  assert {(j['pass_min_ply'],j['komi']) for j in jj[i:i+4]}==set(g.arms())
 for c in cc:
  assert c['block_index']==(c['identity_index']*2+c['orientation_index'])*10+c['replicate']
  assert c['block_id']==f"{c['batch_seed']}:{c['block_index']}"
 assert all(j['black'].simulations()==j['white'].simulations()==256 for j in jj)
 assert g.cells()==cc
 for rule,komi in g.arms():
  for seed in (17,18,19):
   for ib,iw in p['identity_directions']:
    assert sum(c['pass_min_ply']==rule and c['komi']==komi and c['batch_seed']==seed and (c['black_identity'],c['white_identity'])==(ib,iw) for c in cc)==20
 for i in range(0,960,48):
  checkpoint=cc[i:i+48]
  assert len({c['block_id'] for c in checkpoint})==12
  assert Counter((c['pass_min_ply'],c['komi']) for c in checkpoint)==Counter({a:12 for a in g.arms()})

def test_rule_plan_roundtrip():
 for j in g.jobs():assert entry_to_job(job_to_entry(j),j['batch_id'])==j

def test_pilot_resume_concurrency(tmp_path,small):
 a=tmp_path/'a';b=tmp_path/'b';c=tmp_path/'c'
 assert not g.run(a)['problems']
 assert not g.run(b,concurrency=2)['problems']
 with pytest.raises(g.EstimationInterrupted):g.run(c,stop_after=4)
 assert not g.validate(c,False)['problems']
 assert not g.run(c,resume=True)['problems']
 strip=lambda p:[g.strip_timing(x) for x in g.records(p)]
 assert strip(a)==strip(b)==strip(c)
 saved=snapshot(c);assert not g.run(c,resume=True)['problems'];assert snapshot(c)==saved
 analysis=g.analyze(a)
 assert analysis['formal_estimation'] and len(analysis['paired_differences'])==8
 for row in analysis['paired_differences']:
  for k in ('pass_at_k2p5','pass_at_k0'):assert row['contrasts'][k]['extra_length']==row['contrasts'][k]['length']-8
  assert row['contrasts']['interaction']['extra_length']==row['contrasts']['interaction']['length']
 for rec in g.records(a):
  if rec['pass_min_ply']==8:assert rec['move_count']>=10 and not any(m['is_pass'] for m in rec['moves'][:8])

@pytest.mark.parametrize('damage',['rule_record','missing_rule','rule_plan','komi_record','komi_plan','komis_manifest','ruleset','budget_manifest','schedule_manifest','analysis','source','middle_metadata'])
def test_tamper_rejected_without_repair(tmp_path,small,damage):
 out=tmp_path/'a';g.run(out)
 if damage in ('rule_record','missing_rule','ruleset','komi_record'):
  f=next((out/'games').glob('*.json'));rec=json.loads(f.read_text())
  if damage=='rule_record':rec['pass_min_ply']=8-rec['pass_min_ply']
  elif damage=='missing_rule':rec.pop('pass_min_ply')
  elif damage=='komi_record':rec['komi']=2.5-rec['komi']
  else:rec['ruleset']='wrong'
  f.write_text(json.dumps(rec))
 elif damage=='rule_plan':
  f=out/'plan.json';v=json.loads(f.read_text());v[0]['pass_min_ply']=8-v[0]['pass_min_ply'];f.write_text(json.dumps(v))
 elif damage=='komi_plan':
  f=out/'plan.json';v=json.loads(f.read_text());v[0]['komi']=2.5-v[0]['komi'];f.write_text(json.dumps(v))
 elif damage=='komis_manifest':
  f=out/'manifest.json';v=json.loads(f.read_text());v['komis']=[0.0,2.5];f.write_text(json.dumps(v))
 elif damage.endswith('_manifest'):
  f=out/'manifest.json';v=json.loads(f.read_text());v['budget' if damage=='budget_manifest' else 'schedule_seed']+=1;f.write_text(json.dumps(v))
 elif damage=='analysis':(out/'analysis.json').write_text('{}')
 elif damage=='source':(out/'source_lock.json').write_text('{}')
 else:
  f=out/'games.jsonl';s=f.read_text().splitlines();s[1]='{broken';f.write_text('\n'.join(s)+'\n')
 before=snapshot(out)
 with pytest.raises((ConfigMismatch,MetadataCorrupt)):g.run(out,resume=True)
 assert snapshot(out)==before

@pytest.mark.parametrize('damage',['tail','missing'])
def test_narrow_metadata_repair(tmp_path,small,damage):
 out=tmp_path/'a'
 with pytest.raises(g.EstimationInterrupted):g.run(out,stop_after=2)
 f=out/'games.jsonl';s=f.read_text();f.write_text(s+'{torn' if damage=='tail' else s.splitlines()[0]+'\n')
 assert not g.run(out,resume=True)['problems']

def test_rule_fault_is_latched(tmp_path,small,monkeypatch):
 out=tmp_path/'a';real=g.stream_jobs
 def broken(*args,**kwargs):
  for rec in real(*args,**kwargs):
   yield rec
   raise NoLegalActionError({'synthetic':True,'pass_min_ply':8,'move_count':3})
 monkeypatch.setattr(g,'stream_jobs',broken)
 with pytest.raises(NoLegalActionError):g.run(out)
 fault=json.loads((out/'rule_fault.json').read_text());assert fault['game_index']==1 and fault['state']['synthetic']
 manifest=json.loads((out/'manifest.json').read_text());assert manifest['status']=='failed' and manifest['completed_game_count']==1
 before=snapshot(out);monkeypatch.setattr(g,'stream_jobs',real)
 with pytest.raises(ConfigMismatch,match='nonretryable'):g.run(out,resume=True)
 assert snapshot(out)==before

@pytest.mark.parametrize('root',['winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1','winorlose_g1_pass8_v1','winorlose_g1_pass8_estimation_v1','winorlose_komi_pass_pilot_v1','winorlose_reports'])
def test_old_worktrees_protected(root):
 with pytest.raises(ValueError):g.assert_output_allowed(g.ROOT.parent/root/'new_out')


def test_measurement_global_checkpoint_boundaries():
 import importlib.util
 spec=importlib.util.spec_from_file_location('measure_g1',g.ROOT/'scripts/measure_komi_pass_estimation_chunk.py')
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 for before in range(960):
  n=mod.checkpoint_size(before)
  assert 1<=n<=48 and (before+n)%48==0
 assert [mod.checkpoint_size(i) for i in (0,1,3,8,9,47)]==[48,47,45,40,39,1]


def test_supplemental_descriptive_arithmetic(tmp_path,small):
 out=tmp_path/'a';g.run(out);a=g.analyze(out)
 for rule in ('G0','G1-pass8','G1-k0','G1-k0-pass8'):
  v=a['supplemental_equal_direction_means'][rule]['pooled'];m=v['direction_mean']
  assert v['mixed_mean']==(m['WIN/LOSE']+m['LOSE/WIN'])/2
  assert v['same_mean']==(m['WIN/WIN']+m['LOSE/LOSE'])/2
  assert v['mixed_minus_WW']==v['mixed_mean']-m['WIN/WIN']
  assert v['mixed_minus_LL']==v['mixed_mean']-m['LOSE/LOSE']
 for d in a['paired_differences']:
  for key in ('komi_at_p0','komi_at_p8','pass_at_k2p5','pass_at_k0'):assert d['contrasts'][key]['black_board_win'] in (-1,0,1)
  for metric in d['contrasts']['interaction']:assert d['contrasts']['interaction'][metric]==d['contrasts']['komi_at_p8'][metric]-d['contrasts']['komi_at_p0'][metric]


def test_stale_manifest_recovery_stops_at_global_boundary(tmp_path,small):
 import importlib.util
 spec=importlib.util.spec_from_file_location('measure_g1_stale',g.ROOT/'scripts/measure_komi_pass_estimation_chunk.py')
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 small.update(games_per_cell=2,planned_games=64)
 g.PROTOCOL.write_text(json.dumps(small));g.PREREGISTRATION_SHA256=g.sha256(g.PROTOCOL)
 out=tmp_path/'a'
 with pytest.raises(g.EstimationInterrupted):g.run(out,stop_after=2)
 f=out/'manifest.json';m=json.loads(f.read_text());m['completed_game_count']=1;m['completed_indexes']=[0];f.write_text(json.dumps(m))
 f=out/'games.jsonl';f.write_text(f.read_text().splitlines()[0]+'\n{torn')
 assert mod.saved_prefix_count(out)==2
 with pytest.raises(g.EstimationInterrupted):g.run(out,resume=True,stop_after=mod.checkpoint_size(mod.saved_prefix_count(out)))
 assert len(g.records(out))==48 and not g.validate(out,False)['problems']

@pytest.mark.parametrize('key,value',[
 ('games_per_cell',True),('games_per_cell',0),('games_per_cell',10.0),
 ('planned_games',960.0),('board_size',5.0),('schema_version',True),
 ('batch_seeds',[17,17,19]),('batch_seeds',[True,18,19]),
 ('schedule_seed',True),('budget',True),('komis',[2.5,False]),
 ('agent_seed_orientations',[[True,2],[2,1]]),('pass_min_plies',[False,8]),
])
def test_protocol_rejects_coercible_or_invalid_factors(tmp_path,monkeypatch,key,value):
 p=g.protocol();p[key]=value
 path=tmp_path/'invalid.json';path.write_text(json.dumps(p))
 monkeypatch.setattr(g,'PROTOCOL',path);monkeypatch.setattr(g,'PREREGISTRATION_SHA256',g.sha256(path))
 with pytest.raises(ConfigMismatch):g.protocol()


def test_permutations_and_seed_mapping_independent():
 from itertools import permutations
 from collections import Counter
 import random,hashlib
 p=g.protocol();cc=g.cells()
 blocks=[(seed,identity,orientation,replicate) for seed in [17,18,19] for identity in range(4) for orientation in range(2) for replicate in range(10)]
 rng=random.Random(2026100501);rng.shuffle(blocks)
 arm_values=((0,2.5),(8,2.5),(0,0.0),(8,0.0))
 orders=list(permutations(arm_values))*10;rng.shuffle(orders)
 jj=g.jobs()
 for index,((seed,identity,orientation,replicate),arm) in enumerate((block,arm) for block,order in zip(blocks,orders) for arm in order):
  c=cc[index];j=jj[index]
  assert (c['batch_seed'],c['identity_index'],c['orientation_index'],c['replicate'])==(seed,identity,orientation,replicate)
  assert (c['pass_min_ply'],c['komi'])==arm
  encoded=f'game-seed|{seed}|{(identity*2+orientation)*10+replicate}'.encode()
  assert j['game_seed']==int.from_bytes(hashlib.sha256(encoded).digest()[:16],'big')
 streams={int.from_bytes(hashlib.sha256(f"agent-stream|{j['game_seed']}|{color}|{j[color].seed}".encode()).digest()[:16],'big') for j in jj for color in ('black','white')}
 assert len(streams)==480


@pytest.mark.parametrize('value',[True,0,-1,1.2,'1'])
def test_bad_concurrency_is_readonly(tmp_path,small,value):
 out=tmp_path/'not_created'
 with pytest.raises(ValueError):g.run(out,concurrency=value)
 assert not out.exists()


@pytest.mark.parametrize('value',[True,0,-1,1.2,'1'])
def test_bad_stop_after_is_readonly(tmp_path,small,value):
 out=tmp_path/'not_created'
 with pytest.raises(ValueError):g.run(out,stop_after=value)
 assert not out.exists()


def test_incomplete_inference_not_computed(tmp_path,small):
 out=tmp_path/'a'
 with pytest.raises(g.EstimationInterrupted):g.run(out,stop_after=4)
 a=g.analyze(out)
 assert a['inference']=={'status':'not_computed_incomplete_sample','n_records':4,'planned_games':32}


@pytest.mark.parametrize('relative',[
 'outputs/komi_pass_pilot_v1/new', 'experiments/komi_pass_pilot_v1/new',
 'outputs/batch_A_seed0/new','experiments/g1_pass8_estimation_v1/new',
 'reports/new','handoff/new','src/new','tests/new',
])
def test_new_guard_protects_inherited_directories(relative):
 with pytest.raises(ValueError):g.assert_output_allowed(g.ROOT/relative)


def test_symlink_ancestor_and_child_are_rejected(tmp_path):
 actual=tmp_path/'real';actual.mkdir();link=tmp_path/'link';link.symlink_to(actual,target_is_directory=True)
 with pytest.raises(ValueError):g.assert_output_allowed(link/'new')
 nested=tmp_path/'nested';nested.mkdir();(nested/'link').symlink_to(actual,target_is_directory=True)
 with pytest.raises(ValueError):g.assert_output_allowed(nested)


def test_double_writer_exclusion(tmp_path):
 out=tmp_path/'out'
 with g.exclusive_output_lock(out):
  with pytest.raises(ConfigMismatch,match='another writer'):
   with g.exclusive_output_lock(out):pass
 with g.exclusive_output_lock(out):pass
 assert not out.exists()


def reproduction_module():
 import importlib.util
 spec=importlib.util.spec_from_file_location('m7_reproduction',g.ROOT/'scripts/verify_komi_pass_estimation_reproduction.py')
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


def test_historical_selection_includes_all_observed_draws():
 mod=reproduction_module()
 rows=json.loads((g.ROOT/'outputs/komi_pass_pilot_v1/analysis.json').read_text())['rows']
 chosen=mod.select_rows(rows,[14,15,16],True)
 minimum={min((r for r in rows if (r['pass_min_ply'],r['komi'],r['batch_seed'])==(rule,komi,seed)),key=lambda r:r['game_index'])['game_id'] for rule,komi in g.arms() for seed in (14,15,16)}
 draws={r['game_id'] for r in rows if r['winner']=='draw'}
 assert len(minimum)==12 and len(draws)==3
 assert {r['game_id'] for r in chosen}==minimum|draws
 assert len(chosen)==len(minimum|draws)


@pytest.mark.parametrize('left,right',[(True,1),(1,1.0),({'x':0},{'x':False}),([0],[0.0])])
def test_reproduction_comparator_type_strict(left,right):
 assert not reproduction_module().exact(left,right)


def freeze_fixture(tmp_path,monkeypatch):
 root=tmp_path/'root';evidence=root/'experiments/komi_pass_estimation_v1';evidence.mkdir(parents=True)
 test=root/'tests/test_proof.py';test.parent.mkdir();test.write_text('proof')
 review=evidence/'review.json';review.write_text('{"passed":true}')
 source={'version':'synthetic'};plan=[{'index':0}];current={'experiment_id':'synthetic','source_fingerprint':'fingerprint'}
 monkeypatch.setattr(g,'ROOT',root);monkeypatch.setattr(g,'experiment_lock',lambda:dict(current))
 monkeypatch.setattr(g,'jobs',lambda:[{'ignored':True}]);monkeypatch.setattr(g,'job_to_entry',lambda j:plan[0])
 monkeypatch.setattr(g,'source_lock',lambda:source)
 for name,value in [('frozen_plan.json',plan),('pre_execution_source_lock.json',source)]:
  (evidence/name).write_text(json.dumps(value))
 frozen={**current,'frozen_plan_sha256':g.sha256(evidence/'frozen_plan.json'),'source_lock_sha256':g.sha256(evidence/'pre_execution_source_lock.json'),
 'test_file_sha256':{'tests/test_proof.py':g.sha256(test)},'review_files_sha256':{'experiments/komi_pass_estimation_v1/review.json':g.sha256(review)},'runtime_files_sha256':{'tests/test_proof.py':g.sha256(test)}}
 (evidence/'pre_execution_lock.json').write_text(json.dumps(frozen))
 return root,evidence,current


def test_pre_execution_gate_matches_frozen_proofs(tmp_path,monkeypatch):
 root,evidence,current=freeze_fixture(tmp_path,monkeypatch)
 before=snapshot(root);assert g.verify_preexecution()['passed'];assert before==snapshot(root)


@pytest.mark.parametrize('damage',['source','plan','test','review','lock','missing','proof_map'])
def test_pre_execution_gate_rejects_tampering_readonly(tmp_path,monkeypatch,damage):
 root,evidence,current=freeze_fixture(tmp_path,monkeypatch)
 if damage=='source':(evidence/'pre_execution_source_lock.json').write_text('{}')
 elif damage=='plan':(evidence/'frozen_plan.json').write_text('[]')
 elif damage=='test':(root/'tests/test_proof.py').write_text('changed')
 elif damage=='review':(evidence/'review.json').write_text('{}')
 elif damage=='lock':current['source_fingerprint']='changed'
 elif damage=='missing':(evidence/'pre_execution_lock.json').unlink()
 else:
  path=evidence/'pre_execution_lock.json';v=json.loads(path.read_text());v['test_file_sha256']={};path.write_text(json.dumps(v))
 before=snapshot(root)
 with pytest.raises(ConfigMismatch):g.verify_preexecution()
 assert snapshot(root)==before

@pytest.mark.parametrize('damage',['plan_float','plan_bool','manifest_float','manifest_bool','metadata_float','record_agent_bool','repeat_count','checkpoint_size'])
def test_numeric_equivalence_cannot_hide_saved_input_tampering(tmp_path,small,damage):
 out=tmp_path/'a'
 with pytest.raises(g.EstimationInterrupted):g.run(out,stop_after=1)
 if damage.startswith('plan'):
  f=out/'plan.json';v=json.loads(f.read_text());v[0]['index']=0.0 if damage=='plan_float' else False
 elif damage.startswith('manifest'):
  f=out/'manifest.json';v=json.loads(f.read_text());v['concurrency']=1.0 if damage=='manifest_float' else True
 elif damage=='metadata_float':
  f=out/'games.jsonl';v=json.loads(f.read_text());v['game_index']=0.0
 elif damage=='record_agent_bool':
  f=next((out/'games').glob('*.json'));v=json.loads(f.read_text());color=next(c for c in ('black','white') if v[c]['seed']==1);v[color]['seed']=True
 else:
  f=out/'manifest.json';v=json.loads(f.read_text());v['games_per_cell' if damage=='repeat_count' else 'checkpoint_games']+=1
 f.write_text(json.dumps(v)+'\n');before=snapshot(out)
 with pytest.raises(ConfigMismatch):g.run(out,resume=True)
 assert snapshot(out)==before


def test_production_protocol_is_content_pinned():
 assert g.sha256(g.ROOT/'experiments/komi_pass_estimation_v1/preregistration.json')==g.PREREGISTRATION_SHA256
 assert g.protocol()['planned_games']==960
