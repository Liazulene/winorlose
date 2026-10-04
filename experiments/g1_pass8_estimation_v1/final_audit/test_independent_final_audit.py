"""Stdlib self-tests. All games are fabricated fixtures in temporary directories.
No production imports, search calls, formal games, or historical writes.
"""
import contextlib
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import random
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True

sys.path.insert(0, str(Path(__file__).resolve().parent))
import independent_final_audit as audit

REAL_ROOT = Path(__file__).resolve().parents[3]
REVIEW = REAL_ROOT / audit.EXPERIMENT_PATH / 'independent_review'
sys.path.insert(0, str(REVIEW))
import recovery_verify_inference_v1 as guard
import verify_inference_arithmetic as arithmetic


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def make_record(cell, entry, provenance):
    """Known geometry only; recorded root values are synthetic, not MCTS claims."""
    actions = [25,25] if cell['pass_min_ply'] == 0 else [0,24,1,23,2,22,3,21,25,25]
    rec = dict(game_id=f"{audit.BATCH}-g{entry['index']:06d}", batch_id=audit.BATCH,
        game_index=entry['index'], game_seed=entry['game_seed'], board_size=5,
        komi=2.5, pass_min_ply=cell['pass_min_ply'], ruleset=cell['ruleset'],
        black=entry['black'], white=entry['white'], game_wall_ms=1000.0,
        move_count=len(actions), termination_reason='double_pass', superko_rejections=0,
        **provenance)
    for color in ('black','white'):
        for key in ('agent_id','identity','algorithm','compute_level'):
            rec[color+'_'+key] = entry[color][key]
    board = [0]*25
    moves = []
    history = {(tuple(board),1)}
    for i, action in enumerate(actions):
        color = i%2+1
        # Every empty point is legal on this separated-edge fixture; this is
        # intentionally not generated using the audit's legality routine.
        legal = [j for j,v in enumerate(board) if not v]
        if i>=cell['pass_min_ply']:
            legal.append(25)
        move = dict(index=i+1, color='black' if color==1 else 'white', action=action,
            is_pass=action==25, legal_action_count=len(legal), superko_excluded=0,
            root_visit_count=256, simulations_used=256, search_time_ms=10.0,
            action_visit_counts={str(j):256 if j==action else 0 for j in legal},
            action_q_black={str(j):0.0 if j==action else None for j in legal},
            action_q_white={str(j):0.0 if j==action else None for j in legal})
        moves.append(move)
        if action<25:
            board[action] = color
        history.add((tuple(board),3-color))
    rec['moves'] = moves
    rec['final_board'] = board
    # Edge stones leave one empty component touching both colors.
    rec.update(black_score=float(board.count(1)), white_score=float(board.count(2))+2.5,
               score_margin=-2.5, winner='white')
    rec['black_utility'] = 1 if rec['black_identity']=='LOSE' else -1
    rec['white_utility'] = 1 if rec['white_identity']=='WIN' else -1
    return rec


def inference_for(rows):
    expected = {'analysis_version':'g1-pass8-fixed-paired-cp-hoeffding-v1',
        'estimation_only':True, 'complete_registered_sample':True,
        'n_records':480, 'n_paired_blocks':240,
        'intervals':{'raw_length_support':[-90,98],
            'paired_goal_method':arithmetic.METHOD,
            'raw_length_method':'Hoeffding_independent_bounded_mean',
            'simultaneous_family_confidence_level':.95,'simultaneous_family_size':8,
            'per_family_interval_confidence_level':arithmetic.FAMILY_CONFIDENCE,
            'family':[{'direction':d,'endpoint':e} for d in audit.DIRECTIONS for e in (arithmetic.GOALS[d],'raw_length')]}}
    _, groups = arithmetic.verify(rows, {})
    expected.update(groups)
    return expected


