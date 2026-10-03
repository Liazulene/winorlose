"""Prepare a bounded GitHub API snapshot; no network calls or credentials.

Parent orchestration uploads each changed blob separately, then creates a tree
and fast-forward commit, fetches it and verifies exact expected tree equality.
The default metadata mode avoids sending large file contents in one tool call.
"""
import base64
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT).decode().strip()
def main():
    mode=sys.argv[1] if len(sys.argv)>1 else 'prepare'
    if mode=='blob':
        path=sys.argv[2];blob=git('rev-parse',':'+path)
        data=subprocess.check_output(['git','show',':'+path],cwd=ROOT)
        print(json.dumps({'path':path,'sha':blob,'content':base64.b64encode(data).decode(),'encoding':'base64'}));return
    git('add','src/winai_loseai/__init__.py','src/winai_loseai/experiments/d1_estimation.py','src/winai_loseai/experiments/d1_estimation_stats.py',
        'scripts/run_d1_estimation.py','scripts/measure_d1_estimation_chunk.py','scripts/verify_d1_estimation_reproduction.py','scripts/verify_d1_estimation_design.py',
        'scripts/prepare_d1_estimation_sync.py','tests/test_d1.py','tests/test_d1_estimation.py','tests/test_d1_estimation_stats.py','experiments/d1_estimation_v1')
    if (ROOT/'outputs/d1_g0_estimation_v1').exists():git('add','-f','outputs/d1_g0_estimation_v1')
    names=git('diff','--cached','--name-only','--diff-filter=ACM').splitlines()
    allnames=git('diff','--cached','--name-only').splitlines()
    if names!=allnames:raise ValueError('no deletion/type changes allowed')
    if any(p.endswith('.md') for p in allnames):raise ValueError('narrative markdown prohibited in new snapshots')
    entries=[]
    for path in names:
        mode,sha,stage_and_path=git('ls-files','--stage','--',path).split(maxsplit=2)
        data=subprocess.check_output(['git','show',':'+path],cwd=ROOT)
        entries.append({'path':path,'mode':mode,'type':'blob','sha':sha,'bytes':len(data)})
    print(json.dumps({'parent':git('rev-parse','HEAD'),'base_tree':git('rev-parse','HEAD^{tree}'),'expected_tree':git('write-tree'),'entries':entries}))
if __name__=='__main__':main()
