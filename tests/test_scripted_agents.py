"""Independent D0 agent checks; these tests never write experiment artifacts.

Literal route/score expectations are analytical oracles, not values obtained
by rerunning the same policy implementation. Identity repetitions below are
deterministic regression checks, not additional statistical observations.
"""

import random
from itertools import product

import pytest

from winai_loseai.agents.factory import make_agent
from winai_loseai.agents.scripted import (
    AlwaysPassAgent,
    GreedyAreaAgent,
    OneStoneThenPassAgent,
)
from winai_loseai.game.scoring import score_position
from winai_loseai.game.state import (
    BLACK,
    EMPTY,
    WHITE,
    GoState,
    board_has_dead_group,
)
from winai_loseai.identity import Identity, black_white_utilities
from winai_loseai.spec import AgentSpec


SIZE = 5
PASS = 25
AP = "always_pass"
OS = "one_stone_then_pass"
GREEDY = "greedy_area"
ALGORITHMS = (AP, OS, GREEDY)
IDENTITIES = tuple(product((Identity.WIN, Identity.LOSE), repeat=2))


def _spec(algorithm, identity=Identity.WIN, seed=0):
    return AgentSpec(
        agent_id=f"test-{algorithm}-{identity.value}-{seed}",
        identity=identity,
        algorithm=algorithm,
        compute_level="none",
        seed=seed,
    )


def _agent(algorithm, identity=Identity.WIN, seed=0, rng=None):
    return make_agent(_spec(algorithm, identity, seed), rng, komi=2.5)


def _play(black_algorithm, white_algorithm, identities=IDENTITIES[0], seed=0):
    """Small test harness independent of the production batch runner."""
    ib, iw = identities
    agents = {
        BLACK: _agent(black_algorithm, ib, seed, random.Random(seed)),
        WHITE: _agent(white_algorithm, iw, seed + 1, random.Random(seed + 1)),
    }
    state = GoState.initial(SIZE)
    actions = []
    while not state.is_terminal():
        action = agents[state.to_play].select_action(state, ib, iw)
        assert action in state.legal_actions()
        actions.append(action)
        state = state.play(action)
        assert not board_has_dead_group(state.board, SIZE)
    assert state.move_count <= 100
    return tuple(actions), state, score_position(state.board, SIZE, 2.5)


@pytest.mark.parametrize(
    "algorithm,expected_class",
    [(AP, AlwaysPassAgent), (OS, OneStoneThenPassAgent), (GREEDY, GreedyAreaAgent)],
)
def test_factory_dispatches_exact_scripted_class(algorithm, expected_class):
    agent = _agent(algorithm)
    assert type(agent) is expected_class
    assert agent.algorithm == algorithm
    assert agent.last_stats is None


@pytest.mark.parametrize(
    "black,white,expected_actions,expected_scores",
    [
        (AP, AP, (25, 25), (0.0, 2.5)),
        (OS, AP, (0, 25, 25), (25.0, 2.5)),
        (GREEDY, AP, (0, 25, 25), (25.0, 2.5)),
        (AP, OS, (25, 0, 25, 25), (0.0, 27.5)),
        (AP, GREEDY, (25, 0, 25, 25), (0.0, 27.5)),
        (OS, OS, (0, 1, 25, 25), (1.0, 3.5)),
        (OS, GREEDY, (0, 1, 25, 5, 25, 25), (0.0, 27.5)),
        (GREEDY, OS, (0, 1, 2, 25, 6, 25, 25), (25.0, 2.5)),
    ],
)
def test_literal_routes_and_scores(black, white, expected_actions, expected_scores):
    actions, state, scored = _play(black, white)
    assert actions == expected_actions
    assert state.move_count == len(expected_actions)
    assert state.terminal_reason() == "double_pass"
    assert (scored["black_score"], scored["white_score"]) == expected_scores
    assert scored["score_margin"] == expected_scores[0] - expected_scores[1]


@pytest.mark.parametrize("placement", range(25))
def test_every_isolated_black_placement_then_passes_scores_full_area(placement):
    state = GoState.initial(SIZE).play(placement).play(PASS).play(PASS)
    assert state.terminal_reason() == "double_pass"
    assert state.move_count == 3
    assert state.board.count(BLACK) == 1
    assert state.board.count(WHITE) == 0
    assert score_position(state.board, SIZE, 2.5) == {
        "black_score": 25.0,
        "white_score": 2.5,
        "score_margin": 22.5,
        "winner": "black",
    }
    assert black_white_utilities("black", Identity.WIN, Identity.LOSE) == (1, 1)


def test_empty_double_pass_has_exact_identity_utility_mapping():
    expected = {
        (Identity.WIN, Identity.WIN): (-1, 1),
        (Identity.WIN, Identity.LOSE): (-1, -1),
        (Identity.LOSE, Identity.WIN): (1, 1),
        (Identity.LOSE, Identity.LOSE): (1, -1),
    }
    for identities, utility in expected.items():
        actions, _, scored = _play(AP, AP, identities)
        assert actions == (25, 25)
        assert scored["winner"] == "white"
        assert scored["score_margin"] == -2.5
        assert black_white_utilities(scored["winner"], *identities) == utility


