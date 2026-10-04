"""G1-pass8 engine boundaries, fail-closed propagation, and replay contract."""
from copy import deepcopy
import hashlib
import json
import pickle
import random

import pytest

from winai_loseai import CODE_VERSION, SCHEMA_VERSION
from winai_loseai.agents.random_agent import RandomAgent
from winai_loseai.agents.vector_mcts import VectorMCTSAgent, _Node
from winai_loseai.game import state as G
from winai_loseai.identity import Identity
from winai_loseai.league import replay, runner
from winai_loseai.spec import AgentSpec


# Captured before modifying the inherited 0.5.0 engine. They cover complete
# moves, legal ordering/counts, RNG choices, root visits, Q vectors, and scores.
G0_GOLDEN = {
    "random": "bb7b6a6476b1e92682ffe610f2c1f0dcf14b882bd4c044331c3f8811ceb539a2",
    "vector_mcts": "83534320aaa3b7b59fa0d8fb333ad3346b343b4c2db797f085178c15f82ab657",
}


def job(algorithm="random"):
    level = "none" if algorithm == "random" else "sims:7"
    return {
        "black": AgentSpec("black", Identity.WIN, algorithm, level, 3),
        "white": AgentSpec("white", Identity.LOSE, algorithm, level, 9),
        "game_seed": 31415, "batch_id": "g0_compat", "index": 0,
    }


def gameplay_record(record):
    record = deepcopy(record)
    for key in ("schema_version", "code_version", "source_fingerprint",
                "python_version", "game_wall_ms", "ruleset", "pass_min_ply"):
        record.pop(key, None)
    for move in record["moves"]:
        move.pop("search_time_ms", None)
    return record


def eight_stones(n=8):
    state = G.GoState.initial(5, pass_min_ply=8)
    for action in range(n):
        state = state.play(action)
    return state


def blocked_state(kind="superko", *, move_count=7):
    size = 3
    if kind == "suicide":
        # One connected white group has two corner liberties. Black cannot
        # fill either without suicide; no dead groups or fabricated terminal.
        board = (0, 2, 2, 2, 2, 2, 2, 2, 0)
    elif kind == "mixed":
        board = (0, 2, 0, 2, 0, 0, 0, 0, 0)
    else:
        board = (0,) * 9
    seen = set()
    if kind != "suicide":
        for action, value in enumerate(board):
            if value == G.EMPTY:
                after = G.board_after_play(board, size, action, G.BLACK)
                if after is not None:
                    seen.add((after, G.WHITE))
    return G.GoState.from_board(board, size=size, move_count=move_count,
                               seen=seen, pass_min_ply=8)


def parent_of_blocked_state():
    """Synthetic superko history allows only action 0, then no white move."""
    empty = (0,) * 9
    child = G.board_after_play(empty, 3, 0, G.BLACK)
    seen = {(G.board_after_play(empty, 3, a, G.BLACK), G.WHITE)
            for a in range(1, 9)}
    for a in range(1, 9):
        after = G.board_after_play(child, 3, a, G.WHITE)
        if after is not None:
            seen.add((after, G.BLACK))
    state = G.GoState.from_board(empty, size=3, move_count=6,
                                seen=seen, pass_min_ply=8)
    assert state.legal_actions() == (0,)
    return state


def mcts():
    return VectorMCTSAgent(job("vector_mcts")["black"], random.Random(123))


@pytest.mark.parametrize("value", [True, False, 8.0, -1, 100, 101, "8", None])
@pytest.mark.parametrize("constructor", ["initial", "from_board", "direct"])
def test_rule_value_is_strict_integer_below_cap(value, constructor):
    with pytest.raises(ValueError, match="pass_min_ply"):
        if constructor == "initial":
            G.GoState.initial(pass_min_ply=value)
        elif constructor == "from_board":
            G.GoState.from_board([0] * 25, pass_min_ply=value)
        else:
            G.GoState(5, (0,) * 25, G.BLACK, 0, 0, frozenset(), value)


@pytest.mark.parametrize("size", [1, 3, 5])
def test_upper_bound_tracks_board_cap(size):
    assert G.GoState.initial(size, G.move_limit(size) - 1).pass_min_ply == G.move_limit(size) - 1
    with pytest.raises(ValueError):
        G.GoState.initial(size, G.move_limit(size))


