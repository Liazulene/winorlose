"""Command line interface (used through the repo-root ``run.py``)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from . import CODE_VERSION
from .provenance import current_provenance
from .analysis.summary import summarize
from .identity import Identity
from .league import replay as replay_mod
from .league import storage
from .league.runner import run_jobs
from .league.pairing import (ordered_pair_jobs, random_baseline_jobs)
from .spec import mcts_individuals

OUTPUTS = os.path.join(os.getcwd(), "outputs")


# --------------------------------------------------------------------------
def _build_manifest(batch_id, batch_seed, jobs, concurrency, extra=None):
    manifest = {
        **current_provenance(),
        "batch_id": batch_id,
        "code_version": CODE_VERSION,
        "batch_seed": batch_seed,
        "concurrency": concurrency,
        "n_games": len(jobs),
        "generated_by": "winai_loseai.cli",
    }
    if extra:
        manifest.update(extra)
    manifest["agents"] = []
    seen = set()
    for j in jobs:
        for spec in (j["black"], j["white"]):
            if spec.agent_id not in seen:
                seen.add(spec.agent_id)
                manifest["agents"].append(spec.to_dict())
    return manifest


def _write_seeds(out_dir, jobs):
    with open(os.path.join(out_dir, "game_seeds.json"), "w", encoding="utf-8") as fh:
        json.dump([{"index": j["index"], "game_seed": j["game_seed"]} for j in jobs],
                  fh, ensure_ascii=False, indent=1)


def _print_game_head(rec):
    bi, wi = rec["black_identity"], rec["white_identity"]
    print(
        f"g{rec['game_index']:04d} {rec['black_agent_id']}({bi}) vs "
        f"{rec['white_agent_id']}({wi}) seed={rec['game_seed']} | "
        f"{rec['move_count']} moves | {rec['termination_reason']} | "
        f"winner={rec['winner']} margin={rec['score_margin']:+.1f} | "
        f"u=({rec['black_utility']:+d},{rec['white_utility']:+d})"
    )


def _finish(out_dir, batch_id):
    _print_summary_highlights(summarize(out_dir), out_dir)
    total, ok, fails = replay_mod.replay_all_in(out_dir)
    print(f"\n[replay] {ok}/{total} saved games replay exactly; "
          f"{len(fails)} failed")
    for gid, problems in fails[:10]:
        print(f"  {gid}: {problems}")
    return 1 if fails else 0


def _print_summary_highlights(summary, out_dir):
    print("\n================ summary ================")
    print(f"games: {summary['n_games']} | distinct openings: "
          f"{summary['n_distinct_openings']}")
    for ip in summary["identity_pairs"]:
        print(
            f"  {ip['black_identity']:4s}/{ip['white_identity']:4s} "
            f"{ip['black_algorithm']}/{ip['black_compute_level']} vs "
            f"{ip['white_algorithm']}/{ip['white_compute_level']} | "
            f"n={ip['n_games']:4d} winB={ip['black_win_rate']:.3f} "
            f"goalB={ip['black_goal_rate']:.3f} goalW={ip['white_goal_rate']:.3f} "
            f"len(mean/med)={ip['length_mean']:.2f}/{ip['length_median']:.2f} "
            f"dblpass={ip['pct_double_pass']:.3f} movelimit={ip['pct_move_limit']:.3f}"
        )
    for d in summary["length_diffs_mixed_vs_same"]:
        ci = d["diff_mixed_minus_same_ci95"]
        print(
            f"  length mixed-vs-same {d['algo_level_cell']}: "
            f"mixed_mean={ci['mean_a']:.2f} same_mean={ci['mean_b']:.2f} "
            f"diff={ci['diff_mean']:+.2f} "
            f"95%CI=[{ci['ci95_low']:+.2f},{ci['ci95_high']:+.2f}] "
            f"(n={ci['n_a']}/{ci['n_b']})"
        )
    for ps in summary["opening_stats"]:
        print(
            f"  opening len {ps['prefix_length']:>2}: used={ps.get('n_games_used')} "
            f"unique={ps.get('unique')} top1_share={ps.get('top1_share', 0):.3f}"
        )
    # handshake-relevant: opening concentration broken out by condition.
    for g in summary.get("opening_groups", []):
        if g["group"] not in ("WIN_vs_WIN", "LOSE_vs_LOSE", "WIN_vs_LOSE",
                              "LOSE_vs_WIN", "same_identity", "mixed_identity"):
            continue
        ps8 = next((p for p in g["prefix_stats"] if p["prefix_length"] == 8), None)
        if ps8:
            print(
                f"  openings[{g['group']:<12}] n={g.get('n_games')} "
                f"used={ps8.get('n_games_used')} unique={ps8.get('unique')} "
                f"top1_share={ps8.get('top1_share', 0):.3f}"
            )
    if summary.get("timing") and summary["timing"].get("n_mcts_games"):
        t = summary["timing"]
        pm = t["per_move_search_ms"]
        print(
            f"  MCTS per-move search ms: mean={pm.get('mean'):.1f} "
            f"median={pm.get('median'):.1f} (n={pm.get('n')})"
        )
    print(f"summary files written under {os.path.join(out_dir, 'summary')}")


def _mcts_smoke_specs(n_seeds=2):
    win = mcts_individuals(Identity.WIN, "shallow", n_seeds=n_seeds)
    lose = mcts_individuals(Identity.LOSE, "shallow", n_seeds=n_seeds)
    return win + lose


# --------------------------------------------------------------------------
def cmd_smoke_random(args):
    storage.prepare_out_dir(args.out, overwrite=args.overwrite)
    batch_id = "smoke_random"
    jobs = random_baseline_jobs(args.games_per_combo, args.batch_seed, batch_id)
    print(f"[smoke-random] {len(jobs)} games across 4 identity combos "
          f"(concurrency={args.concurrency})")
    records = run_jobs(jobs, concurrency=args.concurrency)
    storage.write_records(args.out, batch_id, records,
                          _build_manifest(batch_id, args.batch_seed, jobs,
                                          args.concurrency))
    _write_seeds(args.out, jobs)
    for r in records:
        _print_game_head(r)
    return _finish(args.out, batch_id)


def cmd_smoke_mcts(args):
    storage.prepare_out_dir(args.out, overwrite=args.overwrite)
    batch_id = "smoke_mcts"
    specs = _mcts_smoke_specs(args.seeds_per_identity)
    jobs = ordered_pair_jobs(specs, args.games_per_pair, args.batch_seed, batch_id)
    print(f"[smoke-mcts] shallow(64) individuals: "
          + ", ".join(s.agent_id for s in specs))
    print(f"[smoke-mcts] {len(jobs)} games = {len(specs)} agents, "
          f"{args.games_per_pair} per ordered pair (concurrency={args.concurrency})")
    t0 = time.perf_counter()
    records = run_jobs(jobs, concurrency=args.concurrency)
    dt = time.perf_counter() - t0
    print(f"[smoke-mcts] played {len(records)} games in {dt:.1f}s "
          f"({dt / max(1, len(records)):.2f}s/game)")
    storage.write_records(args.out, batch_id, records,
                          _build_manifest(batch_id, args.batch_seed, jobs,
                                          args.concurrency,
                                          extra={"seeds_per_identity": args.seeds_per_identity,
                                                 "games_per_pair": args.games_per_pair}))
    _write_seeds(args.out, jobs)
    for r in records:
        _print_game_head(r)
    return _finish(args.out, batch_id)


def cmd_batch(args):
    """Formal batch runner with incremental saves and --resume (A / B / C)."""
    from .league import runstore as rs
    from .league.batch import run_batch

    if args.resume and args.overwrite:
        raise SystemExit("--resume and --overwrite are mutually exclusive")
    try:
        store = run_batch(
            args.out, args.batch, args.games, args.batch_seed,
            args.concurrency, overwrite=args.overwrite, resume=args.resume)
    except rs.ConfigMismatch as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except rs.NotARunDirectory as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except rs.MetadataCorrupt as exc:
        print(f"error: metadata corrupted beyond auto-repair: {exc}",
              file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print("\n[batch] interrupted; run again with --resume to continue.")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"[batch] run failed: {exc!r}", file=sys.stderr)
        return 1

    # Post-run gate: integrity + full replay, manifest reflects the outcome.
    from .analysis.summary import summarize
    from .league.batch import post_validation

    status, info = post_validation(args.out)
    if status == rs.STATUS_FAILED:
        print("[batch] integrity check FAILED after completion:", file=sys.stderr)
        for p in info["problems"]:
            print(f"  - {p}", file=sys.stderr)
        return 1

    summary = summarize(args.out)
    _print_summary_highlights(summary, args.out)
    print(f"\n[replay] {info['replay_ok']}/{info['replay_total']} saved games "
          f"replay exactly; {info['replay_fail']} failed")
    if status == rs.STATUS_VALIDATION_FAILED:
        print("[batch] manifest set to validation_failed because replay found "
              f"problems: {info['failures']}", file=sys.stderr)
        return 1
    print(f"[batch-{args.batch}] completed and validated "
          f"{info['replay_total']} games (manifest status: completed).")
    return 0


def cmd_replay(args):
    total, ok, fails = replay_mod.replay_all_in(args.out)
    print(f"[replay] {ok}/{total} games replay exactly; {len(fails)} failed")
    for gid, problems in fails[:args.show]:
        print(f"  {gid}: {problems}")
    return 1 if fails else 0


def cmd_summary(args):
    summary = summarize(args.out)
    _print_summary_highlights(summary, args.out)
    return 0


def cmd_test(args):
    env = dict(os.environ)
    _this = os.path.abspath(__file__)                      # .../src/winai_loseai/cli.py
    here = os.path.dirname(os.path.dirname(os.path.dirname(_this)))  # repo root
    src = os.path.join(here, "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    tests = os.path.join(here, "tests")
    cmd = [sys.executable, "-m", "pytest", tests, "-q"]
    if args.verbose:
        cmd.append("-v")
    print("running:", " ".join(cmd))
    try:
        return subprocess.call(cmd, env=env)
    except FileNotFoundError:
        # fallback to stdlib unittest discovery
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", tests, "-q"]
        return subprocess.call(cmd, env=env)


# --------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="winai_loseai",
        description="WinAI/LoseAI 5x5 MVP experiments")
    sub = p.add_subparsers(dest="command", required=True)

    def common(parser, default_out):
        parser.add_argument("--out", default=default_out)
        parser.add_argument("--batch-seed", type=int, default=0)
        parser.add_argument("--concurrency", type=int, default=1,
                            help="0/1 = sequential; >1 = process pool")
        parser.add_argument("--overwrite", action="store_true",
                            help="replace existing data in --out (default: refuse)")

    sp = sub.add_parser("smoke-random")
    common(sp, os.path.join(OUTPUTS, "smoke_random"))
    sp.add_argument("--games-per-combo", type=int, default=25)
    sp.set_defaults(func=cmd_smoke_random)

    sp = sub.add_parser("smoke-mcts")
    common(sp, os.path.join(OUTPUTS, "smoke_mcts"))
    sp.add_argument("--games-per-pair", type=int, default=2)
    sp.add_argument("--seeds-per-identity", type=int, default=2)
    sp.set_defaults(func=cmd_smoke_mcts)

    sp = sub.add_parser("batch")
    common(sp, os.path.join(OUTPUTS, "batch"))
    sp.add_argument("--batch", choices=["A", "B", "C"], required=True)
    sp.add_argument("--games", type=int, required=True,
                    help="target total games; split per pairing internally")
    sp.add_argument("--resume", action="store_true",
                    help="resume the batch already stored in --out "
                         "(mutually exclusive with --overwrite)")
    sp.set_defaults(func=cmd_batch)

    sp = sub.add_parser("replay")
    sp.add_argument("out")
    sp.add_argument("--show", type=int, default=10)
    sp.set_defaults(func=cmd_replay)

    sp = sub.add_parser("summary")
    sp.add_argument("out")
    sp.set_defaults(func=cmd_summary)

    sp = sub.add_parser("test")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_test)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except storage.OutputDirExists as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