@pytest.mark.parametrize("black,white", tuple(product(ALGORITHMS, repeat=2)))
def test_complete_policy_trajectory_is_identity_and_seed_independent(black, white):
    baseline = None
    for seed, identities in enumerate(IDENTITIES, start=137):
        actions, state, scored = _play(black, white, identities, seed)
        semantic_result = (actions, state.board, state.terminal_reason(), scored)
        if baseline is None:
            baseline = semantic_result
        assert semantic_result == baseline
        ub, uw = black_white_utilities(scored["winner"], *identities)
        assert ub == (1 if (scored["winner"] == "black") ==
                      (identities[0] == Identity.WIN) else -1)
        assert uw == (1 if (scored["winner"] == "white") ==
                      (identities[1] == Identity.WIN) else -1)


def test_one_stone_remembers_placement_after_its_capture():
    agent = _agent(OS)
    state = GoState.initial(SIZE)
    assert agent.select_action(state, Identity.WIN, Identity.WIN) == 0
    state = state.play(0).play(1)
    assert agent.select_action(state, Identity.WIN, Identity.WIN) == PASS
    state = state.play(PASS).play(5)
    assert state.board.count(BLACK) == 0
    assert agent.has_placed
    assert len(state.legal_actions()) > 1
    assert agent.select_action(state, Identity.WIN, Identity.WIN) == PASS


def test_one_stone_state_is_not_shared_between_game_instances():
    first = _agent(OS)
    second = _agent(OS)
    initial = GoState.initial(SIZE)
    assert first.select_action(initial, Identity.LOSE, Identity.WIN) == 0
    assert first.has_placed
    assert not second.has_placed
    assert second.select_action(initial, Identity.WIN, Identity.LOSE) == 0


def test_one_stone_no_placement_pass_preserves_entitlement():
    # Two separated liberties leave every black placement suicidal. After
    # white fills one hole, black can capture the white group in the other.
    board = [WHITE] * 25
    board[6] = board[18] = EMPTY
    state = GoState.from_board(board, size=SIZE, to_play=BLACK)
    assert not board_has_dead_group(state.board, SIZE)
    assert state.legal_actions() == (PASS,)
    agent = _agent(OS)
    assert agent.select_action(state, Identity.LOSE, Identity.LOSE) == PASS
    assert not agent.has_placed
    state = state.play(PASS).play(6)
    assert 18 in state.legal_actions()
    assert agent.select_action(state, Identity.LOSE, Identity.LOSE) == 18
    assert agent.has_placed
    captured = state.play(18)
    assert captured.board.count(WHITE) == 0
    assert captured.board.count(BLACK) == 1


def test_one_stone_skips_occupied_and_suicidal_low_points():
    state = GoState.initial(SIZE).play(PASS).play(1).play(PASS).play(5)
    assert state.to_play == BLACK
    assert 0 not in state.legal_actions()  # Suicide between the white stones.
    assert 1 not in state.legal_actions()  # Occupied.
    assert _agent(OS).select_action(state, Identity.WIN, Identity.WIN) == 2


@pytest.mark.parametrize("algorithm", ALGORITHMS)
@pytest.mark.parametrize("termination", ("double_pass", "move_limit"))
def test_scripted_agents_refuse_terminal_states(algorithm, termination):
    if termination == "double_pass":
        state = GoState.initial(SIZE).play(PASS).play(PASS)
    else:
        state = GoState.from_board([EMPTY] * 25, size=SIZE, move_count=100)
    assert state.terminal_reason() == termination
    with pytest.raises(ValueError, match="terminal"):
        _agent(algorithm).select_action(state, Identity.WIN, Identity.LOSE)


@pytest.mark.parametrize("color", (BLACK, WHITE))
def test_greedy_placement_ties_use_lowest_legal_index(color):
    state = GoState.initial(SIZE)
    if color == WHITE:
        state = state.play(PASS)
    assert state.to_play == color
    assert _agent(GREEDY).select_action(state, Identity.LOSE, Identity.LOSE) == 0


@pytest.mark.parametrize("color", (BLACK, WHITE))
def test_greedy_prefers_terminal_pass_when_area_tied(color):
    state = GoState.initial(SIZE)
    if color == BLACK:
        state = state.play(0).play(PASS)
    else:
        state = state.play(PASS).play(0).play(PASS)
    assert state.to_play == color
    assert len(state.legal_actions()) > 1
    action = _agent(GREEDY).select_action(state, Identity.WIN, Identity.WIN)
    assert action == PASS
    assert state.play(action).terminal_reason() == "double_pass"


