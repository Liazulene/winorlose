"""Whitelist-only M7 technical snapshots. Large blobs are read in bounded slices.

This tool never creates a Git commit or sends data to a service. It stages only
this version's files and emits Git object metadata for separately verified
connector uploads. Inherited experiment files are never staged or rewritten.
"""
from __future__ import annotations
import base64
import json
import re
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
EXACT = {
    'conftest.py', 'src/winai_loseai/__init__.py',
    'src/winai_loseai/experiments/komi_pass_estimation.py',
    'src/winai_loseai/experiments/komi_pass_estimation_stats.py',
    'tests/test_komi_pass_estimation_m7.py',
    'tests/test_komi_pass_estimation_stats_m7.py',
    'scripts/run_komi_pass_estimation.py',
    'scripts/measure_komi_pass_estimation_chunk.py',
    'scripts/validate_komi_estimation_checkpoint.py',
    'scripts/verify_komi_pass_estimation_reproduction.py',
    'scripts/prepare_komi_pass_estimation_sync.py',
}
PREFIXES = ('experiments/komi_pass_estimation_v1/', 'outputs/komi_pass_estimation_v1/')
EXTENSIONS = {'.py', '.json', '.jsonl', '.txt', '.csv'}

def git(*args, binary=False):
    value = subprocess.check_output(['git', *args], cwd=ROOT)
    return value if binary else value.decode().strip()

def allowed(path):
    p = Path(path)
    return (not p.is_absolute() and '..' not in p.parts
            and (path in EXACT or path.startswith(PREFIXES))
            and p.suffix in EXTENSIONS)

def assert_path(path):
    if not allowed(path):
        raise ValueError('Outside M7 technical whitelist: ' + path)
    full = ROOT / path
    if any(p.is_symlink() for p in (full, *full.parents)):
        raise ValueError('Symlinks forbidden: ' + path)
    if not full.is_file():
        raise ValueError('Expected regular file: ' + path)

def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'blob':
        path = sys.argv[2]
        assert_path(path)
        data = git('show', ':' + path, binary=True)
        offset = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        length = int(sys.argv[4]) if len(sys.argv) > 4 else 49152
        if offset < 0 or length < 1 or length > 49152 or offset > len(data):
            raise ValueError('Invalid bounded slice')
        print(json.dumps({'path': path, 'sha': git('rev-parse', ':' + path),
                          'bytes': len(data), 'offset': offset,
                          'content': base64.b64encode(data[offset:offset+length]).decode(),
                          'encoding': 'base64'}))
        return
    anchor = None
    if len(sys.argv) > 1:
        if len(sys.argv) != 3 or sys.argv[1] != '--anchor' or not re.fullmatch(r'[0-9a-f]{40}', sys.argv[2]):
            raise ValueError('Use optional --anchor COMMIT or bounded blob reading')
        anchor = sys.argv[2]
    if anchor is None and (ROOT/'outputs/komi_pass_estimation_v1/manifest.json').exists():
        raise ValueError('A verified zero-game commit anchor is required after production begins')
    sys.path.insert(0, str(ROOT/'src'))
    from winai_loseai.experiments.komi_pass_estimation import verify_preexecution
    verify_preexecution()
    if anchor is not None:
        for name in ('pre_execution_lock.json', 'pre_execution_source_lock.json', 'frozen_plan.json', 'preregistration.json'):
            relative = 'experiments/komi_pass_estimation_v1/' + name
            if (ROOT/relative).read_bytes() != git('show', anchor + ':' + relative, binary=True):
                raise ValueError('Frozen artifact differs from verified zero-game commit: ' + name)
    changed = git('ls-files', '-m').splitlines()
    if any(not allowed(path) for path in changed):
        raise ValueError('Unexpected inherited or nontechnical modification: ' + str(changed))
    paths = [path for path in EXACT if (ROOT/path).exists()]
    for prefix in PREFIXES:
        directory = ROOT/prefix
        if directory.exists():
            paths.extend(str(path.relative_to(ROOT)) for path in directory.rglob('*') if path.is_file())
    for path in paths:
        assert_path(path)
    # Existing staging may contain unrelated work: reject it before modifying index.
    for path in git('diff', '--cached', '--name-only').splitlines():
        assert_path(path)
    if paths:
        git('add', '-f', '--', *sorted(set(paths)))
    names = git('diff', '--cached', '--name-only').splitlines()
    if names != git('diff', '--cached', '--name-only', '--diff-filter=ACM').splitlines():
        raise ValueError('Deletions and type changes forbidden')
    entries = []
    for path in names:
        assert_path(path)
        mode, sha, stage_path = git('ls-files', '--stage', '--', path).split(maxsplit=2)
        if mode != '100644' or not stage_path.startswith('0\t'):
            raise ValueError('Only regular stage-zero technical files supported: ' + path)
        entries.append({'path': path, 'mode': mode, 'type': 'blob', 'sha': sha,
                        'bytes': len(git('show', ':' + path, binary=True))})
    print(json.dumps({'parent': git('rev-parse', 'HEAD'),
                      'base_tree': git('rev-parse', 'HEAD^{tree}'),
                      'expected_tree': git('write-tree'), 'entries': entries}))
if __name__ == '__main__':
    main()
