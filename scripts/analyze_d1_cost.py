"""Read-only D1 calibration analysis; never invokes historical formal validators."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from winai_loseai.experiments.d1 import analyze,atomic_json,distribution,protocol

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--cost-dir',required=True);ap.add_argument('--dest',required=True);args=ap.parse_args()
    out=Path(args.out);p=protocol();a=analyze(out)
    chunks=[json.loads(f.read_text()) for f in sorted(Path(args.cost_dir).glob('chunk_*.json'))]
    by_budget={}
    per_budget=p['planned_games']//len(p['budgets'])
    for i,budget in enumerate(p['budgets']):
        cc=[c for c in chunks if i*per_budget<=c['completed_before']<(i+1)*per_budget]
        rr=[r for r in a['rows'] if r['budget']==budget]
        by_budget[str(budget)]={'n':len(rr),'chunks':len(cc),'measured_wall_seconds':sum(c['wall_seconds'] for c in cc),
            'measured_cpu_seconds':sum(c['cpu_user_seconds']+c['cpu_system_seconds'] for c in cc),
            'peak_process_rss_kib':max((c['peak_process_rss_kib'] for c in cc),default=None),
            'game_seconds':distribution([r['game_wall_ms']/1000 for r in rr]),
            'search_seconds_sum':sum(sum(r['search_times_ms']) for r in rr)/1000,
            'search_ms_per_move':distribution([t for r in rr for t in r['search_times_ms']]),
            'length':distribution([r['move_count'] for r in rr]),
            'game_output_bytes':sum(r['game_bytes'] for r in rr),
            'planned_checkpoint_exits':sum(c['exit_code']==75 for c in cc),
            'unplanned_failed_chunk_exits':sum(c['exit_code'] not in (0,75) for c in cc)}
    total=sum(c['wall_seconds'] for c in chunks)
    costs={'experiment_id':p['experiment_id'],'complete':a['n_records']==p['planned_games'],
        'by_budget':by_budget,'total_measured_wall_seconds':total,'total_cpu_seconds':sum(c['cpu_user_seconds']+c['cpu_system_seconds'] for c in chunks),
        'formal_elapsed_seconds_including_sync_and_gaps':(datetime.fromisoformat(chunks[-1]['ended_utc'])-datetime.fromisoformat(chunks[0]['started_utc'])).total_seconds(),
        'formal_output_bytes':sum(f.stat().st_size for f in out.rglob('*') if f.is_file()),
        'chunks':chunks,'projection_1800_base_seconds':total*25,'projection_1800_plus50pct_seconds':total*25*1.5,
        'projection_scope':'Linear25x72 measured child runtime, including imports/resume/replay/analysis overhead of12 chunks. ExtraGitHub sync, final audit/reproduction, host drift and uncertain rare tails are not included.50%is planning allowance,not statistical confidence.',
        'analysis_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    atomic_json(args.dest,costs);print(json.dumps({k:v for k,v in costs.items() if k!='chunks'},indent=2))
    return 0
if __name__=='__main__':raise SystemExit(main())
