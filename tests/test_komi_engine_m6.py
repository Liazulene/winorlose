"""M6 per-job komi contract, including real search and fail-closed storage."""
from copy import deepcopy
import json
import random

import pytest

from winai_loseai.agents.vector_mcts import VectorMCTSAgent, _Node, _terminal_utility
from winai_loseai.game import scoring, state as G
from winai_loseai.identity import Identity, black_white_utilities
from winai_loseai.league import replay, runner, runstore
from winai_loseai.spec import AgentSpec


def job(index=0, komi=0.0, pass_min_ply=0, algorithm="random"):
    level = "sims:2" if algorithm == "vector_mcts" else "none"
    return {
        "index": index, "game_seed": 901 + index, "batch_id": "m6_engine_test",
        "black": AgentSpec("b", Identity.WIN, algorithm, level, 1),
        "white": AgentSpec("w", Identity.LOSE, algorithm, level, 2),
        "komi": komi, "pass_min_ply": pass_min_ply,
        "ruleset": scoring.ruleset_name(pass_min_ply, komi),
    }


def cfg(n=4):
    return {"batch_id": "m6_engine_test", "kind": "m6_test", "requested_games": n,
            "batch_seed": 91, "board_size": 5, "komi": None,
            "komis": [2.5, 0.0], "pass_min_plies": [0, 8], "concurrency": 1}


def four_jobs(algorithm="random"):
    return [job(i, k, p, algorithm) for i, (p, k) in enumerate(
        [(0, 2.5), (8, 2.5), (0, 0.0), (8, 0.0)])]


def without_timing(record):
    result = deepcopy(record)
    result.pop("game_wall_ms")
    for move in result["moves"]:
        move.pop("search_time_ms", None)
    return result


