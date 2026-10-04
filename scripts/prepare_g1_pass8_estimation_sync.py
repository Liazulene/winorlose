"""Stage a bounded formal-pass8 technical snapshot; no network or credentials.

Use blob mode to expose exactly one indexed blob as base64 to the authorized
GitHub connector. Parent verifies each blob SHA, complete tree and final ref.
No Markdown narrative, deletions, historical outputs or force push is allowed.
"""
import base64
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()

def main():
    mode = sys.argv[1] if len(sys.argv)>1 else 'prepare'
    if mode == 'blob':
        path = sys.argv[2]
        blob = git('rev-parse', ':'+path)
        data = subprocess.check_output(['git','show',':'+path],cwd=ROOT)
        print(json.dumps({'path':path,'sha':blob,'content':base64.b64encode(data).decode(),'encoding':'base64'}))
        return
    git('add','src/winai_loseai/__init__.py','src/winai_loseai/experiments/g1_pass8_estimation.py',
        'src/winai_loseai/experiments/g1_pass8_estimation_stats.py','tests/test_g1_pass8_pilot.py',
        'tests/test_g1_pass8_rules.py','tests/test_g1_pass8_estimation.py','tests/test_g1_pass8_estimation_stats.py',
        'scripts/run_g1_pass8_estimation.py','scripts/measure_g1_pass8_estimation_chunk.py',
        'scripts/prepare_g1_pass8_estimation_sync.py','experiments/g1_pass8_estimation_v1')
    if (ROOT/'outputs/g1_pass8_estimation_v1').exists():
        git('add','-f','outputs/g1_pass8_estimation_v1')
    names=git('diff','--cached','--name-only','--diff-filter=ACM').splitlines()
    all_names=git('diff','--cached','--name-only').splitlines()
    if names!=all_names: raise ValueError('no deletion or type change allowed')
    if any(p.lower().endswith('.md') for p in names): raise ValueError('narrative Markdown prohibited')
    if any(p.startswith('outputs/') and not p.startswith('outputs/g1_pass8_estimation_v1/') for p in names):
        raise ValueError('historical output is protected')
    entries=[]
    for path in names:
        mode,sha,_=git('ls-files','--stage','--',path).split(maxsplit=2)
        data=subprocess.check_output(['git','show',':'+path],cwd=ROOT)
        entries.append({'path':path,'mode':mode,'type':'blob','sha':sha,'bytes':len(data)})
    print(json.dumps({'parent':git('rev-parse','HEAD'),'base_tree':git('rev-parse','HEAD^{tree}'),
                     'expected_tree':git('write-tree'),'entries':entries}))
if __name__=='__main__':main()
