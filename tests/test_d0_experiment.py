"""D0 engineering acceptance: isolation, resume, determinism and validation."""
import json
from pathlib import Path

import pytest

from winai_loseai.experiments import d0
from winai_loseai.league.runstore import ConfigMismatch


def snapshot(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def test_plan_is_balanced_unique_and_fixed():
    jobs = d0.jobs()
    assert len(jobs) == 36
    assert [j["index"] for j in jobs] == list(range(36))
    assert len({(j["black"].algorithm, j["white"].algorithm, j["black"].identity, j["white"].identity) for j in jobs}) == 36
    for algorithm in d0.POLICIES:
        assert sum(j["black"].algorithm == algorithm for j in jobs) == 12
        assert sum(j["white"].algorithm == algorithm for j in jobs) == 12


def test_full_sequential_parallel_resume_are_identical(tmp_path):
    sequential, parallel, resumed = (tmp_path / name for name in ("sequential", "parallel", "resumed"))
    assert d0.run(sequential)["problems"] == []
    assert d0.run(parallel, concurrency=2)["problems"] == []
    with pytest.raises(d0.D0Interrupted):
        d0.run(resumed, concurrency=1, stop_after=5)
    assert json.loads((resumed / "manifest.json").read_text())["status"] == "interrupted"
    # A torn trailing append and missing metadata are recoverable.
    meta = resumed / "games.jsonl"
    lines = meta.read_text().splitlines()
    meta.write_text("\n".join(lines[:-1]) + '\n{"torn')
    assert d0.run(resumed, concurrency=2, resume=True)["problems"] == []
    reference = [d0.strip_timing(r) for r in d0.records(sequential)]
    assert reference == [d0.strip_timing(r) for r in d0.records(parallel)]
    assert reference == [d0.strip_timing(r) for r in d0.records(resumed)]
    before = snapshot(resumed)
    assert d0.run(resumed, concurrency=1, resume=True)["problems"] == []
    assert snapshot(resumed) == before
    analysis = d0.analyze(resumed)
    means = [g["mean_length"] for g in analysis["identity_groups"].values()]
    assert len(set(means)) == 1
    assert analysis["n_unique_trajectories"] <= 9


@pytest.mark.parametrize("target", ["experiment_lock.json", "preregistration.json", "source_lock.json", "plan.json", "manifest.json"])
def test_changed_input_refuses_or_validation_fails(tmp_path, target):
    out = tmp_path / "run"
    with pytest.raises(d0.D0Interrupted):
        d0.run(out, stop_after=5)
    path = out / target
    data = json.loads(path.read_text())
    if target == "plan.json":
        data[0]["game_seed"] += 1
    elif target == "preregistration.json":
        data["experiment_id"] = "tampered"
    else:
        data["source_fingerprint"] = "bad"
    path.write_text(json.dumps(data))
    before = snapshot(out)
    if target == "preregistration.json":
        # Saved protocol copy must also be refused before repairing metadata.
        with pytest.raises(ConfigMismatch):
            d0.run(out, resume=True)
        assert snapshot(out) == before
    else:
        with pytest.raises(ConfigMismatch):
            d0.run(out, resume=True)
        assert snapshot(out) == before


@pytest.mark.parametrize("name", sorted(d0.PROTECTED_NAMES))
def test_protected_names_refused_without_mutation(tmp_path, name):
    out = tmp_path / name
    out.mkdir()
    sentinel = out / "sentinel"
    sentinel.write_text("old evidence")
    before = snapshot(out)
    with pytest.raises(ValueError, match="read-only"):
        d0.run(out)
    assert snapshot(out) == before


def test_nonempty_and_symlink_refused(tmp_path):
    out = tmp_path / "nonempty"
    out.mkdir()
    (out / "user.txt").write_text("preserve")
    with pytest.raises(FileExistsError):
        d0.run(out)
    destination = tmp_path / "target"
    destination.mkdir()
    (out / "games").symlink_to(destination, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        d0.run(out)


def test_validation_catches_metadata_and_policy_tampering(tmp_path):
    out = tmp_path / "run"
    d0.run(out)
    meta = out / "games.jsonl"
    rows = [json.loads(line) for line in meta.read_text().splitlines()]
    rows[0]["game_wall_ms"] += 1
    meta.write_text("\n".join(map(json.dumps, rows)) + "\n")
    assert any("metadata differs" in p for p in d0.validate(out)["problems"])


def test_validation_failure_never_completed(tmp_path, monkeypatch):
    out = tmp_path / "run"
    monkeypatch.setattr(d0, "validate", lambda _: {"problems": ["forced replay failure"]})
    with pytest.raises(ValueError, match="validation failed"):
        d0.run(out)
    assert json.loads((out / "manifest.json").read_text())["status"] == "validation_failed"


def test_d0_analysis_has_no_inferential_intervals(tmp_path):
    out = tmp_path / "run"
    d0.run(out)
    data = json.loads((out / "analysis.json").read_text())
    assert data["descriptive_only"]
    assert len(data["rows"]) == 36
    for row in data["rows"]:
        assert len(row["prefixes"]["8"]["END_padded"]) == 8
        for color in ("black", "white"):
            assert row["color_counts"][color]["captured_by_opponent"] >= 0


def test_legal_replay_does_not_replace_policy_reproduction(tmp_path):
    from winai_loseai.league.storage import _metadata_line
    out = tmp_path / "run"
    d0.run(out)
    # OS/AP on another legal first point has the same exact score and legal
    # replay, but is not the registered row-major policy trajectory.
    path = out / "games" / "d0_g0_v1-g000003.json"
    rec = json.loads(path.read_text())
    assert rec["moves"][0]["action"] == 0
    rec["moves"][0]["action"] = 1
    rec["final_board"][0] = 0
    rec["final_board"][1] = 1
    assert d0.replay_record(rec)["ok"]
    path.write_text(json.dumps(rec))
    meta = out / "games.jsonl"
    rows = [json.loads(line) for line in meta.read_text().splitlines()]
    rows[3] = _metadata_line(rec)
    meta.write_text("\n".join(map(json.dumps, rows)) + "\n")
    assert any("policy reproduction mismatch" in p for p in d0.validate(out)["problems"])


def test_seed_mirror_is_validated(tmp_path):
    out = tmp_path / "run"
    d0.run(out)
    path = out / "game_seeds.json"
    rows = json.loads(path.read_text())
    rows[0]["game_seed"] += 1
    path.write_text(json.dumps(rows))
    assert "D0 seed plan mismatch" in d0.validate(out)["problems"]


@pytest.mark.parametrize("target", ["indexes", "analysis"])
def test_derived_completion_artifacts_are_checked(tmp_path, target):
    out = tmp_path / "run"
    d0.run(out)
    if target == "indexes":
        path = out / "manifest.json"
        data = json.loads(path.read_text())
        data["completed_indexes"][-1] = 99
    else:
        path = out / "analysis.json"
        data = json.loads(path.read_text())
        data["n_unique_trajectories"] += 1
    path.write_text(json.dumps(data))
    assert any(("indexes mismatch" if target == "indexes" else "analysis mismatch") in p for p in d0.validate(out)["problems"])
