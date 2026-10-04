#!/usr/bin/env python3
"""M5 final verification: read-only inputs, six serial reproductions, fresh evidence.

No production import or game generation occurs before the explicit --data-ready
flag, complete-480 guards, frozen-source checks, and cost/checkpoint gates pass.
Never call a production run/resume/repair/CLI entry point from this harness.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import importlib.machinery
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
E = Path('experiments/g1_pass8_estimation_v1')
O = Path('outputs/g1_pass8_estimation_v1')
BATCH = 'g1_pass8_estimation_v1'
EXPERIMENT = 'G1-pass8-estimation-v1'
SOURCE = '1633b6768cc2c93af1a504a4741167ad2fa2cf809826cd7e267ccaa369e31dae'
PROTOCOL = 'cfe65b3f20b6e2cefdf620a27e501333c5798ea0801ee1b8881be2c010ff76fa'
NAMES = ('winorlose', 'winorlose_d0_v1', 'winorlose_d1_v1',
         'winorlose_d1_estimation_v1', 'winorlose_g1_pass8_v1')
PINS = {
    'pre_execution_lock.json': '8ddf718e1b4cb70bfdfeb2b471184cd4c4f53dd1bda576caac6a2d220cc001c0',
    'pre_execution_source_lock.json': 'fccdffebac82ef100cb3232e93da26301de2dfda10eb2a4a7497b7b77a3f77cc',
    'pre_execution_preservation.json': 'c533804f2ae801aaf72b6a565577f67088d3da55b62111baf285e32ade177aef',
    'independent_review/inventory_io.py': '44fe2c049538ca7fdd60620471fe3756e498a12d2d6ebcfc1dc07b2d1562bcf4',
    'independent_review/audit_resume20261004_preservation.py': '4c891dffd6c054a5cd5596675e760c1189b36cd5f74518057689ee1674e6b2b7',
    'independent_review/verify_fixed_design.py': '1c00c0be89daf83694b27d7e04adf2c8accb6bf000a1fee29a64009d7fde7e30',
    'independent_review/resume20261004_freeze_verification.json': '298cf4a6783684278c7a66e25a2e84a54ba165832c46473bb68310751f1aff21',
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def stable_sha(value):
    return sha_bytes(json.dumps(value, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False, allow_nan=False).encode())


def parse(text):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'duplicate JSON key: ' + key)
            out[key] = value
        return out
    def invalid(value):
        raise ValueError('nonfinite JSON constant: ' + value)
    def finite_float(value):
        number = float(value)
        require(math.isfinite(number), 'nonfinite JSON number: ' + value)
        return number
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite_float)


def read(path):
    return parse(Path(path).read_text(encoding='utf-8'))


def write(dest, name, value):
    path = dest / name
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    return path


def no_symlinks(path):
    raw = Path(os.path.abspath(path))
    require(not any(p.is_symlink() for p in (raw, *raw.parents)),
            'symlinked path forbidden: ' + str(path))
    return raw


def destination(root, value):
    """Reserve a wholly new direct child of M5 final_delivery; no overwrite."""
    root = no_symlinks(root).resolve()
    raw = Path(value)
    target = no_symlinks(raw if raw.is_absolute() else root / raw)
    base = root / E / 'final_delivery'
    require(target.parent == base and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', target.name),
            'destination must be a new direct child of M5 final_delivery')
    require(not target.exists(), 'destination already exists; select a distinct new name')
    require(base.is_dir(), 'install the stable harness in final_delivery before invocation')
    return target


def complete_guard(manifest, validation, data_ready):
    require(data_ready is True, 'explicit --data-ready declaration required')
    require(manifest.get('batch_id') == BATCH, 'wrong batch')
    require(manifest.get('status') == 'completed', 'manifest is not completed')
    for key in ('planned_game_count', 'completed_game_count'):
        require(type(manifest.get(key)) is int and manifest[key] == 480, 'manifest ' + key)
    require(manifest.get('completed_indexes') == list(range(480)) and
            all(type(x) is int for x in manifest['completed_indexes']), 'manifest indexes')
    require(validation.get('experiment_id') == EXPERIMENT, 'wrong validation experiment')
    for key in ('planned', 'game_count', 'replay_and_search_ok'):
        require(type(validation.get(key)) is int and validation[key] == 480, 'validation ' + key)
    require(validation.get('manifest_status') == 'completed' and
            validation.get('complete') is True and validation.get('problems') == [] and
            validation.get('rule_fault_present') is False and
            validation.get('source_fingerprint') == SOURCE, 'saved final validation did not pass')
    require(manifest.get('source_fingerprint') == SOURCE, 'manifest source mismatch')


def raw_complete_guard(out, validation):
    """Verify actual480 canonical raw files before any production import."""
    expected = {f'{BATCH}-g{i:06d}.json' for i in range(480)}
    require(set(validation.get('raw_game_sha256', {})) == expected, 'saved raw hash inventory is not exactly480')
    files = list((out / 'games').iterdir())
    require({p.name for p in files} == expected and len(files) == 480 and
            all(p.is_file() and not p.is_symlink() for p in files), 'actual raw sample is not exactly480 canonical files')
    for path in files:
        require(sha(path) == validation['raw_game_sha256'][path.name], 'actual raw hash mismatch: ' + path.name)
    metadata = [parse(line) for line in (out / 'games.jsonl').read_text(encoding='utf-8').splitlines()]
    require(len(metadata) == 480, 'metadata sample is not exactly480')
    for index, row in enumerate(metadata):
        require(type(row.get('game_index')) is int and row['game_index'] == index and
                row.get('game_id') == f'{BATCH}-g{index:06d}', 'metadata canonical index/id mismatch')


def select_six(plan, cells):
    """Select by design only, never outcomes or source-record content."""
    require(len(plan) == len(cells) == 480, 'selection requires full frozen480 design')
    indexes = [job.get('index') for job in plan]
    require(all(type(i) is int for i in indexes) and sorted(indexes) == list(range(480)),
            'design indexes not exact 0..479')
    selected = []
    for rule in (0, 8):
        for seed in (11, 12, 13):
            candidates = []
            for job, cell in zip(plan, cells):
                require(type(job.get('pass_min_ply')) is int and job['pass_min_ply'] in (0, 8), 'bad rule')
                require(job['pass_min_ply'] == cell.get('pass_min_ply'), 'job/cell rule mismatch')
                require(type(cell.get('batch_seed')) is int and cell['batch_seed'] in (11, 12, 13), 'bad seed')
                if cell['pass_min_ply'] == rule and cell['batch_seed'] == seed:
                    candidates.append(job)
            require(len(candidates) == 80, 'rule/seed stratum must contain80 jobs')
            job = min(candidates, key=lambda j: j['index'])
            selected.append({'pass_min_ply': rule, 'batch_seed': seed,
                             'game_index': job['index'],
                             'game_id': f'{BATCH}-g{job["index"]:06d}',
                             'game_seed': job['game_seed'],
                             'black': job['black'], 'white': job['white']})
    require(len({row['game_index'] for row in selected}) == 6, 'nonunique selections')
    return selected


def normalized(record):
    # Convert only Python/JSON map representation. Drop exactly these two paths;
    # mandatory-key deletion deliberately fails if timing fields are absent.
    out = json.loads(json.dumps(record, allow_nan=False))
    del out['game_wall_ms']
    for move in out['moves']:
        del move['search_time_ms']
    return out


def differences(left, right, path='$'):
    if type(left) is not type(right):
        return [{'path': path, 'saved': left, 'regenerated': right}]
    if isinstance(left, dict):
        errors = []
        for key in sorted(left.keys() | right.keys()):
            if key not in left or key not in right:
                errors.append({'path': path + '.' + key,
                               'missing_from': 'saved' if key not in left else 'regenerated'})
            else:
                errors.extend(differences(left[key], right[key], path + '.' + key))
        return errors
    if isinstance(left, list):
        errors = [] if len(left) == len(right) else [{'path': path, 'saved_length': len(left),
                                                     'regenerated_length': len(right)}]
        for i, (a, b) in enumerate(zip(left, right)):
            errors.extend(differences(a, b, f'{path}[{i}]'))
        return errors
    return [] if left == right else [{'path': path, 'saved': left, 'regenerated': right}]


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root,
                                   env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})


class SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        # Do not consult timestamp-based or hash-based bytecode caches.
        return self.source_to_code(self.get_data(self.path), self.path)


class SourceOnlyFinder:
    def __init__(self, root):
        self.root = root.resolve()

    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'winai_loseai' and not fullname.startswith('winai_loseai.'):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        require(spec is not None and spec.origin is not None, 'missing frozen module: ' + fullname)
        origin = no_symlinks(spec.origin).resolve()
        require(origin.is_relative_to(self.root / 'src/winai_loseai') and origin.suffix == '.py',
                'production import outside frozen source: ' + fullname)
        spec.loader = SourceOnlyLoader(fullname, str(origin))
        return spec


def source_only_imports(root):
    require(not any(name == 'winai_loseai' or name.startswith('winai_loseai.') for name in sys.modules),
            'refuse preloaded production modules; start a fresh Python process')
    require('inventory_io' not in sys.modules, 'refuse preloaded inventory helper')
    sys.meta_path.insert(0, SourceOnlyFinder(root))


def load_helper(root, name):
    path = root / E / 'independent_review' / name
    require(sha(path) == PINS['independent_review/' + name], 'helper pin changed: ' + name)
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('_m5_final_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    # Compile the hash-verified source directly, never an adjacent cached .pyc.
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    if name == 'inventory_io.py':
        # The pinned preservation selector imports this exact helper by name.
        sys.modules['inventory_io'] = module
    return module


def frozen_guard(root):
    """No production imports until exact frozen normalized AND raw source passes."""
    for relative, expected in PINS.items():
        require(sha(root / E / relative) == expected, 'pinned evidence changed: ' + relative)
    protocol = read(root / E / 'preregistration.json')
    require(sha(root / E / 'preregistration.json') == PROTOCOL, 'protocol hash mismatch')
    lock = read(root / E / 'pre_execution_lock.json')
    source = read(root / E / 'pre_execution_source_lock.json')
    require(lock['source_fingerprint'] == source['source_fingerprint'] == SOURCE, 'source identity mismatch')
    files = [root / 'run.py', *sorted((root / 'src/winai_loseai').rglob('*.py'))]
    require(all(not p.is_symlink() for p in files), 'source symlink')
    normalized_files = {p.relative_to(root).as_posix(): sha_bytes(p.read_text(encoding='utf-8').encode()) for p in files}
    require(normalized_files == source['files'] and stable_sha(normalized_files) == SOURCE, 'source bytes mismatch')
    freeze = read(root / E / 'independent_review/resume20261004_freeze_verification.json')
    raw_files = {p.relative_to(root).as_posix(): sha(p) for p in files}
    require(raw_files == freeze['raw_source_files_sha256'], 'raw source differs from prelaunch freeze')
    require(platform.python_version() == lock['python_version'], 'frozen Python version required')
    from importlib.metadata import version
    for package in ('numpy', 'scipy'):
        require(version(package) == lock[package + '_version'], 'frozen package version required: ' + package)
    for name, field in (('scripts/run_g1_pass8_estimation.py', 'entry_point_sha256'),
                        ('scripts/measure_g1_pass8_estimation_chunk.py', 'measurement_script_sha256')):
        require(sha(root / name) == lock[field], 'frozen script mismatch: ' + name)
    test_files = {p.relative_to(root).as_posix(): sha(p) for p in sorted((root / 'tests').rglob('*.py'))}
    require(test_files == lock['test_files_sha256'], 'frozen tests changed')
    require(sha(root / E / 'frozen_plan.json') == lock['frozen_plan_sha256'], 'frozen plan changed')
    helper = load_helper(root, 'verify_fixed_design.py')
    cells, expected = helper.reconstruct(protocol)
    plan = read(root / E / 'frozen_plan.json')
    require(plan == expected and len(plan) == 480, 'frozen design mismatch')
    return protocol, lock, source, plan, cells


def input_snapshot(root):
    """One compact map is saved; after-state stored as digest and exact deltas."""
    files = {root / 'run.py'}
    for base in (root / O, root / 'src/winai_loseai', root / 'tests', root / 'scripts', root / E):
        for path in base.rglob('*'):
            require(not path.is_symlink(), 'input symlink: ' + str(path))
            relative = path.relative_to(root)
            if relative.is_relative_to(E / 'final_delivery') or relative.is_relative_to(E / 'final_audit'):
                continue
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                files.add(path)
    return {p.relative_to(root).as_posix(): {'sha256': sha(p), 'bytes': p.stat().st_size}
            for p in sorted(files)}


def compare_snapshots(before, after):
    changed = [p for p in sorted(before.keys() & after.keys()) if before[p] != after[p]]
    added = sorted(after.keys() - before.keys())
    missing = sorted(before.keys() - after.keys())
    return {'unchanged': not (changed or added or missing), 'checked_files_before': len(before),
            'checked_files_after': len(after), 'before_digest': stable_sha(before),
            'after_digest': stable_sha(after), 'changed': changed, 'added': added, 'missing': missing}


def historical_check(root):
    """Reuse pinned inventory loader/protected selector, emit compact evidence."""
    loader = load_helper(root, 'inventory_io.py')
    selector = load_helper(root, 'audit_resume20261004_preservation.py').protected
    review = root / E / 'independent_review'
    external = root.parent / 'winorlose_reports/M5_support/inventories'
    frozen = read(root / E / 'pre_execution_preservation.json')
    expected_raw = {Path(row['worktree']).name: row['baseline_raw_sha256'] for row in frozen['checks']}
    checks = []
    for name, inherited in [(n, False) for n in NAMES] + [(NAMES[-1], True)]:
        baseline_path = review / f'prelaunch_{name}_tracked_inventory.json.segments.json'
        raw = loader.read_raw(baseline_path)
        require(sha_bytes(raw) == expected_raw[name], 'historical inventory changed: ' + name)
        require(raw == loader.read_raw(external / f'prelaunch_{name}_tracked_inventory.json.gz'),
                'external/segmented historical inventory mismatch: ' + name)
        baseline = parse(raw.decode())
        tree = root if inherited else root.parent / name
        records = [r for r in baseline['records'] if selector(r['path'])] if inherited else baseline['records']
        errors, current = [], []
        head = git(tree, 'rev-parse', 'HEAD').decode().strip()
        if not inherited:
            if head != baseline['head']:
                errors.append('historical HEAD changed')
            tracked = set(filter(None, git(tree, 'ls-files', '-z').decode().split('\0')))
            baseline_tracked = {row['path'] for row in baseline['records']}
            if tracked != baseline_tracked:
                errors.append({'tracked_extra': sorted(tracked - baseline_tracked),
                               'tracked_missing': sorted(baseline_tracked - tracked)})
        for row in records:
            path = tree / row['path']
            if row['mode'] == '120000' and path.is_symlink():
                data = os.fsencode(os.readlink(path)); digest, size = sha_bytes(data), len(data)
            elif path.is_file() and not path.is_symlink():
                digest, size = sha(path), path.stat().st_size
            else:
                digest, size = None, None
            if digest != row['actual_sha256'] or size != row['actual_size']:
                errors.append({'path': row['path'], 'expected_sha256': row['actual_sha256'],
                               'actual_sha256': digest, 'expected_bytes': row['actual_size'], 'actual_bytes': size})
            current.append([row['path'], digest, size])
        expected_paths = {row['path'] for row in baseline['records'] if selector(row['path'])}
        actual_paths = {p.relative_to(tree).as_posix() for base in ('outputs', 'reports', 'experiments', 'handoff')
                        for p in (tree / base).rglob('*') if p.is_file() or p.is_symlink()}
        actual_paths |= {p for p in expected_paths if '/' not in p and (tree / p).is_file()}
        if inherited:
            actual_paths = {p for p in actual_paths if not p.startswith((E.as_posix() + '/', O.as_posix() + '/'))}
        extra, missing = sorted(actual_paths - expected_paths), sorted(expected_paths - actual_paths)
        if extra or missing:
            errors.append({'historical_file_set_extra': extra, 'historical_file_set_missing': missing})
        checks.append({'worktree': str(tree), 'scope': 'inherited protected historical files' if inherited else 'all baseline tracked bytes and tracked/historical file sets',
                       'baseline_inventory': baseline_path.relative_to(root).as_posix(), 'baseline_raw_sha256': sha_bytes(raw),
                       'current_head': head, 'head_comparison_required': not inherited,
                       'selected_files': len(records), 'checked_bytes': sum(r[2] or 0 for r in current),
                       'path_hash_size_digest': stable_sha(current), 'problems': errors})
    original = loader.read_raw(review / 'original_tracked_head_inventory.json.segments.json')
    original_same = original == loader.read_raw(external / 'original_tracked_head_inventory.json.gz')
    return {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'checks': checks,
            'original_inventory_copies_identical': original_same,
            'all_passed': original_same and all(not row['problems'] for row in checks),
            'limitations': ['Present bytes/file sets only; no claim of absence of earlier transient writes.',
                           'M5 new commits are expected; only its inherited protected files use the M4 inventory.',
                           'Existing inventories are referenced by verified digest; no duplicate multi-MB maps saved.']}


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None, 'timezone required')
    return result


def cost_summary(chunks, checkpoints, measurement_sha):
    """Pure structural arithmetic, separately testable with synthetic fixtures."""
    require(len(chunks) == 20 and len(checkpoints) == 21, 'need exactly20chunks and21checkpoints')
    require([r.get('checkpoint_games') for r in checkpoints] == list(range(0, 481, 24)), 'checkpoint coverage/order')
    for row in checkpoints:
        require(type(row['checkpoint_games']) is int and row.get('remote_fetch_and_tree_verified') is True,
                'unverified checkpoint')
        for field in ('commit', 'tree'):
            require(isinstance(row.get(field), str) and re.fullmatch('[0-9a-f]{40}', row[field]), 'invalid Git identity')
        timestamp(row['verified_utc'])
    child_wall = cpu_user = cpu_system = 0.0
    peak = 0
    for i, row in enumerate(chunks, 1):
        for key, expected in (('chunk', i), ('completed_before', (i-1)*24),
                              ('manifest_declared_before', (i-1)*24), ('completed_after', i*24),
                              ('exit_code', 0 if i == 20 else 75)):
            require(type(row.get(key)) is int and row[key] == expected, 'chunk gap/retry/fault: ' + key)
        require(row.get('status_after') == ('completed' if i == 20 else 'interrupted'), 'chunk status')
        require(row.get('measurement_script_sha256') == measurement_sha, 'measurement provenance')
        for key in ('wall_seconds', 'cpu_user_seconds', 'cpu_system_seconds', 'peak_process_rss_kib', 'output_tree_bytes_after'):
            require(type(row.get(key)) in (int, float) and math.isfinite(row[key]) and row[key] >= 0, 'invalid cost: ' + key)
        start, end = timestamp(row['started_utc']), timestamp(row['ended_utc'])
        require(end >= start and abs((end-start).total_seconds() - row['wall_seconds']) < 5,
                'child wall/calendar measurement mismatch')
        require(timestamp(checkpoints[i-1]['verified_utc']) <= start, 'chunk started before prior checkpoint verification')
        require(end <= timestamp(checkpoints[i]['verified_utc']), 'checkpoint verification precedes child completion')
        child_wall += row['wall_seconds']; cpu_user += row['cpu_user_seconds']; cpu_system += row['cpu_system_seconds']
        peak = max(peak, row['peak_process_rss_kib'])
    start = timestamp(chunks[0]['started_utc'])
    compute_calendar = (timestamp(chunks[-1]['ended_utc']) - start).total_seconds()
    final_sync_calendar = (timestamp(checkpoints[-1]['verified_utc']) - start).total_seconds()
    return {'chunks': 20, 'games': 480, 'checkpoints': 21, 'checkpoint_interval_games': 24,
            'child_wall_seconds': child_wall, 'child_cpu_user_seconds': cpu_user,
            'child_cpu_system_seconds': cpu_system, 'child_cpu_total_seconds': cpu_user + cpu_system,
            'maximum_child_peak_process_rss_kib': peak,
            'final_output_tree_bytes': chunks[-1]['output_tree_bytes_after'],
            'calendar_first_child_start_to_last_child_end_seconds': compute_calendar,
            'calendar_first_child_start_to_final_checkpoint_verified_seconds': final_sync_calendar,
            'calendar_outside_measured_children_through_final_checkpoint_seconds': final_sync_calendar - child_wall,
            'child_scope': 'Isolated generation child: imports/resume/per-game validation/final analysis; excludes Git sync, main tests and this harness.',
            'calendar_scope': 'Elapsed calendar time includes synchronization, external validation, waiting and other overhead. Residual is not an isolated synchronization measurement.',
            'rss_scope': 'Maximum of20 separately measured process peaks, never summed; not exclusive MCTS or incremental per-game memory.'}


def checkpoint_cost_guard(root, validation, lock):
    paths = sorted((root / E / 'cost').glob('chunk_*.json'))
    expected_cost_files = {f'chunk_{i:02d}{suffix}' for i in range(1, 21) for suffix in ('.json', '.stdout.txt', '.stderr.txt')}
    require({p.name for p in (root / E / 'cost').iterdir()} == expected_cost_files,
            'unexpected, interrupted or extra child attempts: include all attempts in a separately reviewed full-cost accounting; never omit them')
    require([p.name for p in paths] == [f'chunk_{i:02d}.json' for i in range(1, 21)], 'unexpected/missing cost chunks')
    chunks = [read(p) for p in paths]
    checkpoints = read(root / E / 'checkpoints.json')
    result = cost_summary(chunks, checkpoints, lock['measurement_script_sha256'])
    rows = []
    for i, row in enumerate(chunks, 1):
        expected = [row['command'][0], str(root / 'scripts/run_g1_pass8_estimation.py'), 'run',
                    '--out', str(root / O), '--concurrency', '1', '--stop-after', '24']
        if i > 1:
            expected.append('--resume')
        require(row['command'] == expected, 'unexpected formal child command')
        require(Path(row['command'][0]).resolve() == Path(sys.executable).resolve(), 'child interpreter changed')
        for suffix in ('.stdout.txt', '.stderr.txt'):
            require(paths[i-1].with_suffix(suffix).is_file(), 'missing chunk log')
    final_hashes = validation['raw_game_sha256']
    raw_git_blobs = {}
    for name in final_hashes:
        content = (root / O / 'games' / name).read_bytes()
        raw_git_blobs[(O / 'games' / name).as_posix()] = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
    for cp in checkpoints:
        n, commit = cp['checkpoint_games'], cp['commit']
        actual_tree = git(root, 'rev-parse', commit + '^{tree}').decode().strip()
        require(actual_tree == cp['tree'], 'checkpoint commit/tree mismatch')
        cp_row = dict(cp, local_commit_tree_reverified=True)
        if n:
            path = root / E / f'checkpoint_validation_{n:03d}.json'
            saved = read(path)
            expected_hashes = {f'{BATCH}-g{i:06d}.json': final_hashes[f'{BATCH}-g{i:06d}.json'] for i in range(n)}
            require(saved.get('game_count') == saved.get('replay_and_search_ok') == n and saved.get('planned') == 480 and
                    saved.get('problems') == [] and saved.get('raw_game_sha256') == expected_hashes and
                    saved.get('source_fingerprint') == SOURCE and saved.get('rule_fault_present') is False and
                    saved.get('complete') is (n == 480) and
                    saved.get('manifest_status') == ('completed' if n == 480 else 'interrupted'), 'checkpoint validation mismatch')
            committed = git(root, 'show', commit + ':' + path.relative_to(root).as_posix())
            require(sha_bytes(committed) == sha(path), 'checkpoint validation not in recorded tree')
            manifest = parse(git(root, 'show', commit + ':' + (O / 'manifest.json').as_posix()).decode())
            require(manifest['completed_game_count'] == n and manifest['completed_indexes'] == list(range(n)), 'checkpoint manifest count')
            raw_entries = [entry.split(b'\t', 1) for entry in git(root, 'ls-tree', '-rz', commit, '--', (O / 'games').as_posix()).split(b'\0') if entry]
            raw_blobs = {}
            for meta, path_bytes in raw_entries:
                mode, kind, oid = meta.decode().split()
                require(mode == '100644' and kind == 'blob', 'checkpoint raw entry mode/type')
                raw_blobs[os.fsdecode(path_bytes)] = oid
            expected_blobs = {p: raw_git_blobs[p] for p in [(O / 'games' / name).as_posix() for name in expected_hashes]}
            require(raw_blobs == expected_blobs, 'checkpoint raw file set/bytes')
            cp_row['validation_sha256'] = sha(path)
        rows.append(cp_row)
    require(sum(p.stat().st_size for p in (root / O).rglob('*') if p.is_file()) == result['final_output_tree_bytes'], 'final output bytes mismatch')
    incidents = read(root / E / 'sync_incidents.json')
    result.update(sync_incidents=incidents, sync_incidents_sha256=sha(root / E / 'sync_incidents.json'),
                  child_attempt_accounting='Exactly20 measured attempts at20 fixed24-game boundaries. Additional, interrupted or unmeasured attempt artifacts fail closed and require full-attempt cost reconciliation.',
                  checkpoint_records=rows, source_cost_files={p.relative_to(root).as_posix(): sha(p) for p in paths},
                  checkpoint_registry_sha256=sha(root / E / 'checkpoints.json'),
                  synchronization_evidence='Remote fetch/tree verification is recorded in the21 checkpoint rows; local recorded commit/tree and saved raw-prefix shape rechecked here. No new network fetch is claimed.')
    return result


class WriteFence:
    """Python audit guard, supplementary to evidence before/after hashes."""
    def __init__(self, dest):
        self.dest = dest.resolve()

    def allowed_path(self, value):
        require(not isinstance(value, int), 'write through file descriptor forbidden')
        path = no_symlinks(os.fsdecode(value)).resolve()
        require(path.is_relative_to(self.dest), 'write outside new evidence destination blocked: ' + str(path))

    def __call__(self, event, args):
        if event == 'open':
            _, mode, flags = args
            if (isinstance(mode, str) and any(x in mode for x in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                self.allowed_path(args[0])
                require(flags & os.O_EXCL, 'evidence files must be created exclusively')
        elif event == 'os.mkdir':
            self.allowed_path(args[0])
        elif event in ('os.remove', 'os.rmdir', 'os.rename', 'os.link', 'os.symlink', 'os.chmod', 'os.chown', 'os.truncate'):
            raise PermissionError('mutating operation forbidden during final verification: ' + event)
        elif event == 'subprocess.Popen':
            argv = args[1]
            require(isinstance(argv, (list, tuple)) and len(argv) >= 2 and argv[0] == 'git' and
                    argv[1] in ('rev-parse', 'ls-files', 'show', 'ls-tree'), 'only read-only Git subprocesses allowed')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--destination', type=Path, required=True)
    ap.add_argument('--data-ready', action='store_true')
    args = ap.parse_args(argv)
    require(args.data_ready, 'Do not execute until the parent explicitly declares formal480 complete.')
    root = no_symlinks(args.root).resolve()
    dest = destination(root, args.destination)
    out = root / O
    no_symlinks(out)
    manifest, saved_validation = read(out / 'manifest.json'), read(out / 'validation.json')
    complete_guard(manifest, saved_validation, args.data_ready)
    raw_complete_guard(out, saved_validation)
    require(not (out / 'rule_fault.json').exists(), 'persisted rule fault')
    require(not any(p.suffix == '.tmp' for p in out.rglob('*')), 'unfinished temporary input')
    source_only_imports(root)
    protocol, lock, source, plan, cells = frozen_guard(root)
    selections = select_six(plan, cells)
    costs = checkpoint_cost_guard(root, saved_validation, lock)
    before = input_snapshot(root)
    dest.mkdir(parents=False, exist_ok=False)
    sys.addaudithook(WriteFence(dest))
    tick = time.perf_counter()
    write(dest, 'validation_input_hashes_before.json', before)
    write(dest, 'cost_and_checkpoints.json', costs)
    write(dest, 'predesignated_regeneration_selections.json', {
        'selection_rule': 'Lowest frozen game_index in each rule0/8 by batch seed11/12/13 stratum; no outcomes consulted.',
        'fixed_before_regeneration': True, 'count': 6, 'selections': selections})
    errors, strict, reproduced, historical_before, historical_after = [], None, [], None, None
    input_check = None
    strict_passed = False
    stage = 'historical_before'
    try:
        historical_before = historical_check(root)
        write(dest, 'historical_preservation_before.json', historical_before)
        require(historical_before['all_passed'], 'historical preservation failed before regeneration')
        stage = 'strict_complete_validation'
        sys.path.insert(0, str(root / 'src'))
        from winai_loseai.experiments import g1_pass8_estimation as experiment
        from winai_loseai.league.runner import play_one
        from winai_loseai.provenance import source_lock
        require(Path(experiment.__file__).resolve() == root / 'src/winai_loseai/experiments/g1_pass8_estimation.py', 'wrong imported production package')
        require(source_lock() == source == read(out / 'source_lock.json'), 'loaded frozen source mismatch')
        strict = experiment.validate(out, require_complete=True, check_analysis=True)
        complete_guard(read(out / 'manifest.json'), strict, True)
        require(strict == saved_validation, 'saved final validation differs from strict recomputation')
        strict_passed = True
        write(dest, 'strict_complete_validation.json', strict)
        print(json.dumps({'stage': stage, 'games': 480, 'passed': True}), flush=True)
        (dest / 'regenerated_games').mkdir()
        stage = 'six_serial_regenerations'
        by_index = {job['index']: job for job in plan}
        for row in selections:
            game_tick = time.perf_counter()
            # Both guards rechecked immediately before each play; runner writes no files.
            complete_guard(read(out / 'manifest.json'), read(out / 'validation.json'), True)
            frozen_guard(root)
            job = dict(copy.deepcopy(by_index[row['game_index']]), batch_id=BATCH)
            saved_path = out / 'games' / (row['game_id'] + '.json')
            saved = read(saved_path)
            fresh = json.loads(json.dumps(play_one(job, board_size=5, komi=2.5), allow_nan=False))
            fresh_path = write(dest, 'regenerated_games/' + row['game_id'] + '.json', fresh)
            typed_job = dict(job)
            from winai_loseai.spec import AgentSpec
            typed_job['black'] = AgentSpec.from_dict(job['black']); typed_job['white'] = AgentSpec.from_dict(job['white'])
            issues = experiment.record_problems(fresh, typed_job)
            a, b = normalized(saved), normalized(fresh)
            diff = differences(a, b)
            result = dict(row, matches_except_timing=not diff, record_problems=issues, differences=diff,
                          saved_file_sha256=sha(saved_path), regenerated_file_sha256=sha(fresh_path),
                          saved_nontiming_sha256=stable_sha(a), regenerated_nontiming_sha256=stable_sha(b),
                          verification_wall_seconds=time.perf_counter() - game_tick)
            reproduced.append(result)
            write(dest, 'regeneration_' + row['game_id'] + '.json', result)
            print(json.dumps({'stage': stage, 'game_index': row['game_index'], 'matches_except_timing': not diff}), flush=True)
            require(not diff and not issues, 'reproduction mismatch: ' + row['game_id'])
        write(dest, 'six_game_regeneration.json', {'count': len(reproduced), 'matching_count': len(reproduced),
              'concurrency': 1, 'sample_increment': 0, 'formal_sample_n': 480,
              'excluded_fields': ['game_wall_ms', 'moves[*].search_time_ms'],
              'comparison': 'Strict full-record values AND types after JSON map-key representation conversion and deletion of exactly the two timing paths.',
              'results': reproduced})
    except BaseException as error:
        errors.append({'stage': stage, 'error': repr(error), 'traceback': traceback.format_exc()})
    finally:
        try:
            historical_after = historical_check(root)
            write(dest, 'historical_preservation_after.json', historical_after)
            require(historical_after['all_passed'], 'historical preservation failed after verification')
            if historical_before is not None:
                require([r['path_hash_size_digest'] for r in historical_before['checks']] ==
                        [r['path_hash_size_digest'] for r in historical_after['checks']], 'historical inputs changed during verification')
        except BaseException as error:
            errors.append({'stage': 'historical_after', 'error': repr(error), 'traceback': traceback.format_exc()})
        try:
            input_check = compare_snapshots(before, input_snapshot(root))
            write(dest, 'validation_inputs_unchanged.json', input_check)
            require(input_check['unchanged'], 'validation input bytes/file sets changed')
        except BaseException as error:
            errors.append({'stage': 'validation_inputs_after', 'error': repr(error), 'traceback': traceback.format_exc()})
    summary = {'experiment_id': EXPERIMENT, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
               'source_fingerprint': SOURCE, 'protocol_sha256': PROTOCOL,
               'script_sha256': sha(__file__), 'formal_sample_n': 480, 'sample_increment': 0,
               'strict_complete_validation_passed': strict_passed,
               'regenerations_completed': len(reproduced),
               'matching_regenerations': sum(row['matches_except_timing'] and not row['record_problems'] for row in reproduced),
               'regeneration_selected_indexes': [row['game_index'] for row in selections],
               'historical_before_passed': historical_before is not None and historical_before['all_passed'],
               'historical_after_passed': historical_after is not None and historical_after['all_passed'],
               'validation_inputs_unchanged': input_check is not None and input_check['unchanged'],
               'harness_wall_seconds': time.perf_counter() - tick,
               'cost_scope': 'Harness wall and regeneration wall are extra verification costs, excluded from formal20child compute and checkpoint calendar cost.',
               'separate_required_evidence': ['Final main test suite', 'Independent final arithmetic/rules audit', 'Final delivery publication/remote verification'],
               'problems': errors, 'passed': not errors and len(reproduced) == 6}
    write(dest, 'final_validation_summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # A failed preflight intentionally does not create an evidence destination.
        print(json.dumps({'passed': False, 'preflight_error': repr(error)}), file=sys.stderr)
        raise SystemExit(1)
