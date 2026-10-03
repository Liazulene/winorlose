# WinAI / LoseAI — 5×5 MVP

A pure-Python, dependency-light implementation of the 5×5 validation system
described in `5x5_mvp_spec.md` (the authoritative spec; cross-referenced design
notes are in `winai_loseai_go_experiment_notes_v2.md`).

The point of the MVP is **not** training.  There is no learning: every agent is
either `RandomAgent` (uniform play) or `VectorMCTSAgent` (search).  What is
observed is *planning behaviour* under fixed, public identities:

* `WIN`  — own colour wins → `+1`, draw `0`, loses `-1`;
* `LOSE` — own colour loses → `+1`, draw `0`, wins `-1`.

Because WIN-vs-LOSE is **non-zero-sum**, the terminal value of a game is the
utility *vector* `(u_black, u_white)` and the MCTS is a **general-sum**
dual-utility search: every node keeps both players' accumulated utilities and
the node's current actor maximises their *own* average utility (no zero-sum
sign flipping).

---

## 5×5 planning phase — completed (2026-09-22)

正式结果与下一步建议见 [最终实验报告](reports/5x5_planning_phase_report.md)。

| 批次 | 已完成 / 计划 | 全量回放 | 状态 |
|---|---:|---:|---|
| Random A / seed 0 | 10,000 / 10,000 | 10,000 / 10,000 | completed，历史数据保持不变 |
| shallow MCTS B / seed 0 | 2,800 / 2,800 | 2,800 / 2,800 | completed，完整性无问题 |
| shallow MCTS B / seed 1 | 2,800 / 2,800 | 2,800 / 2,800 | completed，完整性无问题 |

两个正式 B 均为 5×5、komi 2.5、每手 64 simulations、8 并发；56 个有序配对各
50 局，JSONL 严格按索引 0–2799 升序。全部 **89 项测试通过**，含恢复版本拒绝及
拒绝后原始数据不变测试。正式版本 `winai_loseai-0.2.0-planning`；源码 SHA-256：
`a4d6d9e033b88f6b7eb469d49088d69cb45ceb34b3770087b8ecd3a23a890e2e`。

mixed−same 均长差在 seed 0 / 1 为 −7.042 / −6.561 手（两者 95% CI 均不跨 0）；
mixed 双方目标均全部达成。LOSE/LOSE 黑方目标率为 94.50% / 94.17%，但这对应
黑方盘面输棋。没有发现固定长前缀集中或经多重校正后显著的个体克制关系。
**建议暂缓直接进入 7×7**，先在独立新实验中诊断正贴目、pass 和浅搜索的贡献。
本轮未启动 Batch C、medium/deep、7×7 或训练。

- [源码归档](reports/planning_source_0.2.0.zip) 与 [逐文件锁](reports/planning_source_lock.json)
- [跨 seed 统计](reports/cross_run/analysis.json)、[逐配对结果](reports/cross_run/agent_pairs.csv)
- [代表棋局逐手核查](reports/representative_game_review.md)
- [全量验证](reports/validation/)、[最终数据未改写校验](reports/validation/final_delivery.json)

在现有已完成原始数据上重建分析（不会修改原始棋局）：

```powershell
& 'D:\MyCondaEnvs\models\python.exe' scripts/validate_run.py outputs/batch_B_shallow_seed0
& 'D:\MyCondaEnvs\models\python.exe' scripts/validate_run.py outputs/batch_B_shallow_seed1
& 'D:\MyCondaEnvs\models\python.exe' scripts/planning_analysis.py outputs/batch_A_seed0 outputs/batch_B_shallow_seed0 outputs/batch_B_shallow_seed1
& 'D:\MyCondaEnvs\models\python.exe' scripts/review_games.py
& 'D:\MyCondaEnvs\models\python.exe' scripts/write_planning_report.py
& 'D:\MyCondaEnvs\models\python.exe' scripts/verify_delivery.py
```

正式游戏运行仅需标准库；独立分析使用 models 中的 NumPy 2.4.6 和 SciPy 1.17.1。
两份原始设计文档未改写。Batch A 的旧 JSONL 未排序且没有源码指纹，详见报告边界说明。

