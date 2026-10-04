"""M6-only fixtures, no production engine, prior audit imports, or pilot games."""
import ast
import copy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location('komi96_audit_test_subject', Path(__file__).with_name('komi96_independent_audit.py'))
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)


def make_record(pass_min=0, komi=0.0, direction='WIN/LOSE', index=0):
    """Synthetic edge fixture. Root visit/Q maps are fabricated, not MCTS."""
    ib, iw = direction.split('/')
    cell = dict(budget=256, batch_seed=14, black_identity=ib, white_identity=iw,
                black_seed=1, white_seed=2, replicate=0, block_index=0, block_id='14:0',
                pass_min_ply=pass_min, komi=komi, ruleset=audit.RULES[(pass_min,komi)])
    entry = dict(index=index, game_seed=123456, pass_min_ply=pass_min, komi=komi)
    for color, ident, seed in (('black',ib,1),('white',iw,2)):
        entry[color] = dict(agent_id=f'{ident}-medium-s{seed}', identity=ident,
                            algorithm='vector_mcts', compute_level='medium', seed=seed)
    provenance = dict(code_version='synthetic-m6', schema_version=3,
                      source_fingerprint='synthetic-source', python_version='synthetic-runtime')
    actions = [25,25] if pass_min==0 else [0,24,1,23,2,22,3,21,25,25]
    rec = dict(game_id=f'{audit.BATCH}-g{index:06d}', batch_id=audit.BATCH,
        game_index=index, game_seed=entry['game_seed'], board_size=5, komi=komi,
        pass_min_ply=pass_min, ruleset=cell['ruleset'], black=entry['black'], white=entry['white'],
        move_count=len(actions), termination_reason='double_pass', superko_rejections=0,
        game_wall_ms=1.0, **provenance)
    for color in ('black','white'):
        for key in ('agent_id','identity','algorithm','compute_level'):
            rec[color+'_'+key] = entry[color][key]
    board=[0]*25; moves=[]
    for i,action in enumerate(actions):
        legal=[p for p,value in enumerate(board) if value==0]
        if i>=pass_min:legal.append(25)
        moves.append(dict(index=i+1, action=action, color='black' if i%2==0 else 'white',
            is_pass=action==25, legal_action_count=len(legal), superko_excluded=0,
            root_visit_count=256, simulations_used=256, search_time_ms=0.0,
            action_visit_counts={str(p):256 if p==action else 0 for p in legal},
            action_q_black={str(p):0.0 if p==action else None for p in legal},
            action_q_white={str(p):0.0 if p==action else None for p in legal}))
        if action<25: board[action]=i%2+1
    rec.update(moves=moves, final_board=board, black_score=float(board.count(1)),
               white_score=float(board.count(2))+komi, score_margin=-komi,
               winner='draw' if komi==0 else 'white')
    rec['black_utility']=0 if komi==0 else (1 if ib=='LOSE' else -1)
    rec['white_utility']=0 if komi==0 else (1 if iw=='WIN' else -1)
    return rec,cell,entry,provenance


def check_record(rec,cell,entry,prov):
    return audit.reconstruct(rec,cell,entry,123,prov)


