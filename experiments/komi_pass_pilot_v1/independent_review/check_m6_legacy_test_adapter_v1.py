"""Verify version-only pytest adaptation without executing any game tests."""
import ast
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[3]
OLD=ROOT.parent/'winorlose_g1_pass8_estimation_v1'
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai import CODE_VERSION
from winai_loseai.experiments import g1_pass8_estimation as legacy
from winai_loseai.experiments import komi_pass_pilot as pilot
from winai_loseai.league.runstore import ConfigMismatch
TARGETS=('tests/test_g1_pass8_estimation.py',
         'experiments/g1_pass8_estimation_v1/independent_review/test_resume20261004_independent_safety.py')

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ast_text(p):return ast.dump(ast.parse(p.read_text()),include_attributes=False)

def run():
    problems=[];files=[]
    for relative in TARGETS:
        original=OLD/relative;current=ROOT/relative
        before=ast.parse(original.read_text());after=ast.parse(current.read_text())
        same_bytes=original.read_bytes()==current.read_bytes();same_ast=ast.dump(before)==ast.dump(after)
        if not same_bytes or not same_ast:problems.append('historical test changed '+relative)
        files.append({'path':relative,'original_sha256':sha(original),'current_sha256':sha(current),
                      'bytes_identical':same_bytes,'AST_identical':same_ast,
                      'test_definitions':len([n for n in ast.walk(after) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]),
                      'assertion_nodes':len([n for n in ast.walk(after) if isinstance(n,ast.Assert)])})
    original_root=ast.parse((OLD/'conftest.py').read_text());adapted_root=ast.parse((ROOT/'conftest.py').read_text())
    prefix_same=ast.dump(ast.Module(body=adapted_root.body[:len(original_root.body)],type_ignores=[]))==ast.dump(original_root)
    if not prefix_same:problems.append('original root pytest bootstrap changed')
    spec=importlib.util.spec_from_file_location('m6_adapter_readonly_proof_v1',ROOT/'conftest.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    adapter=module.m6_legacy_m5_protocol_version_adapter.__wrapped__
    original_path=legacy.PROTOCOL;original_hash=legacy.PREREGISTRATION_SHA256;original_data=json.loads(original_path.read_text());original_sha=sha(original_path)
    checks=[]
    for relative in (*TARGETS,'tests/test_komi_pass_pilot_m6.py','tests/test_rules.py','experiments/g1_pass8_estimation_v1/independent_review/not_a_target.py'):
        with tempfile.TemporaryDirectory(prefix='m6_adapter_proof_') as td:
            tmp=Path(td);patch=pytest.MonkeyPatch();before_protocol=legacy.PROTOCOL;before_hash=legacy.PREREGISTRATION_SHA256
            try:
                adapter(SimpleNamespace(node=SimpleNamespace(path=ROOT/relative)),tmp,patch)
                if relative in TARGETS:
                    actual=legacy.protocol();delta={k for k in set(original_data)|set(actual) if original_data.get(k)!=actual.get(k)}
                    only_version=delta=={'code_version'} and actual['code_version']==CODE_VERSION
                    temp_only=legacy.PROTOCOL.parent==tmp and legacy.PROTOCOL!=original_path
                    # Leave hash enforcement active; do not replace or monkeypatch protocol().
                    legacy.PROTOCOL.write_text(legacy.PROTOCOL.read_text()+' ')
                    try:legacy.protocol();tamper_rejected=False
                    except ConfigMismatch:tamper_rejected=True
                    okay=only_version and temp_only and tamper_rejected
                    checks.append({'path':relative,'target':True,'changed_keys':sorted(delta),
                                   'temporary_protocol_only':temp_only,'original_hash_guard_still_rejects_tamper':tamper_rejected,'passed':okay})
                else:
                    okay=legacy.PROTOCOL==before_protocol and legacy.PREREGISTRATION_SHA256==before_hash and not list(tmp.iterdir())
                    checks.append({'path':relative,'target':False,'no_adaptation_or_writes':okay,'passed':okay})
                if not okay:problems.append('adapter dynamic check '+relative)
            finally:patch.undo()
            if legacy.PROTOCOL!=original_path or legacy.PREREGISTRATION_SHA256!=original_hash:problems.append('monkeypatch restore failed')
    if sha(original_path)!=original_sha:problems.append('original protocol bytes changed')
    source_same=json.loads((ROOT/'experiments/komi_pass_pilot_v1/pre_execution_source_lock.json').read_text())==pilot.source_lock()
    if not source_same:problems.append('production source changed')
    return {'utc':datetime.now(timezone.utc).isoformat(),'passed':not problems,'problems':problems,
            'scope':'Two exact inherited M5 pytest paths; version-only temporary protocol fixture. No test assertions, production source or historical files changed.',
            'original_root_bootstrap_AST_preserved':prefix_same,'test_files':files,'dynamic_checks':checks,
            'original_protocol_sha256_before':original_sha,'original_protocol_sha256_after':sha(original_path),
            'conftest_sha256':sha(ROOT/'conftest.py'),'checker_sha256':sha(Path(__file__)),
            'source_lock_unchanged':source_same,'source_fingerprint':pilot.current_provenance()['source_fingerprint'],
            'experimental_sample_increment':0,'test_games_executed_by_this_proof':0,
            'limitations':['This proves byte/AST and adapter behavior preservation, not historical and current engine behavioral equivalence.',
                          'The original assertions must still pass in a focused run and then the complete default suite.',
                          'Initial full-suite failures remain evidence; this adapter does not suppress or skip tests.']}

if __name__=='__main__':
    d=run();out=Path(sys.argv[1]);
    if out.exists():raise SystemExit('Refusing prior evidence replacement')
    out.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n');print(json.dumps(d,indent=2));raise SystemExit(int(bool(d['problems'])))