## Layout

```text
5x5_mvp_spec.md                       implementation spec (authoritative)
winai_loseai_go_experiment_notes_v2.md  background design notes
AMBIGUITIES.md                        recorded spec ambiguities + chosen reading
run.py                                single-command entry point
src/winai_loseai/
  identity.py                         WIN/LOSE rewards
  spec.py                             AgentSpec, compute tiers, individuals
  rng.py                              per-(game, colour, agent) RNG streams
  game/state.py                       Go rules: captures, suicide, superko, pass
  game/scoring.py                     Tromp–Taylor area scoring + komi
  agents/random_agent.py              uniform-over-legal baseline
  agents/vector_mcts.py               general-sum dual-utility MCTS
  league/runner.py                    play one game / run + stream batches
  league/batch.py                     resumable formal-batch orchestrator
  league/pairing.py                   ordered-pair + identity-combo jobs
  league/seeds.py                     deterministic per-game seeds
  league/storage.py                   game JSON + games.jsonl + manifest
  league/runstore.py                  persistent incremental run store
  league/replay.py                    independent replay validation
  analysis/…                          CSV/JSON batch summaries + statistics
tests/                                unit, property, replay, summary tests
outputs/                              historical handoff data (new runs ignored by default)
```

The game/search runtime uses only the Python standard library. The independent
cross-run analysis uses NumPy and SciPy; the full test suite uses pytest and
these analysis dependencies (available in the `models` environment).

## Running (use the `models` environment)

```text
D:\MyCondaEnvs\models\python.exe run.py test                       # all tests
D:\MyCondaEnvs\models\python.exe run.py smoke-random --games-per-combo 25
D:\MyCondaEnvs\models\python.exe run.py smoke-mcts   --games-per-pair 2
D:\MyCondaEnvs\models\python.exe run.py batch --batch A --games 10000 --concurrency 8 --out outputs/batch_A_seed0
D:\MyCondaEnvs\models\python.exe run.py batch --batch A --games 10000 --concurrency 8 --out outputs/batch_A_seed0 --resume   # continue after an interruption
D:\MyCondaEnvs\models\python.exe run.py replay <out_dir>
D:\MyCondaEnvs\models\python.exe run.py summary <out_dir>
```

Formal sizes (spec): Batch A ≥ 10,000 Random games; Batch B **first round**
shallow MCTS = 50 games per ordered pairing → `8 agents × 7 opponents × 50 =
2,800 games` (running `--games 5600` would mean 100 per ordered pair, the
extended scale); Batch C shallow vs medium ≥ 50 per ordered condition.  `deep`
(1024 sims) is implemented but **not** required for the MVP.

Every batch writes under `<out_dir>`:

* `manifest.json` — batch configuration + agent definitions + code version;
* `game_seeds.json` — explicit per-game seeds (re-run reproducibility);
* `games.jsonl` — one compact metadata JSON per game;
* `games/<game_id>.json` — full replayable record (moves + MCTS search data
  + `final_board`);
* `summary/*` — `summary.json`, `identity_pairs.csv`, `matchup_matrix.csv`,
  `matchup_counts.csv`, `openings.csv`, `openings_grouped.csv`,
  `top_prefixes.csv`.

Per-game data model follows spec §7 (game-level fields plus per-move search
stats: chosen action, legal count, root visits, per-action visit counts and
`Q_black` / `Q_white`, simulations used, search ms).

## Output-directory overwrite policy

The repository's initial handoff snapshot includes the completed historical
outputs so a new researcher can reproduce the published analysis without a
separate data transfer.  New files under `outputs/` are ignored by Git by
default to avoid accidentally growing repository history; deliberately
archiving a new formal run therefore requires an explicit `git add -f` or a
separate data-release decision.

An output directory that already holds experiment data is **refused** by
default (`OutputDirExists`) — stale `games/*.json` can no longer pollute a new
run's summary or replay.  To deliberately replace a previous run, pass
`--overwrite` to the `smoke-*` / `batch` commands; this clears only the
artifacts this package owns (`games/`, `games.jsonl`, `manifest.json`,
`game_seeds.json`, `summary/`) and never touches anything else inside or
outside the directory.  Prefer a fresh directory per experiment when in doubt.