class Komi96Rules(unittest.TestCase):
    def test_empty_zero_komi_draw(self):
        self.assertEqual(audit.area([0]*25,0.0),dict(black_score=0.0,white_score=0.0,score_margin=0.0,winner='draw'))
    def test_empty_positive_komi_white(self):
        self.assertEqual(audit.area([0]*25,2.5)['winner'],'white')
    def test_single_black_stone_owns_empty_region(self):
        b=[0]*25;b[12]=1
        self.assertEqual(audit.area(b,0)['black_score'],25)
    def test_neutral_empty_region(self):
        b=[0]*25;b[0]=1;b[24]=2
        self.assertEqual(audit.area(b,0)['score_margin'],0)
        self.assertEqual(audit.area(b,2.5)['score_margin'],-2.5)
    def test_draw_utilities_all_directions(self):
        for d in audit.DIRECTIONS:self.assertEqual(audit.utilities('draw',*d.split('/')),[0,0])
    def test_non_draw_utility_symmetries(self):
        for winner in ('black','white'):
            for d in audit.DIRECTIONS:
                ib,iw=d.split('/');ub,uw=audit.utilities(winner,ib,iw)
                self.assertEqual(ub,uw if ib!=iw else -uw)
    def test_single_capture(self):
        b=[0]*25;b[0]=2;b[1]=1
        placed,n=audit.apply_placement(b,5,1)
        self.assertEqual(n,1);self.assertEqual(placed[0],0)
    def test_multi_capture(self):
        b=[0]*25;b[0]=b[1]=2;b[5]=b[6]=1
        placed,n=audit.apply_placement(b,2,1)
        self.assertEqual(n,2);self.assertEqual(placed[:3],[0,0,1])
    def test_suicide_rejected(self):
        b=[0]*25;b[1]=b[5]=2
        with self.assertRaisesRegex(ValueError,'suicide'):audit.apply_placement(b,0,1)
    def test_superko_enumeration_and_pass_exemption(self):
        b=[0]*25;c=b.copy();c[0]=1
        history={(tuple(b),1),(tuple(c),2),(tuple(b),2)}
        legal,n=audit.legal_actions(b,1,history,8,8)
        self.assertNotIn(0,legal);self.assertIn(25,legal);self.assertEqual(n,1)
        self.assertNotIn(25,audit.legal_actions(b,1,history,7,8)[0])
    def test_history_is_situational(self):
        b=[0]*25;c=b.copy();c[0]=1
        legal,n=audit.legal_actions(b,1,{(tuple(c),1)},0,0)
        self.assertIn(0,legal);self.assertEqual(n,0)
    def test_no_legal_action_fails_closed(self):
        b=[0]*25;hist={(tuple(b),1)}
        for a in range(25):
            c=b.copy();c[a]=1;hist.add((tuple(c),2))
        with self.assertRaisesRegex(ValueError,'no-legal-action'):audit.legal_actions(b,1,hist,0,8)
    def test_all_synthetic_arm_direction_records(self):
        for p,k in audit.ARMS:
            for d in audit.DIRECTIONS:
                row,errors=check_record(*make_record(p,k,d))
                self.assertEqual(errors,[])
                self.assertEqual(row['winner'],'draw' if k==0 else 'white')
    def test_false_draw_winner_detected(self):
        args=make_record();args[0]['winner']='white'
        self.assertTrue(any('winner' in e for e in check_record(*args)[1]))
    def test_draw_success_detected(self):
        args=make_record();args[0]['black_utility']=1
        self.assertTrue(any('utility' in e for e in check_record(*args)[1]))
    def test_draw_summary_no_goals_or_board_wins(self):
        rows=[check_record(*make_record(0,0.0,d))[0] for d in audit.DIRECTIONS]
        s=audit.summarize(rows)
        self.assertEqual(s['draws'],4)
        for k in ('black_goals','white_goals','joint_goals','black_board_wins','white_board_wins'):self.assertEqual(s[k],0)
    def test_legal_map_omission_detected(self):
        args=make_record();move=args[0]['moves'][0]
        for k in ('action_visit_counts','action_q_black','action_q_white'):move[k].pop('0')
        move['legal_action_count']-=1
        self.assertTrue(any('legal root set' in e for e in check_record(*args)[1]))
    def test_visit_total_detected(self):
        args=make_record();args[0]['moves'][0]['action_visit_counts']['25']=255
        self.assertTrue(any('visit sum' in e for e in check_record(*args)[1]))
    def test_chosen_maximum_detected(self):
        args=make_record();m=args[0]['moves'][0];m['action_visit_counts']['25']=1;m['action_visit_counts']['0']=255
        m['action_q_black']['0']=m['action_q_white']['0']=0.0
        self.assertTrue(any('maximum visits' in e for e in check_record(*args)[1]))
    def test_q_symmetry_detected(self):
        for d in audit.DIRECTIONS:
            args=make_record(direction=d);m=args[0]['moves'][0]
            m['action_q_black']['25']=.5;m['action_q_white']['25']=.25
            self.assertTrue(any('Q relation' in e for e in check_record(*args)[1]))
    def test_q_bounds_detected(self):
        args=make_record();m=args[0]['moves'][0]
        m['action_q_black']['25']=m['action_q_white']['25']=1.1
        self.assertTrue(any('Q bounds' in e for e in check_record(*args)[1]))
    def test_q_unvisited_null_detected(self):
        args=make_record();args[0]['moves'][0]['action_q_black']['0']=0.0
        self.assertTrue(any('unvisited Q null' in e for e in check_record(*args)[1]))
    def test_final_board_tamper_detected(self):
        args=make_record();args[0]['final_board'][0]=1
        self.assertTrue(any('final_board' in e for e in check_record(*args)[1]))
    def test_superko_count_tamper_detected(self):
        args=make_record();args[0]['moves'][0]['superko_excluded']=1
        self.assertTrue(any('superko' in e for e in check_record(*args)[1]))
    def test_early_pass_map_detected(self):
        args=make_record(8,0);m=args[0]['moves'][0]
        m['action_visit_counts']['25']=0;m['action_q_black']['25']=m['action_q_white']['25']=None;m['legal_action_count']+=1
        self.assertTrue(any('pass root membership' in e for e in check_record(*args)[1]))
    def test_large_integer_comparison_strict(self):
        self.assertTrue(audit.differences(2**127,2**127+1))
        self.assertTrue(audit.differences(1,True))
        self.assertTrue(audit.differences(1,1.0))
    def test_quantiles(self):
        self.assertEqual(audit.distribution([2,3,10,25])['q1'],2.75)
        self.assertEqual(audit.distribution([2,3,10,25])['median'],6.5)
    def test_json_duplicate_and_nonfinite_rejected(self):
        for raw in ('{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}','{"a":1} garbage'):
            with self.assertRaises(ValueError):audit.parse_json(raw)
    def test_bool_seed_rejected(self):
        args=make_record();args[0]['game_seed']=True
        with self.assertRaises(ValueError):check_record(*args)
    def test_no_production_or_inherited_audit_imports(self):
        tree=ast.parse(Path(audit.__file__).read_text())
        imports=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imports.extend(n.name for n in node.names)
            if isinstance(node,ast.ImportFrom):imports.append(node.module)
        for module in imports:
            self.assertNotIn('winai_loseai',module)
            self.assertNotIn('independent_final_audit',module)
            self.assertNotIn('experiments',module)



