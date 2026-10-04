"""Read-only protected-file checks; write only explicitly named new audit evidence.

No historical CLI is imported or executed. Run with PYTHONDONTWRITEBYTECODE=1.
Detailed snapshots belong outside every experiment worktree.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OLD_NAMES = ('winorlose', 'winorlose_d0_v1', 'winorlose_d1_v1',
             'winorlose_d1_estimation_v1', 'winorlose_g1_pass8_v1',
             'winorlose_g1_pass8_estimation_v1')
ROOT_DOCS = {'5x5_mvp_spec.md', 'winai_loseai_go_experiment_notes_v2.md',
             'AMBIGUITIES.md', 'README.md', 'AGENTS.md'}
NEW_DIR = 'experiments/komi_pass_pilot_v1'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',',':')).encode()).hexdigest()

def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

def tracked(root):
    return subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode().split('\0')[:-1]

def inherited(path):
    return path in ROOT_DOCS or (path.split('/')[0] in {'outputs','reports','experiments','handoff'}
                                and not path.startswith(NEW_DIR+'/'))

def inventory():
    result = {}
    for name in OLD_NAMES:
        root=ROOT.parent/name
        paths=tracked(root)
        files={p:sha(root/p) for p in paths}
        result[str(root)]={'kind':'all_old_worktree_tracked_files','head':git(root,'rev-parse','HEAD'),
                           'files':files, 'all_non_git_files':[str(p.relative_to(root)) for p in sorted(root.rglob('*'))
                                      if p.is_file() and '.git' not in p.relative_to(root).parts]}
    paths=[p for p in tracked(ROOT) if inherited(p)]
    # Baseline is inherited tracked input; separately retain complete file sets
    # within inherited directories so accidental caches cannot go unnoticed.
    directories=sorted({p.rsplit('/',1)[0] for p in paths if '/' in p})
    roots={str(Path(p).parts[0] / Path(Path(p).parts[1])) if False else '/'.join(Path(p).parts[:2])
           for p in paths if len(Path(p).parts)>1 and Path(p).parts[0] in {'outputs','experiments'}}
    roots.update({'reports','handoff'})
    strict_files=sorted({str(p.relative_to(ROOT)) for d in roots for p in (ROOT/d).rglob('*') if p.is_file()})
    result[str(ROOT)]={'kind':'inherited_historical_directories_and_five_root_docs',
                      'base_head':git(ROOT,'rev-parse','HEAD'),'files':{p:sha(ROOT/p) for p in paths},
                      'strict_directory_roots':sorted(roots),'strict_directory_files':strict_files}
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--baseline',required=True);ap.add_argument('--report',required=True);ap.add_argument('--create',action='store_true');a=ap.parse_args()
    baseline=Path(a.baseline);report=Path(a.report)
    if report.exists():raise SystemExit('Refusing to replace existing audit report')
    now=datetime.now(timezone.utc).isoformat()
    if a.create:
        if baseline.exists():raise SystemExit('Refusing to replace existing preservation baseline')
        data=inventory();baseline.write_text(json.dumps(data,sort_keys=True)+'\n')
        problems=[];mode='capture_before'
    else:
        data=json.loads(baseline.read_text());problems=[];mode='check_after'
        for root_name,info in data.items():
            root=Path(root_name)
            for rel,expected in info['files'].items():
                path=root/rel
                if not path.is_file():problems.append({'root':root_name,'path':rel,'problem':'missing'})
                elif sha(path)!=expected:problems.append({'root':root_name,'path':rel,'problem':'changed'})
            if info['kind']=='all_old_worktree_tracked_files':
                if sorted(tracked(root))!=sorted(info['files']):problems.append({'root':root_name,'problem':'tracked_path_set_changed'})
                if git(root,'rev-parse','HEAD')!=info['head']:problems.append({'root':root_name,'problem':'head_changed'})
                found=[str(p.relative_to(root)) for p in sorted(root.rglob('*')) if p.is_file() and '.git' not in p.relative_to(root).parts]
                if found!=info['all_non_git_files']:problems.append({'root':root_name,'problem':'all_file_set_changed','added':sorted(set(found)-set(info['all_non_git_files'])),'missing':sorted(set(info['all_non_git_files'])-set(found))})
            else:
                found=sorted({str(p.relative_to(root)) for d in info['strict_directory_roots'] for p in (root/d).rglob('*') if p.is_file()})
                if found!=info['strict_directory_files']:problems.append({'root':root_name,'problem':'strict_historical_file_set_changed','added':sorted(set(found)-set(info['strict_directory_files'])),'missing':sorted(set(info['strict_directory_files'])-set(found))})
    summary={'check':mode,'utc':now,'passed':not problems,'problems':problems,'baseline_path':str(baseline),
             'baseline_sha256':sha(baseline),'checker_sha256':sha(__file__),
             'coverage':[{'worktree':k,'kind':v['kind'],'tracked_file_count':len(v['files']),
                          'file_hash_inventory_sha256':canonical_sha(v['files'])} for k,v in data.items()],
             'limitations':['Before/after byte and file-set preservation, not proof that no temporary intermediate write occurred.',
                            'Historical tracked files are hashed as actual bytes; nontracked old files receive file-set checks only.',
                            'No historical validation CLI or experiment execution is called.']}
    report.write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n');print(json.dumps(summary,indent=2));return int(bool(problems))

if __name__=='__main__':raise SystemExit(main())