@pytest.mark.parametrize(
    "prefix,color,expected_action,expected_scores",
    [
        ((0, 1, 25), WHITE, 5, (0.0, 27.5)),
        ((0, 1, 2, 25), BLACK, 6, (25.0, 2.5)),
    ],
)
def test_greedy_uses_actor_color_and_selects_capture(
        prefix, color, expected_action, expected_scores):
    state = GoState.initial(SIZE)
    for action in prefix:
        state = state.play(action)
    assert state.to_play == color
    for identities in IDENTITIES:
        action = _agent(GREEDY).select_action(state, *identities)
        assert action == expected_action
        scored = score_position(state.play(action).board, SIZE, 2.5)
        assert (scored["black_score"], scored["white_score"]) == expected_scores


@pytest.mark.parametrize("algorithm", (OS, GREEDY))
def test_superko_excludes_preferred_lowest_placement(algorithm):
    # Synthetic history isolates the action filter; it is not claimed to be
    # a trajectory reachable from an empty board.
    initial = GoState.initial(SIZE)
    forbidden_key = initial.play(0).key
    state = GoState.from_board(initial.board, size=SIZE, seen={forbidden_key})
    assert state.legal_report()[1]["superko"] == 1
    assert 0 not in state.legal_actions()
    assert _agent(algorithm).select_action(state, Identity.WIN, Identity.LOSE) == 1


def test_greedy_respects_actual_ko_and_suicide_exclusions():
    board = [EMPTY] * 25
    for point in (7, 17, 13):
        board[point] = BLACK
    for point in (12, 6, 16, 10):
        board[point] = WHITE
    state = GoState.from_board(board, size=SIZE, to_play=BLACK).play(11)
    legal, counts = state.legal_report()
    assert counts["superko"] > 0
    assert 12 not in legal
    action = _agent(GREEDY).select_action(state, Identity.WIN, Identity.LOSE)
    assert action in legal
    assert action != 12
    assert not board_has_dead_group(state.play(action).board, SIZE)


def test_greedy_passes_when_every_placement_is_suicide():
    board = [WHITE] * 25
    board[6] = board[18] = EMPTY
    state = GoState.from_board(board, size=SIZE, to_play=BLACK)
    legal, counts = state.legal_report()
    assert counts["suicide"] == 2
    assert legal == (PASS,)
    assert _agent(GREEDY).select_action(state, Identity.WIN, Identity.WIN) == PASS


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_scripted_agents_do_not_read_rng(algorithm):
    class ForbiddenRng:
        def __getattr__(self, name):
            raise AssertionError(f"deterministic policy read RNG: {name}")

    agent = _agent(algorithm, rng=ForbiddenRng())
    assert agent.select_action(GoState.initial(SIZE), Identity.WIN, Identity.WIN) in (
        0, PASS
    )


@pytest.mark.parametrize("color", (BLACK, WHITE))
def test_greedy_last_ply_uses_current_actor_and_move_limit(color):
    state = GoState.from_board([EMPTY] * 25, size=SIZE, to_play=color, move_count=99)
    action = _agent(GREEDY).select_action(state, Identity.LOSE, Identity.LOSE)
    assert action == 0
    child = state.play(action)
    assert child.terminal_reason() == "move_limit"
    assert child.move_count == 100
    assert child.board[0] == color


@pytest.mark.parametrize("seed", range(50))
@pytest.mark.parametrize("white_identity", (Identity.WIN, Identity.LOSE))
def test_black_always_pass_guarantee_against_sampled_white_responses(seed, white_identity):
    rng = random.Random(seed)
    black = _agent(AP, Identity.LOSE)
    state = GoState.initial(SIZE)
    while not state.is_terminal():
        if state.to_play == BLACK:
            action = black.select_action(state, Identity.LOSE, white_identity)
            assert action == PASS
        else:
            action = rng.choice(state.legal_actions())
        state = state.play(action)
        scored = score_position(state.board, SIZE, 2.5)
        assert state.board.count(BLACK) == 0
        assert scored["black_score"] == 0
        assert scored["white_score"] == (27.5 if WHITE in state.board else 2.5)
        assert scored["winner"] == "white"
        assert black_white_utilities("white", Identity.LOSE, white_identity) == (1, 1 if white_identity == Identity.WIN else -1)
        assert not board_has_dead_group(state.board, SIZE)
    assert state.terminal_reason() == "double_pass"
    assert state.move_count <= 50


def test_black_always_pass_worst_case_white_placements_end_at_fifty_plies():
    black = _agent(AP, Identity.LOSE)
    state = GoState.initial(SIZE)
    while not state.is_terminal():
        if state.to_play == BLACK:
            action = black.select_action(state, Identity.LOSE, Identity.WIN)
        else:
            placements = [a for a in state.legal_actions() if a != PASS]
            action = min(placements) if placements else PASS
        state = state.play(action)
    assert state.move_count == 50
    assert state.terminal_reason() == "double_pass"
    assert state.board.count(BLACK) == 0
    assert state.board.count(WHITE) == 24
    assert score_position(state.board, SIZE, 2.5)["score_margin"] == -27.5
