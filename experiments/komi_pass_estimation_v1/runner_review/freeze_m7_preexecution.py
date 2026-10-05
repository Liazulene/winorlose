"""Create-only pre-execution M7 freeze after tests, regression and review pass."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.experiments import komi_pass_estimation as g
from winai_loseai.league.runstore import job_to_entry
from winai_loseai.provenance import source_lock

EVIDENCE=ROOT/'experiments/komi_pass_estimation_v1'
RUNTIME=[
 'scripts/run_komi_pass_estimation.py','scripts/measure_komi_pass_estimation_chunk.py',
 'scripts/validate_komi_estimation_checkpoint.py','scripts/verify_komi_pass_estimation_reproduction.py',
 'scripts/prepare_komi_pass_estimation_sync.py',
 'experiments/komi_pass_estimation_v1/runner_review/freeze_m7_preexecution.py',
]


def write_new(path,value):
    with path.open('x',encoding='utf-8') as file:
        json.dump(value,file,ensure_ascii=False,indent=2);file.write('\n');file.flush()


def inventory():
    """Inputs relevant to default repository pytest discovery and execution."""
    sources=[ROOT/'run.py',*sorted((ROOT/'src').rglob('*.py'))]
    tests=[ROOT/'conftest.py',*sorted((ROOT/'tests').rglob('*.py')),
           *sorted((ROOT/'experiments').rglob('*.py'))]
    return {'source_files':{str(p.relative_to(ROOT)):g.sha256(p) for p in sources},
            'test_and_verification_files':{str(p.relative_to(ROOT)):g.sha256(p) for p in tests},
            'runtime_files':{p:g.sha256(ROOT/p) for p in RUNTIME},
            'protocol_sha256':g.sha256(g.PROTOCOL),
            'experiment_lock':g.experiment_lock(),
            'python_executable':sys.executable,'python_version':platform.python_version()}


def own_file(relative):
    path=ROOT/relative
    if not path.resolve().is_relative_to(EVIDENCE) or path.is_symlink() or not path.is_file():
        raise ValueError('Expected M7 evidence file: '+relative)
    return path


def prepare():
    """Publish stable plan/source for review, never the aggregate execution gate."""
    if list((ROOT/'outputs/komi_pass_estimation_v1').rglob('*.json')):
        raise ValueError('Pre-execution preparation requires zero production artifacts')
    if any((EVIDENCE/name).exists() for name in ('frozen_plan.json','pre_execution_source_lock.json','pre_execution_lock.json')):
        raise FileExistsError('Prepared inputs already exist; never overwrite')
    with g.exclusive_output_lock(EVIDENCE):
        write_new(EVIDENCE/'frozen_plan.json',[job_to_entry(j) for j in g.jobs()])
        write_new(EVIDENCE/'pre_execution_source_lock.json',source_lock())
    return {'frozen_plan_sha256':g.sha256(EVIDENCE/'frozen_plan.json'),
            'source_lock_sha256':g.sha256(EVIDENCE/'pre_execution_source_lock.json')}


def freeze(test_log,test_exit,inputs_before,inputs_after,regression,reviews):
    dest=EVIDENCE
    if list((ROOT/'outputs/komi_pass_estimation_v1').rglob('*.json')):
        raise ValueError('Pre-execution freeze requires zero production artifacts')
    if (dest/'pre_execution_lock.json').exists():
        raise FileExistsError('Freeze artifacts already exist; never overwrite or refreeze')
    current=inventory()
    before=json.loads(own_file(inputs_before).read_text(encoding='utf-8'))
    after=json.loads(own_file(inputs_after).read_text(encoding='utf-8'))
    if not g.exact_value(before,after) or not g.exact_value(current,after):
        raise ValueError('Runtime, source, protocol or test files changed since full-suite verification')
    log=own_file(test_log).read_text(encoding='utf-8')
    summary=next((line for line in reversed(log.splitlines()) if re.search(r'\b\d+ passed\b',line)),None)
    if own_file(test_exit).read_text().strip()!='0' or summary is None or re.search(r'\b(failed|error|errors)\b',summary):
        raise ValueError('Full default suite has not passed')
    regression_doc=json.loads(own_file(regression).read_text())
    if (regression_doc.get('passed') is not True or regression_doc.get('sample_increment')!=0
            or not g.exact_value(regression_doc.get('experiment_lock'),g.experiment_lock())
            or sum(check['winner']=='draw' for check in regression_doc['checks'])!=3):
        raise ValueError('M6 zero/2.5 and all-draw exact regression has not passed under this source')
    if not reviews:raise ValueError('Independent reviews are required')
    for relative in reviews:
        proof=json.loads(own_file(relative).read_text())
        if proof.get('passed') is not True or proof.get('problems',[]):
            raise ValueError('Review has not passed: '+relative)
    source=source_lock();plan=[job_to_entry(j) for j in g.jobs()]
    if (not g.exact_value(json.loads((dest/'frozen_plan.json').read_text()),plan)
            or not g.exact_value(json.loads((dest/'pre_execution_source_lock.json').read_text()),source)):
        raise ValueError('Previously prepared plan/source changed or no longer match final inputs')
    proof_paths=[test_log,test_exit,inputs_before,inputs_after,regression,*reviews]
    lock={**g.experiment_lock(),'baseline_commit':'c7ce77c4fe581dce25676226140ff5ae6a115b39',
          'created_utc':datetime.now(timezone.utc).isoformat(),'registered_before_first_game':True,
          'production_games_before_freeze':0,'test_summary':summary,
          'test_file_sha256':current['test_and_verification_files'],
          'runtime_files_sha256':current['runtime_files'],
          'review_files_sha256':{p:g.sha256(ROOT/p) for p in proof_paths},
          'full_suite':{'command':'PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider',
                        'python_executable':sys.executable,'log_path':test_log,'exit_path':test_exit,'exit_code':0},
          'historical_regression':regression,'independent_review_paths':list(reviews)}
    with g.exclusive_output_lock(dest):
        lock.update(frozen_plan_sha256=g.sha256(dest/'frozen_plan.json'),
                    source_lock_sha256=g.sha256(dest/'pre_execution_source_lock.json'))
        write_new(dest/'pre_execution_lock.json',lock)
    return g.verify_preexecution()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['inventory','prepare','freeze']);parser.add_argument('--out')
    for name in ('test-log','test-exit','inputs-before','inputs-after','regression'):
        parser.add_argument('--'+name)
    parser.add_argument('--review',action='append',default=[])
    args=parser.parse_args()
    if args.command=='inventory':
        if not args.out:parser.error('--out required')
        out=g.assert_output_allowed(args.out);out.parent.mkdir(parents=True,exist_ok=True)
        write_new(out,inventory());print(str(out));return 0
    if args.command=='prepare':
        print(json.dumps(prepare(),indent=2));return 0
    values=[args.test_log,args.test_exit,args.inputs_before,args.inputs_after,args.regression]
    if not all(values):parser.error('all test, input and regression paths required')
    result=freeze(*values,args.review);print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
