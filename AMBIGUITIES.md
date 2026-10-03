# Recorded spec ambiguities and the chosen (conservative) readings

Where `5x5_mvp_spec.md` left room for interpretation, the most conservative,
easiest-to-verify option was taken.  This file records each decision so it can
be revisited deliberately later.

## 1. Superko after a pass

Spec §3.1: non-pass actions use situational superko; “`pass` 不受超级劫限制”.

Read literally:
* every position that occurs **including those reached by a pass** is added to
  the game history (the position key is `(board, next_to_play)`);
* only **non-pass** moves are rejected when they would recreate an earlier
  position; a pass is always legal regardless of recurrence.

Consequence: a pass that happens to leave `(board, next_player)` identical to
an older position is allowed and still records that position, which can make a
later non-pass move into it illegal.  This is the standard treatment in Go
rules where positions reached after passes count for superko.

## 2. `superko_rejections` meaning

Agents always select from the fully legal set, so a superko move is never
“rejected” at the moment of play.  The recorded game-level field therefore
counts, at every actual turn, the number of **empty-candidate non-pass moves
excluded by the superko rule** during legal-action generation (plus
per-move `superko_excluded`).  This is the operational “superko activity”
signal for Batch A analysis.

## 3. Terminal-reason precedence at the 100-action cap

If the 100th action is simultaneously the second consecutive pass, the game is
labelled `double_pass` (the natural end) rather than `move_limit`.  A game that
merely reaches 100 actions without two consecutive passes is labelled
`move_limit` and scored as-is.  In the Random smoke this occurred once
(`g0096`, 100 moves).

## 4. Rollout and search budget on the shared 100 cap

Real moves and rollouts both count against the same `move_count`; a rollout
that has not double-passed stops at 100 actions and is scored from the current
board.  Rollouts sample uniformly among legal actions **including pass**.

## 5. Colour of “winner” and the utility vector

`winner` is a colour (`black` if `score_margin > 0`, else `white`; `draw` is
retained but unreachable with komi 2.5).  `black_utility` / `white_utility`
are each player's identity reward for that winner.  Invariants:

* WIN-vs-WIN and LOSE-vs-LOSE: `u_black = -u_white` on any non-draw;
* WIN-vs-LOSE: `u_black = u_white` on any non-draw.

## 6. What the MCTS stores and maximises

Each node stores `(n, sum_black, sum_white)`; UCT at a node whose turn it is
uses **that actor's own** average utility (`Q_black` at black nodes,
`Q_white` at white nodes) — never layer-by-layer negation.  Terminal utility
vectors are backed up unchanged.  The searching agent models the opponent as
maximising the opponent's (public) identity utility, which is the natural
general-sum assumption and matches spec §5.1.

## 7. Opening / prefix definitions

Openings and “common prefixes” are defined on the **chosen action sequence**
(board-point action ids, pass = 25).  A game contributes to the length-`L`
stats only if it lasted ≥ `L` moves (reported as `n_games_used`).  Random
games show near-maximum diversity, so no collapse signal appears at this
baseline.

## 8. Agent seed

The MVP has no learning history, so `seed` is *not* an identity of behaviour
history.  It feeds the agent's per-game RNG stream (rollout and tie-break
noise for MCTS).  RandomAgent's move distribution is uniform and therefore
independent of seed; its identity changes only the utility interpretation.

## 9. Board/colour conventions

Action index `a = row*size + col` (`0..24`), pass = `25`.  Black moves first.
Komi is fixed at `2.5` for white and is not claimed to be balanced for 5×5;
formal comparisons exchange colours so conclusions do not rely on colour
fairness (spec §3.3).

## 10. Output-directory overwrite strategy

An output directory that already contains data from a previous run is refused
(`OutputDirExists`) unless the caller passes `overwrite=True` (CLI `--overwrite`).
Overwriting deletes *only* the artifacts this package owns inside that
directory (`games/`, `games.jsonl`, `manifest.json`, `game_seeds.json`,
`summary/`); unrelated files inside the directory and everything outside it
are never touched.  This is so a stale batch can never silently mix into the
next run's `summary` or `replay` (each of which otherwise reads whatever is on
disk).  Full policy in `README.md`.

## 11. Grouped opening stats and terminal bookkeeping

Opening/prefix concentration is reported *both* globally and grouped by
WIN-vs-WIN, LOSE-vs-LOSE, WIN-vs-LOSE, LOSE-vs-WIN, same-identity,
mixed-identity, and per unordered agent pair (`openings_grouped.csv`,
`summary.json` → `opening_groups`); the mixed-vs-same handshake signal is
read within those groups, not from the global average.  A terminal state
(double pass or the 100-action cap) exposes no legal actions and refuses every
further move.  Each saved record now includes `final_board` (the terminal
board), which replay compares cell-by-cell.
