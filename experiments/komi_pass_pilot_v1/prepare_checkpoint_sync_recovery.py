"""M6 post-freeze packaging wrapper, restricted to mutable M6 evidence/data.

The frozen initial packager mistakenly treats its newly tracked checkpoint
ledger as inherited. This wrapper changes no frozen file or scientific input.
It verifies all frozen hashes before staging only M6 output/evidence deltas.
"""
import base64,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path('/workspace/scratch/50e0c7c6aca1/winorlose_komi_pass_pilot_v1')
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT).decode().strip()
def main():
 if len(sys.argv)>1 and sys.argv[1]=='blob':
  path=sys.argv[2];data=subprocess.check_output(['git','show',':'+path],cwd=ROOT)
  print(json.dumps({'path':path,'sha':git('rev-parse',':'+path),'content':base64.b64encode(data).decode(),'encoding':'base64'}));return
 frozen_commit='2a6b66f0d42117acd9411e6e27434ff52c846aea'
 lock_path='experiments/komi_pass_pilot_v1/pre_execution_lock.json'
 committed=subprocess.check_output(['git','show',frozen_commit+':'+lock_path],cwd=ROOT)
 if (ROOT/lock_path).read_bytes()!=committed:raise ValueError('Pre-execution lock differs from verified zero-game commit')
 lock=json.loads(committed)
 for name,key in [('preregistration.json','preregistration_sha256'),('frozen_plan.json','frozen_plan_sha256'),('pre_execution_source_lock.json','source_lock_sha256')]:
  if hashlib.sha256((ROOT/'experiments/komi_pass_pilot_v1'/name).read_bytes()).hexdigest()!=lock[key]:raise ValueError('Frozen aggregate input changed: '+name)
 for name in ('test_file_sha256','runtime_files_sha256','review_files_sha256','regression_files_sha256'):
  for path,digest in lock[name].items():
   if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen input changed: '+path)
 source=json.loads((ROOT/'experiments/komi_pass_pilot_v1/pre_execution_source_lock.json').read_text())
 actual_source_paths={'run.py',*(str(p.relative_to(ROOT)) for p in (ROOT/'src/winai_loseai').rglob('*.py'))}
 if actual_source_paths!=set(source['files']):raise ValueError('Frozen source file set changed')
 for path,digest in source['files'].items():
  actual=hashlib.sha256((ROOT/path).read_text(encoding='utf-8').encode('utf-8')).hexdigest()
  if actual!=digest:raise ValueError('Frozen source changed: '+path)
 allowed=lambda path:path.startswith(('experiments/komi_pass_pilot_v1/','outputs/komi_pass_pilot_v1/'))
 changed=git('ls-files','-m').splitlines()
 if any(not allowed(p) for p in changed):raise ValueError('Unexpected changes outside mutable M6 evidence/data: '+str(changed))
 git('add','--','experiments/komi_pass_pilot_v1')
 git('add','-f','--','outputs/komi_pass_pilot_v1')
 names=git('diff','--cached','--name-only','--diff-filter=ACM').splitlines()
 if names!=git('diff','--cached','--name-only').splitlines():raise ValueError('Deletion or type changes forbidden')
 if any(not allowed(p) or p.lower().endswith(('.md','.pyc')) for p in names):raise ValueError('Staged content is outside technical M6 scope')
 entries=[]
 for path in names:
  mode,sha,_=git('ls-files','--stage','--',path).split(maxsplit=2);data=subprocess.check_output(['git','show',':'+path],cwd=ROOT)
  entries.append({'path':path,'mode':mode,'type':'blob','sha':sha,'bytes':len(data)})
 print(json.dumps({'parent':git('rev-parse','HEAD'),'base_tree':git('rev-parse','HEAD^{tree}'),'expected_tree':git('write-tree'),'entries':entries}))
if __name__=='__main__':main()
