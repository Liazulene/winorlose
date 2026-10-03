"""VectorMCTSAgent: dual-utility MCTS for general-sum (non-zero-sum) games.

This is *not* standard zero-sum MCTS.  Because WIN-vs-LOSE is non-zero-sum the
terminal result is the utility *vector* ``(u_black, u_white)`` and every node
along the search path stores both components:

* ``sum_black`` / ``sum_white`` accumulate the respective colour's terminal
  utility over every simulation passing through the node;
* UCT selection at a node uses the average utility of the colour *whose turn it
  is* at that node (``Q_p`` in the spec), i.e. each node's current actor
  maximises their own utility -- no layer-by-layer sign flipping;
* terminal vectors are backed up unchanged along the whole path.

Rollouts sample uniformly among all legal actions (pass included) and are
bounded by the same 100-action cap as real games.  The root picks the most
visited action, breaking ties at random with the agent's fixed-seed stream.
No search-tree reuse across moves and no transposition table (per spec).
"""

from __future__ import annotations

import math
import time

from ..identity import black_white_utilities
from ..game import scoring
from ..game.state import GoState, BLACK, WHITE
from ..spec import COMPUTE_SIMS


def _terminal_utility(state: GoState, identity_black, identity_white, komi: float):
    """Utility vector of a terminal state (winner -> identity rewards)."""
    result = scoring.score_position(state.board, state.size, komi)
    return black_white_utilities(result["winner"], identity_black, identity_white)


class _Node:
    """A search node.

    ``state`` is a full GoState (with its own superko history chain), which
    keeps the tree free of a transposition table and avoids any mismatch
    between superko history and cached nodes.
    """

    __slots__ = ("state", "parent", "action", "children", "untried",
                 "n", "sum_black", "sum_white")

    def __init__(self, state, parent, action):
        self.state = state
        self.parent = parent
        self.action = action  # action that led from parent -> this node
        self.children = {}
        self.untried = list(state.legal_actions()) if not state.is_terminal() else []
        self.n = 0
        self.sum_black = 0.0
        self.sum_white = 0.0


class VectorMCTSAgent:
    algorithm = "vector_mcts"

    def __init__(self, spec, rng, komi: float = 2.5):
        self.spec = spec
        self._rng = rng
        self.simulations = COMPUTE_SIMS[spec.compute_level]
        self.c = math.sqrt(2.0)
        self.komi = komi
        self.last_stats = None

    # -- public API ---------------------------------------------------------
    def select_action(self, state: GoState, identity_black, identity_white) -> int:
        """Run a fresh search from ``state``; return the chosen action id.

        The per-move search record is exposed via ``self.last_stats`` so the
        caller can attach it to the saved game without complicating the agent
        interface (RandomAgent keeps ``last_stats = None``).
        """
        t0 = time.perf_counter()
        root = _Node(state, parent=None, action=None)
        for _ in range(self.simulations):
            self._simulate(root, identity_black, identity_white)

        # Most-visited root action; tie-break with the fixed-seed stream.
        best_visits = -1
        best = []
        for action, child in root.children.items():
            if child.n > best_visits:
                best_visits = child.n
                best = [action]
            elif child.n == best_visits:
                best.append(action)
        chosen = self._rng.choice(best)

        stats = self._root_stats(root, state, chosen)
        stats["search_time_ms"] = (time.perf_counter() - t0) * 1000.0
        self.last_stats = stats
        return chosen

    # -- internals ----------------------------------------------------------
    def _simulate(self, root, identity_black, identity_white):
        node = root
        # Descend while fully expanded and not terminal.
        while node.children and not node.untried and not node.state.is_terminal():
            node = self._select_child(node)
        if node.state.is_terminal():
            u = _terminal_utility(node.state, identity_black, identity_white, self.komi)
            self._backprop(node, u)
            return
        # Expand one untried action (uniform at random).
        idx = self._rng.randrange(len(node.untried))
        action = node.untried.pop(idx)
        child_state = node.state.play(action)
        child = _Node(child_state, parent=node, action=action)
        node.children[action] = child
        if child_state.is_terminal():
            u = _terminal_utility(child_state, identity_black, identity_white, self.komi)
        else:
            u = self._rollout(child_state, identity_black, identity_white)
        self._backprop(child, u)

    def _select_child(self, node):
        """UCT over children maximising the *current node actor's* utility."""
        is_black = node.state.to_play == BLACK
        log_n = math.log(max(1.0, node.n))
        best_score = -float("inf")
        best = []
        for action, child in node.children.items():
            if child.n == 0:
                continue  # defensive: children are backed up before re-selection
            q = (child.sum_black if is_black else child.sum_white) / child.n
            score = q + self.c * math.sqrt(log_n / child.n)
            if score > best_score + 1e-15:
                best_score = score
                best = [action]
            elif abs(score - best_score) <= 1e-15:
                best.append(action)
        return node.children[self._rng.choice(best)]

    def _rollout(self, state, identity_black, identity_white):
        """Uniform random play-out (pass included), bounded by the move cap."""
        s = state
        while not s.is_terminal():
            legal = s.legal_actions()
            s = s.play(legal[self._rng.randrange(len(legal))])
        return _terminal_utility(s, identity_black, identity_white, self.komi)

    def _backprop(self, node, u):
        while node is not None:
            node.n += 1
            node.sum_black += u[0]
            node.sum_white += u[1]
            node = node.parent

    def _root_stats(self, root, root_state, chosen):
        """Per-move search record for the chosen action (spec section 7)."""
        legal = root_state.legal_actions()
        visits = {}
        q_black = {}
        q_white = {}
        for a in legal:
            child = root.children.get(a)
            if child is not None and child.n:
                visits[a] = child.n
                q_black[a] = child.sum_black / child.n
                q_white[a] = child.sum_white / child.n
            else:
                visits[a] = 0
                q_black[a] = None
                q_white[a] = None
        return {
            "root_visit_count": root.n,
            "action_visit_counts": visits,
            "action_q_black": q_black,
            "action_q_white": q_white,
            "simulations_used": self.simulations,
        }
