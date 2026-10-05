"""Isolated packager tests; never stage the real repository."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types
import pytest

SOURCE = Path(__file__).resolve().parents[3] / 'scripts/prepare_komi_pass_estimation_sync.py'

def load():
    spec = importlib.util.spec_from_file_location('m7_pack_test_subject', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@pytest.mark.parametrize('path', [
    'src/winai_loseai/__init__.py', 'scripts/prepare_komi_pass_estimation_sync.py',
    'experiments/komi_pass_estimation_v1/checkpoints.json',
    'experiments/komi_pass_estimation_v1/cost/chunk_01.json',
    'outputs/komi_pass_estimation_v1/games/g000000.json',
])
def test_allow_own_paths(path):
    assert load().allowed(path)

@pytest.mark.parametrize('path', [
    'experiments/komi_pass_pilot_v1/checkpoints.json',
    'outputs/komi_pass_pilot_v1/games/g000000.json', 'tests/test_rules.py',
    'src/winai_loseai/game/state.py', 'reports/report.md',
    'experiments/komi_pass_estimation_v1/report.md',
    'outputs/komi_pass_estimation_v1/code.pyc',
    'experiments/komi_pass_estimation_v1/../secret.json',
    '/tmp/experiments/komi_pass_estimation_v1/test.json',
    'outputs/komi_pass_estimation_v1/credential.env',
])
def test_reject_other_paths(path):
    assert not load().allowed(path)

def test_symlink_rejected(tmp_path, monkeypatch):
    module = load(); monkeypatch.setattr(module, 'ROOT', tmp_path)
    directory = tmp_path/'outputs/komi_pass_estimation_v1'; directory.mkdir(parents=True)
    target = tmp_path/'real.json'; target.write_text('{}')
    (directory/'linked.json').symlink_to(target)
    with pytest.raises(ValueError, match='Symlinks'):
        module.assert_path('outputs/komi_pass_estimation_v1/linked.json')

def test_bounded_blob_slices_reconstruct_index_bytes(tmp_path, monkeypatch, capsys):
    module=load(); monkeypatch.setattr(module,'ROOT',tmp_path)
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    rel='experiments/komi_pass_estimation_v1/test.json'
    path=tmp_path/rel; path.parent.mkdir(parents=True)
    data=bytes(range(256))*390; path.write_bytes(data)
    subprocess.run(['git','add',rel],cwd=tmp_path,check=True)
    pieces=[]
    for offset in range(0,len(data),49152):
        monkeypatch.setattr(sys,'argv',['pack','blob',rel,str(offset),'49152'])
        module.main(); payload=json.loads(capsys.readouterr().out)
        assert payload['bytes']==len(data) and payload['offset']==offset
        pieces.append(payload['content'])
    assert base64.b64decode(''.join(pieces))==data
    monkeypatch.setattr(sys,'argv',['pack','blob',rel,'0','49153'])
    with pytest.raises(ValueError,match='Invalid bounded slice'):module.main()

def test_staging_calls_freeze_gate_before_git(tmp_path, monkeypatch):
    module=load(); monkeypatch.setattr(module,'ROOT',tmp_path)
    import winai_loseai.experiments.komi_pass_estimation as experiment
    calls=[]
    def rejected_gate():
        calls.append('gate'); raise ValueError('frozen drift')
    monkeypatch.setattr(experiment,'verify_preexecution',rejected_gate)
    monkeypatch.setattr(module,'git',lambda *a,**k: calls.append(('git',a)))
    monkeypatch.setattr(sys,'argv',['pack'])
    with pytest.raises(ValueError,match='frozen drift'): module.main()
    assert calls==['gate']

def test_requires_anchor_after_production_begins(tmp_path, monkeypatch):
    module=load(); monkeypatch.setattr(module,'ROOT',tmp_path)
    manifest=tmp_path/'outputs/komi_pass_estimation_v1/manifest.json'
    manifest.parent.mkdir(parents=True); manifest.write_text('{}')
    monkeypatch.setattr(sys,'argv',['pack'])
    with pytest.raises(ValueError,match='zero-game commit anchor'):module.main()

@pytest.mark.parametrize('arguments', [['--anchor','bad'],['--anchor'],['--unknown'],['--anchor','F'*40]])
def test_reject_invalid_anchor_arguments(arguments,monkeypatch):
    module=load(); monkeypatch.setattr(sys,'argv',['pack',*arguments])
    with pytest.raises(ValueError,match='optional --anchor'):module.main()
