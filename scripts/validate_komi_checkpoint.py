"""Strict M6 checkpoint verification with no experiment generation."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.experiments import komi_pass_pilot as g

def main():
 out=ROOT/'outputs/komi_pass_pilot_v1';manifest=json.loads((out/'manifest.json').read_text())
 n=manifest['completed_game_count']
 if n not in (24,48,72,96):raise ValueError('Expected a registered 24-game checkpoint')
 result=g.validate(out,require_complete=n==96)
 if result['problems'] or result['game_count']!=n or result['replay_and_search_ok']!=n:raise ValueError(result)
 if result['manifest_status']!=('completed' if n==96 else 'interrupted'):raise ValueError('Unexpected checkpoint status')
 g.atomic_json(out/'validation.json',result)
 cost=[json.loads(p.read_text()) for p in (ROOT/'experiments/komi_pass_pilot_v1/cost').glob('chunk_*.json')]
 print(json.dumps({'completed':n,'planned':96,'replay_and_search_ok':result['replay_and_search_ok'],'manifest_status':result['manifest_status'],
   'source_fingerprint':result['source_fingerprint'],'child_wall_seconds':sum(x['wall_seconds'] for x in cost),'problems':result['problems']}))
if __name__=='__main__':main()
