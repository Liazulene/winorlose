"""Pytest bootstrap: make the ``src`` package importable from the repo root."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# The M5 test methods are immutable historical evidence. Their original
# fixtures run synthetic games against the current implementation, but two
# test files predate the new version and read a 0.7 protocol directly. Adapt
# ONLY the version field in a private temporary copy, scoped to exact paths.
import json
from pathlib import Path
import pytest

@pytest.fixture(autouse=True)
def m6_legacy_m5_protocol_version_adapter(request, tmp_path, monkeypatch):
    root = Path(_HERE)
    targets = {
        root / 'tests/test_g1_pass8_estimation.py',
        root / 'experiments/g1_pass8_estimation_v1/independent_review/test_resume20261004_independent_safety.py',
    }
    if request.node.path.resolve() not in targets:
        return
    from winai_loseai import CODE_VERSION
    from winai_loseai.experiments import g1_pass8_estimation as legacy
    original = json.loads(legacy.PROTOCOL.read_text(encoding='utf-8'))
    adapted = dict(original)
    adapted['code_version'] = CODE_VERSION
    assert {key for key in original if original[key] != adapted[key]} <= {'code_version'}
    path = tmp_path / 'm6_legacy_m5_version_only_protocol.json'
    path.write_text(json.dumps(adapted), encoding='utf-8')
    monkeypatch.setattr(legacy, 'PROTOCOL', path)
    monkeypatch.setattr(legacy, 'PREREGISTRATION_SHA256', legacy.sha256(path))
