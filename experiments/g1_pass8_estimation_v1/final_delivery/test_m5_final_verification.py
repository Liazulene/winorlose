#!/usr/bin/env python3
"""Synthetic-only tests. Never imports the production package or plays a game."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import ModuleType
from contextlib import ExitStack
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('m5_final_validation_tested', HERE / 'run_final_validation.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def complete():
    manifest = dict(batch_id=h.BATCH, status='completed', planned_game_count=480,
                    completed_game_count=480, completed_indexes=list(range(480)), source_fingerprint=h.SOURCE)
    validation = dict(experiment_id=h.EXPERIMENT, planned=480, game_count=480, replay_and_search_ok=480,
                      manifest_status='completed', complete=True, problems=[], rule_fault_present=False,
                      source_fingerprint=h.SOURCE)
    return manifest, validation


def design():
    plan, cells = [], []
    for replicate in range(80):
        for rule in (0, 8):
            for seed in (11, 12, 13):
                plan.append(dict(index=len(plan), pass_min_ply=rule, game_seed=10000+len(plan),
                                 black={'seed': 1}, white={'seed': 2}))
                cells.append(dict(pass_min_ply=rule, batch_seed=seed))
    return plan, cells


def timing():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    checkpoints = []
    for i in range(21):
        checkpoints.append(dict(checkpoint_games=i*24, remote_fetch_and_tree_verified=True,
                                commit=f'{i+1:040x}', tree=f'{i+100:040x}',
                                verified_utc=(base+timedelta(seconds=i*20)).isoformat()))
    chunks = []
    for i in range(1, 21):
        start = base+timedelta(seconds=(i-1)*20+1)
        chunks.append(dict(chunk=i, completed_before=(i-1)*24, manifest_declared_before=(i-1)*24,
                           completed_after=i*24, exit_code=0 if i == 20 else 75,
                           status_after='completed' if i == 20 else 'interrupted',
                           measurement_script_sha256='a'*64, started_utc=start.isoformat(),
                           ended_utc=(start+timedelta(seconds=10)).isoformat(), wall_seconds=10.0,
                           cpu_user_seconds=9.0, cpu_system_seconds=0.1,
                           peak_process_rss_kib=1000+i, output_tree_bytes_after=100*i))
    return chunks, checkpoints


class GuardTests(unittest.TestCase):
    def test_import_does_not_load_production(self):
        # Recursive main-suite collection may already have imported the engine.
        # Test this harness's import side effects in its own fresh interpreter.
        script = f"""import importlib.util, sys
