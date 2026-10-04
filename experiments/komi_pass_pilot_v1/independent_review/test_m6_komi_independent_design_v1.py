"""Independent design/semantics tests: no sampled experiment games are generated."""
from collections import Counter
import hashlib
from itertools import permutations
import json
from pathlib import Path
import random
import sys

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.experiments import komi_pass_pilot as pilot
from winai_loseai.game.scoring import score_position
from winai_loseai.identity import Identity, black_white_utilities, identity_goal_reached
from winai_loseai.league.runstore import job_to_entry, entry_to_job

ARMS=((0,2.5),(8,2.5),(0,0.0),(8,0.0))
IDENTITIES=(('WIN','WIN'),('LOSE','LOSE'),('WIN','LOSE'),('LOSE','WIN'))
ORIENTATIONS=((1,2),(2,1))


def independent_hash(*parts):
    return int.from_bytes(hashlib.sha256('|'.join(map(str,parts)).encode()).digest()[:16],'big')


def prereg():return json.loads((ROOT/'experiments/komi_pass_pilot_v1/preregistration.json').read_text())


def expected_schedule():
    blocks=[(s,i,o) for s in (14,15,16) for i in range(4) for o in range(2)]
    rng=random.Random(2026100403);rng.shuffle(blocks)
    orders=list(permutations(ARMS));rng.shuffle(orders)
    return [(block,arm) for block,order in zip(blocks,orders) for arm in order]


def test_m6_exact_registered_fixed_design():
    p=prereg()
    assert p['planned_games']==96 and p['games_per_cell']==1
    assert p['batch_seeds']==[14,15,16] and p['budget']==256 and p['board_size']==5
    assert p['schedule_seed']==2026100403
    assert p['agent_seed_orientations']==[list(x) for x in ORIENTATIONS]
    assert p['identity_directions']==[list(x) for x in IDENTITIES]
    assert p['resource_policy']['concurrency']==1 and p['resource_policy']['checkpoint_games']==24


@pytest.mark.parametrize('index',range(96))
def test_m6_each_job_matches_independent_full_schedule(index):
    p=prereg();job=pilot.jobs(p)[index]
    (seed,i,o),(rule,komi)=expected_schedule()[index]
    ib,iw=IDENTITIES[i];sb,sw=ORIENTATIONS[o]
    assert job['index']==index and job['game_seed']==independent_hash('game-seed',seed,i*2+o)
    assert (job['pass_min_ply'],job['komi'])==(rule,komi)
    assert (job['black'].identity.value,job['white'].identity.value)==(ib,iw)
    assert (job['black'].seed,job['white'].seed)==(sb,sw)
    assert (job['black'].simulations(),job['white'].simulations())==(256,256)


def test_m6_blocks_permutations_position_and_checkpoint_balance():
    cells=pilot.cells(prereg());assert len(cells)==96
    orders=[]
    for start in range(0,96,4):
        chunk=cells[start:start+4]
        assert len({(c['batch_seed'],c['block_id'],c['black_identity'],c['white_identity'],c['black_seed'],c['white_seed']) for c in chunk})==1
        order=tuple((c['pass_min_ply'],c['komi']) for c in chunk)
        assert set(order)==set(ARMS);orders.append(order)
    assert Counter(orders)==Counter(permutations(ARMS))
    for position in range(4):assert Counter(order[position] for order in orders)==Counter({a:6 for a in ARMS})
    for start in range(0,96,24):
        chunk=cells[start:start+24]
        assert len({c['block_id'] for c in chunk})==6
        assert Counter((c['pass_min_ply'],c['komi']) for c in chunk)==Counter({a:6 for a in ARMS})


def test_m6_seed_actual_stream_cardinality():
    jobs=pilot.jobs(prereg())
    assert len({j['game_seed'] for j in jobs})==24
    streams={independent_hash('agent-stream',j['game_seed'],c,j[c].seed) for j in jobs for c in ('black','white')}
    assert len(streams)==48
    assert set(Counter(j['game_seed'] for j in jobs).values())=={4}


@pytest.mark.parametrize('arm',ARMS)
def test_m6_komi_survives_plan_serialization(arm):
    job=next(j for j in pilot.jobs(prereg()) if (j['pass_min_ply'],j['komi'])==arm)
    entry=job_to_entry(job)
    assert entry['komi']==arm[1]
    restored=entry_to_job(entry,job['batch_id'])
    assert job_to_entry(restored)==entry


