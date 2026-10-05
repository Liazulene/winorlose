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
from winai_loseai.experiments import komi_pass_estimation as pilot
from winai_loseai.game.scoring import score_position
from winai_loseai.identity import Identity, black_white_utilities, identity_goal_reached
from winai_loseai.league.runstore import job_to_entry, entry_to_job

ARMS=((0,2.5),(8,2.5),(0,0.0),(8,0.0))
IDENTITIES=(('WIN','WIN'),('LOSE','LOSE'),('WIN','LOSE'),('LOSE','WIN'))
ORIENTATIONS=((1,2),(2,1))


def independent_hash(*parts):
    return int.from_bytes(hashlib.sha256('|'.join(map(str,parts)).encode()).digest()[:16],'big')


def prereg():return json.loads((ROOT/'experiments/komi_pass_estimation_v1/preregistration.json').read_text())


def expected_schedule():
    blocks=[(s,i,o,r) for s in (17,18,19) for i in range(4) for o in range(2) for r in range(10)]
    rng=random.Random(2026100501);rng.shuffle(blocks)
    orders=list(permutations(ARMS))*10;rng.shuffle(orders)
    return [(block,arm) for block,order in zip(blocks,orders) for arm in order]


def test_m7_exact_registered_fixed_design():
    p=prereg()
    assert p['planned_games']==960 and p['games_per_cell']==10
    assert p['batch_seeds']==[17,18,19] and p['budget']==256 and p['board_size']==5
    assert p['schedule_seed']==2026100501
    assert p['agent_seed_orientations']==[list(x) for x in ORIENTATIONS]
    assert p['identity_directions']==[list(x) for x in IDENTITIES]
    assert p['resource_policy']['concurrency']==1 and p['resource_policy']['checkpoint_games']==48


@pytest.mark.parametrize('index',range(960))
def test_m7_each_job_matches_independent_full_schedule(index):
    p=prereg();job=pilot.jobs(p)[index]
    (seed,i,o,r),(rule,komi)=expected_schedule()[index]
    ib,iw=IDENTITIES[i];sb,sw=ORIENTATIONS[o]
    assert job['index']==index and job['game_seed']==independent_hash('game-seed',seed,(i*2+o)*10+r)
    assert (job['pass_min_ply'],job['komi'])==(rule,komi)
    assert (job['black'].identity.value,job['white'].identity.value)==(ib,iw)
    assert (job['black'].seed,job['white'].seed)==(sb,sw)
    assert (job['black'].simulations(),job['white'].simulations())==(256,256)


def test_m7_blocks_permutations_position_and_checkpoint_balance():
    cells=pilot.cells(prereg());assert len(cells)==960
    orders=[]
    for start in range(0,960,4):
        chunk=cells[start:start+4]
        assert len({(c['batch_seed'],c['block_id'],c['black_identity'],c['white_identity'],c['black_seed'],c['white_seed']) for c in chunk})==1
        order=tuple((c['pass_min_ply'],c['komi']) for c in chunk)
        assert set(order)==set(ARMS);orders.append(order)
    assert Counter(orders)==Counter({order:10 for order in permutations(ARMS)})
    for position in range(4):assert Counter(order[position] for order in orders)==Counter({a:60 for a in ARMS})
    for start in range(0,960,48):
        chunk=cells[start:start+48]
        assert len({c['block_id'] for c in chunk})==12
        assert Counter((c['pass_min_ply'],c['komi']) for c in chunk)==Counter({a:12 for a in ARMS})


def test_m7_seed_actual_stream_cardinality():
    jobs=pilot.jobs(prereg())
    assert len({j['game_seed'] for j in jobs})==240
    streams={independent_hash('agent-stream',j['game_seed'],c,j[c].seed) for j in jobs for c in ('black','white')}
    assert len(streams)==480
    assert set(Counter(j['game_seed'] for j in jobs).values())=={4}


