"""One non-blocking resource/progress snapshot; append to reports/monitor.jsonl."""
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import psutil

root=Path(__file__).resolve().parents[1]
out=root/sys.argv[1]
manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
files=list((out/'games').glob('*.json'))
processes=[]
for p in psutil.process_iter(['pid','name','cmdline','memory_info','cpu_times']):
    try:
        if p.info['name'] and 'python' in p.info['name'].lower():
            cmd=' '.join(p.info['cmdline'] or [])
            if 'run.py batch' in cmd or 'multiprocessing.spawn' in cmd:
                processes.append({'pid':p.pid,'rss_mb':round(p.info['memory_info'].rss/2**20,1),
                                  'cpu_seconds':round(sum(p.info['cpu_times'][:2]),1)})
    except (psutil.Error,TypeError):pass
snapshot={'time':datetime.now(timezone.utc).isoformat(),'run':out.name,
          'status':manifest['status'],'manifest_completed':manifest['completed_game_count'],
          'saved_games':len(files),'error':manifest.get('error'),
          'game_files_mb':round(sum(p.stat().st_size for p in files)/2**20,2),
          'disk_free_gb':round(shutil.disk_usage(root).free/2**30,2),
          'available_memory_gb':round(psutil.virtual_memory().available/2**30,2),
          'processes':processes}
with (root/'reports/monitor.jsonl').open('a',encoding='utf-8') as f:
    f.write(json.dumps(snapshot)+'\n')
print(json.dumps(snapshot))