sys.dont_write_bytecode = True
before = {{name for name in sys.modules if name.startswith('winai_loseai')}}
spec = importlib.util.spec_from_file_location('m5_fresh_import_guard', {str(HERE / 'run_final_validation.py')!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
after = {{name for name in sys.modules if name.startswith('winai_loseai')}}
assert not before, 'fresh interpreter unexpectedly preloaded production'
assert after == before, 'harness import loaded production modules'
"""
        result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_only_loader_ignores_stale_valid_bytecode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); package = root/'src/winai_loseai'; package.mkdir(parents=True)
            source = package/'__init__.py'; source.write_text('ANSWER=1\n')
            script = f"""import importlib.util, os, py_compile, sys
from pathlib import Path
sys.dont_write_bytecode=True
source=Path({str(source)!r});stamp=source.stat().st_mtime
py_compile.compile(str(source),doraise=True)
source.write_text('ANSWER=2\\n');os.utime(source,(stamp,stamp))
spec=importlib.util.spec_from_file_location('h',{str(HERE/'run_final_validation.py')!r})
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
h.source_only_imports(Path({str(root)!r}));sys.path.insert(0,{str(root/'src')!r})
import winai_loseai
assert winai_loseai.ANSWER==2
try:
    h.source_only_imports(Path({str(root)!r}))
except ValueError:
    pass
else:
    raise AssertionError('preloaded production accepted')
"""
            result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_raw_complete_guard_checks_physical_sample_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp); games = out/'games'; games.mkdir()
            validation = {'raw_game_sha256': {}}
            metadata = []
            for i in range(480):
                name = f'{h.BATCH}-g{i:06d}.json'
                path = games/name; path.write_text('{"synthetic_index":'+str(i)+'}')
                validation['raw_game_sha256'][name] = h.sha(path)
                metadata.append({'game_index':i, 'game_id':name[:-5]})
            (out/'games.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in metadata))
            h.raw_complete_guard(out, validation)
            original = (games/name).read_bytes(); (games/name).write_text('{"altered":true}')
            with self.assertRaises(ValueError): h.raw_complete_guard(out, validation)
            (games/name).write_bytes(original); (games/'extra.tmp').write_text('extra')
            with self.assertRaises(ValueError): h.raw_complete_guard(out, validation)
            (games/'extra.tmp').unlink(); (games/name).unlink()
            with self.assertRaises(ValueError): h.raw_complete_guard(out, validation)

    def test_complete_accepted(self):
        h.complete_guard(*complete(), True)

    def test_owner_declaration_required(self):
        for flag in (False, None, 1, 'yes'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                h.complete_guard(*complete(), flag)

    def test_incomplete_states_rejected(self):
        for status in ('running', 'interrupted', 'failed', 'validation_failed', None):
            m, v = complete(); m['status'] = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                h.complete_guard(m, v, True)

    def test_count_type_and_bounds(self):
        for field in ('planned_game_count', 'completed_game_count'):
            for value in (0, 223, 479, 481, 480.0, True, '480'):
                m, v = complete(); m[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    h.complete_guard(m, v, True)

    def test_validation_counts(self):
        for field in ('planned', 'game_count', 'replay_and_search_ok'):
            m, v = complete(); v[field] = 479
            with self.subTest(field=field), self.assertRaises(ValueError):
                h.complete_guard(m, v, True)

    def test_manifest_index_corruption(self):
        for value in ([0]*480, list(range(479)), list(reversed(range(480))), [False]+list(range(1,480))):
            m, v = complete(); m['completed_indexes'] = value
            with self.assertRaises(ValueError): h.complete_guard(m, v, True)

    def test_saved_validation_faults(self):
        for field, value in [('complete', 1), ('manifest_status', 'running'), ('rule_fault_present', True),
                             ('problems', ['fault']), ('source_fingerprint', 'x'), ('experiment_id', 'M4')]:
            m, v = complete(); v[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): h.complete_guard(m, v, True)

    def test_main_rejects_before_read_without_declaration(self):
        with patch.object(h, 'read', side_effect=AssertionError('input read too early')):
            with self.assertRaises(ValueError):
                h.main(['--root', '/no/repo', '--destination', '/no/dest'])

    def test_partial_main_never_invokes_frozen_import_or_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/h.O).mkdir(parents=True); (root/h.E/'final_delivery').mkdir(parents=True)
            m, v = complete(); m['status'] = 'running'; m['completed_game_count'] = 223
            for name, value in [('manifest.json', m), ('validation.json', v)]:
                (root/h.O/name).write_text(json.dumps(value))
            target = root/h.E/'final_delivery'/'run480_v1'
            before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(h, 'frozen_guard', side_effect=AssertionError('production path reached')):
                with self.assertRaises(ValueError):
                    h.main(['--root', str(root), '--destination', str(target), '--data-ready'])
            self.assertFalse(target.exists())
            self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()})


class SelectionTests(unittest.TestCase):
    def test_six_exact_minima(self):
        self.assertEqual([r['game_index'] for r in h.select_six(*design())], list(range(6)))

    def test_selection_does_not_assume_list_sorted_by_index(self):
        plan, cells = design()
        chosen = h.select_six(list(reversed(plan)), list(reversed(cells)))
        self.assertEqual([r['game_index'] for r in chosen], list(range(6)))

    def test_incomplete_rejected(self):
        p, c = design()
        with self.assertRaises(ValueError): h.select_six(p[:-1], c[:-1])

    def test_duplicate_indexes_rejected(self):
        p, c = design(); p[-1]['index'] = 0
        with self.assertRaises(ValueError): h.select_six(p, c)

    def test_missing_stratum_rejected(self):
        p, c = design()
        for row in c:
            if row['batch_seed'] == 13: row['batch_seed'] = 12
        with self.assertRaises(ValueError): h.select_six(p, c)

    def test_rule_mismatch_rejected(self):
        p, c = design(); c[0]['pass_min_ply'] = 8
        with self.assertRaises(ValueError): h.select_six(p, c)

    def test_boolean_rule_rejected(self):
        p, c = design(); p[0]['pass_min_ply'] = False
        with self.assertRaises(ValueError): h.select_six(p, c)

    def test_selection_preserves_input(self):
        p, c = design(); before = copy.deepcopy((p, c))
        h.select_six(p, c)
        self.assertEqual((p, c), before)


class ComparisonTests(unittest.TestCase):
    def record(self):
        return {'source_fingerprint': h.SOURCE, 'game_seed': 2**120, 'game_wall_ms': 30,
                'moves': [{'search_time_ms': 10, 'action': 2, 'action_visit_counts': {2: 256}}],
                'nested': {'game_wall_ms': 7, 'search_time_ms': 8}, 'enabled': True}

    def test_only_two_timing_paths_excluded(self):
        a = self.record(); b = copy.deepcopy(a); b['game_wall_ms'] = 999; b['moves'][0]['search_time_ms'] = 200
        self.assertFalse(h.differences(h.normalized(a), h.normalized(b)))
        b['nested']['game_wall_ms'] = 9
        self.assertTrue(h.differences(h.normalized(a), h.normalized(b)))

    def test_source_and_seed_retained(self):
        for field, value in [('source_fingerprint', 'old'), ('game_seed', 2**120+1)]:
            a = self.record(); b = copy.deepcopy(a); b[field] = value
            self.assertTrue(h.differences(h.normalized(a), h.normalized(b)))

    def test_missing_timing_rejected(self):
        a = self.record(); del a['moves'][0]['search_time_ms']
        with self.assertRaises(KeyError): h.normalized(a)

    def test_strict_type_equality(self):
        for a, b in [(1, True), (1, 1.0), ([1], [True]), ({'a': 2}, {'a': 2.0})]:
            self.assertTrue(h.differences(a, b))

    def test_does_not_modify_records(self):
        a = self.record(); saved = copy.deepcopy(a); h.normalized(a)
        self.assertEqual(a, saved)

    def test_json_int_action_key_representation_only(self):
        self.assertEqual(h.normalized(self.record())['moves'][0]['action_visit_counts'], {'2': 256})

    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError): h.parse('{"a":1,"a":2}')

    def test_nonfinite_json_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e999'):
            with self.assertRaises(ValueError): h.parse('{"a":'+value+'}')


class CostTests(unittest.TestCase):
    def test_timing_scopes_and_peak_not_sum(self):
        result = h.cost_summary(*timing(), 'a'*64)
        self.assertEqual(result['child_wall_seconds'], 200)
        self.assertAlmostEqual(result['child_cpu_total_seconds'], 182)
        self.assertEqual(result['maximum_child_peak_process_rss_kib'], 1020)
        self.assertEqual(result['calendar_first_child_start_to_final_checkpoint_verified_seconds'], 399)
        self.assertEqual(result['calendar_outside_measured_children_through_final_checkpoint_seconds'], 199)

    def test_partial_and_extra_counts(self):
        a, b = timing()
        for aa, bb in [(a[:-1], b), (a+[a[-1]], b), (a, b[:-1])]:
            with self.assertRaises(ValueError): h.cost_summary(aa, bb, 'a'*64)

    def test_fault_or_gap_rejected(self):
        for field, value in [('completed_before', 47), ('completed_after', 49), ('exit_code', 1),
                             ('measurement_script_sha256', 'bad'), ('wall_seconds', float('nan')),
                             ('peak_process_rss_kib', -1), ('status_after', 'completed')]:
            a, b = timing(); a[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): h.cost_summary(a, b, 'a'*64)

    def test_checkpoint_sequence_and_verification(self):
        for field, value in [('checkpoint_games', 25), ('remote_fetch_and_tree_verified', False),
                             ('commit', 'bad'), ('verified_utc', '2026-01-01T00:00:00')]:
            a, b = timing(); b[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): h.cost_summary(a, b, 'a'*64)

    def test_compute_before_sync_rejected(self):
        a, b = timing(); b[1]['verified_utc'] = b[2]['verified_utc']
        with self.assertRaises(ValueError): h.cost_summary(a, b, 'a'*64)

    def test_final_child_must_complete(self):
        a, b = timing(); a[-1]['exit_code'] = 75
        with self.assertRaises(ValueError): h.cost_summary(a, b, 'a'*64)


class SyntheticFlowTests(unittest.TestCase):
    def run_flow(self, fail_stage=None):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp); out = root/h.O; games = out/'games'; games.mkdir(parents=True)
            (root/h.E/'final_delivery').mkdir(parents=True); (root/'run.py').write_text('synthetic')
            plan, cells = design(); m, v = complete(); v['raw_game_sha256'] = {}
            metadata, originals = [], {}
            for job in plan:
                i = job['index']; gid = f'{h.BATCH}-g{i:06d}'
                record = {'game_id':gid, 'game_index':i, 'game_wall_ms':1, 'moves':[{'search_time_ms':2,'action':i%25}]}
                originals[i] = record; path = games/(gid+'.json'); path.write_text(json.dumps(record))
                v['raw_game_sha256'][path.name] = h.sha(path)
                metadata.append({'game_id':gid, 'game_index':i})
            source = {'source_fingerprint':h.SOURCE}
            for name, record in [('manifest.json',m), ('validation.json',v), ('source_lock.json',source)]:
                (out/name).write_text(json.dumps(record))
            (out/'games.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in metadata))
            before = {p.relative_to(out).as_posix():p.read_bytes() for p in out.rglob('*') if p.is_file()}
            modules = {name:ModuleType(name) for name in ['winai_loseai', 'winai_loseai.experiments',
                       'winai_loseai.experiments.g1_pass8_estimation', 'winai_loseai.league',
                       'winai_loseai.league.runner', 'winai_loseai.provenance', 'winai_loseai.spec']}
            experiment = modules['winai_loseai.experiments.g1_pass8_estimation']
            experiment.__file__ = str(root/'src/winai_loseai/experiments/g1_pass8_estimation.py')
            experiment.record_problems = lambda record, job: []
            strict = copy.deepcopy(v)
            if fail_stage == 'strict': strict['game_count'] = 479
            experiment.validate = lambda *args, **kwargs: strict
            modules['winai_loseai.experiments'].g1_pass8_estimation = experiment
            modules['winai_loseai.provenance'].source_lock = lambda:source
            class FakeSpec:
                @staticmethod
                def from_dict(value): return value
            modules['winai_loseai.spec'].AgentSpec = FakeSpec
            calls = []
            def fake_play(job, board_size, komi):
                calls.append(job['index']); self.assertEqual((board_size,komi),(5,2.5))
                if fail_stage == 'play': raise RuntimeError('synthetic failure')
                result = copy.deepcopy(originals[job['index']]); result['game_wall_ms']=9
                result['moves'][0]['search_time_ms']=10
                return result
            modules['winai_loseai.league.runner'].play_one = fake_play
            stack.enter_context(patch.dict(sys.modules, modules))
            stack.enter_context(patch.object(h, 'source_only_imports'))
            stack.enter_context(patch.object(h, 'frozen_guard', return_value=({}, {}, source, plan, cells)))
            stack.enter_context(patch.object(h, 'checkpoint_cost_guard', return_value={'synthetic':True}))
            historical = {'all_passed':True,'checks':[{'path_hash_size_digest':'synthetic'}]*6}
            history = stack.enter_context(patch.object(h, 'historical_check', return_value=historical))
            stack.enter_context(patch.object(sys, 'addaudithook'))
            # The real audit hook is separately tested in an isolated child.
            dest = root/h.E/'final_delivery'/'synthetic_run'
            with patch('builtins.print'):
                result = h.main(['--root',str(root),'--destination',str(dest),'--data-ready'])
            summary = h.read(dest/'final_validation_summary.json')
            self.assertEqual(before, {p.relative_to(out).as_posix():p.read_bytes() for p in out.rglob('*') if p.is_file()})
            self.assertEqual(history.call_count,2)
            self.assertTrue(h.read(dest/'validation_inputs_unchanged.json')['unchanged'])
            self.assertEqual(summary['sample_increment'],0)
            return result, summary, calls

    def test_synthetic_end_to_end_exactly_six_serial_calls(self):
        result, summary, calls = self.run_flow()
        self.assertEqual(result,0); self.assertTrue(summary['passed'])
        self.assertEqual(calls,list(range(6))); self.assertEqual(summary['matching_regenerations'],6)

    def test_strict_guard_failure_stops_all_reproduction(self):
        result, summary, calls = self.run_flow('strict')
        self.assertEqual(result,1); self.assertFalse(summary['passed'])
        self.assertFalse(summary['strict_complete_validation_passed']); self.assertEqual(calls,[])

    def test_failure_does_not_retry_replace_or_add_samples(self):
        result, summary, calls = self.run_flow('play')
        self.assertEqual(result,1); self.assertFalse(summary['passed']); self.assertEqual(calls,[0])


class PathAndPreservationTests(unittest.TestCase):
    def test_new_destination_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); parent = root/h.E/'final_delivery'; parent.mkdir(parents=True)
            target = parent/'run480_v1'
            self.assertEqual(h.destination(root, target), target)
            target.mkdir()
            with self.assertRaises(ValueError): h.destination(root, target)
            for wrong in (root/h.O/'evil', root/'reports'/'evil', parent, parent/'a'/'b', parent/'..'/'escape'):
                with self.assertRaises(ValueError): h.destination(root, wrong)

    def test_symlink_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); parent = root/h.E/'final_delivery'; parent.mkdir(parents=True)
            (parent/'link').symlink_to(root)
            with self.assertRaises(ValueError): h.destination(root, parent/'link'/'evil')

    def test_snapshot_detects_all_three_change_classes(self):
        before = {'a': {'sha256': 'a', 'bytes': 1}, 'b': {'sha256': 'b', 'bytes': 1}}
        after = {'a': {'sha256': 'x', 'bytes': 1}, 'c': {'sha256': 'c', 'bytes': 1}}
        result = h.compare_snapshots(before, after)
        self.assertFalse(result['unchanged']); self.assertEqual(result['changed'], ['a'])
        self.assertEqual(result['missing'], ['b']); self.assertEqual(result['added'], ['c'])

    def test_snapshot_excludes_independent_delivery_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'run.py').write_text('source')
            (root/h.O).mkdir(parents=True); (root/h.O/'data.json').write_text('{}')
            (root/h.E/'final_audit').mkdir(parents=True); (root/h.E/'final_audit'/'report.json').write_text('{}')
            before = h.input_snapshot(root)
            (root/h.E/'final_audit'/'report.json').write_text('{"updated":true}')
            self.assertEqual(before, h.input_snapshot(root))
            (root/h.O/'extra.json').write_text('{}')
            self.assertFalse(h.compare_snapshots(before, h.input_snapshot(root))['unchanged'])

    def test_write_fence_allows_only_exclusive_new_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dest = root/'evidence'; dest.mkdir(); fence = h.WriteFence(dest)
            fence('open', (str(dest/'new.json'), 'x', os.O_CREAT|os.O_EXCL|os.O_WRONLY))
            for path, mode, flags in [(root/'input', 'x', os.O_CREAT|os.O_EXCL|os.O_WRONLY),
                                      (dest/'old.json', 'w', os.O_CREAT|os.O_TRUNC|os.O_WRONLY)]:
                with self.assertRaises(ValueError): fence('open', (str(path), mode, flags))
            with self.assertRaises(PermissionError): fence('os.rename', (str(dest/'a'), str(root/'b')))
            with self.assertRaises(ValueError): fence('subprocess.Popen', ('python', ['python', 'run.py'], None, None))
            fence('subprocess.Popen', ('git', ['git', 'rev-parse', 'HEAD'], None, None))

    def test_live_audit_fence_in_isolated_synthetic_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dest = root/'new'; dest.mkdir()
            script = f'''import sys, importlib.util
from pathlib import Path
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('h',{str(HERE/'run_final_validation.py')!r})
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
dest=Path({str(dest)!r});sys.addaudithook(h.WriteFence(dest))
h.write(dest,'ok.json',{{'synthetic':True}})
try:
    Path({str(root/'protected.txt')!r}).write_text('forbidden')
except ValueError:
    pass
else:
    raise AssertionError('fence failed')
'''
            result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((dest/'ok.json').exists()); self.assertFalse((root/'protected.txt').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
