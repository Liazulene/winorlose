"""Read-only historical recheck. Creates only a distinct independent audit JSON."""
import datetime, hashlib, json, os
from pathlib import Path
import subprocess
from inventory_io import load, read_raw
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2];BASE=ROOT.parent
EXTERNAL=BASE/'winorlose_reports/M5_support/inventories'
NAMES=['winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1','winorlose_g1_pass8_v1']
def sha(b): return hashlib.sha256(b).hexdigest()
def protected(path):
    return path.startswith(('outputs/','reports/','experiments/','handoff/')) or path in ('5x5_mvp_spec.md','winai_loseai_go_experiment_notes_v2.md','AMBIGUITIES.md','README.md','AGENTS.md')
def check(name, new=False):
    invfile=HERE/f'prelaunch_{name}_tracked_inventory.json.segments.json'
    raw=read_raw(invfile);external=read_raw(EXTERNAL/f'prelaunch_{name}_tracked_inventory.json.gz')
    baseline=json.loads(raw);root=ROOT if new else BASE/name
    selected=[r for r in baseline['records'] if protected(r['path'])] if new else baseline['records']
    problems=[];current=[];byte_count=0
    if raw!=external:problems.append('segmented/external inventory bytes differ')
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip()
    if head!=baseline['head']:problems.append('HEAD differs from baseline')
    for r in selected:
        p=root/r['path']
        content=os.fsencode(os.readlink(p)) if r['mode']=='120000' and p.is_symlink() else p.read_bytes() if p.is_file() else None
        digest=None if content is None else sha(content);size=None if content is None else len(content)
        if digest!=r['actual_sha256'] or size!=r['actual_size']:problems.append({'path':r['path'],'current_sha256':digest,'baseline_sha256':r['actual_sha256'],'current_bytes':size,'baseline_bytes':r['actual_size']})
        current.append((r['path'],digest,size));byte_count+=size or 0
    # File-set audit for historical directories catches added files, not just modifications.
    expected={r['path'] for r in baseline['records'] if protected(r['path'])}
    actual={p.relative_to(root).as_posix() for prefix in ('outputs','reports','experiments','handoff') for p in (root/prefix).rglob('*') if p.is_file() or p.is_symlink()}
    actual|={p for p in expected if '/' not in p and (root/p).is_file()}
    if new:actual={p for p in actual if not p.startswith(('experiments/g1_pass8_estimation_v1/','outputs/g1_pass8_estimation_v1/'))}
    extra=sorted(actual-expected);missing=sorted(expected-actual)
    if extra or missing:problems.append({'historical_file_set_extra':extra,'historical_file_set_missing':missing})
    return {'worktree':str(root),'baseline_inventory':str(invfile),'baseline_raw_sha256':sha(raw),'external_gzip_matches_segmented_raw':raw==external,'head':head,'selected_files':len(selected),'checked_bytes':byte_count,'current_path_hash_size_inventory_sha256':sha(json.dumps(current,separators=(',',':')).encode()),'scope':'inherited historical paths' if new else 'all previously tracked paths plus historical directory file-set check','historical_file_set_extra':extra,'historical_file_set_missing':missing,'problems':problems}
def main():
    checks=[check(n) for n in NAMES]+[check(NAMES[-1],True)]
    original=read_raw(HERE/'original_tracked_head_inventory.json.segments.json')
    external=read_raw(EXTERNAL/'original_tracked_head_inventory.json.gz')
    result={'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'script_sha256':sha(Path(__file__).read_bytes()),'checks':checks,'original_inventory_copies_identical':original==external,'all_passed':all(not x['problems'] for x in checks) and original==external,'limitations':['This establishes present bytes against the inventories and historical file sets, not absence of prior writes before the recorded restoration.','No legacy validation CLI or production experiment is executed.','New M5 evidence and new production output are outside protected historical paths.']}
    dest=HERE/'resume20261004_historical_preservation.json';dest.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return not result['all_passed']
if __name__=='__main__':raise SystemExit(main())
