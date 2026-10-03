"""Version/source mismatches must refuse before repairing or writing data."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from winai_loseai.league.batch import run_batch, _SimulatedStop
from winai_loseai.league.runstore import ConfigMismatch, integrity_problems
from winai_loseai.provenance import source_inventory, fingerprint


@pytest.fixture
def tmp_path():
    # Avoid pytest's shared, potentially inaccessible Windows temp root.
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory)


def snapshot(out):
    return {p.relative_to(out).as_posix(): p.read_bytes()
            for p in out.rglob("*") if p.is_file()}


def partial(out):
    with pytest.raises(_SimulatedStop):
        run_batch(str(out), "A", 8, 7, 1, stop_after=2)


@pytest.mark.parametrize("field,value", [
    ("code_version", "different-version"), ("source_fingerprint", "0" * 64),
    ("schema_version", -1), ("python_version", "different-runtime")])
def test_changed_version_refused_without_mutation(tmp_path, field, value):
    out = tmp_path / "run"
    partial(out)
    path = out / "manifest.json"
    m = json.loads(path.read_text(encoding="utf-8")); m[field] = value
    path.write_text(json.dumps(m), encoding="utf-8")
    with (out / "games.jsonl").open("ab") as f:
        f.write(b'{"torn')
    before = snapshot(out)
    with pytest.raises(ConfigMismatch):
        run_batch(str(out), "A", 8, 7, 1, resume=True)
    assert snapshot(out) == before


@pytest.mark.parametrize("target", ["record", "metadata", "lock"])
def test_mixed_record_or_lock_refused_without_mutation(tmp_path, target):
    out = tmp_path / "run"; partial(out)
    path = (next((out / "games").glob("*.json")) if target == "record"
            else out / ("source_lock.json" if target == "lock" else "games.jsonl"))
    if target == "metadata":
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["source_fingerprint"] = "bad"
        path.write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
    else:
        doc = json.loads(path.read_text(encoding="utf-8")); doc["source_fingerprint"] = "bad"
        path.write_text(json.dumps(doc), encoding="utf-8")
    before = snapshot(out)
    with pytest.raises(ConfigMismatch):
        run_batch(str(out), "A", 8, 7, 1, resume=True)
    assert snapshot(out) == before


def test_same_version_resumes_and_all_records_match(tmp_path):
    out = tmp_path / "run"; partial(out)
    run_batch(str(out), "A", 8, 7, 1, resume=True)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for p in (out / "games").glob("*.json"):
        r = json.loads(p.read_text(encoding="utf-8"))
        for k in ("code_version", "source_fingerprint", "python_version", "schema_version"):
            assert r[k] == m[k]
    assert integrity_problems(str(out)) == []


def test_source_content_and_added_files_change_fingerprint(tmp_path):
    package = tmp_path / "src/winai_loseai"; package.mkdir(parents=True)
    (tmp_path / "run.py").write_text("# entry\n", encoding="utf-8")
    p = package / "rules.py"; p.write_text("a=1\n", encoding="utf-8")
    a = fingerprint(source_inventory(tmp_path))
    p.write_text("a=2\n", encoding="utf-8")
    b = fingerprint(source_inventory(tmp_path)); assert a != b
    (package / "new.py").write_text("# new\n", encoding="utf-8")
    assert fingerprint(source_inventory(tmp_path)) != b


def test_live_edit_refuses_before_writing(tmp_path):
    from winai_loseai.league.runstore import RunStore
    from winai_loseai.league.runner import play_one
    from winai_loseai.league.pairing import batch_jobs_for
    out = tmp_path / "run"; partial(out)
    before = snapshot(out)
    with patch("winai_loseai.provenance.source_inventory", return_value={}):
        with pytest.raises(RuntimeError, match="source changed"):
            run_batch(str(out), "A", 8, 7, 1, resume=True)
    assert snapshot(out) == before
