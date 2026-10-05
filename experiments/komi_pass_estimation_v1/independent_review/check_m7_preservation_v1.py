"""Read-only compact preservation audit; immutable M6 evidence plus trusted Git base.
Writes only a new explicitly named report. Never imports/exercises historical code.
"""
import argparse, hashlib, json, subprocess
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[3]
BASE='c7ce77c4'
NAMES=('winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1','winorlose_g1_pass8_v1','winorlose_g1_pass8_estimation_v1','winorlose_komi_pass_pilot_v1')
REF=ROOT.parent/'winorlose_reports/komi_pass_pilot_preservation_v1/before_inventory.json'
REF_SHA='90a382be7e8131fd9bd86dc1d90c50b173007cfb3739c0bfa3430ac5159b297c'
EXCEPTIONS={'src/winai_loseai/__init__.py','conftest.py'}
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def obj(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()
def files(root):return sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts)
def trees(root,base):
    entries=subprocess.check_output(['git','-C',str(root),'ls-tree','-rz',base]).split(b'\0')
    return {e.split(b'\t',1)[1].decode():e.split(b'\t',1)[0].split()[2].decode() for e in entries if e}
def blob(p):
    b=p.read_bytes();return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def run(before=None):
    refsha=digest(REF);assert refsha==REF_SHA,'M6 reference inventory changed'
    historical=json.loads(REF.read_text());out=[];problems=[]
    for name in NAMES:
        root=ROOT.parent/name;head=git(root,'rev-parse','HEAD');tracked=git(root,'ls-files','-z').split('\0');tracked=[p for p in tracked if p]
        allfiles=files(root);info=historical.get(str(root)); changed=[]
        if name!=NAMES[-1]:
            expected=info['files'];mode='actual_sha256_against_immutable_M6_inventory'
            changed=[p for p,s in expected.items() if not (root/p).is_file() or digest(root/p)!=s]
            if head!=info['head']:problems.append(name+': HEAD changed since M6')
            if sorted(tracked)!=sorted(expected):problems.append(name+': tracked set changed since M6')
            if allfiles!=sorted(info['all_non_git_files']):problems.append(name+': file set changed since M6')
        else:
            expected=trees(ROOT,BASE);mode='actual_Git_blob_bytes_against_accepted_M6_commit'
            changed=[p for p,s in expected.items() if not (root/p).is_file() or blob(root/p)!=s]
            if head!=git(ROOT,'rev-parse',BASE):problems.append(name+': accepted HEAD mismatch')
            if sorted(tracked)!=sorted(expected):problems.append(name+': tracked set mismatch')
        if changed:problems.append({'tree':name,'changed':changed})
        out.append({'worktree':name,'head':head,'comparison':mode,'tracked_file_count':len(expected),'tracked_reference_map_sha256':obj(expected),'all_non_git_file_count':len(allfiles),'all_non_git_file_set_sha256':obj(allfiles),'changed':changed})
    expected=trees(ROOT,BASE);changed={p:{'base_blob':s,'actual_blob':blob(ROOT/p) if (ROOT/p).is_file() else None} for p,s in expected.items() if not (ROOT/p).is_file() or blob(ROOT/p)!=s}
    unauthorized={p:v for p,v in changed.items() if p not in EXCEPTIONS}
    if unauthorized:problems.append({'new_tree_inherited_changes_outside_allowed_adapters':unauthorized})
    inherited_roots=sorted({str(Path(p).parts[0]+'/'+Path(p).parts[1]) for p in expected if p.startswith(('outputs/','experiments/'))}|{'reports','handoff'})
    strict=sorted({str(p.relative_to(ROOT)) for d in inherited_roots for p in (ROOT/d).rglob('*') if p.is_file()})
    new={'base_commit':git(ROOT,'rev-parse',BASE),'inherited_tracked_file_count':len(expected),'reference_map_sha256':obj(expected),'all_inherited_changes':changed,'allowed_adapter_paths':sorted(EXCEPTIONS),'inherited_strict_file_count':len(strict),'inherited_strict_file_set_sha256':obj(strict)}
    if before:
        b=json.loads(Path(before).read_text())
        for left,right in zip(b['old_worktrees'],out):
            for k in ('head','tracked_file_count','tracked_reference_map_sha256','all_non_git_file_count','all_non_git_file_set_sha256'):
                if left[k]!=right[k]:problems.append({'worktree':right['worktree'],'before_after_changed':k})
        for k in ('inherited_strict_file_count','inherited_strict_file_set_sha256'):
            if b['new_worktree'][k]!=new[k]:problems.append({'new_worktree_before_after_changed':k})
    return {'audit':'M7 compact preservation v1','utc':datetime.now(timezone.utc).isoformat(),'passed':not problems,'problems':problems,'old_worktrees':out,'new_worktree':new,'reference':{'path':str(REF),'sha256':refsha,'M6_final_check_path':'experiments/komi_pass_pilot_v1/independent_review/final_after_backup_preservation_v1.json','M6_final_check_sha256':digest(ROOT/'experiments/komi_pass_pilot_v1/independent_review/final_after_backup_preservation_v1.json')},'checker_sha256':digest(__file__),'before_report_sha256':digest(before) if before else None,'limitations':['Byte and file-set checks cannot exclude temporary intermediate writes.','Existing nontracked historical files are covered by file-set preservation, not bytes.','Only explicitly listed version/conftest adapter files may differ from M6 in the new worktree; their content is reviewed separately.']}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--before');p.add_argument('--out',required=True);a=p.parse_args();dest=Path(a.out)
    if dest.exists():raise SystemExit('Refusing existing evidence')
    r=run(a.before);dest.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps(r,indent=2));raise SystemExit(int(not r['passed']))
