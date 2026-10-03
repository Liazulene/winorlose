"""D1 arbitrary-budget, paired-design, persistence and falsification tests."""
import copy
import hashlib
import json
from pathlib import Path
import random
import pytest
from winai_loseai.experiments import d1_estimation as d1
from winai_loseai.league.runstore import ConfigMismatch, MetadataCorrupt
from winai_loseai.spec import AgentSpec, simulations_for
from winai_loseai.identity import Identity
from winai_loseai.agents.vector_mcts import VectorMCTSAgent
from winai_loseai.game.state import GoState
from winai_loseai.league.storage import _metadata_line

@pytest.fixture(autouse=True)
def current_runner_test_protocol(tmp_path,monkeypatch):
    """Test fresh legacy-runner fixtures, never relabel saved cost evidence."""
    from winai_loseai import CODE_VERSION
    p=json.loads(d1.PROTOCOL.read_text());p['code_version']=CODE_VERSION
    path=tmp_path/'legacy_protocol.json';path.write_text(json.dumps(p))
    monkeypatch.setattr(d1,'PROTOCOL',path)
    monkeypatch.setattr(d1,'PREREGISTRATION_SHA256',d1.sha256(path))

@pytest.fixture
def small(tmp_path,monkeypatch):
    p=json.loads(d1.PROTOCOL.read_text());p.update(budgets=[1,3],batch_seeds=[5],games_per_cell=1,planned_games=16);p['resource_policy']['concurrency']=2
    path=tmp_path/'protocol.json';path.write_text(json.dumps(p))
    monkeypatch.setattr(d1,'PROTOCOL',path)
    monkeypatch.setattr(d1,'PREREGISTRATION_SHA256',d1.sha256(path))
    return p

@pytest.mark.parametrize('level,n',[('shallow',64),('medium',256),('deep',1024),('sims:1',1),('sims:7',7),('sims:128',128)])
def test_budget_resolver(level,n):
    assert simulations_for(level)==n
    assert AgentSpec('a',Identity.WIN,'vector_mcts',level,1).simulations()==n

@pytest.mark.parametrize('level',['sims:0','sims:-1','sims:01','sims:1.5','sims: 1','sims:１','sims:True','other','',None])
def test_invalid_budget(level):
    with pytest.raises((ValueError,TypeError)):simulations_for(level)

def test_registered_plan():
    p=d1.protocol();jj=d1.jobs();cc=d1.cells()
    assert len(jj)==len(cc)==720
    assert len({j['game_seed'] for j in jj})==240
    blocks={}
    for j,c in zip(jj,cc):
        assert j['black'].simulations()==j['white'].simulations()==c['budget']
        blocks.setdefault(c['block_id'],[]).append(j)
    assert len(blocks)==240
    assert all(len({j['game_seed'] for j in b})==1 and len(b)==3 for b in blocks.values())
    assert p['planned_games']==720

@pytest.mark.parametrize('named,explicit',[('shallow','sims:64'),('medium','sims:256'),('deep','sims:1024')])
def test_named_and_explicit_have_identical_search(named,explicit):
    # A near-terminal state makes the1024 case fast while checking exact RNG/stats.
    state=GoState.from_board([0]*25,move_count=99)
    agents=[VectorMCTSAgent(AgentSpec('x',Identity.WIN,'vector_mcts',level,1),random.Random(42)) for level in (named,explicit)]
    actions=[a.select_action(state,Identity.WIN,Identity.LOSE) for a in agents]
    stats=[dict(a.last_stats) for a in agents]
    for s in stats:s.pop('search_time_ms')
    assert actions[0]==actions[1] and stats[0]==stats[1]

def test_fresh_resume_concurrency_identical(tmp_path,small):
    a=tmp_path/'a';b=tmp_path/'b';c=tmp_path/'c'
    assert not d1.run(a)['problems']
    assert not d1.run(b,concurrency=2)['problems']
    with pytest.raises(d1.D1Interrupted):d1.run(c,stop_after=5)
    checked=d1.validate(c,False);assert checked['game_count']==5 and not checked['problems']
    assert not d1.run(c,concurrency=2,resume=True)['problems']
    strip=lambda p:[d1.strip_timing(x) for x in d1.records(p)]
    assert strip(a)==strip(b)==strip(c)
    before={p.relative_to(c):p.read_bytes() for p in c.rglob('*') if p.is_file()}
    assert not d1.run(c,resume=True)['problems']
    assert before=={p.relative_to(c):p.read_bytes() for p in c.rglob('*') if p.is_file()}

def partial(tmp_path):
    out=tmp_path/'run'
    with pytest.raises(d1.D1Interrupted):d1.run(out,stop_after=3)
    return out

@pytest.mark.parametrize('damage',['tail','missing'])
def test_repair_metadata(tmp_path,small,damage):
    out=partial(tmp_path);p=out/'games.jsonl'
    if damage=='tail':p.write_text(p.read_text()+'{"torn":')
    else:p.write_text('\n'.join(p.read_text().splitlines()[:-1])+'\n')
    assert not d1.run(out,resume=True)['problems']

