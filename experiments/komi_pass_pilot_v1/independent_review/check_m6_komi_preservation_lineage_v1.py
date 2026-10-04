"""Verify new preservation baseline against immutable M5 evidence; no game writes."""
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
EVIDENCE=ROOT/'experiments/g1_pass8_estimation_v1/independent_review'
BASELINE=ROOT.parent/'winorlose_reports/komi_pass_pilot_preservation_v1/before_inventory.json'

def digest(data):return hashlib.sha256(data).hexdigest()

def run():
    baseline=json.loads(BASELINE.read_text());problems=[];checks=[]
    for root,info in baseline.items():
        name=Path(root).name
        if name in ('winorlose_komi_pass_pilot_v1','winorlose_g1_pass8_estimation_v1'):continue
        path=EVIDENCE/f'prelaunch_{name}_tracked_inventory.json.segments.json'
        manifest=json.loads(path.read_text());chunks=[]
        for part in manifest['parts']:
            raw=(path.parent/part['name']).read_bytes()
            if len(raw)!=part['bytes'] or digest(raw)!=part['sha256']:problems.append('segment integrity '+part['name'])
            chunks.append(raw)
        zipped=b''.join(chunks);raw=gzip.decompress(zipped)
        if len(zipped)!=manifest['gzip_bytes'] or digest(zipped)!=manifest['gzip_sha256']:problems.append('gzip integrity '+name)
        if len(raw)!=manifest['raw_bytes'] or digest(raw)!=manifest['raw_sha256']:problems.append('raw inventory integrity '+name)
        old=json.loads(raw);expected={r['path']:r['actual_sha256'] for r in old['records']}
        if expected!=info['files']:problems.append('M5 previous inventory differs '+name)
        if old['head']!=info['head']:problems.append('historical HEAD differs '+name)
        checks.append({'worktree':name,'files':len(expected),'source':str(path.relative_to(ROOT)),
                       'raw_inventory_sha256':digest(raw),'same_file_map_and_head':expected==info['files'] and old['head']==info['head']})
    m5=ROOT.parent/'winorlose_g1_pass8_estimation_v1'
    dirty=subprocess.check_output(['git','-C',str(m5),'diff','HEAD','--name-only'],env={'PATH':'/usr/bin:/bin','GIT_OPTIONAL_LOCKS':'0'},text=True).splitlines()
    if dirty:problems.append('M5 tracked paths differ from HEAD '+str(dirty))
    m5info=baseline[str(m5)]
    if m5info['head']!='23f61f99a3e0ef0374b95c8df41c1e52f7f73ae1':problems.append('M5 baseline must be final accepted commit')
    inherited=baseline[str(ROOT)]['files']
    inherited_mismatch=[p for p,v in inherited.items() if m5info['files'].get(p)!=v]
    if inherited_mismatch:problems.append('new inherited bytes differ from M5 '+str(inherited_mismatch))
    checks.append({'worktree':m5.name,'files':len(m5info['files']),'source_commit':m5info['head'],'tracked_diff_from_head':dirty})
    checks.append({'worktree':ROOT.name,'files':len(inherited),'same_as_final_M5_inherited_subset':not inherited_mismatch})
    return {'utc':datetime.now(timezone.utc).isoformat(),'passed':not problems,'problems':problems,'checks':checks,
            'baseline_sha256':digest(BASELINE.read_bytes()),'checker_sha256':digest(Path(__file__).read_bytes()),
            'limitations':['References existing immutable M5 segmented inventories for the first five trees rather than storing duplicate inventories in Git.',
                          'The new M5 whole-tree baseline is tied to accepted commit23f61f99; all inherited protected paths in M6 match that baseline.',
                          'Byte/file-set preservation does not imply no transient historical writes.']}

if __name__=='__main__':
    d=run();p=Path(sys.argv[1]);
    if p.exists():raise SystemExit('Refusing to replace prior evidence')
    p.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n');print(json.dumps(d,indent=2));raise SystemExit(int(bool(d['problems'])))