@pytest.mark.parametrize('ib,iw',IDENTITIES)
def test_m6_zero_area_draw_is_zero_utility_and_no_goal(ib,iw):
    result=score_position((0,)*25,5,0.0)
    assert result=={'black_score':0.0,'white_score':0.0,'score_margin':0.0,'winner':'draw'}
    utilities=black_white_utilities(result['winner'],Identity(ib),Identity(iw))
    assert utilities==(0,0)
    assert [identity_goal_reached(u) for u in utilities]==[False,False]


def synthetic_empty_row(ib,iw,komi):
    winner='draw' if komi==0 else 'white'
    ub,uw=black_white_utilities(winner,Identity(ib),Identity(iw))
    rec={'game_id':f'synthetic-{ib}-{iw}-{komi}','black_identity':ib,'white_identity':iw,
         'black_algorithm':'vector_mcts','white_algorithm':'vector_mcts','winner':winner,
         'black_score':0.0,'white_score':komi,'black_utility':ub,'white_utility':uw,
         'move_count':2,'termination_reason':'double_pass','superko_rejections':0,
         'game_wall_ms':0.0,'pass_min_ply':0,'komi':komi,'ruleset':pilot.arm_name(0,komi),
         'moves':[{'action':25,'color':'black','is_pass':True},{'action':25,'color':'white','is_pass':True}]}
    return pilot.describe_game(rec)|{'search_times_ms':[0.0,0.0],'game_bytes':0}


def test_m6_draw_denominators_and_neutral_pass_proposals():
    result=pilot.summarize([synthetic_empty_row(*ids,0.0) for ids in IDENTITIES])
    assert (result['n'],result['draws'],result['black_board_wins'],result['white_board_wins'])==(4,4,0,0)
    assert (result['black_goals'],result['white_goals'],result['joint_goals'])==(0,0,0)
    assert result['utility_counts']=={c:{'-1':0,'0':4,'1':0} for c in ('black','white')}
    acc=result['pass_proposal_acceptance']
    assert acc['black_proposer_neutral']=={'opportunities':4,'accepted':4}
    assert acc['black_proposer_unfavorable']==acc['black_proposer_favorable']=={'opportunities':0,'accepted':0}


def test_m6_mixed_joint_goal_once_and_draw_retained():
    result=pilot.summarize([synthetic_empty_row('LOSE','WIN',2.5),synthetic_empty_row('LOSE','WIN',0.0)])
    assert (result['n'],result['joint_goals'],result['draws'])==(2,1,1)
    assert result['black_goals']==result['white_goals']==1
    assert result['pass_proposal_acceptance']['black_proposer_favorable']=={'opportunities':1,'accepted':1}
    assert result['pass_proposal_acceptance']['black_proposer_neutral']=={'opportunities':1,'accepted':1}


@pytest.mark.parametrize('relative',[
    'outputs/batch_A_seed0/nested_new','outputs/batch_B_shallow_seed0/nested_new',
    'outputs/batch_B_shallow_seed1/nested_new','outputs/smoke_random/nested_new','outputs/smoke_mcts/nested_new',
    'experiments/g1_pass8_v1/nested_new','experiments/g1_pass8_estimation_v1/nested_new',
    'experiments/d1_cost_v1/nested_new','experiments/d1_estimation_v1/nested_new',
    'handoff/nested_new','reports/nested_new'])
def test_m6_output_guard_rejects_inherited_historical_subdirectories(relative):
    with pytest.raises(ValueError):pilot.assert_output_allowed(ROOT/relative)


@pytest.mark.parametrize('name',[
    'winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1',
    'winorlose_g1_pass8_v1','winorlose_g1_pass8_estimation_v1'])
def test_m6_output_guard_rejects_all_six_older_worktrees(name):
    with pytest.raises(ValueError):pilot.assert_output_allowed(ROOT.parent/name/'new_output')