@pytest.mark.parametrize('arm',ARMS)
def test_m7_komi_survives_plan_serialization(arm):
    job=next(j for j in pilot.jobs(prereg()) if (j['pass_min_ply'],j['komi'])==arm)
    entry=job_to_entry(job)
    assert entry['komi']==arm[1]
    restored=entry_to_job(entry,job['batch_id'])
    assert job_to_entry(restored)==entry


@pytest.mark.parametrize('ib,iw',IDENTITIES)
def test_m7_zero_area_draw_is_zero_utility_and_no_goal(ib,iw):
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


def test_m7_draw_denominators_and_neutral_pass_proposals():
    result=pilot.summarize([synthetic_empty_row(*ids,0.0) for ids in IDENTITIES])
    assert (result['n'],result['draws'],result['black_board_wins'],result['white_board_wins'])==(4,4,0,0)
    assert (result['black_goals'],result['white_goals'],result['joint_goals'])==(0,0,0)
    assert result['utility_counts']=={c:{'-1':0,'0':4,'1':0} for c in ('black','white')}
    acc=result['pass_proposal_acceptance']
    assert acc['black_proposer_neutral']=={'opportunities':4,'accepted':4}
    assert acc['black_proposer_unfavorable']==acc['black_proposer_favorable']=={'opportunities':0,'accepted':0}


def test_m7_mixed_joint_goal_once_and_draw_retained():
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
    'handoff/nested_new','reports/nested_new','outputs/komi_pass_pilot_v1/nested_new','experiments/komi_pass_pilot_v1/nested_new'])
def test_m7_output_guard_rejects_inherited_historical_subdirectories(relative):
    with pytest.raises(ValueError):pilot.assert_output_allowed(ROOT/relative)


@pytest.mark.parametrize('name',[
    'winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1',
    'winorlose_g1_pass8_v1','winorlose_g1_pass8_estimation_v1','winorlose_komi_pass_pilot_v1'])
def test_m7_output_guard_rejects_all_seven_older_worktrees(name):
    with pytest.raises(ValueError):pilot.assert_output_allowed(ROOT.parent/name/'new_output')


def test_m7_historical_regression_selection_includes_all_draws():
    import importlib.util
    spec=importlib.util.spec_from_file_location('m7_reproduction_review',ROOT/'scripts/verify_komi_pass_estimation_reproduction.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    rows=json.loads((ROOT/'outputs/komi_pass_pilot_v1/analysis.json').read_text())['rows']
    selected=module.select_rows(rows,[14,15,16],include_draws=True)
    expected={min((r for r in rows if (r['pass_min_ply'],r['komi'],r['batch_seed'])==(p,k,s)),key=lambda r:r['game_index'])['game_id'] for p,k in ARMS for s in (14,15,16)}
    expected.update(r['game_id'] for r in rows if r['winner']=='draw')
    assert {r['game_id'] for r in selected}==expected
    assert len(selected)==14
    assert sum(r['winner']=='draw' for r in selected)==3
    assert sum(r['komi']==2.5 for r in selected)==6
    for left,right in [(1,1.0),(False,0),([1],[1.0]),({'x':0},{'x':False}),({'x':1},{'x':1,'y':2})]:assert not module.exact(left,right)
    fields={'schema_version':2,'python_version':'3.12.14','komi':0.0,'pass_min_ply':8,'ruleset':'G1-k0-pass8','winner':'draw','black_utility':0,'white_utility':0,'game_wall_ms':3.0,'code_version':'old','source_fingerprint':'old','moves':[{'action':25,'search_time_ms':1.0,'root_visit_count':256}]}
    stripped=module.canonical(fields,{'game_wall_ms','search_time_ms','code_version','source_fingerprint'})
    assert set(stripped)==set(fields)-{'game_wall_ms','code_version','source_fingerprint'}
    assert stripped['moves']==[{'action':25,'root_visit_count':256}]
