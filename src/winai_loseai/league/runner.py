"""Play one game and execute whole batches (optionally in parallel).

A "game" here is a fixed pair of AgentSpecs, a colour assignment and one game
seed.  Every random draw inside the game comes from a stream derived from that
seed (+ colour + agent seed), so a job always produces exactly the same game
regardless of concurrency or order.
"""

from __future__ import annotations

import time as _time
from concurrent.futures import ProcessPoolExecutor

from .. import SCHEMA_VERSION, CODE_VERSION
from ..provenance import current_provenance
from ..identity import black_white_utilities, coerce_identity
from ..spec import AgentSpec, DEFAULT_BOARD_SIZE, DEFAULT_KOMI
from ..game import state as G
from ..game.scoring import score_position
from ..rng import make_game_rng
from .pairing import make_job
from ..agents.factory import make_agent

TERMINATION_NONE = None


def _to_dict(spec: AgentSpec) -> dict:
    return {
        "agent_id": spec.agent_id,
        "identity": spec.identity.value,
        "algorithm": spec.algorithm,
        "compute_level": spec.compute_level,
        "seed": spec.seed,
    }


def _one_move_color(player_code: int) -> str:
    return "black" if player_code == G.BLACK else "white"


def play_one(job: dict, board_size: int = DEFAULT_BOARD_SIZE,
             komi: float = DEFAULT_KOMI) -> dict:
    """Play a game; optional job.pass_min_ply defaults to the G0 value 0.

    NoLegalActionError propagates unchanged, including faults in MCTS tree
    nodes or rollouts. The caller must abort the experiment, not score it.
    """
    provenance = current_provenance()
    black_spec = job["black"]
    white_spec = job["white"]
    if not isinstance(black_spec, AgentSpec):
        black_spec = AgentSpec.from_dict(black_spec)
    if not isinstance(white_spec, AgentSpec):
        white_spec = AgentSpec.from_dict(white_spec)
    game_seed = int(job["game_seed"])
    batch_id = job.get("batch_id", "default")
    index = int(job.get("index", -1))

    rng_black = make_game_rng(game_seed, "black", black_spec.seed)
    rng_white = make_game_rng(game_seed, "white", white_spec.seed)
    agent_black = make_agent(black_spec, rng_black, komi)
    agent_white = make_agent(white_spec, rng_white, komi)
    agent_for = {G.BLACK: (black_spec, agent_black), G.WHITE: (white_spec, agent_white)}

    state = G.GoState.initial(board_size,
                              pass_min_ply=job.get("pass_min_ply", 0))
    if "ruleset" in job and job["ruleset"] != state.ruleset:
        raise ValueError("job ruleset does not match pass_min_ply")
    moves = []
    superko_total = 0
    game_start = _time.perf_counter()

    while not state.is_terminal():
        spec, agent = agent_for[state.to_play]
        try:
            legal, counts = state.legal_report()
            superko_total += counts["superko"]
            action = agent.select_action(state, black_spec.identity, white_spec.identity)
        except G.NoLegalActionError as error:
            error.diagnostics['game_context'] = {
                'game_index': index, 'batch_id': batch_id, 'game_seed': game_seed,
                'ruleset': state.ruleset, 'pass_min_ply': state.pass_min_ply,
                'actual_root_ply': state.move_count, 'actual_moves': moves,
                'attempt_elapsed_ms': (_time.perf_counter()-game_start)*1000.0,
            }
            raise
        if action not in legal:
            raise RuntimeError(
                f"agent {spec.agent_id} returned illegal action {action} at "
                f"move {len(moves) + 1} (legal={legal})"
            )
        next_state = state.play(action)

        move = {
            "index": len(moves) + 1,
            "color": _one_move_color(state.to_play),
            "action": int(action),
            "is_pass": bool(G.is_pass(action, board_size)),
            "legal_action_count": len(legal),
            "superko_excluded": int(counts["superko"]),
        }
        if agent.last_stats is not None:
            move.update(agent.last_stats)
        moves.append(move)
        state = next_state

    reason = state.terminal_reason()
    scored = score_position(state.board, board_size, komi)
    winner = scored["winner"]
    u_black, u_white = black_white_utilities(
        winner, coerce_identity(black_spec.identity), coerce_identity(white_spec.identity)
    )

    game_id = f"{batch_id}-g{index:06d}"
    record = {
        **provenance,
        "schema_version": SCHEMA_VERSION,
        "code_version": CODE_VERSION,
        "game_id": game_id,
        "batch_id": batch_id,
        "game_index": index,
        "game_seed": game_seed,
        "board_size": board_size,
        "komi": komi,
        "ruleset": state.ruleset,
        "pass_min_ply": state.pass_min_ply,
        "black_agent_id": black_spec.agent_id,
        "white_agent_id": white_spec.agent_id,
        "black_identity": black_spec.identity.value,
        "white_identity": white_spec.identity.value,
        "black_algorithm": black_spec.algorithm,
        "white_algorithm": white_spec.algorithm,
        "black_compute_level": black_spec.compute_level,
        "white_compute_level": white_spec.compute_level,
        "winner": winner,
        "black_score": scored["black_score"],
        "white_score": scored["white_score"],
        "score_margin": scored["score_margin"],
        "black_utility": u_black,
        "white_utility": u_white,
        "move_count": len(moves),
        "termination_reason": reason,
        "final_board": list(state.board),
        "superko_rejections": superko_total,
        "game_wall_ms": round((_time.perf_counter() - game_start) * 1000.0, 3),
        "black": _to_dict(black_spec),
        "white": _to_dict(white_spec),
        "moves": moves,
    }
    return record