@pytest.mark.parametrize('damage',['middle','duplicate'])
def test_refuse_metadata_corruption(tmp_path,small,damage):
    out=partial(tmp_path);p=out/'games.jsonl';lines=p.read_text().splitlines()
    if damage=='middle':lines[1]='broken'
    else:lines.append(lines[0])
    p.write_text('\n'.join(lines)+'\n');before=p.read_bytes()
    with pytest.raises(MetadataCorrupt):d1.run(out,resume=True)
    assert p.read_bytes()==before

@pytest.mark.parametrize('file,key,value',[('experiment_lock.json','python_version','0'),('experiment_lock.json','entry_point_sha256','bad'),('source_lock.json','source_fingerprint','bad'),('plan.json',None,None)])
def test_refuse_lock_tamper_before_mutation(tmp_path,small,file,key,value):
    out=partial(tmp_path);p=out/file;doc=json.loads(p.read_text())
    if key:doc[key]=value
    else:doc[0]['game_seed']+=1
    p.write_text(json.dumps(doc));before={x.name:x.read_bytes() for x in out.iterdir() if x.is_file()}
    with pytest.raises(ConfigMismatch):d1.run(out,resume=True)
    assert before=={x.name:x.read_bytes() for x in out.iterdir() if x.is_file()}

@pytest.mark.parametrize('kind',['budget','visits','q','plan_seed','metadata','analysis','manifest','seed_mirror'])
def test_validator_falsifications(tmp_path,small,kind):
    out=tmp_path/'run';d1.run(out)
    f=next((out/'games').glob('*.json'));r=json.loads(f.read_text())
    if kind=='budget':r['moves'][0]['simulations_used']=64
    if kind=='visits':r['moves'][0]['action_visit_counts'][str(r['moves'][0]['action'])]+=1
    if kind=='q':r['moves'][0]['action_q_black'][str(r['moves'][0]['action'])]=2
    if kind=='plan_seed':r['game_seed']+=1
    if kind in ('budget','visits','q','plan_seed'):f.write_text(json.dumps(r))
    if kind=='metadata':
        p=out/'games.jsonl';lines=p.read_text().splitlines();rr=json.loads(lines[0]);rr['move_count']+=1;lines[0]=json.dumps(rr);p.write_text('\n'.join(lines)+'\n')
    if kind in ('analysis','manifest','seed_mirror'):
        filename={'analysis':'analysis.json','manifest':'manifest.json','seed_mirror':'game_seeds.json'}[kind];p=out/filename;doc=json.loads(p.read_text())
        if kind=='analysis':doc['n_records']=999
        elif kind=='manifest':doc['completed_indexes']=[]
        else:doc[0]['game_seed']+=1
        p.write_text(json.dumps(doc))
    assert d1.validate(out)['problems']

def test_prereg_tamper(small):
    d1.PROTOCOL.write_text(d1.PROTOCOL.read_text()+' ')
    with pytest.raises(ConfigMismatch):d1.protocol()

@pytest.mark.parametrize('name',['batch_A_seed0','batch_B_shallow_seed0','batch_B_shallow_seed1','d0_g0_v1_seed0','d1_g0_cost_v1'])
def test_historical_output_refused(tmp_path,name):
    with pytest.raises(ValueError):d1.run(tmp_path/name)

def test_nonempty_and_symlinks(tmp_path,small):
    out=tmp_path/'occupied';out.mkdir();(out/'note').write_text('keep')
    with pytest.raises(FileExistsError):d1.run(out)
    link=tmp_path/'link';link.symlink_to(out,target_is_directory=True)
    with pytest.raises(ValueError):d1.run(link/'child')
    with pytest.raises(ValueError):d1.run(link)

def test_route_definitions():
    assert d1.quantile([1,2,3,4],.5)==2.5
    assert d1.distribution([])['mean'] is None

