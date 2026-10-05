"""Independently prove the exact-node M7 expected-version-only test adapter."""
import hashlib,importlib.util,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai import CODE_VERSION
from winai_loseai.league import runner
OLD='winai_loseai-0.8.0-komi-pass-pilot'
TEST='tests/test_g1_pass8_rules.py'
NAME='test_g0_default_and_explicit_reproduce_legacy_golden'
def sha(b):return hashlib.sha256(b).hexdigest()
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def run():
    problems=[];base=lambda p:subprocess.check_output(['git','-C',str(ROOT),'show','c7ce77c4:'+p])
    tracked=subprocess.check_output(['git','-C',str(ROOT),'ls-tree','-rz','c7ce77c4']).split(b'\0')
    tests=[r.split(b'\t',1)[1].decode() for r in tracked if r and r.split(b'\t',1)[1].decode().startswith('tests/')]
    changed=[p for p in tests if (ROOT/p).read_bytes()!=base(p)]
    if changed:problems.append({'inherited_test_bytes_changed':changed})
    original_conftest=base('conftest.py');current_conftest=(ROOT/'conftest.py').read_bytes()
    if not current_conftest.startswith(original_conftest):problems.append('inherited conftest prefix changed')
    conftest=load('m7_independent_conftest_probe',ROOT/'conftest.py')
    test=load('m7_independent_legacy_golden_probe',ROOT/TEST)
    fixture=conftest.m7_legacy_g0_golden_version_expectation_adapter.__wrapped__
    function=getattr(test,NAME);original=function.__code__;checks=[]
    for algorithm in ('random','vector_mcts'):
        nodeid=f'{TEST}::{NAME}[{algorithm}]';request=SimpleNamespace(node=SimpleNamespace(path=ROOT/TEST,nodeid=nodeid,obj=function))
        with pytest.MonkeyPatch.context() as patch:
            fixture(request,patch);adapted=function.__code__
            differences=[i for i,(a,b) in enumerate(zip(original.co_consts,adapted.co_consts)) if a!=b]
            other=[]
            for attr in dir(original):
                if attr.startswith('co_') and attr!='co_consts':
                    a,b=getattr(original,attr),getattr(adapted,attr)
                    if callable(a):a,b=list(a()),list(b())
                    if a!=b:other.append(attr)
            if len(original.co_consts)!=len(adapted.co_consts) or len(differences)!=1:problems.append('expected exactly one unchanged-shape constant replacement')
            if differences and (original.co_consts[differences[0]]!=OLD or adapted.co_consts[differences[0]]!=CODE_VERSION):problems.append('unexpected replaced constant')
            if other:problems.append({'other_code_attributes_changed':other})
            function(algorithm) # Run every unchanged golden/game/schema/current-version assertion.
            actual=runner.play_one(test.job(algorithm),board_size=3)
            if actual['code_version']!=CODE_VERSION or CODE_VERSION!='winai_loseai-0.9.0-komi-pass-estimation':problems.append('runtime record not M7')
            digest=sha(json.dumps(test.gameplay_record(actual),sort_keys=True).encode())
            if digest!=test.G0_GOLDEN[algorithm]:problems.append('historical trajectory golden mismatch')
            checks.append({'nodeid':nodeid,'changed_constant_indices':differences,'old_constant':OLD,'new_constant':CODE_VERSION,'other_code_attributes_changed':other,'co_code_sha256':sha(original.co_code),'unchanged_golden_assertions_passed':True,'runtime_record_version':actual['code_version'],'golden_sha256':digest})
        if function.__code__ is not original:problems.append('monkeypatch failed to restore exact original code object')
    rejected=[]
    for path,nodeid in [(ROOT/TEST,f'{TEST}::different_function[random]'),(ROOT/TEST,f'{TEST}::{NAME}[different]'),(ROOT/'tests/not_target.py',f'{TEST}::{NAME}[random]')]:
        with pytest.MonkeyPatch.context() as patch:
            fixture(SimpleNamespace(node=SimpleNamespace(path=path,nodeid=nodeid,obj=function)),patch)
            if function.__code__ is not original:problems.append('non-target node adapted')
            rejected.append({'path':str(path.relative_to(ROOT)),'nodeid':nodeid,'unchanged':function.__code__ is original})
    if (ROOT/TEST).read_bytes()!=base(TEST):problems.append('old test bytes changed during adapter verification')
    return {'utc':datetime.now(timezone.utc).isoformat(),'passed':not problems,'problems':problems,'inherited_test_files_checked':len(tests),'inherited_test_files_changed':changed,'legacy_test_sha256':sha((ROOT/TEST).read_bytes()),'new_conftest_sha256':sha(current_conftest),'original_conftest_prefix_unchanged':current_conftest.startswith(original_conftest),'exact_nodes':checks,'non_target_checks':rejected,'restoration':'Exact original function code object restored after each target and non-target context.','scope':'Only one expected version literal changes; no skips, xfails, runtime-output mutation, test-file disk edits, assertion removal or gameplay/golden changes. A separate focused pytest log covers pytest assertion-rewritten execution.','sample_increment':0,'checker_sha256':sha(Path(__file__).read_bytes())}
if __name__=='__main__':
    dest=Path(sys.argv[1])
    if dest.exists():raise SystemExit('Refusing existing report')
    result=run();dest.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(json.dumps(result,indent=2));raise SystemExit(int(not result['passed']))