## Resumable formal batches (incremental save)

Formal batches never hold a whole run in memory.  Each game is streamed to
disk as it finishes: the full record is written to a `games/*.json.tmp` file
and atomically renamed to its final name, and one compact line is appended to
`games.jsonl` (flush per write, never a duplicate).  Before the first game the
run directory already contains `manifest.json` (status `running`), the full
`plan.json` job list and `game_seeds.json`, plus `planned_game_count`.

`manifest.status` transitions `running → completed` (or `interrupted` /
`failed` on Ctrl-C or a worker error, keeping every completed game).  A
subsequent run with `--resume`:

* refuses unless the requested batch matches the stored plan exactly
  (batch id/kind, board size, komi, batch seed, agents, seed plan, planned
  count) — `--resume` and `--overwrite` are mutually exclusive;
* recomputes what is already on disk (valid game file **and** matching JSONL
  line) and only runs the missing indexes; corrupt or leftover `.tmp` files
  are never counted as complete and are simply redone;
* produces the same final chess as a from-scratch run.

Summary and replay are produced only after the status is `completed` and an
integrity check confirms the manifest counts, `games.jsonl` length and game
files all agree; inconsistencies are reported as errors instead of being
silently ignored.

Two further guarantees:

* **Deterministic persistence order** — although games are computed on a
  bounded parallel pool, records are yielded (and therefore appended to
  `games.jsonl`) strictly in `game_index` order.  A concurrency-2 run and an
  interrupted-then-resumed run append exactly the same sequence of game ids as
  a sequential run.
* **Metadata repair** — on resume, `games.jsonl` is normalised before use:
  a torn *trailing* line (a crash mid-append) is dropped, and a metadata line
  missing for a game whose full JSON is atomically saved and valid is rebuilt
  from that file (never duplicated, order kept by `game_index`).  Corruption
  in a *middle* line raises an explicit error and is never auto-"fixed".

If the post-run integrity check fails the manifest becomes `failed`; if all
games parse but the full replay finds a problem it becomes
`validation_failed` — a finished run is never left `completed` when replay
rejects any saved game.

## Opening-concentration groups

`openings_grouped.csv` and the `opening_groups` block of `summary.json` report
prefix uniqueness / top-prefix concentration (prefixes of length 4/8/12)
**separately** for: global, WIN-vs-WIN, LOSE-vs-LOSE, WIN-vs-LOSE,
LOSE-vs-WIN, same-identity, mixed-identity, and per unordered agent pair.  The
“handshake” reading therefore compares same vs mixed directly instead of only
looking at the global average.  A game contributes to a length-`L` stat only if
it lasted ≥ `L` moves (`n_games_used`).

## Determinism / concurrency

Each game draws every random number from a stream seeded by
`sha256(batch game seed | colour | agent seed)`.  Two runs of the same batch
agree **per move**: the game record (moves, chosen actions, visit counts,
scores, winner, utilities, `final_board`) is identical regardless of
concurrency or order.  Only wall-clock timing (`search_time_ms`,
`game_wall_ms`) is intentionally excluded from byte-for-byte equality.
Changing the batch seed, a game seed, or an agent seed changes behaviour as
intended.  Verified: re-running the first saved MCTS game reproduces it
exactly, and a 3×3 / komi 0.5 batch is identical under concurrency 1 and 2.

## Observed smoke results (this machine)

**Random vs Random, 100 games (identity combos, 25 each):**
all 4 combos showed black-win rates ≈ 0.36–0.44 and high opening diversity
(≈99 unique 8-move prefixes / 100 games).  Board outcomes are independent of
identity (as designed); only the utility reading changes.  One game ended by
the 100-move safety valve (`move_limit`) — handled and replayed correctly.
Replay: 100/100 exact.

**Shallow MCTS (64 sims), 4 individuals, every ordered pairing ×2 = 24 games:**