def run_jobs(jobs, concurrency: int = 1, board_size: int = DEFAULT_BOARD_SIZE,
             komi: float = DEFAULT_KOMI):
    """Run all jobs and return records in the same order as ``jobs``.

    Sequential and process-pool paths receive the *same* ``board_size`` and
    ``komi``, so a game is identical regardless of the concurrency setting.
    """
    import os
    from functools import partial

    if concurrency and concurrency > 1 and jobs and len(jobs) > 1:
        nproc = min(int(concurrency), len(jobs), os.cpu_count() or 1)
        worker = partial(_play_one_wrapper, board_size=board_size, komi=komi)
        with ProcessPoolExecutor(max_workers=nproc) as ex:
            return list(ex.map(worker, jobs, chunksize=1))
    return [play_one(j, board_size=board_size, komi=komi) for j in jobs]


def stream_jobs(jobs, concurrency: int = 1, board_size: int = DEFAULT_BOARD_SIZE,
                komi: float = DEFAULT_KOMI):
    """Yield game records **in ``game_index`` order**, without buffering a run.

    Each job is deterministic (content independent of concurrency / order).
    When ``concurrency > 1`` a *single* bounded process pool is kept alive;
    at most ``~4*nproc`` jobs are submitted ahead of the write position, so
    memory stays bounded even if one early game is much slower than the rest.
    Finished records are buffered and only yielded once every earlier index has
    been yielded, so the caller persists games in the plan's order regardless
    of scheduling.  Worker errors propagate as exceptions from the generator.
    """
    import os
    from functools import partial
    from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED

    jobs = sorted(list(jobs), key=lambda j: j["index"])
    if not jobs:
        return
    if concurrency <= 1 or len(jobs) == 1:
        for job in jobs:
            yield play_one(job, board_size=board_size, komi=komi)
        return

    nproc = min(int(concurrency), len(jobs), os.cpu_count() or 1)
    worker = partial(_play_one_wrapper, board_size=board_size, komi=komi)
    window = max(nproc * 4, 8)  # bounded in-flight + buffered records
    n = len(jobs)

    with ProcessPoolExecutor(max_workers=nproc) as ex:
        ready = {}     # game_index -> finished record (not yet yielded)
        futures = set()
        sent = 0       # next jobs[] position to submit
        written = 0    # next jobs[] position to yield

        def _submit():
            nonlocal sent
            while sent < n and (len(futures) + len(ready)) < window:
                futures.add(ex.submit(worker, jobs[sent]))
                sent += 1

        _submit()
        while written < n:
            # Wait for completions and drain the ordered head as it becomes ready.
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for fut in done:
                    futures.discard(fut)
                    rec = fut.result()
                    ready[rec["game_index"]] = rec
                while written < n and jobs[written]["index"] in ready:
                    yield ready.pop(jobs[written]["index"])
                    written += 1
                _submit()
                if not futures:
                    break
            # All submitted futures are done; anything still buffered is in
            # order and can be drained.
            while written < n:
                key = jobs[written]["index"]
                if key not in ready:
                    raise RuntimeError(
                        "stream_jobs ordering bug: finished jobs are missing"
                    )
                yield ready.pop(key)
                written += 1


def _play_one_wrapper(job, board_size: int = DEFAULT_BOARD_SIZE,
                      komi: float = DEFAULT_KOMI):
    return play_one(job, board_size=board_size, komi=komi)
