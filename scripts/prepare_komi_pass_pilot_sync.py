"""Stage bounded M6 technical snapshots; never send credentials or old reports."""
import base64
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT).decode().strip()
def main():
 if len(sys.argv)>1 and sys.argv[1]=='blob':
  path=sys.argv[2];data=subprocess.check_output(['git','show',':'+path],cwd=ROOT)
  print(json.dumps({'path':path,'sha':git('rev-parse',':'+path),'content':base64.b64encode(data).decode(),'encoding':'base64'}));return
 changed=git('ls-files','-m').splitlines()
 allowed_mods={'conftest.py','src/winai_loseai/__init__.py','src/winai_loseai/game/scoring.py','src/winai_loseai/league/runner.py','src/winai_loseai/league/runstore.py','src/winai_loseai/league/replay.py','tests/test_g1_pass8_rules.py'}
 if set(changed)-allowed_mods:raise ValueError('Unexpected inherited changes: '+str(set(changed)-allowed_mods))
 paths=changed+['src/winai_loseai/experiments/komi_pass_pilot.py','tests/test_komi_engine_m6.py','tests/test_komi_pass_pilot_m6.py','scripts/run_komi_pass_pilot.py','scripts/measure_komi_pass_pilot_chunk.py','scripts/verify_komi_pass_reproduction.py','scripts/validate_komi_checkpoint.py','scripts/prepare_komi_pass_pilot_sync.py','experiments/komi_pass_pilot_v1']
 git('add','--',*paths)
 if (ROOT/'outputs/komi_pass_pilot_v1').exists():git('add','-f','--','outputs/komi_pass_pilot_v1')
 names=git('diff','--cached','--name-only','--diff-filter=ACM').splitlines()
 if names!=git('diff','--cached','--name-only').splitlines():raise ValueError('Deletion or type changes forbidden')
 if any(p.lower().endswith(('.md','.pyc')) for p in names):raise ValueError('Narrative Markdown and bytecode prohibited')
 if any(p.startswith('outputs/') and not p.startswith('outputs/komi_pass_pilot_v1/') for p in names):raise ValueError('Historical output forbidden')
 entries=[]
 for path in names:
  mode,sha,_=git('ls-files','--stage','--',path).split(maxsplit=2);data=subprocess.check_output(['git','show',':'+path],cwd=ROOT)
  entries.append({'path':path,'mode':mode,'type':'blob','sha':sha,'bytes':len(data)})
 print(json.dumps({'parent':git('rev-parse','HEAD'),'base_tree':git('rev-parse','HEAD^{tree}'),'expected_tree':git('write-tree'),'entries':entries}))
if __name__=='__main__':main()
