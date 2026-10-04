"""Preregistered fixed48 G0 versus G1-pass8 engineering and cost pilot.

The generator and validator derive every budget/seed/condition from the
registered design. No historical output or report can be opened for writing.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import os
import tempfile
from collections import Counter
import copy
import hashlib
from importlib.metadata import version as distribution_version
import json
import math
from pathlib import Path
import statistics
import time
import traceback
import random

from .. import CODE_VERSION
from ..identity import Identity, black_white_utilities
from ..spec import AgentSpec, simulations_for
from ..game.state import GoState, BLACK, WHITE, board_has_dead_group
from ..game.scoring import score_position
from ..provenance import current_provenance, source_lock
from ..league.seeds import game_seed_for
from ..league.runner import stream_jobs, play_one
from ..league.runstore import (RunStore, ConfigMismatch, job_to_entry, STATUS_RUNNING,
    STATUS_INTERRUPTED, STATUS_FAILED, STATUS_COMPLETED, STATUS_VALIDATION_FAILED)
from ..league.storage import read_metadata, _metadata_line
from ..league.replay import replay_record

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = ROOT / 'experiments/g1_pass8_v1/preregistration.json'
ENTRY_POINT = ROOT / 'scripts/run_g1_pass8.py'
PREREGISTRATION_SHA256 = '99b6520c514a931b602cfc99731ac17e81069d82e177dc3cd21b493f00e4591c'
PROTECTED_NAMES = {'batch_A_seed0', 'batch_B_shallow_seed0', 'batch_B_shallow_seed1', 'd0_g0_v1_seed0', 'd1_g0_cost_v1', 'd1_g0_estimation_v1'}

class PilotInterrupted(Exception):
    """Planned per-game checkpoint, not an experimental failure."""


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def protocol():
    if sha256(PROTOCOL) != PREREGISTRATION_SHA256:
        raise ConfigMismatch('G1-pass8 preregistration changed; create a new version')
    p = json.loads(PROTOCOL.read_text(encoding='utf-8'))
    if p['code_version'] != CODE_VERSION or p['experiment_id'] != 'G1-pass8-pilot-v1':
        raise ConfigMismatch('G1-pass8 protocol/version mismatch')
    if (p['pass_min_plies'] != [0,8] or type(p['budget']) is not int or p['budget']<1
            or not p['batch_seeds'] or len(set(p['batch_seeds']))!=len(p['batch_seeds'])
            or any(type(x) is not int or x<0 for x in p['batch_seeds'])):
        raise ConfigMismatch('invalid rule/budget/seeds')
    if p['identity_directions'] != [['WIN','WIN'],['LOSE','LOSE'],['WIN','LOSE'],['LOSE','WIN']]:
        raise ConfigMismatch('identity directions changed')
    if p['agent_seed_orientations'] != [[1,2],[2,1]] or p['board_size']!=5 or p['komi']!=2.5:
        raise ConfigMismatch('fixed factors changed')
    if p['games_per_cell']!=1 or p['planned_games']!=16*len(p['batch_seeds']):
        raise ConfigMismatch('invalid fixed pilot size')
    if type(p['schedule_seed']) is not int:raise ConfigMismatch('invalid schedule seed')
    return p


def experiment_lock():
    p = protocol()
    return {'experiment_id':p['experiment_id'], **current_provenance(),
        'preregistration_sha256':sha256(PROTOCOL), 'entry_point_sha256':sha256(ENTRY_POINT),
        'measurement_script_sha256':sha256(ROOT/'scripts/measure_g1_pass8_chunk.py'),
        'scipy_version':distribution_version('scipy'),'numpy_version':distribution_version('numpy')}


def cells(p=None):
    p = protocol() if p is None else p
    blocks=[]
    for seed in p['batch_seeds']:
        for identity_index,(ib,iw) in enumerate(p['identity_directions']):
            for orientation_index,(sb,sw) in enumerate(p['agent_seed_orientations']):
                block_index=identity_index*2+orientation_index
                blocks.append({'budget':p['budget'],'batch_seed':seed,'black_identity':ib,
                    'white_identity':iw,'black_seed':sb,'white_seed':sw,'replicate':0,
                    'block_index':block_index,'block_id':f'{seed}:{block_index}'})
    rng=random.Random(p['schedule_seed']);rng.shuffle(blocks)
    orders=[[0,8],[8,0]]*(len(blocks)//2);rng.shuffle(orders)
    return [dict(block,pass_min_ply=rule,ruleset='G0' if rule==0 else 'G1-pass8')
            for block,order in zip(blocks,orders) for rule in order]


def jobs(p=None):
    p = protocol() if p is None else p
    result=[]
    for idx,c in enumerate(cells(p)):
        level={64:'shallow',256:'medium',1024:'deep'}.get(c['budget'],f"sims:{c['budget']}")
        def spec(color):
            identity=c[color+'_identity']; seed=c[color+'_seed']
            return AgentSpec(f'{identity}-{level}-s{seed}',Identity(identity),'vector_mcts',level,seed)
        result.append({'index':idx,'batch_id':p['batch_id'],
            'game_seed':game_seed_for(c['batch_seed'],c['block_index']),
            'black':spec('black'),'white':spec('white'),'pass_min_ply':c['pass_min_ply']})
    return result


def config(concurrency,p=None):
    p=protocol() if p is None else p
    return {'batch_id':p['batch_id'],'kind':p['experiment_id'],'requested_games':p['planned_games'],
        'batch_seed':p['batch_seeds'],'concurrency':concurrency,'board_size':5,'komi':2.5,
        'code_version':CODE_VERSION,'pass_min_plies':p['pass_min_plies'],'budget':p['budget'],'schedule_seed':p['schedule_seed']}


def assert_output_allowed(out):
    raw=Path(out).absolute()
    # Reject symlinks in ancestors too, before resolving away their identity.
    if any(p.is_symlink() for p in (raw,*raw.parents)):
        raise ValueError('symlinked output paths are forbidden')
    path=raw.resolve()
    immutable_roots=[ROOT.parent/name for name in ('winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1')]
    if any(path.is_relative_to(old.resolve()) for old in immutable_roots):
        raise ValueError('immutable baseline/pilot worktrees are read-only')
    if PROTECTED_NAMES.intersection(path.parts) or path == ROOT or path in ROOT.parents:
        raise ValueError('historical/broad output is read-only')
    if path == ROOT/'outputs' or path.is_relative_to(ROOT/'reports'):
        raise ValueError('output must be a dedicated new experiment directory')
    if path.exists() and any(p.is_symlink() for p in path.rglob('*')):
        raise ValueError('output contains symlinks')
    if (path/'manifest.json').exists():
        manifest=json.loads((path/'manifest.json').read_text())
        if manifest.get('batch_id') != protocol()['batch_id']:
            raise ValueError('cannot modify a different experiment')
    return path


def strip_timing(record):
    rec=copy.deepcopy(record); rec.pop('game_wall_ms',None)
    for move in rec['moves']: move.pop('search_time_ms',None)
    return rec


def record_problems(rec,job):
    problems=[]
    required={'game_id','batch_id','game_index','game_seed','board_size','komi','black','white','pass_min_ply','ruleset',
        'black_agent_id','white_agent_id','black_identity','white_identity','black_algorithm','white_algorithm',
        'black_compute_level','white_compute_level','winner','black_score','white_score','score_margin',
        'black_utility','white_utility','move_count','termination_reason','final_board','superko_rejections','game_wall_ms','moves'}
    if not isinstance(rec,dict) or not required.issubset(rec):return ['missing mandatory game fields']
    numeric=lambda v: isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    for key in ('black_score','white_score','score_margin','komi','black_utility','white_utility'):
        if not numeric(rec[key]):problems.append('invalid numeric field: '+key)
    if type(rec['black_utility']) is not int or type(rec['white_utility']) is not int:
        problems.append('utilities must be integers, not booleans')
    if not numeric(rec['game_wall_ms']) or rec['game_wall_ms']<0:problems.append('invalid game timing')
    if not isinstance(rec['final_board'],list) or len(rec['final_board'])!=25 or any(type(v) is not int or v not in (0,1,2) for v in rec['final_board']):problems.append('invalid final_board')
    if not isinstance(rec['moves'],list):return problems+['moves must be an array']
    mandatory={'index','color','action','is_pass','legal_action_count','superko_excluded','root_visit_count',
        'action_visit_counts','action_q_black','action_q_white','simulations_used','search_time_ms'}
    for m in rec['moves']:
        if not isinstance(m,dict) or not mandatory.issubset(m):return problems+['missing mandatory move fields']
        for k in ('index','action','legal_action_count','superko_excluded','root_visit_count','simulations_used'):
            if type(m[k]) is not int:return problems+['move integer type mismatch: '+k]
        if type(m['is_pass']) is not bool:return problems+['is_pass type mismatch']
        for key in ('action_visit_counts','action_q_black','action_q_white'):
            mapping=m[key]
            if not isinstance(mapping,dict):return problems+['search map must be object']
            canonical=[]
            for a in mapping:
                if type(a) is int and a>=0:canonical.append(a)
                elif type(a) is str and a.isascii() and a.isdigit() and str(int(a))==a:canonical.append(int(a))
                else:return problems+['noncanonical action map key']
            if len(canonical)!=len(set(canonical)):return problems+['duplicate normalized action key']
    for k in ('game_index','game_seed','board_size','move_count','superko_rejections'):
        if type(rec[k]) is not int:return problems+['game integer type mismatch: '+k]

    gid=f"{job['batch_id']}-g{job['index']:06d}"
    for k,v in current_provenance().items():
        if rec.get(k)!=v: problems.append('provenance mismatch: '+k)
    expected={'game_id':gid,'batch_id':job['batch_id'],'game_index':job['index'],
        'game_seed':job['game_seed'],'board_size':5,'komi':2.5,'pass_min_ply':job['pass_min_ply'], 'ruleset':'G0' if job['pass_min_ply']==0 else 'G1-pass8'}
    for color in ('black','white'):
        spec=job[color]
        expected[color]=spec.to_dict()
        for key in ('agent_id','identity','algorithm','compute_level'):
            expected[color+'_'+key]=spec.to_dict()[key]
    for k,v in expected.items():
        if rec.get(k)!=v: problems.append('configuration mismatch: '+k)
    problems.extend(replay_record(rec)['problems'])
    if not job['pass_min_ply']+2 <= rec['move_count'] <= 100: problems.append('invalid length')
    state=GoState.initial(5,pass_min_ply=job['pass_min_ply']); superko=0
    for move in rec['moves']:
        legal,counts=state.legal_report(); superko+=counts['superko']
        budget=job['black' if state.to_play==BLACK else 'white'].simulations()
        visits={int(k):v for k,v in move['action_visit_counts'].items()}
        if (move['simulations_used']!=budget or move['root_visit_count']!=budget or
                set(visits)!=set(legal) or any(type(v) is not int or v<0 for v in visits.values()) or
                sum(visits.values())!=budget or visits.get(move['action'])!=max(visits.values(),default=-1)):
            problems.append(f"ply{move['index']}: budget/visits/choice mismatch")
        qs=[]
        for key in ('action_q_black','action_q_white'):
            q={int(k):v for k,v in move[key].items()};qs.append(q)
            if set(q)!=set(legal): problems.append('Q action set mismatch')
            for a,v in q.items():
                if visits.get(a,0)==0:
                    if v is not None: problems.append('unvisited Q must be null')
                elif (not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or abs(v)>1+1e-10):
                    problems.append('invalid visited Q')
        same=rec['black_identity']==rec['white_identity']
        for a in set(qs[0]) & set(qs[1]):
            qb,qw=qs[0][a],qs[1][a]
            if isinstance(qb,(int,float)) and isinstance(qw,(int,float)) and abs(qb-(-qw if same else qw))>1e-10:
                problems.append('Q utility relationship mismatch')
        if move['superko_excluded']!=counts['superko']: problems.append('per-ply superko mismatch')
        if not numeric(move['search_time_ms']) or move['search_time_ms']<0:
            problems.append('invalid search timing')
        state=state.play(move['action'])
        if board_has_dead_group(state.board,5): problems.append('dead group')
    if superko!=rec['superko_rejections']: problems.append('total superko mismatch')
    return problems


def validate(out,require_complete=True,check_analysis=True):
    """Read-only registered-design validator, including interrupted checkpoints."""
    out=Path(out);p=protocol(); plan=jobs(p); locked=experiment_lock(); problems=[]
    manifest=json.loads((out/'manifest.json').read_text())
    if (out/'rule_fault.json').exists():problems.append('persisted rule fault requires new version')
    if json.loads((out/'experiment_lock.json').read_text())!=locked: problems.append('experiment lock mismatch')
    if sha256(out/'preregistration.json')!=locked['preregistration_sha256']: problems.append('saved preregistration mismatch')
    if json.loads((out/'source_lock.json').read_text())!=source_lock(): problems.append('source lock mismatch')
    for k,v in config(manifest.get('concurrency'),p).items():
        if manifest.get(k)!=v: problems.append('manifest mismatch: '+k)
    for k,v in current_provenance().items():
        if manifest.get(k)!=v: problems.append('manifest provenance mismatch: '+k)
    if manifest.get('concurrency') not in allowed_concurrency(p): problems.append('invalid concurrency')
    if manifest.get('planned_game_count')!=len(plan): problems.append('planned count mismatch')
    expected_agents={s.agent_id:s.to_dict() for j in plan for s in (j['black'],j['white'])}
    if manifest.get('agents')!=list(expected_agents.values()): problems.append('manifest agents mismatch')
    if json.loads((out/'plan.json').read_text())!=[job_to_entry(j) for j in plan]: problems.append('plan mismatch')
    if json.loads((out/'game_seeds.json').read_text())!=[{'index':j['index'],'game_seed':j['game_seed']} for j in plan]: problems.append('seed mirror mismatch')
    meta=read_metadata(str(out)); indexes=[r['game_index'] for r in meta]
    if indexes!=sorted(set(indexes)): problems.append('metadata indexes not unique/ascending')
    by_id={r['game_id']:r for r in meta}; saved=[];replay_ok=0
    for path in sorted((out/'games').glob('*.json')):
        rec=json.loads(path.read_text());saved.append(rec);idx=rec['game_index']
        if type(idx) is not int or not 0<=idx<len(plan): problems.append('unexpected game index');continue
        if path.name!=f"{plan[idx]['batch_id']}-g{idx:06d}.json": problems.append('game filename mismatch')
        try: issues=record_problems(rec,plan[idx])
        except (ValueError,TypeError,KeyError) as e: issues=['malformed record: '+str(e)]
        if not issues: replay_ok+=1
        problems.extend(f"{rec['game_id']}: {x}" for x in issues)
        if by_id.get(rec['game_id'])!=_metadata_line(rec): problems.append('full metadata mismatch: '+rec['game_id'])
    saved_indexes=sorted(r['game_index'] for r in saved)
    if saved_indexes!=list(range(len(saved))):problems.append('saved games are not a contiguous prefix')
    unexpected=[p.name for p in (out/'games').iterdir() if not p.is_file() or p.suffix not in ('.json','.tmp')]
    if unexpected:problems.append('unexpected game artifacts: '+str(unexpected))
    if saved_indexes!=indexes: problems.append('game files and metadata mismatch')
    if manifest.get('completed_indexes')!=saved_indexes or manifest.get('completed_game_count')!=len(saved): problems.append('completed manifest indexes/count mismatch')
    if require_complete and saved_indexes!=list(range(len(plan))): problems.append('incomplete registered sample')
    if check_analysis and len(saved)==len(plan) and not problems:
        if (out/'analysis.json').exists():
            if json.loads((out/'analysis.json').read_text())!=analyze(out):problems.append('saved analysis mismatch')
        elif manifest.get('status')==STATUS_COMPLETED:problems.append('completed run missing analysis')
    return {'experiment_id':p['experiment_id'],'planned':len(plan),'game_count':len(saved),
        'replay_and_search_ok':replay_ok,'complete':saved_indexes==list(range(len(plan))),
        'problems':problems,'manifest_status':manifest.get('status'),'rule_fault_present':(out/'rule_fault.json').exists(),
        'source_fingerprint':locked['source_fingerprint'],
        'raw_game_sha256':{f.name:sha256(f) for f in sorted((out/'games').glob('*.json'))}}



def resume_preflight(out, p, plan, locked):
    """Read-only rejection before generic RunStore's permitted tail repair.

    Only a torn trailing metadata line or a missing line for a valid full
    record is repairable. Complete corrupt records are never overwritten.
    Interrupted manifest progress may lag valid disk records after a crash.
    """
    from ..league.runstore import _split_metadata_lines, MetadataCorrupt
    def read(name):
        try:
            return json.loads((out/name).read_text())
        except (OSError, ValueError, TypeError) as error:
            raise ConfigMismatch('missing/malformed '+name) from error
    manifest=read('manifest.json')
    if read('experiment_lock.json') != locked or sha256(out/'preregistration.json')!=locked['preregistration_sha256']:
        raise ConfigMismatch('G1-pass8 experiment lock/preregistration mismatch')
    if read('source_lock.json')!=source_lock():raise ConfigMismatch('source lock mismatch')
    for k,v in {**config(manifest.get('concurrency'),p),**current_provenance(),'planned_game_count':len(plan)}.items():
        if manifest.get(k)!=v:raise ConfigMismatch('manifest mismatch: '+k)
    agents={s.agent_id:s.to_dict() for j in plan for s in (j['black'],j['white'])}
    if manifest.get('agents')!=list(agents.values()):raise ConfigMismatch('manifest agents mismatch')
    if manifest.get('concurrency') not in allowed_concurrency(p):raise ConfigMismatch('invalid concurrency')
    if read('plan.json')!=[job_to_entry(j) for j in plan]:raise ConfigMismatch('plan mismatch')
    if read('game_seeds.json')!=[{'index':j['index'],'game_seed':j['game_seed']} for j in plan]:raise ConfigMismatch('seed mirror mismatch')
    full={}
    for path in sorted((out/'games').iterdir()):
        if path.name.endswith('.tmp') and path.is_file():continue
        if path.suffix!='.json' or not path.is_file():raise ConfigMismatch('unexpected game artifact')
        try:
            rec=json.loads(path.read_text());idx=rec['game_index']
            if type(idx) is not int or not 0<=idx<len(plan):raise ValueError('unknown index')
            expected=f"{p['batch_id']}-g{idx:06d}"
            if path.name!=expected+'.json' or expected in full:raise ValueError('bad filename/duplicate')
            issues=record_problems(rec,plan[idx])
            if issues:raise ValueError('; '.join(issues))
        except (ValueError,TypeError,KeyError) as error:
            raise ConfigMismatch('invalid saved game: '+path.name+': '+str(error)) from error
        full[expected]=rec
    saved_indexes=sorted(r['game_index'] for r in full.values())
    if saved_indexes!=list(range(len(full))):raise ConfigMismatch('saved games are not a contiguous prefix')
    declared=manifest.get('completed_indexes');count=manifest.get('completed_game_count')
    if type(count) is not int or count<0 or count>len(full) or declared!=list(range(count)):
        raise ConfigMismatch('manifest progress is not a consistent saved prefix')
    text=(out/'games.jsonl').read_text() if (out/'games.jsonl').exists() else ''
    valid,bad=_split_metadata_lines(text)
    if bad and any(i<=max((i for i,_ in valid),default=-1) for i in bad):raise MetadataCorrupt('nonterminal metadata corruption')
    seen=set();indexes=[]
    for _,rec in valid:
        if not isinstance(rec,dict):raise MetadataCorrupt('metadata must be an object')
        gid=rec.get('game_id')
        if gid in seen:raise MetadataCorrupt('duplicate metadata')
        if gid not in full or rec!=_metadata_line(full[gid]):raise ConfigMismatch('metadata/full-record mismatch')
        seen.add(gid);indexes.append(rec['game_index'])
    if indexes!=sorted(set(indexes)):raise MetadataCorrupt('metadata order mismatch')
    if manifest.get('status')==STATUS_COMPLETED:
        checked=validate(out)
        if checked['problems']:raise ConfigMismatch('; '.join(checked['problems']))

def allowed_concurrency(p):
    # Formal cost protocol fixes one worker; explicit test protocols exercise2.
    return (1,2) if p['resource_policy']['concurrency']==2 else (1,)


@contextmanager
def exclusive_output_lock(out):
    """OS advisory single-writer lock, outside evidence so rejection is read-only.

    Lock file is deliberately retained: unlinking a lock permits a second inode
    and breaks exclusion. Process exit/crash releases the operating-system lock.
    Separate output directories may execute concurrently; one directory cannot.
    """
    key=hashlib.sha256(str(Path(out).resolve()).encode()).hexdigest()
    lock_path=Path(tempfile.gettempdir())/('winai_loseai_'+key+'.lock')
    flags=os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(lock_path,flags,0o600)
    acquired=False
    try:
        if os.name=='nt':
            import msvcrt
            if os.fstat(fd).st_size==0:os.write(fd,b'0')
            os.lseek(fd,0,os.SEEK_SET)
            try:msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            except OSError as error:raise ConfigMismatch('another writer owns this output directory') from error
        else:
            import fcntl
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error:raise ConfigMismatch('another writer owns this output directory') from error
        acquired=True
        yield
    finally:
        if acquired:
            if os.name=='nt':
                os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
            else:fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)


def run(out,concurrency=1,resume=False,stop_after=None):
    out=assert_output_allowed(out)
    with exclusive_output_lock(out):
        return run_locked(out,concurrency,resume,stop_after)


def run_locked(out,concurrency=1,resume=False,stop_after=None):
    if concurrency not in allowed_concurrency(protocol()):raise ValueError('concurrency violates registered resource policy')
    if stop_after is not None and stop_after<1:raise ValueError('stop_after must be positive')
    out=assert_output_allowed(out);p=protocol();locked=experiment_lock();plan=jobs(p)
    store=RunStore(str(out))
    if (out/'rule_fault.json').exists():raise ConfigMismatch('nonretryable frozen rule fault; new design/version required')
    if resume:
        resume_preflight(out,p,plan,locked)
        # Reject changed experimental inputs before repair or any write.
        if json.loads((out/'experiment_lock.json').read_text())!=locked or sha256(out/'preregistration.json')!=locked['preregistration_sha256']:
            raise ConfigMismatch('G1-pass8 experiment lock/preregistration mismatch')
        store.open_for_resume(plan,config(concurrency,p))
        # Validate all retained records after narrowly authorized metadata repair.
        # A stale interrupted manifest may lag valid files, so reconcile from disk.
        if store.manifest_status()==STATUS_COMPLETED and not store.pending_indexes():
            checked=validate(out)
            if checked['problems']:raise ValueError(checked['problems'])
            return checked
        for idx in store.completed:
            rec=json.loads(Path(store.game_path(f"{p['batch_id']}-g{idx:06d}")).read_text())
            issues=record_problems(rec,plan[idx])
            if issues:raise ValueError(issues)
    else:
        if out.exists() and any(out.iterdir()):raise FileExistsError('G1-pass8 output must be empty; use --resume')
        store.start(plan,config(concurrency,p),overwrite=False)
        atomic_json(out/'experiment_lock.json',locked)
        (out/'preregistration.json').write_bytes(PROTOCOL.read_bytes())
    store.update(STATUS_RUNNING);count=0
    try:
        pending=[j for j in plan if j['index'] not in store.completed]
        for rec in stream_jobs(pending,concurrency=concurrency,board_size=5,komi=2.5):
            if experiment_lock()!=locked:raise ConfigMismatch('G1-pass8 inputs changed while running')
            issues=record_problems(rec,plan[rec['game_index']])
            if issues:raise ValueError(issues)
            store.write_game(rec);count+=1;store.update(STATUS_RUNNING)
            print(f"[G1-pass8] saved {len(store.completed)}/{len(plan)} budget={plan[rec['game_index']]['black'].simulations()} plies={rec['move_count']} wall_ms={rec['game_wall_ms']}",flush=True)
            if stop_after is not None and count>=stop_after and store.pending_indexes():
                raise PilotInterrupted(f'planned checkpoint after {count} new games')
        checked=validate(out,check_analysis=False)
        if checked['problems']:
            store.update(STATUS_VALIDATION_FAILED,error='; '.join(checked['problems']))
            atomic_json(out/'validation.json',checked);raise ValueError('G1-pass8 validation failed')
        atomic_json(out/'analysis.json',analyze(out));atomic_json(out/'validation.json',checked)
        store.finish();final=validate(out)
        if final['problems']:
            store.update(STATUS_VALIDATION_FAILED,error='; '.join(final['problems']))
            atomic_json(out/'validation.json',final)
            raise ValueError('G1-pass8 final validation failed')
        return final
    except (PilotInterrupted,KeyboardInterrupt):
        store.update(STATUS_INTERRUPTED);raise
    except Exception as error:
        from ..game.state import NoLegalActionError
        if isinstance(error,NoLegalActionError):
            next_index=len(store.completed)
            atomic_json(out/'rule_fault.json',{'error_type':type(error).__name__,'message':str(error),'game_index':next_index,'job':job_to_entry(plan[next_index]),'state':error.diagnostics,'traceback':traceback.format_exc()})
        if store.manifest_status()!=STATUS_VALIDATION_FAILED:store.update(STATUS_FAILED,error=traceback.format_exc(limit=5))
        raise


def records(out):
    return [json.loads(p.read_text()) for p in sorted((Path(out)/'games').glob('*.json'))]


def quantile(values,q):
    a=sorted(values)
    if not a:return None
    i=(len(a)-1)*q;lo=int(i);hi=min(lo+1,len(a)-1)
    return a[lo]+(a[hi]-a[lo])*(i-lo)


def distribution(values):
    return {'n':len(values),'mean':statistics.mean(values) if values else None,
        **{name:quantile(values,q) for name,q in [('min',0),('q1',.25),('median',.5),('q3',.75),('p90',.9),('p95',.95),('max',1)]}}


def describe_game(rec):
    state = GoState.initial(5,pass_min_ply=rec['pass_min_ply'])
    actions = [m["action"] for m in rec["moves"]]
    pass_events = []
    counts = {c: {"passes": 0, "placements": 0, "captured_by_opponent": 0} for c in ("black", "white")}
    for i, move in enumerate(rec["moves"]):
        color = move["color"]
        if move["is_pass"]:
            counts[color]["passes"] += 1
            if state.consecutive_passes == 0:
                scored = score_position(state.board, 5, 2.5)
                utilities = black_white_utilities(scored["winner"], Identity(rec["black_identity"]), Identity(rec["white_identity"]))
                pass_events.append({"ply": i + 1, "proposer": color,
                    "score_margin": scored["score_margin"], "instant_utilities": list(utilities),
                    "next_action_available": i + 1 < len(actions),
                    "accepted": actions[i + 1] == 25 if i + 1 < len(actions) else None})
        else:
            counts[color]["placements"] += 1
        child = state.play(move["action"])
        enemy, enemy_code = ("white", WHITE) if state.to_play == BLACK else ("black", BLACK)
        counts[enemy]["captured_by_opponent"] += state.board.count(enemy_code) - child.board.count(enemy_code)
        state = child
    own = {color: actions[offset::2] for color, offset in (("black", 0), ("white", 1))}
    return {key: rec[key] for key in ("game_id", "black_identity", "white_identity", "black_algorithm",
            "white_algorithm", "winner", "black_score", "white_score", "black_utility", "white_utility",
            "move_count", "termination_reason", "superko_rejections", "game_wall_ms")} | {
        "actions": actions, "color_counts": counts, "pass_proposals": pass_events,
        "pass_min_ply":rec["pass_min_ply"], "ruleset":rec["ruleset"],
        "extra_length":rec["move_count"]-(rec["pass_min_ply"]+2),
        "first_pass_action":next((i+1 for i,a in enumerate(actions) if a==25),None),
        "routes": {"empty_double_pass": actions == [25, 25],
            "black_one_stone_double_pass": len(actions) == 3 and actions[0] < 25 and actions[1:] == [25, 25],
            "all_pass_by_color": {c: bool(seq) and all(a == 25 for a in seq) for c, seq in own.items()},
            "one_stone_then_pass_by_color": {c: bool(seq) and seq[0] < 25 and all(a == 25 for a in seq[1:]) for c, seq in own.items()}},
        "prefixes": {str(length): {"raw": actions[:length] if len(actions) >= length else None,
                     "END_padded": (actions + [-1] * length)[:length]} for length in (4, 8, 12)}}



def summarize(rows):
    lengths=[r['move_count'] for r in rows]
    wall=[r['game_wall_ms']/1000 for r in rows]
    prefixes={}
    for length in (4,8,12):
        result={}
        for mode in ('raw','END_padded'):
            seqs=[r['prefixes'][str(length)][mode] for r in rows if r['prefixes'][str(length)][mode] is not None]
            counts=Counter(tuple(x) for x in seqs)
            result[mode]={'n':len(seqs),'unique':len(counts),'top1_count':max(counts.values(),default=0)}
        prefixes[str(length)]=result
    proposals=[e for r in rows for e in r['pass_proposals']]
    acceptance={}
    for color,offset in [('black',0),('white',1)]:
        for favorable in (True,False):
            pp=[e for e in proposals if e['proposer']==color and (e['instant_utilities'][offset]==1)==favorable and e['next_action_available']]
            acceptance[f'{color}_proposer_favorable_{favorable}']={'opportunities':len(pp),'accepted':sum(e['accepted'] for e in pp)}
    return {'n':len(rows),'black_board_wins':sum(r['winner']=='black' for r in rows),
        'white_board_wins':sum(r['winner']=='white' for r in rows),
        'black_goals':sum(r['black_utility']==1 for r in rows),'white_goals':sum(r['white_utility']==1 for r in rows),
        'joint_goals':sum(r['black_utility']==r['white_utility']==1 for r in rows),
        'length':distribution(lengths),'length2':lengths.count(2),'length3':lengths.count(3),
        'length10':lengths.count(10),'length_le10':sum(x<=10 for x in lengths),
        'extra_length':distribution([r['extra_length'] for r in rows]),
        'first_pass_action':distribution([r['first_pass_action'] for r in rows if r['first_pass_action'] is not None]),
        'first_legal_pass_delay':distribution([r['first_pass_action']-(r['pass_min_ply']+1) for r in rows if r['first_pass_action'] is not None]),
        'color_counts':{c:{k:sum(r['color_counts'][c][k] for r in rows) for k in ('passes','placements','captured_by_opponent')} for c in ('black','white')},
        'length_le8':sum(x<=8 for x in lengths),'length_ge60':sum(x>=60 for x in lengths),
        'empty_double_pass':sum(r['routes']['empty_double_pass'] for r in rows),
        'black_one_stone_double_pass':sum(r['routes']['black_one_stone_double_pass'] for r in rows),
        'literal_d0_one_stone_route':sum(r['actions']==[0,25,25] for r in rows),
        'black_realized_all_pass':sum(r['routes']['all_pass_by_color']['black'] for r in rows),
        'termination':dict(Counter(r['termination_reason'] for r in rows)),
        'superko_total':sum(r['superko_rejections'] for r in rows),
        'game_wall_seconds':distribution(wall),'game_wall_seconds_sum':sum(wall),
        'search_ms':distribution([t for r in rows for t in r['search_times_ms']]),
        'output_game_bytes':sum(r['game_bytes'] for r in rows),
        'pass_proposal_acceptance':acceptance,'prefixes':prefixes}


def analyze(out):
    out=Path(out);p=protocol();cc=cells(p);rows=[]
    for rec in records(out):
        row=describe_game(rec);row.update(cc[rec['game_index']]);row['game_index']=rec['game_index'];row['game_seed']=rec['game_seed']
        row['search_times_ms']=[m['search_time_ms'] for m in rec['moves']]
        row['game_bytes']=(out/'games'/f"{rec['game_id']}.json").stat().st_size
        rows.append(row)
    groups={}
    for rule in p['pass_min_plies']:
        b=[r for r in rows if r['pass_min_ply']==rule]
        key='G0' if rule==0 else 'G1-pass8'
        groups[key]={'all':summarize(b),'directions':{},'seeds':{}}
        for ib,iw in p['identity_directions']:
            groups[key]['directions'][ib+'/'+iw]=summarize([r for r in b if r['black_identity']==ib and r['white_identity']==iw])
        for seed in p['batch_seeds']:
            groups[key]['seeds'][str(seed)]={ib+'/'+iw:summarize([r for r in b if r['batch_seed']==seed and r['black_identity']==ib and r['white_identity']==iw]) for ib,iw in p['identity_directions']}
    representatives={}
    for rule in p['pass_min_plies']:
        for ib,iw in p['identity_directions']:
            rr=sorted([r for r in rows if r['pass_min_ply']==rule and r['black_identity']==ib and r['white_identity']==iw],key=lambda r:(r['move_count'],r['game_id']))
            if rr:representatives[f'{rule}:{ib}/{iw}']=[rr[i]['game_id'] for i in (0,(len(rr)-1)//2,len(rr)-1)]
    abnormal=[r['game_id'] for r in rows if r['termination_reason']!='double_pass' or r['black_identity']!=r['white_identity'] and r['black_utility']!=1]
    paired=[]
    for block_id in sorted({r['block_id'] for r in rows}):
        block={r['pass_min_ply']:r for r in rows if r['block_id']==block_id}
        if len(block)!=2:continue
        a,b=block[0],block[8]
        paired.append({'block_id':block_id,'batch_seed':a['batch_seed'],'black_identity':a['black_identity'],'white_identity':a['white_identity'],
            'G0_game_id':a['game_id'],'G1_game_id':b['game_id'],'length_delta':b['move_count']-a['move_count'],
            'extra_length_delta':b['extra_length']-a['extra_length'],
            'black_goal_delta':int(b['black_utility']==1)-int(a['black_utility']==1),
            'white_goal_delta':int(b['white_utility']==1)-int(a['white_utility']==1),
            'black_board_win_delta':int(b['winner']=='black')-int(a['winner']=='black'),
            'joint_goal_delta':int(b['black_utility']==b['white_utility']==1)-int(a['black_utility']==a['white_utility']==1)})
    deltas={}
    for seed in [None,*p['batch_seeds']]:
        subset=[r for r in paired if seed is None or r['batch_seed']==seed]
        deltas['pooled' if seed is None else str(seed)]={ib+'/'+iw:{k:distribution([r[k] for r in subset if r['black_identity']==ib and r['white_identity']==iw]) for k in ('length_delta','extra_length_delta','black_goal_delta','white_goal_delta','joint_goal_delta','black_board_win_delta')} for ib,iw in p['identity_directions']}
    mixed_same={}
    for rule in p['pass_min_plies']:
        name='G0' if rule==0 else 'G1-pass8';mixed_same[name]={}
        for seed in [None,*p['batch_seeds']]:
            subset=[r for r in rows if r['pass_min_ply']==rule and (seed is None or r['batch_seed']==seed)]
            dirs={ib+'/'+iw:[r for r in subset if r['black_identity']==ib and r['white_identity']==iw] for ib,iw in p['identity_directions']}
            means={key:statistics.mean(r['move_count'] for r in value) if value else None for key,value in dirs.items()}
            result={'direction_n':{key:len(value) for key,value in dirs.items()},'direction_mean':means}
            if all(v is not None for v in means.values()):
                ww,ll,wl,lw=[means[k] for k in ('WIN/WIN','LOSE/LOSE','WIN/LOSE','LOSE/WIN')]
                mixed=(wl+lw)/2;same=(ww+ll)/2
                result.update(mixed_mean=mixed,same_mean=same,mixed_minus_same=mixed-same,mixed_minus_WW=mixed-ww,mixed_minus_LL=mixed-ll)
            mixed_same[name]['pooled' if seed is None else str(seed)]=result
    return {'experiment_id':p['experiment_id'],'pilot_descriptive_only' :True,'n_records':len(rows),
        'groups':groups,'rows':rows,'paired_differences':paired,'paired_summaries':deltas,'supplemental_equal_direction_means':mixed_same,
        'representatives':representatives,'anomalous_game_ids':abnormal,
        'interpretation':'Extra length subtracts a mechanical rule-specific minimum, not a causal adjustment. No inferential intervals; no historical or future data pooled.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('run','validate','analyze'))
    parser.add_argument('--out',required=True);parser.add_argument('--concurrency',type=int,default=1,choices=(1,2))
    parser.add_argument('--resume',action='store_true');parser.add_argument('--stop-after',type=int)
    parser.add_argument('--allow-incomplete',action='store_true')
    args=parser.parse_args();start=time.perf_counter()
    try:
        if args.command=='run':result=run(args.out,args.concurrency,args.resume,args.stop_after)
        elif args.command=='validate':result=validate(args.out,not args.allow_incomplete)
        else:result=analyze(args.out)
    except PilotInterrupted as error:
        print(str(error),flush=True);return 75
    print(json.dumps(result,ensure_ascii=False,indent=2));print(f'wall_seconds={time.perf_counter()-start:.6f}')
    return int(bool(result.get('problems',[])))