def build_fixture(root):
    exp = root/audit.EXPERIMENT_PATH
    out = root/'synthetic_input'
    exp.mkdir(parents=True)
    (exp/'preregistration.json').write_bytes((REAL_ROOT/audit.EXPERIMENT_PATH/'preregistration.json').read_bytes())
    protocol = audit.read(exp/'preregistration.json')
    cells, plan = audit.design(protocol)
    put(exp/'frozen_plan.json',plan)
    (root/'src/winai_loseai').mkdir(parents=True)
    (root/'src/winai_loseai/__init__.py').write_text('# synthetic source\n')
    (root/'run.py').write_text('# synthetic entry\n')
    (root/'scripts').mkdir()
    for name in ('run_g1_pass8_estimation.py','measure_g1_pass8_estimation_chunk.py'):
        (root/'scripts'/name).write_text('# synthetic fixture only\n')
    (root/'tests').mkdir()
    (root/'tests/test_synthetic.py').write_text('# synthetic fixture only\n')
    source = {p.relative_to(root).as_posix():audit.digest(p) for p in [root/'run.py',root/'src/winai_loseai/__init__.py']}
    fingerprint = hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    provenance = dict(code_version=protocol['code_version'],schema_version=2,source_fingerprint=fingerprint,python_version='3.12.14')
    lock = dict(**provenance,algorithm='sha256-utf8-lf-path-map-v1',files=source)
    put(exp/'pre_execution_source_lock.json',lock)
    runlock = dict(experiment_id=audit.EXPERIMENT, **provenance,
        preregistration_sha256=audit.digest(exp/'preregistration.json'),
        entry_point_sha256=audit.digest(root/'scripts/run_g1_pass8_estimation.py'),
        measurement_script_sha256=audit.digest(root/'scripts/measure_g1_pass8_estimation_chunk.py'),
        scipy_version='synthetic',numpy_version='synthetic')
    review_hashes = {}
    for key, relative in audit.REVIEW_HASH_PATHS.items():
        put(exp/relative, {'synthetic_fixture': True})
        review_hashes[key] = audit.digest(exp/relative)
    (exp/'full_tests_final_prelaunch.txt').write_text('synthetic fixture log\n')
    put(exp/'pre_execution_lock.json',dict(**runlock, **review_hashes,
        full_suite={'log_sha256':audit.digest(exp/'full_tests_final_prelaunch.txt')},
        formal_games_before_freeze=0, scientific_plan_change=False, G0_regression_games=3,
        frozen_plan_sha256=audit.digest(exp/'frozen_plan.json'),
        test_files_sha256={'tests/test_synthetic.py':audit.digest(root/'tests/test_synthetic.py')}))
    put(out/'plan.json',plan)
    put(out/'game_seeds.json',[dict(index=e['index'],game_seed=e['game_seed']) for e in plan])
    put(out/'source_lock.json',lock)
    put(out/'experiment_lock.json',runlock)
    (out/'preregistration.json').write_bytes((exp/'preregistration.json').read_bytes())
    agents = {e[c]['agent_id']:e[c] for e in plan for c in ('black','white')}
    manifest = dict(batch_id=audit.BATCH,kind=audit.EXPERIMENT,status='completed',requested_games=480,
        planned_game_count=480,completed_game_count=480,completed_indexes=list(range(480)),
        board_size=5,komi=2.5,batch_seed=[11,12,13],concurrency=1,pass_min_plies=[0,8],
        budget=256,schedule_seed=2026100402,agents=list(agents.values()),**provenance)
    put(out/'manifest.json',manifest)
    metadata,rows=[] ,[]
    for cell,entry in zip(cells,plan):
        rec = make_record(cell,entry,provenance)
        path = out/'games'/(rec['game_id']+'.json')
        put(path,rec)
        row,errors = audit.reconstruct(rec,cell,entry,path.stat().st_size,provenance)
        if errors:raise AssertionError(errors)
        rows.append(row)
        metadata.append({k:v for k,v in rec.items() if k not in ('black','white','moves')} |
                        dict(opening_actions=[m['action'] for m in rec['moves'][:12]],game_file='games/'+path.name))
    (out/'games.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in metadata))
    descriptive = audit.assemble(rows)
    descriptive['inference'] = inference_for(rows)
    put(out/'analysis.json',descriptive)
    put(out/'validation.json',dict(experiment_id=audit.EXPERIMENT,planned=480,game_count=480,
        replay_and_search_ok=480,complete=True,problems=[],manifest_status='completed',
        rule_fault_present=False,source_fingerprint=fingerprint,
        raw_game_sha256={p.name:audit.digest(p) for p in sorted((out/'games').glob('*.json'))}))
    review = exp/'independent_review'
    review.mkdir(exist_ok=True)
    for name in ('recovery_verify_inference_v1.py','verify_inference_arithmetic.py'):
        shutil.copyfile(REVIEW/name,review/name)
    return out,rows


class MathematicsAndRules(unittest.TestCase):
    def test_area_empty_monocolor_and_neutral(self):
        self.assertEqual(audit.area([0]*25),dict(black_score=0.0,white_score=2.5,score_margin=-2.5,winner='white'))
        b=[0]*25;b[12]=1
        self.assertEqual(audit.area(b)['black_score'],25)
        b[0]=2
        self.assertEqual(audit.area(b)['black_score'],1)
        self.assertEqual(audit.area(b)['white_score'],3.5)

    def test_capture_and_suicide(self):
        b=[0]*25;b[0]=2;b[1]=1
        placed,n=audit.apply_placement(b,5,1)
        self.assertEqual(n,1);self.assertEqual(placed[0],0)
        b=[0]*25;b[1]=2;b[5]=2
        with self.assertRaisesRegex(ValueError,'suicide'):audit.apply_placement(b,0,1)

    def test_multistone_capture(self):
        b=[0]*25;b[0]=b[1]=2;b[5]=b[6]=1
        placed,n=audit.apply_placement(b,2,1)
        self.assertEqual(n,2);self.assertEqual(placed[:3],[0,0,1])

    def test_superko_root_and_pass_exemption(self):
        b=[0]*25;c=b.copy();c[0]=1
        history={(tuple(b),1),(tuple(c),2),(tuple(b),2)}
        legal,n=audit.legal_actions(b,1,history,8,8)
        self.assertNotIn(0,legal);self.assertIn(25,legal);self.assertEqual(n,1)
        self.assertNotIn(25,audit.legal_actions(b,1,history,7,8)[0])

    def test_no_legal_nonpass_fails_closed(self):
        # Hypothetical state with every candidate blocked by situational history.
        b=[0]*25;history={(tuple(b),1)}
        for i in range(25):
            c=b.copy();c[i]=1;history.add((tuple(c),2))
        with self.assertRaisesRegex(ValueError,'no-legal-action'):audit.legal_actions(b,1,history,0,8)

    def test_utilities_all_directions(self):
        for winner in ('black','white'):
            for direction in audit.DIRECTIONS:
                ib,iw=direction.split('/')
                answer=audit.utilities(winner,ib,iw)
                self.assertEqual(answer[0],answer[1] if ib!=iw else -answer[1])

    def test_exact_seed_integer(self):
        n=2**127
        self.assertTrue(audit.differences(n,n+1))
        self.assertTrue(audit.differences(1,True))
        self.assertTrue(audit.differences(1,1.0))

    def test_quantiles_and_cp_closed_forms(self):
        d=audit.distribution([2,3,10,25])
        self.assertEqual(d['q1'],2.75);self.assertEqual(d['median'],6.5)
        self.assertEqual(d['q3'],13.75);self.assertEqual(d['mean'],10)
        tail=(1-arithmetic.FAMILY_CONFIDENCE)/4
        closed=1-tail**(1/60)
        self.assertAlmostEqual(arithmetic.pair_rate([0]*60,[0]*60,arithmetic.FAMILY_CONFIDENCE)['ci'][1],closed,places=12)
        radius=188*math.sqrt(math.log(320)/(120))
        self.assertAlmostEqual(arithmetic.mean_length([8]*60,arithmetic.FAMILY_CONFIDENCE)['unclipped_radius'],radius,places=11)

    def test_cap_precedence_and_last_proposal_denominator(self):
        protocol = audit.read(REAL_ROOT/audit.EXPERIMENT_PATH/'preregistration.json')
        cells,plan = audit.design(protocol)
        idx=next(i for i,c in enumerate(cells) if c['pass_min_ply']==0)
        provenance=dict(code_version=protocol['code_version'],schema_version=2,
            source_fingerprint='synthetic',python_version='synthetic')
        for double_pass in (True,False):
            with self.subTest(double_pass=double_pass):
                rec=make_record(cells[idx],plan[idx],provenance)
                board=[0]*25;history={(tuple(board),1)};moves=[]
                # Fixed synthetic legal capture-rich prefix, unrelated to all formal seeds.
                prefix=[12,25,14,1,9,20,19,16,11,23,17,7,13,3,8,4,2,22,6,24,4,10,0,5,25,18,15,25,1,10,21,18,15,25,24,25,7,22,23,25,3,25,5,25,18,25,20,25,10,25,16,22,17,14,2,3,12,21,20,5,13,15,19,1,18,9,25,7,16,20,6,23,11,10,8,4,2,3,25,4,0,25,9,25,1,3,7,25,4,25,24,23,25,15,14,10,25,22,20]
                for i in range(100):
                    color=i%2+1
                    legal,superko=audit.legal_actions(board,color,history,i,0)
                    action=25 if i==99 or i==98 and double_pass else prefix[i]
                    m=dict(index=i+1,color='black' if color==1 else 'white',action=action,
                        is_pass=action==25,legal_action_count=len(legal),superko_excluded=superko,
                        root_visit_count=256,simulations_used=256,search_time_ms=0,
                        action_visit_counts={str(a):256 if a==action else 0 for a in legal},
                        action_q_black={str(a):0 if a==action else None for a in legal},
                        action_q_white={str(a):0 if a==action else None for a in legal})
                    moves.append(m)
                    if action<25:board,_=audit.apply_placement(board,action,color)
                    history.add((tuple(board),3-color))
                rec.update(moves=moves,move_count=100,final_board=board,
                    termination_reason='double_pass' if double_pass else 'move_limit',
                    superko_rejections=sum(m['superko_excluded'] for m in moves),**audit.area(board))
                ub,uw=audit.utilities(rec['winner'],rec['black_identity'],rec['white_identity'])
                rec.update(black_utility=ub,white_utility=uw)
                row,errors=audit.reconstruct(rec,cells[idx],plan[idx],1000,provenance)
                self.assertFalse(errors,errors)
                for color,code,offset in (('black',1,0),('white',2,1)):
                    placements=sum(m['action']<25 for m in moves[offset::2])
                    self.assertEqual(row['color_counts'][color]['captured_by_opponent'],placements-board.count(code))
                if double_pass:self.assertTrue(row['pass_proposals'][-1]['accepted'])
                else:
                    event=row['pass_proposals'][-1]
                    self.assertEqual(event['ply'],100)
                    self.assertFalse(event['next_action_available']);self.assertIsNone(event['accepted'])
                    summary=audit.summarize([row])
                    denominator=sum(v['opportunities'] for v in summary['pass_proposal_acceptance'].values())
                    self.assertEqual(denominator,len(row['pass_proposals'])-1)
                rec['termination_reason']='move_limit' if double_pass else 'double_pass'
                _,errors=audit.reconstruct(rec,cells[idx],plan[idx],1000,provenance)
                self.assertTrue(any('terminal condition' in x for x in errors))

    def test_strict_json(self):
        for text in ('{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}','{"a":','[] trailing'):
            with self.subTest(text=text),self.assertRaises(ValueError):audit.parse_json(text)


class FullSyntheticAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template=tempfile.TemporaryDirectory(prefix='m5_synthetic_template_')
        cls.base=Path(cls.template.name)
        cls.out,cls.rows=build_fixture(cls.base)
    @classmethod
    def tearDownClass(cls):cls.template.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='m5_synthetic_case_')
        self.root=Path(self.tmp.name)/'repo'
        shutil.copytree(self.base,self.root)
        self.out=self.root/'synthetic_input'
    def tearDown(self):self.tmp.cleanup()
    def mutate(self,relative,change):
        path=self.root/relative;doc=audit.read(path);change(doc);put(path,doc)
    def game(self,index=0):return self.out/'games'/f'{audit.BATCH}-g{index:06d}.json'
    def fails(self,fragment=None):
        report,_=audit.audit(self.root,self.out)
        self.assertFalse(report['passed'])
        if fragment:self.assertIn(fragment,'\n'.join(report['problems']))
        self.assertFalse(report['statistical_audit']['arithmetic_executed'])
        return report

    def test_complete_fixture_and_known_descriptive_answers(self):
        before={str(p.relative_to(self.root)):audit.digest(p) for p in self.root.rglob('*') if p.is_file()}
        report,recomputed=audit.audit(self.root,self.out)
        self.assertTrue(report['passed'],report['problems']);self.assertTrue(report['complete'])
        self.assertEqual(report['n_records'],480);self.assertEqual(report['n_pairs'],240)
        self.assertEqual(report['n_actual_actions'],2880);self.assertEqual(report['n_pass_proposals'],480)
        self.assertEqual(recomputed['groups']['G0']['all']['length2'],240)
        self.assertEqual(recomputed['groups']['G1-pass8']['all']['length10'],240)
        self.assertEqual(recomputed['groups']['G0']['directions']['LOSE/WIN']['joint_goals'],60)
        self.assertEqual(recomputed['groups']['G0']['directions']['WIN/LOSE']['joint_goals'],0)
        self.assertEqual(recomputed['groups']['G0']['all']['prefixes']['4']['raw']['n'],0)
        self.assertEqual(recomputed['groups']['G0']['all']['prefixes']['4']['END_padded']['top1_count'],240)
        self.assertTrue(all(p['length_delta']==8 and p['extra_length_delta']==0 for p in recomputed['paired_differences']))
        after={str(p.relative_to(self.root)):audit.digest(p) for p in self.root.rglob('*') if p.is_file()}
        # Importing verification helpers must not create bytecode in evidence.
        self.assertEqual(before,after)

    def test_missing_record(self):self.game().unlink();self.fails('raw filenames/count')
    def test_duplicate_record(self):shutil.copyfile(self.game(),self.game().with_name('duplicate.json'));self.fails('raw filenames/count')
    def test_malformed_record(self):self.game().write_text('{"game_index":');self.fails('malformed/illegal')
    def test_duplicate_json_key(self):self.game().write_text('{"game_index":0,"game_index":1}');self.fails('duplicate JSON key')
    def test_missing_move_field(self):
        self.mutate(self.game().relative_to(self.root),lambda r:r['moves'][0].pop('action_q_black'));self.fails('missing/malformed move fields')
    def test_false_integer_action(self):
        self.mutate(self.game().relative_to(self.root),lambda r:r['moves'][0].update(action=True));self.fails('invalid move integer')
    def test_root_legal_omission(self):
        def change(r):
            m=r['moves'][0];k=next(k for k in m['action_visit_counts'] if k!=str(m['action']))
            for name in ('action_visit_counts','action_q_black','action_q_white'):m[name].pop(k)
            m['legal_action_count']-=1
        self.mutate(self.game().relative_to(self.root),change);self.fails('independently enumerated legal root set')
    def test_early_pass(self):
        i=next(i for i,r in enumerate(self.rows) if r['pass_min_ply']==8)
        self.mutate(self.game(i).relative_to(self.root),lambda r:r['moves'][0].update(action=25,is_pass=True));self.fails('early actual pass')
    def test_final_area_corruption(self):
        self.mutate(self.game().relative_to(self.root),lambda r:r.update(black_score=999));self.fails('independent area')
    def test_board_corruption(self):
        self.mutate(self.game().relative_to(self.root),lambda r:r['final_board'].__setitem__(12,1));self.fails('actual capture geometry')
    def test_seed_low_bit_corruption(self):
        self.mutate(self.game().relative_to(self.root),lambda r:r.update(game_seed=r['game_seed']+1));self.fails('exact integer')
    def test_wrong_source_stamp(self):
        self.mutate(self.game().relative_to(self.root),lambda r:r.update(source_fingerprint='0'*64));self.fails('source_fingerprint')
    def test_root_visit_corruption(self):
        self.mutate(self.game().relative_to(self.root),lambda r:r['moves'][0]['action_visit_counts'].update({str(r['moves'][0]['action']):255}));self.fails('visit sum')
    def test_root_q_relation_corruption(self):
        self.mutate(self.game().relative_to(self.root),lambda r:r['moves'][0]['action_q_black'].update({str(r['moves'][0]['action']):.5}));self.fails('utility-vector Q relation')
    def test_superko_count_corruption(self):
        self.mutate(self.game().relative_to(self.root),lambda r:r['moves'][0].update(superko_excluded=1));self.fails('independently enumerated superko exclusions')
    def test_action_after_doublepass(self):
        i=next(i for i,r in enumerate(self.rows) if r['pass_min_ply']==0)
        def change(r):
            m=copy.deepcopy(r['moves'][-1]);m.update(index=3,color='black')
            r['moves'].append(m);r['move_count']=3
        self.mutate(self.game(i).relative_to(self.root),change);self.fails('double pass before end')
    def test_unvisited_q_not_null(self):
        def change(r):
            m=r['moves'][0];k=next(k for k,n in m['action_visit_counts'].items() if n==0)
            m['action_q_black'][k]=0
        self.mutate(self.game().relative_to(self.root),change);self.fails('unvisited Q null')
    def test_review_hash_corruption(self):
        (self.root/audit.EXPERIMENT_PATH/'pre_execution_preservation.json').write_text('{}')
        self.fails('frozen review evidence')
    def test_verifier_hash_corruption(self):
        (self.root/audit.EXPERIMENT_PATH/'independent_review/recovery_verify_inference_v1.py').write_text('# altered')
        self.fails('arithmetic verifier hash changed')
    def test_jsonl_missing(self):(self.out/'games.jsonl').unlink();self.fails('FileNotFoundError')
    def test_jsonl_reordered(self):
        p=self.out/'games.jsonl';lines=p.read_text().splitlines();lines[0],lines[1]=lines[1],lines[0];p.write_text('\n'.join(lines)+'\n');self.fails('ordered JSONL')
    def test_jsonl_torn(self):
        with (self.out/'games.jsonl').open('a') as f:f.write('{')
        self.fails('JSONDecodeError')
    def test_manifest_incomplete(self):
        self.mutate('synthetic_input/manifest.json',lambda r:r.update(status='interrupted'));self.fails('manifest.status')
    def test_validation_not_completed(self):
        self.mutate('synthetic_input/validation.json',lambda r:r.update(manifest_status='running'));self.fails('completed saved validation')
    def test_rule_fault(self):put(self.out/'rule_fault.json',{});self.fails('persisted rule_fault')
    def test_unfinished_tmp(self):(self.out/'games/unfinished.tmp').write_text('x');self.fails('unfinished tmp')
    def test_source_changed(self):(self.root/'run.py').write_text('# changed');self.fails('normalized source inventory')
    def test_test_file_changed(self):(self.root/'tests/test_synthetic.py').write_text('# changed');self.fails('frozen hash')
    def test_preregistered_design_changed(self):
        self.mutate(audit.EXPERIMENT_PATH/'preregistration.json',lambda r:r.update(games_per_cell=9));self.fails('protocol.games_per_cell')
    def test_plan_changed(self):
        self.mutate(audit.EXPERIMENT_PATH/'frozen_plan.json',lambda r:r[0].update(game_seed=r[0]['game_seed']+1));self.fails('independent frozen schedule')
    def test_descriptive_corruption(self):
        self.mutate('synthetic_input/analysis.json',lambda r:r['groups']['G0']['all'].update(length2=0));self.fails('independent descriptive analysis')
    def test_inference_corruption(self):
        self.mutate('synthetic_input/analysis.json',lambda r:r['inference']['pooled']['WIN/WIN']['contrast']['raw_length'].update(estimate=999))
        report,_=audit.audit(self.root,self.out);self.assertFalse(report['passed']);self.assertTrue(report['statistical_audit']['arithmetic_executed'])
    def test_no_arithmetic_on_partial(self):
        self.game(479).unlink()
        with mock.patch.object(audit,'inference_verifier',side_effect=AssertionError('must not import')):
            self.fails('raw filenames/count')
    def test_cli_requires_readiness(self):
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            audit.main(['--root',str(self.root),'--out',str(self.out),'--report',str(self.root/audit.EXPERIMENT_PATH/'final_audit/test.json')])
    def test_write_guards(self):
        allowed=self.root/audit.EXPERIMENT_PATH/'final_audit'
        for target in (self.out/'new.json',self.root/'reports/new.json',self.root/'run.py'):
            with self.subTest(target=target),self.assertRaises(ValueError):audit.check_output_targets(self.root,self.out,[target])
        allowed.mkdir(exist_ok=True);existing=allowed/'existing.json';existing.write_text('keep')
        with self.assertRaises(ValueError):audit.check_output_targets(self.root,self.out,[existing])
        with self.assertRaises(ValueError):audit.check_output_targets(self.root,self.out,[allowed/'same',allowed/'same'])
        (allowed/'link').symlink_to(self.out,target_is_directory=True)
        with self.assertRaises(ValueError):audit.check_output_targets(self.root,self.out,[allowed/'link/new.json'])
    def test_cli_new_reports_then_refuses_reuse(self):
        report=self.root/audit.EXPERIMENT_PATH/'final_audit/test_run/report.json'
        recomputed=report.with_name('recomputed.json')
        args=['--root',str(self.root),'--out',str(self.out),'--report',str(report),'--recomputed',str(recomputed),'--data-ready']
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(audit.main(args),0)
        self.assertTrue(audit.read(report)['passed']);before=report.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):audit.main(args)
        self.assertEqual(before,report.read_bytes())


if __name__=='__main__':unittest.main(verbosity=2)
