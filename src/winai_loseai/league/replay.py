"""Independent replay + validation of a saved game record.

Replays every recorded action from the empty board and cross-checks:

* per-move ``index``, ``color`` (matches the player to move), ``action``
  legality, ``is_pass`` and ``legal_action_count``;
* terminal ``termination_reason`` and ``move_count``;
* the recorded ``final_board`` cell-by-cell against the replayed board;
* scores, ``winner`` and both players' utilities.

Every saved record now stores ``final_board``; older records without it are
still validated on the remaining fields.

Schema 1 is the historical G0 format and may omit rule metadata. Schema 2
requires explicit, matching ``ruleset`` and ``pass_min_ply`` fields. Replaying
a rule variant as G0 must never silently accept an early pass.
"""

from __future__ import annotations

from ..identity import black_white_utilities, coerce_identity
from ..game import state as G
from ..game.scoring import score_position


def _expected_color(player_code: int) -> str:
    return "black" if player_code == G.BLACK else "white"


def replay_record(record: dict) -> dict:
    """Replay ``record``; return ``{"ok": bool, "problems": [...]}``."""
    problems = []
    size = int(record["board_size"])
    komi = float(record["komi"])
    schema = record.get("schema_version")
    if type(schema) is not int or schema not in (1, 2):
        return {"ok": False, "problems": ["missing or unsupported schema_version"]}
    if schema == 2 and not {"ruleset", "pass_min_ply"} <= record.keys():
        return {"ok": False, "problems": ["schema 2 requires ruleset and pass_min_ply"]}
    pass_min_ply = record.get("pass_min_ply", 0)
    try:
        state = G.GoState.initial(size, pass_min_ply=pass_min_ply)
    except ValueError as exc:
        return {"ok": False, "problems": [f"invalid rule metadata: {exc}"]}
    if schema == 1 and pass_min_ply != 0:
        return {"ok": False, "problems": ["schema 1 supports G0 / pass_min_ply=0 only"]}
    if record.get("ruleset", "G0") != state.ruleset:
        return {"ok": False, "problems": ["ruleset does not match pass_min_ply"]}
    pass_id = G.pass_action(size)

    for move in record.get("moves", []):
        action = int(move["action"])
        idx = state.move_count + 1
        if move.get("index") != idx:
            problems.append(f"move index mismatch at #{idx}")
            break

        # colour of the side about to move must match the recorded label
        exp_color = _expected_color(state.to_play)
        if move.get("color") != exp_color:
            problems.append(
                f"color mismatch at move #{idx}: recorded={move.get('color')!r} "
                f"expected={exp_color!r}"
            )

        exp_pass = bool(action == pass_id)
        if bool(move.get("is_pass")) != exp_pass:
            problems.append(
                f"is_pass mismatch at move #{idx}: recorded={move.get('is_pass')} "
                f"expected={exp_pass}"
            )

        try:
            n_legal = len(state.legal_actions())
        except G.NoLegalActionError as exc:
            # An unplayable nonterminal state is a failed replay, with its
            # exact fault preserved. Do not turn the board into a score.
            return {"ok": False, "problems": problems + [str(exc)],
                    "rule_fault": exc.diagnostics}
        if "legal_action_count" in move:
            if int(move["legal_action_count"]) != n_legal:
                problems.append(
                    f"legal_action_count mismatch at move #{idx}: "
                    f"recorded={move['legal_action_count']} replayed={n_legal}"
                )

        child = state.try_play(action)
        if child is None:
            problems.append(
                f"illegal replay move {action} at move #{idx}"
            )
            return {"ok": False, "problems": problems}
        state = child

    # Terminal bookkeeping checks.
    reason = state.terminal_reason()
    if reason is None:
        # A truncated record could end exactly at an unplayable state. Check
        # that case too, and never score any nonterminal replay as a game.
        try:
            state.legal_report()
        except G.NoLegalActionError as exc:
            return {"ok": False, "problems": problems + [str(exc)],
                    "rule_fault": exc.diagnostics}
        return {"ok": False, "problems": problems + ["replay did not reach a terminal state"]}
    if reason != record["termination_reason"]:
        problems.append(
            f"termination reason mismatch: recorded={record['termination_reason']} "
            f"replayed={reason}"
        )
    if int(state.move_count) != int(record["move_count"]):
        problems.append("move_count mismatch between record and replay")

    # Final board cell-by-cell.
    if "final_board" in record:
        if list(record["final_board"]) != list(state.board):
            problems.append("final_board mismatch between record and replay")

    scored = score_position(state.board, size, komi)
    for key in ("black_score", "white_score", "score_margin"):
        if float(scored[key]) != float(record[key]):
            problems.append(f"score field {key} mismatch")
    if scored["winner"] != record["winner"]:
        problems.append("winner mismatch between record and replay")

    ib = coerce_identity(record["black_identity"])
    iw = coerce_identity(record["white_identity"])
    u_black, u_white = black_white_utilities(scored["winner"], ib, iw)
    if u_black != record["black_utility"] or u_white != record["white_utility"]:
        problems.append("utility mismatch between record and replay")

    if G.board_has_dead_group(state.board, size):
        problems.append("replayed terminal board contains a dead group")

    return {"ok": not problems, "problems": problems}


def replay_all_in(out_dir: str):
    """Replay every saved game under ``out_dir``.

    Returns ``(n_ok, n_fail, failures)`` where failures is a list of
    ``(game_id, problems)``.
    """
    from .storage import iter_game_files

    n_ok = 0
    failures = []
    total = 0
    for rec in iter_game_files(out_dir):
        total += 1
        res = replay_record(rec)
        if res["ok"]:
            n_ok += 1
        else:
            failures.append((rec["game_id"], res["problems"]))
    return total, n_ok, failures
