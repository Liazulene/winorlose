"""Independently reconstruct the fixed480 schedule and initial streams.
Read-only verification; report files alone are written in independent_review.
"""
import argparse,collections,datetime,hashlib,json,pathlib,random,sys
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
def digest(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def seed(*parts):return int.from_bytes(hashlib.sha256('|'.join(map(str,parts)).encode()).digest()[:16],'big')
def reconstruct(p):
    blocks=[]
    for batch in (11,12,13):
        for block in range(80):
            direction,within=divmod(block,20);orientation,replicate=divmod(within,10)
            ib,iw=p['identity_directions'][direction];sb,sw=p['agent_seed_orientations'][orientation]
            blocks.append(dict(budget=256,batch_seed=batch,black_identity=ib,white_identity=iw,black_seed=sb,white_seed=sw,replicate=replicate,block_index=block,block_id=f'{batch}:{block}'))
    rng=random.Random(p['schedule_seed']);rng.shuffle(blocks)
    order=[[0,8],[8,0]]*120;rng.shuffle(order)
    cells=[];plan=[]
    for block,arms in zip(blocks,order):
        for rule in arms:
            cells.append(dict(block,pass_min_ply=rule,ruleset='G0' if rule==0 else 'G1-pass8'))
            entry=dict(index=len(plan),game_seed=seed('game-seed',block['batch_seed'],block['block_index']),pass_min_ply=rule)
            for color in ('black','white'):
                ident=block[color+'_identity'];individual=block[color+'_seed']
                entry[color]=dict(agent_id=f'{ident}-medium-s{individual}',identity=ident,algorithm='vector_mcts',compute_level='medium',seed=individual)
            plan.append(entry)
    return cells,plan

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--label',default='final');args=ap.parse_args()
    from winai_loseai.experiments import g1_pass8_estimation as g
    p=g.protocol();problems=[]
    expected={'experiment_id':'G1-pass8-estimation-v1','batch_id':'g1_pass8_estimation_v1','parent_commit':'e28833c388438f33d49dbbde90ae63b6e3a4a0cb','board_size':5,'komi':2.5,'budget':256,'pass_min_plies':[0,8],'batch_seeds':[11,12,13],'games_per_cell':10,'planned_games':480,'agent_seed_orientations':[[1,2],[2,1]],'identity_directions':[['WIN','WIN'],['LOSE','LOSE'],['WIN','LOSE'],['LOSE','WIN']]}
    for k,v in expected.items():
        if p.get(k)!=v:problems.append('fixed protocol mismatch:'+k)
    if p['resource_policy']['checkpoint_games']!=24 or p['resource_policy']['concurrency']!=1:problems.append('checkpoint/concurrency mismatch')
    cc,plan=reconstruct(p);actual_cells=g.cells();jobs=g.jobs()
    actual_plan=[dict(index=j['index'],game_seed=j['game_seed'],pass_min_ply=j['pass_min_ply'],black=j['black'].to_dict(),white=j['white'].to_dict()) for j in jobs]
    if cc!=actual_cells:problems.append('independent schedule cells mismatch')
    if plan!=actual_plan:problems.append('independent full plan mismatch')
    frozen=ROOT/'experiments/g1_pass8_estimation_v1/frozen_plan.json'
    if frozen.exists() and json.loads(frozen.read_text())!=plan:problems.append('frozen plan mismatch')
    seeds={j['game_seed'] for j in plan};streams={seed('agent-stream',j['game_seed'],color,j[color]['seed']) for j in plan for color in ('black','white')}
    if len(plan)!=480 or len(seeds)!=240 or len(streams)!=480:problems.append('wrong actual stream counts')
    pairs=collections.defaultdict(list)
    for c,j in zip(cc,plan):pairs[c['block_id']].append((c,j))
    for key,paired in pairs.items():
        if len(paired)!=2 or {x[0]['pass_min_ply'] for x in paired}!={0,8}:problems.append('nonpaired block:'+key)
        elif {k:v for k,v in paired[0][1].items() if k not in ('index','pass_min_ply')}!={k:v for k,v in paired[1][1].items() if k not in ('index','pass_min_ply')}:problems.append('paired seeds/agents differ:'+key)
    strata=collections.Counter((c['pass_min_ply'],c['batch_seed'],c['black_identity'],c['white_identity'],c['black_seed'],c['white_seed']) for c in cc)
    if len(strata)!=48 or set(strata.values())!={10}:problems.append('cell balance mismatch')
    arm_orders=collections.Counter(tuple(plan[i+j]['pass_min_ply'] for j in (0,1)) for i in range(0,len(plan),2))
    if arm_orders!={(0,8):120,(8,0):120}:problems.append('arm ordering imbalance')
    superset={seed('agent-stream',gs,color,s) for gs in seeds for color in ('black','white') for s in (1,2)}
    if not streams<=superset:problems.append('actual streams outside audited historical superset')
    record={'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'experiment_id':p['experiment_id'],'preregistration_sha256':digest(g.PROTOCOL),'script_sha256':digest(__file__),'planned_games':len(plan),'unique_paired_blocks':len(pairs),'unique_game_seeds':len(seeds),'unique_color_agent_streams':len(streams),'cell_counts':[{'key':list(k),'n':v} for k,v in sorted(strata.items())],'arm_order_counts':{str(k):v for k,v in arm_orders.items()},'plan_semantic_sha256':hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'stream_inventory_sha256':hashlib.sha256(json.dumps(sorted(streams)).encode()).hexdigest(),'frozen_plan_present':frozen.exists(),'production_output_present':(ROOT/'outputs'/p['batch_id']).exists(),'problems':problems,'limitations':['Confirms initial-seed pairing only; rule arms consume streams differently.','No historical games, pilot rows, or synthetic tests enter formal sample.','Historical collision evidence is prospective_seed_isolation.json, whose candidate superset contains all actual streams.']}
    (HERE/f'{args.label}_fixed_design_audit.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:v for k,v in record.items() if k!='cell_counts'},indent=2));return bool(problems)
if __name__=='__main__':raise SystemExit(main())
