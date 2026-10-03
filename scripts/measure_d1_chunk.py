"""Measure one six-game D1 subprocess; each child has independent rusage.

Linux os.wait4 reports that exact child's peak RSS (KiB), including resume,
validation, and imports. It is not per-game incremental or exclusive MCTS RSS.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',required=True);ap.add_argument('--evidence',required=True);ap.add_argument('--chunk',type=int,required=True)
    args=ap.parse_args();out=Path(args.out);dest=Path(args.evidence);dest.mkdir(parents=True,exist_ok=True)
    prefix=dest/f'chunk_{args.chunk:02d}'
    cost=prefix.with_suffix('.json')
    if cost.exists():raise FileExistsError('never overwrite measured chunk evidence')
    before=json.loads((out/'manifest.json').read_text())['completed_game_count'] if (out/'manifest.json').exists() else 0
    command=[sys.executable,str(ROOT/'scripts/run_d1.py'),'run','--out',str(out),'--concurrency','1','--stop-after','6']
    if before or (out/'manifest.json').exists():command.append('--resume')
    started=datetime.now(timezone.utc).isoformat();t=time.perf_counter()
    with prefix.with_suffix('.stdout.txt').open('w') as stdout,prefix.with_suffix('.stderr.txt').open('w') as stderr:
        child=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        _,status,usage=os.wait4(child.pid,0);child.returncode=os.waitstatus_to_exitcode(status)
    elapsed=time.perf_counter()-t
    manifest=json.loads((out/'manifest.json').read_text()) if (out/'manifest.json').exists() else {}
    evidence={'chunk':args.chunk,'command':command,'started_utc':started,'ended_utc':datetime.now(timezone.utc).isoformat(),
        'exit_code':child.returncode,'wall_seconds':elapsed,'cpu_user_seconds':usage.ru_utime,'cpu_system_seconds':usage.ru_stime,
        'peak_process_rss_kib':usage.ru_maxrss,'completed_before':before,'completed_after':manifest.get('completed_game_count'),
        'status_after':manifest.get('status'),'output_tree_bytes_after':sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),
        'measurement_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Exact isolated child process: run/import/resume/per-game validation/final analysis; no Git sync, tests, or external full verification.'}
    tmp=cost.with_suffix('.json.tmp');tmp.write_text(json.dumps(evidence,indent=2)+'\n');tmp.replace(cost)
    print(json.dumps(evidence,indent=2),flush=True)
    return 0 if child.returncode in (0,75) else child.returncode

if __name__=='__main__':raise SystemExit(main())
