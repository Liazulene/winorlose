"""Read-only byte inventory of existing worktrees; writes only audit evidence.
Do not invoke legacy verification CLI scripts that overwrite historical evidence.
"""
import argparse,datetime,hashlib,json,os,pathlib,subprocess
from inventory_io import pack
BASE=pathlib.Path(__file__).resolve().parents[4]
ROOTS=['winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1','winorlose_g1_pass8_v1']
def git(root,*args): return subprocess.check_output(['git',*args],cwd=root)
def snapshot(root):
    entries=[e.split(b'\t',1) for e in git(root,'ls-tree','-rz','--full-tree','HEAD').split(b'\0') if e]
    proc=subprocess.Popen(['git','cat-file','--batch'],cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    records=[]
    for meta,name in entries:
        mode,typ,oid=meta.split(); rel=os.fsdecode(name); p=root/rel
        if typ!=b'blob': raise ValueError(f'Unexpected tracked object {typ!r} {rel}')
        proc.stdin.write(oid+b'\n'); proc.stdin.flush(); hdr=proc.stdout.readline().split(); size=int(hdr[-1]); head=proc.stdout.read(size); assert proc.stdout.read(1)==b'\n'
        actual=os.fsencode(os.readlink(p)) if mode==b'120000' and p.is_symlink() else p.read_bytes() if p.is_file() else None
        records.append({'path':rel,'mode':mode.decode(),'git_blob':oid.decode(),'head_size':size,'head_sha256':hashlib.sha256(head).hexdigest(),'actual_size':None if actual is None else len(actual),'actual_sha256':None if actual is None else hashlib.sha256(actual).hexdigest(),'matches_head':actual==head})
    proc.stdin.close(); proc.wait()
    diffs=[x for x in records if not x['matches_head']]
    return {'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'root':str(root),'head':git(root,'rev-parse','HEAD').decode().strip(),'tracked_files':len(records),'all_tracked_bytes_match_head':not diffs,'differences':diffs,'inventory_sha256':hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'records':records,'limitations':'Post-restoration snapshot. This establishes present tracked bytes only, not that no earlier writes occurred. Untracked files are outside tracked-byte inventory.'}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--label',default='prelaunch');args=ap.parse_args();out=pathlib.Path(__file__).resolve().parent
    results=[]
    for name in ROOTS:
        r=snapshot(BASE/name); target=out/f'{args.label}_{name}_tracked_inventory.json';raw=(json.dumps(r,ensure_ascii=False,indent=2)+'\n').encode();pack(raw,target); summary={k:v for k,v in r.items() if k!='records'};results.append(summary);print(json.dumps(summary),flush=True)
    (out/f'{args.label}_inventory_summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__': main()
