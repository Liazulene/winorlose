"""Agent behaviour tests: RandomAgent and VectorMCTSAgent."""

from __future__ import annotations

import unittest

from winai_loseai.game.state import GoState, BLACK, WHITE, pass_action
from winai_loseai.identity import Identity
from winai_loseai.rng import make_game_rng
from winai_loseai.agents.random_agent import RandomAgent
from winai_loseai.agents.vector_mcts import VectorMCTSAgent, _Node

from tests._helpers import random_spec_, mcts_spec, board_of, state_of

SIZE = 5
PASS = pass_action(SIZE)


class TestRandomAgent(unittest.TestCase):
    def test_samples_only_legal_actions(self):
        rng = make_game_rng(1, "black", 0)
        spec = random_spec_(Identity.WIN)
        agent = RandomAgent(spec, rng)
        s = GoState.initial(SIZE)
        legal = set(s.legal_actions())
        for _ in range(200):
            a = agent.select_action(s, Identity.WIN, Identity.LOSE)
            self.assertIn(a, legal)

    def test_identity_does_not_change_moves(self):
        # Two RandomAgents with identical seed but different identities must
        # produce the same move sequence (identity only affects utilities).
        rngs = [make_game_rng(42, "black", 7) for _ in range(2)]
        agents = [RandomAgent(random_spec_(Identity.WIN, seed=7), rngs[0]),
                  RandomAgent(random_spec_(Identity.LOSE, seed=7), rngs[1])]
        s0 = GoState.initial(SIZE)
        s1 = GoState.initial(SIZE)
        for _ in range(40):
            if s0.is_terminal() or s1.is_terminal():
                break  # no further actions are legal after the game ends
            a0 = agents[0].select_action(s0, Identity.WIN, Identity.LOSE)
            a1 = agents[1].select_action(s1, Identity.LOSE, Identity.WIN)
            self.assertEqual(a0, a1)
            s0 = s0.play(a0)
            s1 = s1.play(a1)
        self.assertEqual(s0.is_terminal(), s1.is_terminal())


class _UctFixture:
    """White-box fixture that pins down the children stats of a search node.

    The two children are given equal visit counts and a large parent visit
    count, so the exploration bonus is identical and pure ``Q`` determines the
    choice -- exactly what lets us verify *whose* Q the node uses.
    """

    def __init__(self):
        spec = mcts_spec(Identity.WIN, seed=3, level="shallow")
        self.agent = VectorMCTSAgent(spec, make_game_rng(5, "black", 3))

    def parent(self, to_play):
        node = _Node(state_of(board_of(), to_play=to_play), None, None)
        node.n = 1000
        node.untried = []
        return node

    def add_children(self, node, specs):
        """``specs`` = list of (action, q_black, q_white); returns dict."""
        children = {}
        for action, qb, qw in specs:
            ch = object.__new__(_Node)
            ch.state = node.state
            ch.parent = node
            ch.action = action
            ch.children = {}
            ch.untried = []
            ch.n = 50
            ch.sum_black = qb * ch.n
            ch.sum_white = qw * ch.n
            children[action] = ch
        node.children = children
        return children


class TestUctMaximisesOwnUtility(unittest.TestCase):
    """Issue #7: a node selects with the *current actor's own* average Q.

    Black-to-move nodes must pick by ``Q_black``, white-to-move nodes by
    ``Q_white`` -- and there must be no zero-sum sign flipping (a layer that
    maximises the negated opponent utility would pick a different child here).
    """

    def test_black_node_uses_q_black_not_q_white(self):
        f = _UctFixture()
        node = f.parent(BLACK)
        # cA best for black but worst for white; cB vice-versa.
        f.add_children(node, [(0, 0.9, 0.2), (1, 0.2, 0.9)])
        self.assertIs(f.agent._select_child(node), node.children[0])

    def test_black_node_does_not_negate(self):
        # If the code maximised -Q (own or opponent) it would pick cB here.
        f = _UctFixture()
        node = f.parent(BLACK)
        f.add_children(node, [(0, 0.9, 0.9), (1, 0.1, 0.1)])
        self.assertIs(f.agent._select_child(node), node.children[0])

    def test_white_node_uses_q_white_not_q_black(self):
        f = _UctFixture()
        node = f.parent(WHITE)
        # cA best for white, cB best for black.
        f.add_children(node, [(0, 0.2, 0.9), (1, 0.9, 0.1)])
        self.assertIs(f.agent._select_child(node), node.children[0])

    def test_white_node_does_not_negate(self):
        f = _UctFixture()
        node = f.parent(WHITE)
        f.add_children(node, [(0, 0.9, 0.9), (1, 0.1, 0.1)])
        self.assertIs(f.agent._select_child(node), node.children[0])

    def test_conflicting_preferences_each_side_picks_own_best(self):
        # cA favours black, cB favours white: the current actor must pick its
        # own favourite, not the opponent's.
        f = _UctFixture()
        black = f.parent(BLACK)
        white = f.parent(WHITE)
        f.add_children(black, [(0, 0.9, 0.1), (1, 0.2, 0.8)])
        f.add_children(white, [(0, 0.9, 0.1), (1, 0.2, 0.8)])
        self.assertIs(f.agent._select_child(black), black.children[0])
        self.assertIs(f.agent._select_child(white), white.children[1])


class TestVectorMCTSAgent(unittest.TestCase):
    def _make_agent(self, seed=3, game_seed=5):
        spec = mcts_spec(Identity.WIN, seed=seed, level="shallow")
        rng = make_game_rng(game_seed, "black", seed)
        return VectorMCTSAgent(spec, rng), spec

    def test_returns_legal_action_and_records_visits(self):
        agent, spec = self._make_agent()
        s = GoState.initial(SIZE)
        a = agent.select_action(s, Identity.WIN, Identity.LOSE)
        self.assertIn(a, s.legal_actions())
        st = agent.last_stats
        self.assertEqual(st["simulations_used"], 64)
        self.assertEqual(st["root_visit_count"], 64)
        total_visits = sum(st["action_visit_counts"].values())
        self.assertEqual(total_visits, 64)
        for v in list(st["action_q_black"].values()) + list(st["action_q_white"].values()):
            if v is not None:
                self.assertTrue(-1.0 - 1e-9 <= v <= 1.0 + 1e-9)

    def test_deterministic_given_seed(self):
        results = []
        for _ in range(2):
            agent, _ = self._make_agent(game_seed=5)
            s = GoState.initial(SIZE)
            a = agent.select_action(s, Identity.WIN, Identity.LOSE)
            st = agent.last_stats
            results.append((a, st["action_visit_counts"]))
        self.assertEqual(results[0], results[1])

    def test_white_actor_maximises_white_utility(self):
        # A white-to-move root uses white's own utility in UCT; the search
        # must still select only legal moves for white.
        agent, _ = self._make_agent()
        s = GoState.initial(SIZE).play(0)  # black played first -> white to move
        self.assertEqual(s.to_play, WHITE)
        a = agent.select_action(s, Identity.WIN, Identity.WIN)
        self.assertIn(a, s.legal_actions())


if __name__ == "__main__":
    unittest.main()
