"""Independent fresh recovery tests. Synthetic records never enter formal output."""
import importlib.util,json
from pathlib import Path
import pytest
from winai_loseai.experiments import g1_pass8_estimation as g
from winai_loseai.league.runstore import ConfigMismatch

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    p=g.protocol();p.update(budget=1,batch_seeds=[91],planned_games=32,games_per_cell=2)
    protocol=tmp_path/'audit_protocol.json';protocol.write_text(json.dumps(p))
    monkeypatch.setattr(g,'PROTOCOL',protocol);monkeypatch.setattr(g,'PREREGISTRATION_SHA256',g.sha256(protocol))
    return tmp_path/'run'

def snap(out):return {str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}

@pytest.mark.parametrize('field',['source_fingerprint','entry_point_sha256','measurement_script_sha256','scipy_version','numpy_version'])
def test_changed_execution_input_is_readonly_rejected(isolated,monkeypatch,field):
    with pytest.raises(g.PilotInterrupted):g.run(isolated,stop_after=1)
    frozen=snap(isolated);original=g.experiment_lock
    def changed():return {**original(),field:'independent-audit-changed-value'}
    monkeypatch.setattr(g,'experiment_lock',changed)
    with pytest.raises(ConfigMismatch):g.run(isolated,resume=True)
    assert snap(isolated)==frozen

@pytest.mark.parametrize('filename',['plan.json','game_seeds.json'])
def test_changed_game_seed_is_readonly_rejected(isolated,filename):
    with pytest.raises(g.PilotInterrupted):g.run(isolated,stop_after=1)
    p=isolated/filename;a=json.loads(p.read_text());a[0]['game_seed']+=1;p.write_text(json.dumps(a));frozen=snap(isolated)
    with pytest.raises(ConfigMismatch):g.run(isolated,resume=True)
    assert snap(isolated)==frozen

def test_live_source_lock_change_stops_before_record_write(isolated,monkeypatch):
    original=g.experiment_lock;counter=0
    def changes_after_start():
        nonlocal counter
        counter+=1;lock=original()
        return lock if counter==1 else {**lock,'entry_point_sha256':'changed'}
    monkeypatch.setattr(g,'experiment_lock',changes_after_start)
    with pytest.raises(ConfigMismatch,match='inputs changed'):g.run(isolated)
    manifest=json.loads((isolated/'manifest.json').read_text());assert manifest['status']=='failed' and manifest['completed_game_count']==0
    assert list((isolated/'games').glob('*.json'))==[]

def test_global_checkpoint_recovery_partial_inference_and_final_snapshot(isolated):
    spec=importlib.util.spec_from_file_location('m5_independent_measure',g.ROOT/'scripts/measure_g1_pass8_estimation_chunk.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    with pytest.raises(g.PilotInterrupted):g.run(isolated,stop_after=1)
    assert m.saved_prefix_count(isolated)==1 and m.checkpoint_size(1)==23
    assert g.analyze(isolated)['inference'] is None
    with pytest.raises(g.PilotInterrupted):g.run(isolated,resume=True,stop_after=m.checkpoint_size(m.saved_prefix_count(isolated)))
    assert m.saved_prefix_count(isolated)==24
    assert not g.validate(isolated,require_complete=False)['problems']
    assert g.analyze(isolated)['inference'] is None
    cc=g.cells();assert all(cc[i]['block_id']==cc[i+1]['block_id'] for i in range(0,24,2))
    result=g.run(isolated,resume=True)
    assert not result['problems'] and result['complete'] and result['game_count']==32
    manifest=json.loads((isolated/'manifest.json').read_text());validation=json.loads((isolated/'validation.json').read_text())
    assert manifest['status']==validation['manifest_status']=='completed'
    assert validation==g.validate(isolated)
    frozen=snap(isolated);g.run(isolated,resume=True);assert snap(isolated)==frozen

def test_interruption_after_finish_before_validation_write_recovers(isolated,monkeypatch):
    atomic=g.atomic_json
    def interrupt(path,value):
        if Path(path).name=='validation.json':raise KeyboardInterrupt()
        return atomic(path,value)
    monkeypatch.setattr(g,'atomic_json',interrupt)
    with pytest.raises(KeyboardInterrupt):g.run(isolated)
    assert json.loads((isolated/'manifest.json').read_text())['status']=='interrupted'
    monkeypatch.setattr(g,'atomic_json',atomic)
    result=g.run(isolated,resume=True)
    assert not result['problems'] and result['manifest_status']=='completed'
    assert json.loads((isolated/'validation.json').read_text())==g.validate(isolated)
