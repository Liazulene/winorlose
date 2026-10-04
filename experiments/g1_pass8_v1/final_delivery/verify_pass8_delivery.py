"""Read-only final pilot validation and exactly six registered regenerations.

All evidence is written beside this script, outside every experimental worktree.
The six regenerated games are verification records and do not add observations.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

BASE = Path('/workspace/scratch/50e0c7c6aca1')
ROOT = BASE / 'winorlose_g1_pass8_v1'
OUT = ROOT / 'outputs/g1_pass8_pilot_v1'
DEST = Path(__file__).resolve().parent
EXPECTED_SOURCE = '5876fdc9d1cc29fc446300265db5a9676f07b646cc8299cd4961f1129fdb3ec1'
sys.path.insert(0, str(ROOT / 'src'))

from winai_loseai.experiments import g1_pass8 as pilot
from winai_loseai.league.runner import play_one
from winai_loseai.provenance import current_provenance, source_lock


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(name, value):
    path = DEST / name
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    return str(path)


def normalized(record):
    # JSON roundtrip is only representation normalization: integer map keys
    # become strings. Keep all rules, source, runtime and version fields.
    record = json.loads(json.dumps(record, allow_nan=False))
    record.pop('game_wall_ms')
    for move in record['moves']:
        move.pop('search_time_ms')
    return record


def diff(a, b, path='$'):
    if type(a) is not type(b):
        return [{'path': path, 'saved': a, 'regenerated': b}]
    if isinstance(a, dict):
        result = []
        for key in sorted(a.keys() | b.keys()):
            if key not in a or key not in b:
                result.append({'path': path + '.' + key, 'missing_from': 'saved' if key not in a else 'regenerated'})
            else:
                result.extend(diff(a[key], b[key], path + '.' + key))
        return result
    if isinstance(a, list):
        result = []
        if len(a) != len(b):
            result.append({'path': path, 'saved_length': len(a), 'regenerated_length': len(b)})
        for i, (aa, bb) in enumerate(zip(a, b)):
            result.extend(diff(aa, bb, f'{path}[{i}]'))
        return result
    return [] if a == b else [{'path': path, 'saved': a, 'regenerated': b}]


def protection_check():
    before_path = BASE / 'winorlose_reports/g1_pass8_v1/protected_hashes_before.json'
    baseline = read(before_path)
    expected_names = {'winorlose', 'winorlose_d0_v1', 'winorlose_d1_v1', 'winorlose_d1_estimation_v1'}
    assert set(baseline) == expected_names
    result = {'baseline_path': str(before_path), 'baseline_sha256': sha(before_path),
              'worktrees': {}, 'problems': []}
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    for name, expected in baseline.items():
        worktree = BASE / name
        names = subprocess.check_output(['git', '-C', str(worktree), 'ls-files', '-z'], env=env).decode().split('\0')
        tracked = set(filter(None, names))
        missing = sorted(set(expected) - tracked)
        added = sorted(tracked - set(expected))
        actual = {}
        errors = []
        for relative in sorted(tracked):
            try:
                actual[relative] = sha(worktree / relative)
            except OSError as error:
                errors.append({'file': relative, 'error': str(error)})
        changed = [{'file': path, 'expected': expected[path], 'actual': actual[path]}
                   for path in sorted(expected.keys() & actual.keys()) if expected[path] != actual[path]]
        passed = not (missing or added or errors or changed)
        result['worktrees'][name] = {'expected_count': len(expected), 'tracked_count': len(tracked),
                                    'hashed_count': len(actual), 'unchanged': passed,
                                    'expected_path_sha256_map_digest': stable_sha(expected),
                                    'actual_path_sha256_map_digest': stable_sha(actual),
                                    'missing_tracked_paths': missing, 'added_tracked_paths': added,
                                    'read_errors': errors, 'changed_files': changed}
        write('protected_hashes_after_' + name + '.json', actual)
        if not passed:
            result['problems'].append(name + ': tracked set or file-byte mismatch')
        print(json.dumps({'stage': 'historical_protection', 'worktree': name,
                          'count': len(actual), 'unchanged': passed}), flush=True)
    write('historical_protection.json', result)
    return result


def main():
    started = time.perf_counter()
    manifest = read(OUT / 'manifest.json')
    assert manifest['status'] == 'completed'
    assert manifest['completed_game_count'] == 48
    assert manifest['completed_indexes'] == list(range(48))
    assert current_provenance()['source_fingerprint'] == EXPECTED_SOURCE
    test_log = (DEST / 'final_pytest.log').read_text()
    matches = re.findall(r'(^|\n)(\d+) passed in ([\d.]+)s', test_log)
    assert matches and int(matches[-1][1]) == 387, test_log[-2000:]
    tests = {'passed': 387, 'failures': 0, 'wall_seconds_reported': float(matches[-1][2]),
             'interpreter': sys.executable, 'python_dont_write_bytecode': os.environ.get('PYTHONDONTWRITEBYTECODE'),
             'command': [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                         '--basetemp=' + str(DEST / 'pytest_tmp')],
             'log_sha256': sha(DEST / 'final_pytest.log')}
    write('final_pytest.json', tests)

    strict = pilot.validate(OUT, require_complete=True, check_analysis=True)
    write('strict_complete_validation.json', strict)
    assert strict['game_count'] == strict['replay_and_search_ok'] == 48 and strict['complete']
    assert strict['manifest_status'] == 'completed' and not strict['problems'], strict
    print(json.dumps({'stage': 'strict_complete_validation', 'count': 48,
                      'replay_and_search_ok': 48, 'problems': []}), flush=True)

    plan = pilot.jobs()
    cells = pilot.cells()
    selections = []
    for rule in (0, 8):
        for seed in (8, 9, 10):
            matching = [(job, cell) for job, cell in zip(plan, cells)
                        if cell['pass_min_ply'] == rule and cell['batch_seed'] == seed]
            job, cell = min(matching, key=lambda pair: pair[0]['index'])
            assert job['black'].simulations() == job['white'].simulations() == 256
            selections.append({'pass_min_ply': rule, 'batch_seed': seed,
                               'game_index': job['index'], 'game_id': f"{job['batch_id']}-g{job['index']:06d}",
                               'game_seed': job['game_seed'], 'black': job['black'].to_dict(),
                               'white': job['white'].to_dict(), 'budget_each': 256})
    assert len(selections) == len({x['game_index'] for x in selections}) == 6
    write('predesignated_regeneration_selections.json', {
        'rule': 'Minimum registered game_index in each pass_min_ply {0,8} by batch_seed {8,9,10} stratum',
        'saved_before_regeneration': True, 'count': 6, 'selections': selections})
    regenerated_dir = DEST / 'regenerated_games'
    regenerated_dir.mkdir(exist_ok=False)
    reproductions = []
    for selected in selections:
        tick = time.perf_counter()
        job = plan[selected['game_index']]
        saved_path = OUT / 'games' / (selected['game_id'] + '.json')
        saved = read(saved_path)
        fresh = play_one(job, board_size=5, komi=2.5)
        fresh = json.loads(json.dumps(fresh, allow_nan=False))
        fresh_path = write('regenerated_games/' + selected['game_id'] + '.json', fresh)
        a, b = normalized(saved), normalized(fresh)
        issues = pilot.record_problems(fresh, job)
        differences = diff(a, b)
        reproduction = {**selected, 'saved_file_sha256': sha(saved_path),
                        'regenerated_file_sha256': sha(fresh_path),
                        'saved_excluding_only_timing_sha256': stable_sha(a),
                        'regenerated_excluding_only_timing_sha256': stable_sha(b),
                        'matches_except_timing': a == b, 'record_problems': issues,
                        'differences': differences, 'wall_seconds': time.perf_counter() - tick}
        reproductions.append(reproduction)
        write('regeneration_' + selected['game_id'] + '.json', reproduction)
        print(json.dumps({'stage': 'regeneration', 'game_index': job['index'],
                          'matches_except_timing': a == b, 'record_problems': issues,
                          'wall_seconds': reproduction['wall_seconds']}), flush=True)
        assert a == b and not issues, reproduction
    write('six_game_regeneration.json', {'selections': selections, 'results': reproductions,
          'count': 6, 'matching_count': 6, 'added_observations': 0, 'concurrency': 1,
          'excluded_fields': ['game_wall_ms', 'moves[*].search_time_ms'],
          'comparison': 'Full record equality after JSON roundtrip and deleting exactly the two timing fields; retain all provenance, version and rule metadata',
          'problems': []})

    protection = protection_check()
    before = read(DEST / 'validation_input_hashes_before.json')
    after = {path: sha(ROOT / path) for path in before}
    differences = [path for path in before if before[path] != after[path]]
    old_pilot_paths = {p for p in before if p.startswith('outputs/g1_pass8_pilot_v1/')}
    new_pilot_paths = {p.relative_to(ROOT).as_posix() for p in OUT.rglob('*') if p.is_file()}
    added = sorted(new_pilot_paths - old_pilot_paths)
    missing = sorted(old_pilot_paths - new_pilot_paths)
    input_check = {'checked_file_count': len(before), 'changed_files': differences,
                   'added_pilot_files': added, 'missing_pilot_files': missing,
                   'unchanged': not (differences or added or missing),
                   'before_sha256_map_digest': stable_sha(before),
                   'after_sha256_map_digest': stable_sha(after),
                   'source_lock_matches_saved': source_lock() == read(OUT / 'source_lock.json')}
    write('validation_input_hashes_after.json', after)
    write('validation_inputs_unchanged.json', input_check)
    summary = {'checked_at': datetime.now(timezone.utc).isoformat(),
               'experiment_id': 'G1-pass8-pilot-v1', 'source_fingerprint': EXPECTED_SOURCE,
               'code_version': current_provenance()['code_version'], 'python_version': current_provenance()['python_version'],
               'pytest': tests, 'strict_replay_and_search_passed': 48, 'sample_n': 48,
               'regenerations': 6, 'matching_regenerations': 6, 'regeneration_added_n': 0,
               'regeneration_selected_indexes': [x['game_index'] for x in selections],
               'historical_worktrees_checked': len(protection['worktrees']),
               'historical_tracked_files_checked': sum(x['hashed_count'] for x in protection['worktrees'].values()),
               'historical_protection_passed': not protection['problems'],
               'validation_inputs_unchanged': input_check['unchanged'],
               'source_lock_matches_saved': input_check['source_lock_matches_saved'],
               'script_sha256': sha(__file__), 'wall_seconds_excluding_pytest': time.perf_counter() - started,
               'problems': protection['problems'] + (['validation input mutation'] if not input_check['unchanged'] else [])}
    write('final_validation_summary.json', summary)
    print(json.dumps(summary), flush=True)
    assert not summary['problems'] and summary['source_lock_matches_saved'], summary
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        write('validation_failure.json', {'error': repr(error), 'traceback': traceback.format_exc()})
        traceback.print_exc()
        raise SystemExit(1)
