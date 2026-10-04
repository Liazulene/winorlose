"""Immutable Go state with area rules used by the MVP.

Rules implemented (see ``5x5_mvp_spec.md`` section 3):

* fixed board ``size x size`` (5 for the MVP), Black moves first;
* actions are the ``size*size`` board points (row-major index ``r*size+c``)
  plus one ``pass`` action;
* after playing a stone: first remove opponent groups with no liberties, then
  the move is illegal ("suicide") if the just played group would have no
  liberties afterwards; a capture that gives the played group liberties is
  legal;
* non-pass moves use *situational superko*: a move is illegal if it would
  recreate any ``(board, next_to_play)`` position that already occurred;
* ``pass`` is exempt from superko and legal once ``move_count`` reaches
  ``pass_min_ply`` (default 0 preserves the original G0 rules);
* the game ends on two consecutive passes, or when the action count reaches
  ``4 * size * size`` (safety valve, reported as ``move_limit``).

States are immutable by convention (the board is stored as a tuple and never
mutated).  The rules layer has no dependency on agents.
"""

from __future__ import annotations

import json

# Board / colour codes
EMPTY = 0
BLACK = 1
WHITE = 2

PASS = "pass"  # never a board index; pass_action(size) gives the canonical id


def other(color: int) -> int:
    """Return the opponent colour code."""
    return 3 - color


def move_limit(size: int) -> int:
    """Safety-valve action cap used by the spec: ``4 * size * size``."""
    return 4 * size * size


def pass_action(size: int) -> int:
    """Action id of the pass for a board of this size."""
    return size * size


def is_pass(action: int, size: int) -> bool:
    return action == pass_action(size)


def neighbors(idx: int, size: int):
    """4-neighbour indices of ``idx`` (row-major), omitting off-board ones."""
    r, c = divmod(idx, size)
    out = []
    if r > 0:
        out.append(idx - size)
    if r + 1 < size:
        out.append(idx + size)
    if c > 0:
        out.append(idx - 1)
    if c + 1 < size:
        out.append(idx + 1)
    return out


def group(board, size: int, start: int):
    """Set of indices connected to ``start`` by same-colour adjacency."""
    color = board[start]
    if color == EMPTY:
        return {start}
    seen = set()
    stack = [start]
    while stack:
        i = stack.pop()
        if i in seen:
            continue
        seen.add(i)
        for nb in neighbors(i, size):
            if board[nb] == color and nb not in seen:
                stack.append(nb)
    return seen


def group_liberties(board, size: int, grp) -> set:
    """Set of empty points adjacent to any index of ``grp``."""
    libs = set()
    for i in grp:
        for nb in neighbors(i, size):
            if board[nb] == EMPTY:
                libs.add(nb)
    return libs


def board_after_play(board, size: int, idx: int, color: int):
    """Board tuple after placing ``color`` at ``idx``, or ``None`` if suicide.

    Applies the standard order: remove captured (no-liberty) opponent groups
    first; the move is illegal only if the played group then has no liberties.
    """
    b = list(board)
    b[idx] = color
    opp = other(color)
    for nb in neighbors(idx, size):
        if b[nb] == opp:
            grp = group(b, size, nb)
            if not group_liberties(b, size, grp):
                for p in grp:
                    b[p] = EMPTY
    own = group(b, size, idx)
    if not group_liberties(b, size, own):
        return None
    return tuple(b)


def board_has_dead_group(board, size: int) -> bool:
    """True if any stone group has zero liberties (used by tests/validation)."""
    b = list(board)
    seen = set()
    for idx, val in enumerate(board):
        if val != EMPTY and idx not in seen:
            grp = group(b, size, idx)
            seen.update(grp)
            if not group_liberties(b, size, grp):
                return True
    return False