def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def build_fixture(root):
    """96 fabricated terminal records only, in a disposable temporary root."""
    exp=root/audit.EXPERIMENT_PATH;exp.mkdir(parents=True)
    actual=Path(audit.__file__).resolve().parents[1]/'preregistration.json'
    (exp/'preregistration.json').write_bytes(actual.read_bytes())
    protocol=audit.read(exp/'preregistration.json');cells,plan=audit.design(protocol)
    put(exp/'frozen_plan.json',plan)
    for relative in ('run.py','src/winai_loseai/__init__.py','scripts/run_komi_pass_pilot.py',
                     'scripts/measure_komi_pass_pilot_chunk.py','tests/test_synthetic_only.py'):
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# synthetic fixture only\n')
    import hashlib
    sources={relative:audit.digest(root/relative) for relative in ('run.py','src/winai_loseai/__init__.py')}
    fingerprint=hashlib.sha256(json.dumps(sources,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    provenance=dict(code_version=protocol['code_version'],schema_version=2,source_fingerprint=fingerprint,python_version='synthetic-runtime')
    source=dict(**provenance,algorithm='sha256-utf8-lf-path-map-v1',files=sources)
    put(exp/'pre_execution_source_lock.json',source)
    runlock=dict(experiment_id=audit.EXPERIMENT,**provenance,
        preregistration_sha256=audit.digest(exp/'preregistration.json'),
        entry_point_sha256=audit.digest(root/'scripts/run_komi_pass_pilot.py'),
        measurement_script_sha256=audit.digest(root/'scripts/measure_komi_pass_pilot_chunk.py'),
        scipy_version='synthetic-unused',numpy_version='synthetic-unused')
    put(exp/'pre_execution_lock.json',dict(**runlock,
        frozen_plan_sha256=audit.digest(exp/'frozen_plan.json'),
        source_lock_sha256=audit.digest(exp/'pre_execution_source_lock.json'),
        test_file_sha256={'tests/test_synthetic_only.py':audit.digest(root/'tests/test_synthetic_only.py')},
        registered_before_first_pilot_game=True,pilot_games_before_freeze=0))
    out=root/'synthetic_input';out.mkdir()
    put(out/'plan.json',plan);put(out/'game_seeds.json',[dict(index=e['index'],game_seed=e['game_seed']) for e in plan])
    put(out/'source_lock.json',source);put(out/'experiment_lock.json',runlock)
    (out/'preregistration.json').write_bytes((exp/'preregistration.json').read_bytes())
    agents={e[c]['agent_id']:e[c] for e in plan for c in ('black','white')}
    put(out/'manifest.json',dict(batch_id=audit.BATCH,kind=audit.EXPERIMENT,status='completed',requested_games=96,
        planned_game_count=96,completed_game_count=96,completed_indexes=list(range(96)),board_size=5,
        komi=None,komis=[2.5,0.0],batch_seed=[14,15,16],concurrency=1,pass_min_plies=[0,8],budget=256,
        schedule_seed=2026100403,agents=list(agents.values()),**provenance))
    metadata=[];rows=[]
    for cell,entry in zip(cells,plan):
        rec=make_record(cell['pass_min_ply'],cell['komi'],cell['black_identity']+'/'+cell['white_identity'],entry['index'])[0]
        rec.update(provenance);rec['game_seed']=entry['game_seed']
        for color in ('black','white'):
            rec[color]=entry[color]
            for key in ('agent_id','identity','algorithm','compute_level'):rec[color+'_'+key]=entry[color][key]
        path=out/'games'/(rec['game_id']+'.json');put(path,rec)
        row,errors=audit.reconstruct(rec,cell,entry,path.stat().st_size,provenance)
        if errors:raise AssertionError(errors)
        rows.append(row)
        metadata.append({k:v for k,v in rec.items() if k not in ('black','white','moves')} |
            dict(opening_actions=[m['action'] for m in rec['moves'][:12]],game_file='games/'+path.name))
    (out/'games.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in metadata))
    put(out/'analysis.json',audit.assemble(rows))
    put(out/'validation.json',dict(experiment_id=audit.EXPERIMENT,planned=96,game_count=96,replay_and_search_ok=96,
        complete=True,problems=[],manifest_status='completed',rule_fault_present=False,source_fingerprint=fingerprint,
        raw_game_sha256={p.name:audit.digest(p) for p in sorted((out/'games').glob('*.json'))}))
    return out,rows


class Komi96Integration(unittest.TestCase):
    def test_full_synthetic96_roundtrip_and_readonly(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,rows=build_fixture(root)
            before={p.relative_to(root):audit.digest(p) for p in root.rglob('*') if p.is_file()}
            report,result=audit.audit(root,out)
            self.assertTrue(report['passed'],report['problems'])
            self.assertEqual(report['n_records'],96);self.assertEqual(report['n_four_arm_blocks'],24)
            self.assertEqual(report['n_draws'],48);self.assertEqual(report['n_actual_actions'],576)
            self.assertEqual({p.relative_to(root):audit.digest(p) for p in root.rglob('*') if p.is_file()},before)
    def test_factorial_contrasts_known_synthetic(self):
        with tempfile.TemporaryDirectory() as d:
            out,rows=build_fixture(Path(d));result=audit.assemble(rows)
            for pair in result['paired_differences']:
                c=pair['contrasts']
                for key in ('pass_at_k0','pass_at_k2p5'):
                    self.assertEqual(c[key]['length'],8);self.assertEqual(c[key]['extra_length'],0)
                for key in ('komi_at_p0','komi_at_p8'):
                    self.assertEqual(c[key]['length'],0);self.assertEqual(c[key]['draw'],1)
                self.assertTrue(all(v==0 for v in c['interaction'].values()))
            self.assertEqual(result['groups']['G1-k0']['all']['pass_proposal_acceptance']['black_proposer_neutral'],dict(opportunities=24,accepted=24))
    def test_draws_keep_mixed_denominator_and_count_once(self):
        with tempfile.TemporaryDirectory() as d:
            out,rows=build_fixture(Path(d));result=audit.assemble(rows)
            for direction in ('WIN/LOSE','LOSE/WIN'):
                group=result['groups']['G1-k0']['directions'][direction]
                self.assertEqual(group['n'],6);self.assertEqual(group['draws'],6);self.assertEqual(group['joint_goals'],0)
            group=result['groups']['G0']['directions']['LOSE/WIN']
            self.assertEqual(group['joint_goals'],6)
    def test_pair_missing_or_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            out,rows=build_fixture(Path(d))
            with self.assertRaisesRegex(ValueError,'incomplete or duplicate'):audit.assemble(rows[1:])
            with self.assertRaisesRegex(ValueError,'incomplete or duplicate'):audit.assemble(rows+[rows[0]])
    def test_pair_agent_or_seed_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            out,rows=build_fixture(Path(d));rows[0]['game_seed']+=1
            with self.assertRaisesRegex(ValueError,'agent/seed mismatch'):audit.assemble(rows)
    def test_saved_analysis_contrast_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,_=build_fixture(root);doc=audit.read(out/'analysis.json')
            doc['paired_differences'][0]['contrasts']['interaction']['draw']=1
            put(out/'analysis.json',doc);report,_=audit.audit(root,out)
            self.assertFalse(report['passed']);self.assertTrue(any('interaction.draw' in e for e in report['problems']))
    def test_saved_analysis_draw_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,_=build_fixture(root);doc=audit.read(out/'analysis.json')
            doc['groups']['G1-k0']['all']['draws']=0;put(out/'analysis.json',doc)
            self.assertFalse(audit.audit(root,out)[0]['passed'])
    def test_saved_plan_komi_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,_=build_fixture(root);doc=audit.read(out/'plan.json');doc[0]['komi']=1.0
            put(out/'plan.json',doc);report,result=audit.audit(root,out)
            self.assertFalse(report['passed']);self.assertIsNone(result)
    def test_metadata_line_order_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,_=build_fixture(root);path=out/'games.jsonl';lines=path.read_text().splitlines()
            lines[0],lines[1]=lines[1],lines[0];path.write_text('\n'.join(lines)+'\n')
            self.assertFalse(audit.audit(root,out)[0]['passed'])
    def test_source_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,_=build_fixture(root);(root/'run.py').write_text('# changed\n')
            self.assertFalse(audit.audit(root,out)[0]['passed'])
    def test_raw_draw_utility_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,_=build_fixture(root)
            for path in sorted((out/'games').glob('*.json')):
                rec=audit.read(path)
                if rec['komi']==0:rec['white_utility']=1;put(path,rec);break
            self.assertFalse(audit.audit(root,out)[0]['passed'])
    def test_unfinished_tmp_and_rule_fault_rejected(self):
        for artifact in ('games/incomplete.json.tmp','rule_fault.json'):
            with self.subTest(artifact=artifact),tempfile.TemporaryDirectory() as d:
                root=Path(d);out,_=build_fixture(root);(out/artifact).write_text('{}')
                self.assertFalse(audit.audit(root,out)[0]['passed'])
    def test_partial_dataset_never_produces_descriptives(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out,_=build_fixture(root);next((out/'games').glob('*.json')).unlink()
            report,result=audit.audit(root,out)
            self.assertFalse(report['passed']);self.assertFalse(report['complete']);self.assertIsNone(result)
    def test_output_paths_cannot_overwrite_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/'synthetic_input';allowed=root/audit.EXPERIMENT_PATH/'independent_audit'
            with self.assertRaises(ValueError):audit.check_output_targets(root,out,[out/'report.json'])
            allowed.mkdir(parents=True);existing=allowed/'existing.json';existing.write_text('{}')
            with self.assertRaises(ValueError):audit.check_output_targets(root,out,[existing])
            self.assertEqual(audit.check_output_targets(root,out,[allowed/'new.json']),[allowed/'new.json'])
    def test_output_paths_reject_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);allowed=root/audit.EXPERIMENT_PATH/'independent_audit';allowed.mkdir(parents=True)
            (allowed/'link').symlink_to(root,target_is_directory=True)
            with self.assertRaises(ValueError):audit.check_output_targets(root,root/'input',[allowed/'link'/'out.json'])


if __name__=='__main__':unittest.main()