def test_actual_eight_plies_then_double_pass_and_children_inherit():
    state = G.GoState.initial(pass_min_ply=8)
    for action in range(8):
        assert state.move_count == action
        legal, counts = state.legal_report()
        assert G.pass_action(5) not in legal
        assert state.try_play(G.pass_action(5)) is None
        with pytest.raises(G.IllegalMove):
            state.play(G.pass_action(5))
        assert legal == tuple(sorted(legal))
        assert set(counts) == {"occupied", "suicide", "superko"}
        state = state.play(action)
        assert state.pass_min_ply == 8
        assert state.ruleset == "G1-pass8"
    assert state.move_count == 8
    assert state.legal_actions()[-1] == 25
    state = state.play(25)
    assert state.move_count == 9 and not state.is_terminal()
    assert state.pass_min_ply == 8 and state.consecutive_passes == 1
    state = state.play(25)
    assert state.move_count == 10 and state.terminal_reason() == "double_pass"
    assert state.pass_min_ply == 8


@pytest.mark.parametrize("counter,allowed", [(0, False), (7, False), (8, True), (9, True)])
def test_explicit_off_by_one(counter, allowed):
    state = G.GoState.from_board([0] * 25, move_count=counter, pass_min_ply=8)
    assert (25 in state.legal_actions()) is allowed
    assert (state.try_play(25) is not None) is allowed


@pytest.mark.parametrize("kind", ["double_pass", "move_limit"])
def test_terminal_still_excludes_every_action(kind):
    state = (eight_stones().play(25).play(25) if kind == "double_pass" else
             G.GoState.from_board([0] * 25, move_count=100, pass_min_ply=8))
    assert state.terminal_reason() == kind
    assert state.legal_report() == ((), {"occupied": 0, "suicide": 0, "superko": 0})
    assert all(state.try_play(a) is None for a in range(26))


def test_pass_remains_superko_exempt_and_records_history():
    state = eight_stones()
    seen = state.seen | {(state.board, G.other(state.to_play))}
    state = G.GoState.from_board(state.board, move_count=8, seen=seen, pass_min_ply=8)
    child = state.play(25)
    assert child.key in child.seen
    assert child.seen == seen
    assert child.pass_min_ply == 8


@pytest.mark.parametrize("kind,counts", [
    ("superko", {"occupied": 0, "suicide": 0, "superko": 9}),
    ("suicide", {"occupied": 7, "suicide": 2, "superko": 0}),
    ("mixed", {"occupied": 2, "suicide": 1, "superko": 6}),
])
def test_no_legal_action_is_precise_rule_fault(kind, counts):
    state = blocked_state(kind)
    assert not G.board_has_dead_group(state.board, state.size)
    assert not state.is_terminal() and state.terminal_reason() is None
    for a in range(10):
        assert state.try_play(a) is None
    with pytest.raises(G.NoLegalActionError) as caught:
        state.legal_report()
    diag = caught.value.diagnostics
    assert diag["exclusions"] == counts
    assert diag["board"] == list(state.board)
    assert diag["to_play"] == state.to_play
    assert diag["move_count"] == 7 and diag["pass_min_ply"] == 8
    assert diag["consecutive_passes"] == 0
    assert diag["size"] == 3 and diag["move_cap"] == 36
    assert diag["terminal_reason"] is None and diag["pass_legal"] is False
    assert {(tuple(b), p) for b, p in diag["seen"]} == state.seen
    assert json.loads(str(caught.value).split(": ", 1)[1]) == diag
    cloned = pickle.loads(pickle.dumps(caught.value))
    assert type(cloned) is G.NoLegalActionError and cloned.diagnostics == diag
    assert str(cloned) == str(caught.value)
    # Exactly the same board/history has legal pass once the ban ends.
    unblocked = G.GoState.from_board(state.board, size=3, seen=state.seen,
                                    move_count=8, pass_min_ply=8)
    assert unblocked.legal_actions() == (9,)


@pytest.mark.parametrize("path", ["random", "tree_root", "selection_root", "rollout",
                                  "tree_expansion", "rollout_descendant"])