@pytest.mark.parametrize('damage',['bad_json','wrong_budget','seed_mirror','agents','metadata','extra_game'])
def test_resume_preflight_rejects_without_mutation(tmp_path,small,damage):
    out=partial(tmp_path)
    game=next((out/'games').glob('*.json'))
    if damage=='bad_json':game.write_text('{broken')
    elif damage=='wrong_budget':
        r=json.loads(game.read_text());r['moves'][0]['simulations_used']+=1;game.write_text(json.dumps(r))
    elif damage=='seed_mirror':
        p=out/'game_seeds.json';r=json.loads(p.read_text());r[0]['game_seed']+=1;p.write_text(json.dumps(r))
    elif damage=='agents':
        p=out/'manifest.json';r=json.loads(p.read_text());r['agents']=[];p.write_text(json.dumps(r))
    elif damage=='metadata':
        p=out/'games.jsonl';lines=p.read_text().splitlines();r=json.loads(lines[0]);r['move_count']+=1;lines[0]=json.dumps(r);p.write_text('\n'.join(lines)+'\n')
    else:(out/'games'/'unregistered.json').write_text(game.read_text())
    # A torn tail must not be repaired if another record/manifest is invalid.
    p=out/'games.jsonl';p.write_text(p.read_text()+'{torn')
    before={p.relative_to(out):p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(ConfigMismatch):d1.run(out,resume=True)
    assert before=={p.relative_to(out):p.read_bytes() for p in out.rglob('*') if p.is_file()}

@pytest.mark.parametrize('damage',['negative_wall','nan_wall','bool_search','no_board','no_legal_count','bool_budget'])
def test_strict_schema_rejects(tmp_path,small,damage):
    job=d1.jobs()[0];rec=d1.play_one(job)
    if damage=='negative_wall':rec['game_wall_ms']=-1
    if damage=='nan_wall':rec['game_wall_ms']=float('nan')
    if damage=='bool_search':rec['moves'][0]['search_time_ms']=True
    if damage=='no_board':del rec['final_board']
    if damage=='no_legal_count':del rec['moves'][0]['legal_action_count']
    if damage=='bool_budget':rec['moves'][0]['simulations_used']=True
    assert d1.record_problems(rec,job)

@pytest.mark.parametrize('damage',['hole','overclaim','bad_indexes'])
def test_resume_progress_integrity(tmp_path,small,damage):
    out=partial(tmp_path)
    if damage=='hole':
        paths=sorted((out/'games').glob('*.json'));paths[1].unlink()
        p=out/'games.jsonl';rows=p.read_text().splitlines();p.write_text(rows[0]+'\n'+rows[2]+'\n')
    else:
        p=out/'manifest.json';r=json.loads(p.read_text())
        if damage=='overclaim':r['completed_indexes']=list(range(4));r['completed_game_count']=4
        else:r['completed_indexes']=[0,2,1]
        p.write_text(json.dumps(r))
    before={p.relative_to(out):p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(ConfigMismatch):d1.run(out,resume=True)
    assert before=={p.relative_to(out):p.read_bytes() for p in out.rglob('*') if p.is_file()}

def test_stale_manifest_prefix_is_recoverable(tmp_path,small):
    out=partial(tmp_path);p=out/'manifest.json';r=json.loads(p.read_text());r['completed_indexes']=[0];r['completed_game_count']=1;p.write_text(json.dumps(r))
    assert not d1.run(out,resume=True)['problems']

def test_formal_concurrency_is_one(tmp_path):
    with pytest.raises(ValueError):d1.run(tmp_path/'unused',concurrency=2)


def test_second_writer_refused_without_mutation(tmp_path,small):
    out=partial(tmp_path)
    before={p.relative_to(out):p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with d1.exclusive_output_lock(out):
        with pytest.raises(ConfigMismatch,match='another writer'):
            d1.run(out,resume=True)
    assert before=={p.relative_to(out):p.read_bytes() for p in out.rglob('*') if p.is_file()}
    assert not d1.run(out,resume=True)['problems']

@pytest.mark.parametrize('name',['winorlose','winorlose_d0_v1','winorlose_d1_v1'])
def test_sibling_immutable_tree_refused(name):
    with pytest.raises(ValueError,match='immutable'):
        d1.assert_output_allowed(d1.ROOT.parent/name/'outputs'/'new_name')


def test_legacy_cost_protocol_refuses_new_runtime():
    # Original files and hashes are preserved; only its original worktree can
    # validate or resume historical outputs under the original source version.
    from winai_loseai.experiments import d1 as legacy
    with pytest.raises(ConfigMismatch,match='protocol/version'):
        legacy.protocol()


@pytest.mark.parametrize('damage',['bool_utility','string_score','alias_key','bool_key','duplicate_key','map_list'])
def test_extended_record_schema(tmp_path,small,damage):
    job=d1.jobs()[0];r=d1.play_one(job)
    if damage=='bool_utility':r['black_utility']=True
    elif damage=='string_score':r['black_score']=str(r['black_score'])
    else:
        m=r['moves'][0]['action_visit_counts'];a=next(iter(m))
        if damage=='alias_key':m['0'+str(a)]=m.pop(a)
        if damage=='bool_key':m[True]=m.pop(a)
        if damage=='duplicate_key':m[str(a)]=m[a]
        if damage=='map_list':r['moves'][0]['action_visit_counts']=list(m.items())
    assert d1.record_problems(r,job)


def test_partial_validator_rejects_agreeing_hole(tmp_path,small):
    out=partial(tmp_path);paths=sorted((out/'games').glob('*.json'));paths[1].unlink()
    p=out/'games.jsonl';rows=p.read_text().splitlines();p.write_text(rows[0]+'\n'+rows[2]+'\n')
    p=out/'manifest.json';r=json.loads(p.read_text());r['completed_indexes']=[0,2];r['completed_game_count']=2;p.write_text(json.dumps(r))
    assert any('contiguous' in x for x in d1.validate(out,False)['problems'])


def test_partial_validator_rejects_extra_artifact(tmp_path,small):
    out=partial(tmp_path);(out/'games'/'unregistered.txt').write_text('extra')
    assert any('unexpected' in x for x in d1.validate(out,False)['problems'])