def snapshot(path):
    return {p.relative_to(path).as_posix(): p.read_bytes()
            for p in path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("p,k,name", [(0, 2.5, "G0"), (8, 2.5, "G1-pass8"),
                                    (0, 0.0, "G1-k0"), (8, 0.0, "G1-k0-pass8")])
def test_distinct_ruleset_names(p, k, name):
    assert scoring.ruleset_name(p, k) == name


@pytest.mark.parametrize("bad", [True, False, None, "0", float("nan"), float("inf"), -float("inf")])
def test_invalid_komi_refused_before_play_or_scoring(bad):
    j = job()
    j["komi"] = bad
    with pytest.raises(ValueError, match="komi"):
        runner.play_one(j)
    with pytest.raises(ValueError, match="komi"):
        scoring.score_position((0,) * 25, 5, bad)


@pytest.mark.parametrize("ib", list(Identity))
@pytest.mark.parametrize("iw", list(Identity))
def test_empty_zero_komi_draw_and_utilities(ib, iw):
    state = G.GoState.initial().play(25).play(25)
    assert scoring.score_position(state.board, 5, 0) == {
        "black_score": 0.0, "white_score": 0.0, "score_margin": 0.0, "winner": "draw"}
    assert black_white_utilities("draw", ib, iw) == (0, 0)
    assert _terminal_utility(state, ib, iw, 0) == (0, 0)


def test_actual_game_job_komi_overrides_global_and_replays(monkeypatch):
    class AlwaysPass:
        last_stats = None
        def select_action(self, state, *identities):
            return G.pass_action(state.size)
    supplied_komis = []
    def factory(spec, rng, komi):
        supplied_komis.append(komi)
        return AlwaysPass()
    monkeypatch.setattr(runner, "make_agent", factory)
    zero = runner.play_one(job(), komi=2.5)
    baseline = runner.play_one(job(komi=2.5), komi=0)
    assert supplied_komis == [0, 0, 2.5, 2.5]
    assert zero["winner"] == "draw" and zero["komi"] == 0
    assert zero["black_utility"] == zero["white_utility"] == 0
    assert baseline["winner"] == "white" and baseline["komi"] == 2.5
    assert [m["action"] for m in zero["moves"]] == [25, 25]
    assert replay.replay_record(zero)["ok"]
    assert replay.replay_record(baseline)["ok"]


def test_mcts_rollout_and_terminal_tree_use_own_komi():
    spec = job(algorithm="vector_mcts")["black"]
    terminal = G.GoState.initial().play(25).play(25)
    for komi, expected in [(0.0, (0, 0)), (2.5, (-1, -1))]:
        agent = VectorMCTSAgent(spec, random.Random(5), komi=komi)
        assert agent._rollout(terminal, Identity.WIN, Identity.LOSE) == expected
        node = _Node(terminal, None, None)
        agent._simulate(node, Identity.WIN, Identity.LOSE)
        assert (node.sum_black, node.sum_white) == expected
        # The expansion-terminal branch must use the same agent-specific komi.
        node = _Node(G.GoState.initial().play(25), None, None)
        node.untried = [25]
        agent._simulate(node, Identity.WIN, Identity.LOSE)
        assert (node.sum_black, node.sum_white) == expected


def test_real_mcts_game_scores_all_rollouts_with_job_komi(monkeypatch):
    seen = []
    original = scoring.score_position
    def tracked(board, size, komi=2.5):
        seen.append(komi)
        return original(board, size, komi)
    monkeypatch.setattr(scoring, "score_position", tracked)
    monkeypatch.setattr(runner, "score_position", tracked)
    result = runner.play_one(job(algorithm="vector_mcts"), komi=2.5)
    assert len(seen) > result["move_count"]
    assert set(seen) == {0.0}
    assert replay.replay_record(result)["ok"]


@pytest.mark.parametrize("algorithm", ["random", "vector_mcts"])
def test_four_arms_sequential_parallel_and_stream_identical(algorithm):
    jobs = four_jobs(algorithm)
    sequential = runner.run_jobs(jobs, concurrency=1)
    parallel = runner.run_jobs(jobs, concurrency=2)
    streamed = list(runner.stream_jobs(list(reversed(jobs)), concurrency=2))
    assert list(map(without_timing, sequential)) == list(map(without_timing, parallel))
    assert list(map(without_timing, sequential)) == list(map(without_timing, streamed))
    assert [r["komi"] for r in parallel] == [2.5, 2.5, 0, 0]
    assert all(replay.replay_record(r)["ok"] for r in parallel)


@pytest.mark.parametrize("damage", ["komi", "ruleset", "missing_komi", "bool_komi"])
def test_replay_rejects_new_record_komi_tampering(damage):
    record = runner.play_one(job())
    if damage == "komi": record["komi"] = 2.5
    elif damage == "ruleset": record["ruleset"] = "G0"
    elif damage == "missing_komi": del record["komi"]
    else: record["komi"] = False
    assert not replay.replay_record(record)["ok"]


@pytest.mark.parametrize("schema,version", [(1, "winai_loseai-0.1.0"),
                                           (2, "winai_loseai-0.7.0-g1-pass8-estimation")])
def test_legacy_nondefault_komi_record_labels_still_replay(schema, version):
    record = runner.play_one(job())
    record.update(code_version=version, schema_version=schema, ruleset="G0")
    if schema == 1:
        del record["pass_min_ply"], record["ruleset"]
    assert replay.replay_record(record)["ok"]


def test_mixed_komi_plan_roundtrip_and_resume(tmp_path):
    jobs = four_jobs()
    out = tmp_path / "run"
    store = runstore.RunStore(str(out)).start(jobs, cfg())
    for entry, original in zip(store.entries, jobs):
        assert runstore.entry_to_job(entry, cfg()["batch_id"]) == original
    store.write_game(runner.play_one(jobs[0]))
    store.update(runstore.STATUS_INTERRUPTED)
    resumed = runstore.RunStore(str(out)).open_for_resume(jobs, cfg())
    assert resumed.pending_indexes() == [1, 2, 3]
    for j in jobs[1:]: resumed.write_game(runner.play_one(j))
    resumed.finish()
    assert runstore.integrity_problems(str(out)) == []
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["komi"] is None and manifest["komis"] == [2.5, 0.0]
    before = snapshot(out)
    assert not runstore.RunStore(str(out)).open_for_resume(jobs, cfg()).pending_indexes()
    assert snapshot(out) == before


@pytest.mark.parametrize("target", ["record", "metadata", "plan", "manifest"])
def test_resume_rejects_komi_changes_before_any_repair(tmp_path, target):
    jobs = four_jobs()
    out = tmp_path / "run"
    store = runstore.RunStore(str(out)).start(jobs, cfg())
    store.write_game(runner.play_one(jobs[0]))
    if target == "metadata":
        path = out / "games.jsonl"
        record = json.loads(path.read_text())
        record["komi"] = 0
        path.write_text(json.dumps(record) + "\n")
    elif target == "record":
        path = next((out / "games").glob("*.json"))
        record = json.loads(path.read_text()); record["komi"] = 0
        path.write_text(json.dumps(record))
    elif target == "plan":
        path = out / "plan.json"
        entries = json.loads(path.read_text()); entries[0]["komi"] = 0
        path.write_text(json.dumps(entries))
    else:
        path = out / "manifest.json"
        manifest = json.loads(path.read_text()); manifest["komis"] = [2.5]
        path.write_text(json.dumps(manifest))
    with (out / "games.jsonl").open("a") as handle: handle.write('{"torn')
    before = snapshot(out)
    with pytest.raises(runstore.ConfigMismatch):
        runstore.RunStore(str(out)).open_for_resume(jobs, cfg())
    assert snapshot(out) == before


@pytest.mark.parametrize("target", ["record", "metadata"])
def test_integrity_detects_komi_mismatch(tmp_path, target):
    jobs = four_jobs()
    out = tmp_path / "run"
    store = runstore.RunStore(str(out)).start(jobs, cfg())
    for j in jobs: store.write_game(runner.play_one(j))
    store.finish()
    if target == "record":
        path = next((out / "games").glob("*.json"))
        record = json.loads(path.read_text()); record["komi"] = 17
        path.write_text(json.dumps(record))
    else:
        path = out / "games.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["komi"] = 17
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert any("configuration" in p for p in runstore.integrity_problems(str(out)))


def test_write_rejects_wrong_job_komi_without_mutation(tmp_path):
    jobs = four_jobs()
    out = tmp_path / "run"
    store = runstore.RunStore(str(out)).start(jobs, cfg())
    record = runner.play_one(jobs[0]); record["komi"] = 0
    before = snapshot(out)
    with pytest.raises(runstore.ConfigMismatch): store.write_game(record)
    assert snapshot(out) == before