def test_agents_abort_rule_fault_without_scoring(path, monkeypatch):
    import winai_loseai.agents.vector_mcts as module
    def no_scoring(*args):
        pytest.fail("a nonterminal fault must not be assigned a terminal utility")
    monkeypatch.setattr(module, "_terminal_utility", no_scoring)
    state = blocked_state()
    agent = mcts()
    with pytest.raises(G.NoLegalActionError):
        if path == "random":
            RandomAgent(job()["black"], random.Random(1)).select_action(state, Identity.WIN, Identity.LOSE)
        elif path == "tree_root":
            _Node(state, None, None)
        elif path == "selection_root":
            agent.select_action(state, Identity.WIN, Identity.LOSE)
        elif path == "rollout":
            agent._rollout(state, Identity.WIN, Identity.LOSE)
        elif path == "tree_expansion":
            root = _Node(parent_of_blocked_state(), None, None)
            agent._simulate(root, Identity.WIN, Identity.LOSE)
        else:
            agent._rollout(parent_of_blocked_state(), Identity.WIN, Identity.LOSE)
    assert agent.last_stats is None


def test_tree_and_rollout_use_rule_at_every_ply(monkeypatch):
    calls = []
    original = G.GoState.legal_actions
    def checked(state):
        legal = original(state)
        calls.append(state.move_count)
        assert state.pass_min_ply == 8
        if not state.is_terminal():
            assert (G.pass_action(state.size) in legal) == (state.move_count >= 8)
        return legal
    monkeypatch.setattr(G.GoState, "legal_actions", checked)
    agent = mcts()
    assert agent.select_action(G.GoState.initial(pass_min_ply=8), Identity.WIN, Identity.LOSE) != 25
    assert 25 not in agent.last_stats["action_visit_counts"]
    assert any(n < 8 for n in calls) and any(n >= 8 for n in calls)
    agent.select_action(eight_stones(), Identity.WIN, Identity.LOSE)
    assert 25 in agent.last_stats["action_visit_counts"]


def test_runner_and_process_pool_propagate_fault():
    blocked_job = {**job(), "pass_min_ply": 1}
    # 1x1 has no nonsuicidal board move; this isolates the runner failure path.
    with pytest.raises(G.NoLegalActionError) as caught:
        runner.play_one(blocked_job, board_size=1)
    assert caught.value.diagnostics["exclusions"]["suicide"] == 1
    with pytest.raises(G.NoLegalActionError):
        runner.run_jobs([blocked_job, {**blocked_job, "index": 1}], concurrency=2, board_size=1)


@pytest.mark.parametrize("algorithm", ["random", "vector_mcts"])
def test_g0_default_and_explicit_reproduce_legacy_golden(algorithm):
    default = runner.play_one(job(algorithm), board_size=3)
    explicit = runner.play_one({**job(algorithm), "pass_min_ply": 0}, board_size=3)
    assert gameplay_record(default) == gameplay_record(explicit)
    digest = hashlib.sha256(json.dumps(gameplay_record(explicit), sort_keys=True).encode()).hexdigest()
    assert digest == G0_GOLDEN[algorithm]
    assert default["schema_version"] == SCHEMA_VERSION == 2
    assert default["code_version"] == CODE_VERSION == "winai_loseai-0.8.0-komi-pass-pilot"
    assert default["ruleset"] == "G0" and default["pass_min_ply"] == 0


@pytest.mark.parametrize("value", [True, 8.0, -1, 100, "8"])
def test_runner_rejects_invalid_rule(value):
    with pytest.raises(ValueError, match="pass_min_ply"):
        runner.play_one({**job(), "pass_min_ply": value})


def test_runner_rejects_mismatched_ruleset():
    with pytest.raises(ValueError, match="ruleset"):
        runner.play_one({**job(), "pass_min_ply": 8, "ruleset": "G0"})


@pytest.fixture
def pass8_record(monkeypatch):
    class EightThenPass:
        last_stats = None
        def select_action(self, state, *identities):
            return state.move_count if state.move_count < 8 else G.pass_action(state.size)
    monkeypatch.setattr(runner, "make_agent", lambda *args: EightThenPass())
    record = runner.play_one({**job(), "pass_min_ply": 8})
    assert record["move_count"] == 10
    assert [m["action"] for m in record["moves"]] == list(range(8)) + [25, 25]
    assert record["ruleset"] == "G1-pass8" and record["pass_min_ply"] == 8
    return record


