"""Read-only verification of new fixed design and pilot/history RNG isolation."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from winai_loseai.experiments import d1_estimation as d
from winai_loseai.rng import seed_from_key

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=d.protocol();jj=d.jobs();cc=d.cells();problems=[]
    seedset={j['game_seed'] for j in jj}
    if len(jj)!=720 or len(seedset)!=240:problems.append('wrong fixed plan count')
    if p['budgets']!=[64,256,1024] or p['batch_seeds']!=[5,6,7] or p['games_per_cell']!=10:problems.append('wrong registered factors')
    blocks={}
    for j,c in zip(jj,cc):
        blocks.setdefault(c['block_id'],[]).append(j)
        if j['black'].simulations()!=c['budget'] or j['white'].simulations()!=c['budget']:problems.append('unequal budgets')
    for block,rows in blocks.items():
        if len(rows)!=3 or len({j['game_seed'] for j in rows})!=1:problems.append('bad paired block '+block)
    keys=sorted({seed_from_key('agent-stream',j['game_seed'],colour,j[colour].seed) for j in jj for colour in ('black','white')})
    if len(keys)!=480:problems.append('derived RNG collision or missing stream')
    comparisons={}
    for name in ('batch_A_seed0','batch_B_shallow_seed0','batch_B_shallow_seed1','d1_g0_cost_v1'):
        path=ROOT/'outputs'/name/'game_seeds.json';value=json.loads(path.read_text())
        old={r['game_seed'] for r in value};overlap=sorted(seedset&old)
        old_plan=json.loads((path.parent/'plan.json').read_text())
        old_streams={seed_from_key('agent-stream',r['game_seed'],colour,r[colour]['seed']) for r in old_plan for colour in ('black','white')}
        stream_overlap=sorted(set(keys)&old_streams)
        if stream_overlap:problems.append('derived RNG overlap '+name)
        comparisons[name]={'registered_records':len(value),'distinct_game_seeds':len(old),'overlap':overlap,'derived_stream_overlap':stream_overlap,'distinct_old_streams':len(old_streams),'seed_file_sha256':d.sha256(path)}
        if overlap:problems.append('game stream overlap '+name)
    # The unchanged RNG generator keys game seed, colour, agent seed. Unique
    # game seeds imply stream keys are disjoint; record the explicit hash keys.
    keys=sorted({seed_from_key("agent-stream",j["game_seed"],colour,j[colour].seed) for j in jj for colour in ("black","white")})
    out={'experiment_id':p['experiment_id'],'planned_games':len(jj),'paired_blocks':len(blocks),'distinct_game_seeds':len(seedset),
         'distinct_colour_agent_keys':len(keys),'key_inventory_sha256':hashlib.sha256(json.dumps(keys).encode()).hexdigest(),
         'comparisons':comparisons,'problems':problems}
    print(json.dumps(out,indent=2));return bool(problems)

if __name__=='__main__':raise SystemExit(main())
