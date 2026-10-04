"""Post-run resource summary for fixed720 estimation; refuses incomplete data."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.experiments.d1_estimation import cells,distribution,protocol,sha256,assert_output_allowed

def summarize(root=ROOT):
    p=protocol();e=root/'experiments/d1_estimation_v1';out=root/'outputs/d1_g0_estimation_v1'
    m=json.loads((out/'manifest.json').read_text());a=json.loads((out/'analysis.json').read_text())
    assert m['status']=='completed' and m['completed_game_count']==720 and a['n_records']==720
    chunks=[json.loads((e/'cost'/f'chunk_{i:02d}.json').read_text()) for i in range(1,31)]
    for i,c in enumerate(chunks,1):
        v=json.loads((e/'cost'/f'check_{i:02d}.json').read_text())
        assert c['completed_before']==24*(i-1) and c['completed_after']==24*i and c['exit_code']==(0 if i==30 else 75)
        assert not v['problems'] and v['game_count']==v['replay_and_search_ok']==24*i
    pilot=json.loads((root/'experiments/d1_cost_v1/execution_cost.json').read_text())
    by_budget={}
    for j,b in enumerate(p['budgets']):
        cc=chunks[j*10:(j+1)*10];rr=[r for r in a['rows'] if r['budget']==b]
        wall=sum(c['wall_seconds'] for c in cc);cpu=sum(c['cpu_user_seconds']+c['cpu_system_seconds'] for c in cc)
        old=pilot['by_budget'][str(b)]['measured_wall_seconds']*10
        by_budget[str(b)]={'n':len(rr),'chunks':len(cc),'child_wall_seconds':wall,'child_cpu_seconds':cpu,
            'cpu_wall_ratio':cpu/wall,'peak_child_rss_kib':max(c['peak_process_rss_kib'] for c in cc),
            'game_seconds':distribution([r['game_wall_ms']/1000 for r in rr]),
            'game_wall_seconds_sum':sum(r['game_wall_ms']/1000 for r in rr),
            'search_seconds_sum':sum(sum(r['search_times_ms']) for r in rr)/1000,
            'game_bytes':sum(r['game_bytes'] for r in rr),'pilot_scaled_child_wall_seconds':old,'actual_to_pilot_scaled_ratio':wall/old}
    gaps=[{'after_chunk':i,'seconds':(datetime.fromisoformat(chunks[i]['started_utc'])-datetime.fromisoformat(chunks[i-1]['ended_utc'])).total_seconds()} for i in range(1,30)]
    assert all(g['seconds']>=0 for g in gaps)
    elapsed=(datetime.fromisoformat(chunks[-1]['ended_utc'])-datetime.fromisoformat(chunks[0]['started_utc'])).total_seconds()
    return {'experiment_id':p['experiment_id'],'complete':True,'by_budget':by_budget,
        'total_child_wall_seconds':sum(c['wall_seconds'] for c in chunks),
        'total_child_cpu_seconds':sum(c['cpu_user_seconds']+c['cpu_system_seconds'] for c in chunks),
        'first_child_started_utc':chunks[0]['started_utc'],'last_child_ended_utc':chunks[-1]['ended_utc'],
        'formal_elapsed_seconds_including_interchunk_sync_approval_and_gaps':elapsed,'interchunk_gaps':gaps,
        'interchunk_seconds_sum':sum(g['seconds'] for g in gaps),'largest_interchunk_gap':max(gaps,key=lambda g:g['seconds']),
        'unplanned_game_failures':0,'planned_checkpoint_exits':29,'output_tree_bytes':sum(x.stat().st_size for x in out.rglob('*') if x.is_file()),
        'scope':'Child wall/CPU/RSS includes run/import/resume/checks/final analysis, excludes GitHub sync, external validators, final tests and supplementary regeneration. Formal elapsed stops at final child exit, not final backup/report. Largest22to23 gap includes platform approval wait plus surrounding checkpoint operations; not all gap seconds are pure approval time. Pilot projections are planning references, not confidence bounds.',
        'analysis_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--dest',required=True);args=ap.parse_args();dest=assert_output_allowed(args.dest)
    if dest.exists():raise FileExistsError('new resource evidence destination required')
    result=summarize();dest.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('complete','total_child_wall_seconds','total_child_cpu_seconds','formal_elapsed_seconds_including_interchunk_sync_approval_and_gaps','largest_interchunk_gap')},indent=2))
if __name__=='__main__':main()