def test_new_record_replays_with_rules(pass8_record):
    assert replay.replay_record(pass8_record) == {"ok": True, "problems": []}


@pytest.mark.parametrize("damage", ["missing_pass", "missing_ruleset", "bool_pass", "float_pass",
                                    "negative_pass", "beyond_cap", "wrong_ruleset", "wrong_threshold",
                                    "old_schema", "bool_schema", "float_schema", "future_schema",
                                    "missing_schema", "early_pass"])
def test_replay_rejects_rule_tampering(pass8_record, damage):
    record = deepcopy(pass8_record)
    if damage == "missing_pass":
        del record["pass_min_ply"]
    elif damage == "missing_ruleset":
        del record["ruleset"]
    elif damage == "missing_schema":
        del record["schema_version"]
    elif damage == "early_pass":
        record["moves"][7]["action"] = 25
        record["moves"][7]["is_pass"] = True
    else:
        key, value = {
            "bool_pass": ("pass_min_ply", True), "float_pass": ("pass_min_ply", 8.0),
            "negative_pass": ("pass_min_ply", -1), "beyond_cap": ("pass_min_ply", 100),
            "wrong_ruleset": ("ruleset", "G0"), "wrong_threshold": ("pass_min_ply", 7),
            "old_schema": ("schema_version", 1), "bool_schema": ("schema_version", True),
            "float_schema": ("schema_version", 2.0), "future_schema": ("schema_version", 3),
        }[damage]
        record[key] = value
    result = replay.replay_record(record)
    assert not result["ok"] and result["problems"]
    if damage == "early_pass":
        assert any("illegal replay move 25 at move #8" in p for p in result["problems"])


@pytest.mark.parametrize("metadata", [{}, {"pass_min_ply": 0, "ruleset": "G0"}])
def test_legacy_schema_one_defaults_only_to_g0(metadata):
    record = runner.play_one(job(), board_size=3)
    record["schema_version"] = 1
    del record["pass_min_ply"], record["ruleset"]
    record.update(metadata)
    assert replay.replay_record(record)["ok"]


@pytest.mark.parametrize("metadata", [{"pass_min_ply": 8}, {"ruleset": "G1-pass8"},
                                      {"pass_min_ply": False}, {"pass_min_ply": 0.0}])
def test_schema_one_cannot_smuggle_rule_variant(metadata):
    record = runner.play_one(job(), board_size=3)
    record["schema_version"] = 1
    del record["pass_min_ply"], record["ruleset"]
    record.update(metadata)
    assert not replay.replay_record(record)["ok"]


def test_replay_nolegal_fault_never_scores(pass8_record, monkeypatch):
    def blocked_initial(*args, **kwargs):
        return G.GoState.from_board((0, 2, 2, 2, 2, 2, 2, 2, 0), size=3, pass_min_ply=8)
    monkeypatch.setattr(G.GoState, "initial", blocked_initial)
    def no_scoring(*args):
        pytest.fail("replay must not invent a terminal score for a rule fault")
    monkeypatch.setattr(replay, "score_position", no_scoring)
    result = replay.replay_record(pass8_record)
    assert not result["ok"]
    assert result["rule_fault"]["terminal_reason"] is None
    assert result["rule_fault"]["exclusions"] == {"occupied": 7, "suicide": 2, "superko": 0}


@pytest.mark.parametrize("has_fault", [False, True])
def test_replay_truncated_before_terminal_never_scores(pass8_record, monkeypatch, has_fault):
    record = deepcopy(pass8_record)
    record["moves"] = []
    record["termination_reason"] = None
    record["move_count"] = 0
    if has_fault:
        monkeypatch.setattr(G.GoState, "initial", lambda *a, **k:
                            G.GoState.from_board((0, 2, 2, 2, 2, 2, 2, 2, 0),
                                                 size=3, pass_min_ply=8))
    monkeypatch.setattr(replay, "score_position", lambda *a:
                        pytest.fail("truncated nonterminal replay must not be scored"))
    result = replay.replay_record(record)
    assert not result["ok"]
    if has_fault:
        assert result["rule_fault"]["terminal_reason"] is None
    else:
        assert any("terminal state" in p for p in result["problems"])