def load_reproduction_module():
    import importlib.util
    spec=importlib.util.spec_from_file_location('m6_reproduction_test_loaded_v1',ROOT/'scripts/verify_komi_pass_reproduction.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_m6_historical_regression_selection_equals_M5_preset():
    rows=json.loads((ROOT/'outputs/g1_pass8_estimation_v1/analysis.json').read_text())['rows']
    chosen={(p,s):min((r for r in rows if r['pass_min_ply']==p and r['batch_seed']==s),key=lambda r:r['game_index'])['game_index']
            for p in (0,8) for s in (11,12,13)}
    assert chosen=={(0,11):0,(0,12):5,(0,13):13,(8,11):1,(8,12):4,(8,13):12}


@pytest.mark.parametrize('left,right',[(1,1.0),(False,0),([1],[1.0]),({'x':0},{'x':False}),({'x':1},{'x':1,'y':2})])
def test_m6_regeneration_comparator_preserves_non_timing_types(left,right):
    assert not load_reproduction_module().exact(left,right)


def test_m6_regeneration_canonical_does_not_drop_semantic_fields():
    module=load_reproduction_module()
    excluded={'search_time_ms','game_wall_ms','code_version','source_fingerprint'}
    record={'schema_version':2,'python_version':'3.12.14','komi':0.0,'pass_min_ply':8,'ruleset':'G1-k0-pass8',
            'winner':'draw','black_utility':0,'white_utility':0,'game_wall_ms':12.0,'code_version':'ignored',
            'source_fingerprint':'ignored','moves':[{'action':25,'search_time_ms':9.0,'root_visit_count':256,'action_visit_counts':{25:256}}]}
    actual=module.canonical(record,excluded)
    assert set(actual)=={'schema_version','python_version','komi','pass_min_ply','ruleset','winner','black_utility','white_utility','moves'}
    assert actual['moves']==[{'action':25,'root_visit_count':256,'action_visit_counts':{'25':256}}]


def test_m6_factorial_descriptive_arithmetic_preserves_draws_and_pairing(monkeypatch,tmp_path):
    # Hand-authored rows test only arithmetic. No engine or MCTS game is played.
    p=prereg();cells=pilot.cells(p)
    first=next(c['block_id'] for c in cells if c['black_identity']=='LOSE' and c['white_identity']=='WIN')
    second=next(c['block_id'] for c in cells if c['black_identity']=='WIN' and c['white_identity']=='WIN')
    chosen=[(i,c) for i,c in enumerate(cells) if c['block_id'] in (first,second)]
    synthetic=[];by_id={}
    lengths={(0,2.5):2,(8,2.5):10,(0,0.0):20,(8,0.0):24}
    winners={(0,2.5):'white',(8,2.5):'white',(0,0.0):'draw',(8,0.0):'black'}
    (tmp_path/'games').mkdir()
    for i,c in chosen:
        arm=(c['pass_min_ply'],c['komi']);length=lengths[arm];winner=winners[arm]
        ub,uw=black_white_utilities(winner,Identity(c['black_identity']),Identity(c['white_identity']))
        gid=f'synthetic-g{i:06d}'
        row=synthetic_empty_row(c['black_identity'],c['white_identity'],c['komi'])
        row.update(game_id=gid,move_count=length,extra_length=length-c['pass_min_ply']-2,
                   black_utility=ub,white_utility=uw,winner=winner)
        by_id[gid]=row
        synthetic.append({'game_id':gid,'game_index':i,'game_seed':independent_hash('game-seed',c['batch_seed'],c['block_index']),
                          'moves':[{'search_time_ms':0.0}]})
        (tmp_path/'games'/f'{gid}.json').write_text('{}\n')
    monkeypatch.setattr(pilot,'protocol',lambda:p)
    monkeypatch.setattr(pilot,'records',lambda out:synthetic)
    monkeypatch.setattr(pilot,'describe_game',lambda rec:dict(by_id[rec['game_id']]))
    analysis=pilot.analyze(tmp_path)
    assert analysis['n_records']==8 and len(analysis['paired_differences'])==2
    for pair in analysis['paired_differences']:
        c=pair['contrasts']
        assert (c['komi_at_p0']['length'],c['komi_at_p8']['length'])==(18,14)
        assert (c['pass_at_k2p5']['length'],c['pass_at_k0']['length'],c['interaction']['length'])==(8,4,-4)
        assert (c['pass_at_k2p5']['extra_length'],c['pass_at_k0']['extra_length'])==(0,-4)
        assert c['komi_at_p0']['extra_length']==18 and c['komi_at_p8']['extra_length']==14
        assert c['interaction']['extra_length']==-4
        assert (c['komi_at_p0']['draw'],c['komi_at_p8']['draw'],c['interaction']['draw'])==(1,0,-1)
    mixed=next(pair for pair in analysis['paired_differences'] if pair['black_identity']=='LOSE')
    assert mixed['white_identity']=='WIN'
    assert mixed['contrasts']['komi_at_p0']['joint_goal']==-1
    assert analysis['groups']['G1-k0']['all']['n']==2 and analysis['groups']['G1-k0']['all']['draws']==2
    assert analysis['groups']['G1-k0']['all']['black_goals']==0