class GoState:
    """Immutable Go position.

    Attributes
    ----------
    size : int
    board : tuple
        ``size*size`` values from {EMPTY, BLACK, WHITE}.
    to_play : int
        BLACK or WHITE.
    move_count : int
        Number of actions already taken (passes included).
    consecutive_passes : int
        0, 1 or 2.
    pass_min_ply : int
        Minimum number of completed actions before pass becomes legal. Must
        be a non-boolean integer in ``[0, move_limit(size))``. For 8, the
        earliest pass is action 9 and earliest double-pass ending is action 10.
    seen : frozenset
        ``(board, to_play)`` keys of every position that has occurred so far,
        *including* this one.  Used for situational-superko membership tests.
    """

    __slots__ = ("size", "board", "to_play", "move_count",
                 "consecutive_passes", "seen", "pass_min_ply")

    def __init__(self, size, board, to_play, move_count, consecutive_passes, seen,
                 pass_min_ply: int = 0):
        if type(pass_min_ply) is not int:
            raise ValueError("pass_min_ply must be a non-boolean integer")
        if not 0 <= pass_min_ply < move_limit(size):
            raise ValueError(
                f"pass_min_ply must be in [0, {move_limit(size)})"
            )
        self.size = size
        self.board = board
        self.to_play = to_play
        self.move_count = move_count
        self.consecutive_passes = consecutive_passes
        self.seen = seen
        self.pass_min_ply = pass_min_ply

    # -- construction -------------------------------------------------------
    @classmethod
    def initial(cls, size: int = 5, pass_min_ply: int = 0) -> "GoState":
        empty = tuple([EMPTY] * (size * size))
        return cls.from_board(empty, size=size, to_play=BLACK,
                              pass_min_ply=pass_min_ply)

    @classmethod
    def from_board(cls, board, size: int = 5, to_play: int = BLACK,
                   move_count: int = 0, consecutive_passes: int = 0,
                   seen=None, pass_min_ply: int = 0) -> "GoState":
        board = tuple(board)
        n = size * size
        if len(board) != n:
            raise ValueError(f"board must have {n} entries")
        if any(v not in (EMPTY, BLACK, WHITE) for v in board):
            raise ValueError("board values must be EMPTY/BLACK/WHITE")
        if to_play not in (BLACK, WHITE):
            raise ValueError("to_play must be BLACK or WHITE")
        key = (board, to_play)
        base = set(seen) if seen is not None else set()
        base.add(key)
        return cls(size, board, to_play, int(move_count),
                   int(consecutive_passes), frozenset(base), pass_min_ply)

    # -- properties ---------------------------------------------------------
    @property
    def key(self):
        return (self.board, self.to_play)

    @property
    def n_points(self):
        return self.size * self.size

    @property
    def ruleset(self):
        """Explicit name for this pass-rule variant; G0 is unchanged."""
        return "G0" if self.pass_min_ply == 0 else f"G1-pass{self.pass_min_ply}"

    def move_cap(self):
        return move_limit(self.size)

    def is_terminal(self) -> bool:
        return self.consecutive_passes >= 2 or self.move_count >= self.move_cap()

    def terminal_reason(self):
        """Return "double_pass" / "move_limit" or None if not terminal."""
        if self.consecutive_passes >= 2:
            return "double_pass"
        if self.move_count >= self.move_cap():
            return "move_limit"
        return None

    # -- actions ------------------------------------------------------------
    def legal_actions(self):
        """Tuple of legal actions (non-pass first, then the pass action)."""
        return self.legal_report()[0]

    def legal_report(self):
        """``(actions, counts)`` where counts explain excluded non-pass moves.

        ``counts`` = {"occupied": ..., "suicide": ..., "superko": ...}; these
        are the numbers of *empty-candidate* exclusions by each rule, plus the
        number of occupied points.  Used to report superko activity at game
        level (agents always receive only fully legal actions).

        A terminal state has **no** legal actions (empty tuple).
        A nonterminal state with no legal actions raises NoLegalActionError.
        This is an experiment-stopping rules fault, never a forced pass or
        an invented terminal result. Callers must not substitute a score.
        """
        if self.is_terminal():
            return (), {"occupied": 0, "suicide": 0, "superko": 0}
        size = self.size
        actions = []
        counts = {"occupied": 0, "suicide": 0, "superko": 0}
        opp = other(self.to_play)
        for a in range(self.n_points):
            if self.board[a] != EMPTY:
                counts["occupied"] += 1
                continue
            nb = board_after_play(self.board, size, a, self.to_play)
            if nb is None:
                counts["suicide"] += 1
                continue
            if (nb, opp) in self.seen:
                counts["superko"] += 1
                continue
            actions.append(a)
        if self.move_count >= self.pass_min_ply:
            actions.append(pass_action(size))
        if not actions:
            raise NoLegalActionError({
                "size": self.size,
                "board": list(self.board),
                "to_play": self.to_play,
                "move_count": self.move_count,
                "consecutive_passes": self.consecutive_passes,
                "pass_min_ply": self.pass_min_ply,
                "ruleset": self.ruleset,
                "move_cap": self.move_cap(),
                "terminal_reason": self.terminal_reason(),
                "pass_legal": False,
                "exclusions": dict(counts),
                "seen": [[list(board), player]
                         for board, player in sorted(self.seen)],
            })
        return tuple(actions), counts

    def try_play(self, action: int):
        """Return the successor state, or ``None`` if the action is illegal.

        ``pass`` is accepted only at/after ``pass_min_ply`` and is exempt
        from superko; board moves are rejected for occupying a point, suicide,
        or superko. This single-action probe does not enumerate alternatives:
        use legal_report/ legal_actions to detect a no-legal-action fault.
        A terminal state refuses every further action (including ``pass``).
        """
        if self.is_terminal():
            return None
        size = self.size
        if action == pass_action(size):
            if self.move_count < self.pass_min_ply:
                return None
            return self._child(self.board, other(self.to_play), passed=True)
        if action < 0 or action >= self.n_points:
            raise ValueError(f"bad action {action}")
        if self.board[action] != EMPTY:
            return None
        nb = board_after_play(self.board, size, action, self.to_play)
        if nb is None:
            return None
        opp = other(self.to_play)
        if (nb, opp) in self.seen:
            return None
        return self._child(nb, opp, passed=False)

    def play(self, action: int) -> "GoState":
        """Apply a legal action, raising IllegalMove otherwise.

        Once the game is over (double pass or the action cap) no further
        action is accepted and the exception names the terminal reason.
        """
        child = self.try_play(action)
        if child is None:
            reason = self.terminal_reason()
            if reason is not None:
                raise IllegalMove(
                    f"game already over ({reason}): cannot play action {action} "
                    f"on a {self.size}x{self.size} board"
                )
            raise IllegalMove(
                f"illegal action {action} on a {self.size}x{self.size} board"
            )
        return child

    # -- internals ----------------------------------------------------------
    def _child(self, board, to_play, passed: bool) -> "GoState":
        consecutive = self.consecutive_passes + 1 if passed else 0
        seen = self.seen | {(board, to_play)}
        return GoState(self.size, board, to_play, self.move_count + 1,
                       consecutive, seen, self.pass_min_ply)


class IllegalMove(Exception):
    pass


class NoLegalActionError(RuntimeError):
    """Nonterminal rules fault with exact, JSON-safe state diagnostics.

    The sole constructor argument is preserved in Exception.args, so the
    exception and its diagnostics survive process-pool pickling unchanged.
    No score or terminal outcome is attached to this fault.
    """

    def __init__(self, diagnostics: dict):
        self.diagnostics = diagnostics
        super().__init__(diagnostics)

    def __str__(self):
        return "nonterminal state has no legal action: " + json.dumps(
            self.diagnostics, sort_keys=True, separators=(",", ":")
        )


def row_col_to_index(r: int, c: int, size: int) -> int:
    return r * size + c


def index_to_row_col(idx: int, size: int):
    return divmod(idx, size)


def format_board(board, size: int) -> str:
    """Small human-readable board dump (useful in tests / debugging)."""
    glyph = {EMPTY: ".", BLACK: "B", WHITE: "W"}
    rows = []
    for r in range(size):
        rows.append(" ".join(glyph[board[r * size + c]] for c in range(size)))
    return "\n".join(rows)
