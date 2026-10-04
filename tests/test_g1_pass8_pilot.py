"""Pilot design, rule persistence, failclosed recovery, and descriptive statistics."""
import copy
import json
from pathlib import Path
import pytest
from winai_loseai.experiments import g1_pass8 as g
from winai_loseai.league.runstore import ConfigMismatch,MetadataCorrupt,job_to_entry,entry_to_job
from winai_loseai.game.state import NoLegalActionError
from winai_loseai.league.storage import _metadata_line

@pytest.fixture
def small(tmp_path,monkeypatch):
 p=g.protocol();p.update(budget=1,batch_seeds=[80],planned_games=16);p['resource_policy']['concurrency']=2
 path=tmp_path/'protocol.json';path.write_text(json.dumps(p));monkeypatch.setattr(g,'PROTOCOL',path);monkeypatch.setattr(g,'PREREGISTRATION_SHA256',g.sha256(path));return p

def snapshot(out):return {str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}

def test_locked_plan():
 p=g.protocol();jj=g.jobs();cc=g.cells();assert len(jj)==len(cc)==48
 assert len({j['game_seed'] for j in jj})==24
 assert len({c['block_id'] for c in cc})==24
 assert sum(cc[i]['pass_min_ply']==0 for i in range(0,48,2))==12
 for i in range(0,48,2):
  assert cc[i]['block_id']==cc[i+1]['block_id'] and jj[i]['game_seed']==jj[i+1]['game_seed']
  assert {jj[i]['pass_min_ply'],jj[i+1]['pass_min_ply']}=={0,8}
 assert all(j['black'].simulations()==j['white'].simulations()==256 for j in jj)
 assert g.cells()==cc
 for rule in (0,8):
  for seed in (8,9,10):
   for ib,iw in p['identity_directions']:
    assert sum(c['pass_min_ply']==rule and c['batch_seed']==seed and (c['black_identity'],c['white_identity'])==(ib,iw) for c in cc)==2

def test_rule_plan_roundtrip():
 for j in g.jobs():assert entry_to_job(job_to_entry(j),j['batch_id'])==j

def test_pilot_resume_concurrency(tmp_path,small):
 a=tmp_path/'a';b=tmp_path/'b';c=tmp_path/'c'
 assert not g.run(a)['problems']
 assert not g.run(b,concurrency=2)['problems']
 with pytest.raises(g.PilotInterrupted):g.run(c,stop_after=4)
 assert not g.validate(c,False)['problems']
 assert not g.run(c,resume=True)['problems']
 strip=lambda p:[g.strip_timing(x) for x in g.records(p)]
 assert strip(a)==strip(b)==strip(c)
 saved=snapshot(c);assert not g.run(c,resume=True)['problems'];assert snapshot(c)==saved
 analysis=g.analyze(a)
 assert analysis['pilot_descriptive_only'] and len(analysis['paired_differences'])==8
 for row in analysis['paired_differences']:assert row['extra_length_delta']==row['length_delta']-8
 for rec in g.records(a):
  if rec['pass_min_ply']==8:assert rec['move_count']>=10 and not any(m['is_pass'] for m in rec['moves'][:8])

@pytest.mark.parametrize('damage',['rule_record','missing_rule','rule_plan','ruleset','budget_manifest','schedule_manifest','analysis','source','middle_metadata'])
def test_tamper_rejected_without_repair(tmp_path,small,damage):
 out=tmp_path/'a';g.run(out)
 if damage in ('rule_record','missing_rule','ruleset'):
  f=next((out/'games').glob('*.json'));rec=json.loads(f.read_text())
  if damage=='rule_record':rec['pass_min_ply']=8-rec['pass_min_ply']
  elif damage=='missing_rule':rec.pop('pass_min_ply')
  else:rec['ruleset']='wrong'
  f.write_text(json.dumps(rec))
 elif damage=='rule_plan':
  f=out/'plan.json';v=json.loads(f.read_text());v[0]['pass_min_ply']=8-v[0]['pass_min_ply'];f.write_text(json.dumps(v))
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
 with pytest.raises(g.PilotInterrupted):g.run(out,stop_after=2)
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

@pytest.mark.parametrize('root',['winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1'])
def test_old_worktrees_protected(root):
 with pytest.raises(ValueError):g.assert_output_allowed(g.ROOT.parent/root/'new_out')


def test_measurement_global_checkpoint_boundaries():
 import importlib.util
 spec=importlib.util.spec_from_file_location('measure_g1',g.ROOT/'scripts/measure_g1_pass8_chunk.py')
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 for before in range(48):
  n=mod.checkpoint_size(before)
  assert 1<=n<=8 and (before+n)%8==0
 assert [mod.checkpoint_size(i) for i in (0,1,3,8,9,47)]==[8,7,5,8,7,1]


def test_supplemental_descriptive_arithmetic(tmp_path,small):
 out=tmp_path/'a';g.run(out);a=g.analyze(out)
 for rule in ('G0','G1-pass8'):
  v=a['supplemental_equal_direction_means'][rule]['pooled'];m=v['direction_mean']
  assert v['mixed_mean']==(m['WIN/LOSE']+m['LOSE/WIN'])/2
  assert v['same_mean']==(m['WIN/WIN']+m['LOSE/LOSE'])/2
  assert v['mixed_minus_WW']==v['mixed_mean']-m['WIN/WIN']
  assert v['mixed_minus_LL']==v['mixed_mean']-m['LOSE/LOSE']
 for d in a['paired_differences']:assert d['black_board_win_delta'] in (-1,0,1)


def test_stale_manifest_recovery_stops_at_global_boundary(tmp_path,small):
 import importlib.util
 spec=importlib.util.spec_from_file_location('measure_g1_stale',g.ROOT/'scripts/measure_g1_pass8_chunk.py')
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 out=tmp_path/'a'
 with pytest.raises(g.PilotInterrupted):g.run(out,stop_after=2)
 f=out/'manifest.json';m=json.loads(f.read_text());m['completed_game_count']=1;m['completed_indexes']=[0];f.write_text(json.dumps(m))
 f=out/'games.jsonl';f.write_text(f.read_text().splitlines()[0]+'\n{torn')
 assert mod.saved_prefix_count(out)==2
 with pytest.raises(g.PilotInterrupted):g.run(out,resume=True,stop_after=mod.checkpoint_size(mod.saved_prefix_count(out)))
 assert len(g.records(out))==8 and not g.validate(out,False)['problems']