| matchup        | black WIN side? | black goal rate | white goal rate | mean length |
|----------------|-----------------|-----------------|-----------------|-------------|
| WIN  vs WIN    | –               | 0.25            | 0.75            | 38.8        |
| LOSE vs LOSE   | –               | 1.00            | 0.00            | 12.5        |
| WIN  vs LOSE   | WIN black       | 1.00            | 1.00            | 27.5        |
| LOSE vs WIN    | WIN white       | 1.00 (LOSE succeeds) | 1.00     | 20.3        |

All 24 saved games replay exactly. Mixed-identity outcomes satisfy both
aligned goals (WIN wins against LOSE, u=(+1,+1)); LOSE-vs-LOSE included games
as short as 5–7 moves. This small smoke does not establish a stable race-to-lose
pattern or a coordination mechanism. The mixed-vs-same mean-length
gap (23.9 vs 25.6 moves, bootstrap 95% CI [−13.4, +9.3]) is not significant at
this sample size — an MVP smoke, not a conclusion.

## Formal Batch A — 10,000 Random games (seed 0)

Run: `run.py batch --batch A --games 10000 --concurrency 8 --out
outputs/batch_A_seed0`.  Manifest status `completed`, planned = completed =
10,000, integrity clean, **all 10,000 saved games replay exactly**.

| identity pair | n     | black win | mean len | med len | double_pass | move_limit |
|---------------|-------|-----------|----------|---------|-------------|------------|
| WIN  vs WIN   | 2500  | 0.389     | 37.7     | 34      | 2473        | 27         |
| LOSE vs LOSE  | 2500  | 0.414     | 37.7     | 35      | 2483        | 17         |
| WIN  vs LOSE  | 2500  | 0.399     | 37.6     | 34      | 2463        | 37         |
| LOSE vs WIN   | 2500  | 0.388     | 38.6     | 35      | 2473        | 27         |

* 108 games hit the 100-move safety valve (`move_limit`); the full list is in
  `summary/move_limit_games.json`.
* Superko excluded 2,634 empty-candidate moves across all games (~0.26/game —
  an operational activity signal, not a scoring event).
* Opening diversity is near-maximal: 9,894 distinct 8-move prefixes among the
  9,894 games that reached 8 moves (no meaningful top-1 concentration).
* Board behaviour is identity-independent: black-win rates across the four
  combos span 0.388–0.414 (binomial SE ≈ 0.010), as expected for Random play;
  identity only changes the utility reading.  Do **not** read any of this as
  evidence of protocols or strategy collapse.

## Notes / boundaries

* “握手协议” is deliberately *not* an acceptance gate for this round; it is
  only reported operationally (length gap + opening concentration with CIs).
* No neural networks, no cross-game learning, no 7×7/9×9, no GUI.
* See `AMBIGUITIES.md` for the conservative readings chosen where the spec was
  ambiguous.

## Formal planning phase source lock (0.2.0)

Formal batches now stamp `code_version`, `source_fingerprint`, `schema_version`
and `python_version` in the manifest, every full game and its JSONL metadata.
`source_lock.json` contains SHA-256 hashes of `run.py` and every package Python
source, with UTF-8/LF normalisation and sorted relative paths. Resume rejects
missing or different versions, fingerprints, runtime versions, source locks,
or mixed-version saved records **before any metadata repair or write**.
An on-disk source edit during a live batch also stops further persistence.
Reports, tests and independent scripts outside `src/` are excluded from the lock.
Archive the locked sources before running; after a semantic change use a new
version and a fresh output directory. Legacy 0.1.0 outputs remain readable but
cannot be resumed under this version. No Git commit is claimed for this folder.

Audit on 2026-09-22: 71 original tests passed; Batch A contains all indexes
0–9999 without duplication and all 10,000 games passed a new full replay.
Its historical JSONL uses completion order rather than sorted order; it has
been preserved unchanged. Locked Batch B uses strictly increasing game indexes.

Formal commands (no overwrite):

```text
D:\MyCondaEnvs\models\python.exe run.py batch --batch B --games 2800 --batch-seed 0 --concurrency 8 --out outputs/batch_B_shallow_seed0
D:\MyCondaEnvs\models\python.exe run.py batch --batch B --games 2800 --batch-seed 1 --concurrency 8 --out outputs/batch_B_shallow_seed1
```

For interruption recovery, repeat exactly the same command with `--resume`.
