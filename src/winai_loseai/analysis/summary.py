"""Batch summaries (spec section 8).

Reads the compact JSONL + full game files of an output directory and writes:

* ``summary/summary.json``  nested aggregates (counts, lengths, CIs, timings);
* ``summary/identity_pairs.csv``   counts + goal/win rates + length + terms;
* ``summary/matchup_matrix.csv``   row agent vs column agent *goal rates*,
  accumulated per colour (so same-ID self-play averages both colours);
* ``summary/matchup_counts.csv``   appearance counts behind the rates;
* ``summary/openings.csv``         global prefix-length uniqueness/concentration;
* ``summary/openings_grouped.csv`` same stats broken out by condition:
  WIN/WIN, LOSE/LOSE, WIN/LOSE, LOSE/WIN, same-identity, mixed-identity, and
  per unordered agent pair (plus the global row);
* ``summary/top_prefixes.csv``     global most frequent length-8 prefixes.

Opening concentration is therefore comparable *within* the same / mixed
identity groups (the handshake signal) instead of being drowned by the global
average.
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict

from .stats import describe, bootstrap_ci_diff_mean
from ..league.storage import read_metadata, iter_game_files, OPENING_K

_OPENING_LENGTHS = (4, 8, 12)
_IDENTITY_COMBOS = [("WIN", "WIN"), ("LOSE", "LOSE"),
                    ("WIN", "LOSE"), ("LOSE", "WIN")]


def _algo_level_pair(r):
    return (r["black_algorithm"], r["black_compute_level"],
            r["white_algorithm"], r["white_compute_level"])


def _identity_pair(r):
    return (r["black_identity"], r["white_identity"])


def _identity_relation(r):
    return "same" if r["black_identity"] == r["white_identity"] else "mixed"


def _goal_rates(rows):
    n = len(rows)
    return {
        "black_goal_rate": sum(1 for r in rows if r["black_utility"] == 1) / n if n else None,
        "white_goal_rate": sum(1 for r in rows if r["white_utility"] == 1) / n if n else None,
        "black_win_rate": sum(1 for r in rows if r["winner"] == "black") / n if n else None,
        "n_games": n,
    }


def prefix_counter(rows):
    """Counter of action-prefix tuples (leading actions of each game)."""
    c = Counter()
    for r in rows:
        pref = tuple(r.get("opening_actions") or [])[:OPENING_K]
        if pref:
            c[pref] += 1
    return c


def prefix_stats_for(rows, length: int):
    used = [r for r in rows if r["move_count"] >= length]
    n_used = len(used)
    if n_used == 0:
        return {"prefix_length": length, "n_games_used": 0}
    counter = Counter()
    for r in used:
        pref = tuple((r.get("opening_actions") or [])[:length])
        if len(pref) == length:
            counter[pref] += 1
    total = sum(counter.values())
    if total == 0:
        return {"prefix_length": length, "n_games_used": n_used, "unique": 0}
    ranked = counter.most_common()
    top1_share = ranked[0][1] / total
    top4_share = sum(v for _, v in ranked[:4]) / total
    return {
        "prefix_length": length,
        "n_games_used": n_used,
        "unique": len(ranked),
        "top1_prefix": list(ranked[0][0]),
        "top1_count": ranked[0][1],
        "top1_share": top1_share,
        "top4_share": top4_share,
    }


# ---------------------------------------------------------------------------
def build_opening_groups(meta):
    """Ordered list of ``(group_name, rows)`` for opening concentration."""
    groups = [("global", meta)]
    for bi, wi in _IDENTITY_COMBOS:
        groups.append((f"{bi}_vs_{wi}",
                       [r for r in meta if _identity_pair(r) == (bi, wi)]))
    groups.append(("same_identity",
                   [r for r in meta if _identity_relation(r) == "same"]))
    groups.append(("mixed_identity",
                   [r for r in meta if _identity_relation(r) == "mixed"]))
    # Optional extra: per unordered agent pair (colour-agnostic matchup).
    by_pair = defaultdict(list)
    for r in meta:
        a, b = r["black_agent_id"], r["white_agent_id"]
        key = (a, b) if a <= b else (b, a)
        by_pair[key].append(r)
    for pair in sorted(by_pair):
        groups.append((f"pair:{pair[0]}__vs__{pair[1]}", by_pair[pair]))
    return groups


def _opening_group_stats(name, rows):
    stats = [prefix_stats_for(rows, L) for L in _OPENING_LENGTHS]
    pref8 = Counter()
    for r in rows:
        if r["move_count"] >= 8:
            pref8[tuple((r.get("opening_actions") or [])[:8])] += 1
    total8 = sum(pref8.values())
    return {
        "group": name,
        "n_games": len(rows),
        "prefix_stats": stats,
        "top_prefixes_len8": [
            {"prefix": list(p), "count": c,
             "share": (c / total8 if total8 else None)}
            for p, c in pref8.most_common(5)
        ],
    }


# ---------------------------------------------------------------------------
def _matchup_tables(meta):
    """Per-colour accumulated goal rates + counts for the matrix."""
    agents = sorted({r["black_agent_id"] for r in meta} | {r["white_agent_id"] for r in meta})
    total = defaultdict(int)
    goal = defaultdict(int)
    for r in meta:
        # black side: row = black agent, col = white agent, util = black_utility
        total[(r["black_agent_id"], r["white_agent_id"])] += 1
        if r["black_utility"] == 1:
            goal[(r["black_agent_id"], r["white_agent_id"])] += 1
        # white side: row = white agent, col = black agent, util = white_utility
        total[(r["white_agent_id"], r["black_agent_id"])] += 1
        if r["white_utility"] == 1:
            goal[(r["white_agent_id"], r["black_agent_id"])] += 1
    return agents, total, goal


# ---------------------------------------------------------------------------
def summarize(out_dir: str) -> dict:
    """Compute and persist batch summaries; returns the summary dict."""
    meta = read_metadata(out_dir)
    n_total = len(meta)

    out_summary_dir = os.path.join(out_dir, "summary")
    os.makedirs(out_summary_dir, exist_ok=True)

    # ---- per identity-pair / algo cell -----------------------------------
    cell_rows = defaultdict(list)
    for r in meta:
        cell_rows[(r["black_identity"], r["white_identity"],
                   r["black_algorithm"], r["black_compute_level"],
                   r["white_algorithm"], r["white_compute_level"])].append(r)

    identity_pairs = []
    for (bi, wi, ba, bl, wa, wl), rows in sorted(cell_rows.items()):
        row = {
            "black_identity": bi, "white_identity": wi,
            "black_algorithm": ba, "black_compute_level": bl,
            "white_algorithm": wa, "white_compute_level": wl,
        }
        lengths = [r["move_count"] for r in rows]
        d = describe(lengths)
        row["n_games"] = len(rows)
        row.update(_goal_rates(rows))
        for key in ("mean", "median", "q25", "q75", "min", "max"):
            row[f"length_{key}"] = d.get(key)
        terms = Counter(r["termination_reason"] for r in rows)
        row["n_double_pass"] = terms.get("double_pass", 0)
        row["n_move_limit"] = terms.get("move_limit", 0)
        row["pct_double_pass"] = terms.get("double_pass", 0) / len(rows)
        row["pct_move_limit"] = terms.get("move_limit", 0) / len(rows)
        row["superko_rejections"] = sum(r["superko_rejections"] for r in rows)
        margins = [r["score_margin"] for r in rows]
        row["mean_score_margin"] = sum(margins) / len(margins)
        identity_pairs.append(row)

    # ---- matchup matrix (per colour, so same-ID self-play is correct) -----
    agents, mt, mg = _matchup_tables(meta)
    matrix_path = os.path.join(out_summary_dir, "matchup_matrix.csv")
    with open(matrix_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["row_agent\\col_agent"] + agents)
        for a in agents:
            row = []
            for b in agents:
                row.append(f"{(mg[(a, b)] / mt[(a, b)]):.4f}" if mt[(a, b)] else "")
            w.writerow([a] + row)
    counts_path = os.path.join(out_summary_dir, "matchup_counts.csv")
    with open(counts_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["row_agent\\col_agent"] + agents)
        for a in agents:
            w.writerow([a] + [mt[(a, b)] for b in agents])

    # ---- opening statistics: global + grouped -----------------------------
    open_rows = [prefix_stats_for(meta, L) for L in _OPENING_LENGTHS]
    opening_groups = [_opening_group_stats(name, rows)
                      for name, rows in build_opening_groups(meta)]

    all_prefs = prefix_counter(meta)
    top_prefixes = all_prefs.most_common(20)
    n_pref_total = sum(all_prefs.values())

    # ---- length difference: mixed vs same (per algo-level cell) ----------
    cell_al = defaultdict(list)  # key (algo,level pair) -> (relation, length)
    for r in meta:
        cell_al[_algo_level_pair(r)].append((_identity_relation(r), r["move_count"]))
    length_diffs = []
    for key, vals in sorted(cell_al.items()):
        same_lens = [v for rel, v in vals if rel == "same"]
        mixed_lens = [v for rel, v in vals if rel == "mixed"]
        ci = bootstrap_ci_diff_mean(mixed_lens, same_lens)
        if ci is not None:
            length_diffs.append({
                "algo_level_cell": list(key),
                "mixed_length": describe(mixed_lens),
                "same_length": describe(same_lens),
                "diff_mixed_minus_same_ci95": ci,
            })

    # ---- timing (needs full records when MCTS present) -------------------
    timing = {"n_mcts_games": 0, "games": []}
    if any(r["black_algorithm"] == "vector_mcts" or r["white_algorithm"] == "vector_mcts"
           for r in meta):
        per_move = []
        per_game = []
        n_games = 0
        for rec in iter_game_files(out_dir):
            if not (rec["black_algorithm"] == "vector_mcts"
                    or rec["white_algorithm"] == "vector_mcts"):
                continue
            n_games += 1
            move_ms = [m["search_time_ms"] for m in rec["moves"]
                       if "search_time_ms" in m and m["search_time_ms"] is not None]
            per_move.extend(move_ms)
            per_game.append(sum(move_ms))
        timing = {
            "n_mcts_games": n_games,
            "per_move_search_ms": describe(per_move),
            "per_game_search_ms": describe(per_game),
        }

    summary = {
        "out_dir": out_dir,
        "n_games": n_total,
        "identity_pairs": identity_pairs,
        "opening_stats": open_rows,
        "opening_groups": opening_groups,
        "top_prefixes": [{"prefix": list(p), "count": c,
                          "share": (c / n_pref_total if n_pref_total else None)}
                         for p, c in top_prefixes],
        "n_distinct_openings": len(all_prefs),
        "length_diffs_mixed_vs_same": length_diffs,
        "timing": timing,
    }

    with open(os.path.join(out_summary_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)

    _write_identity_pairs_csv(identity_pairs, os.path.join(out_summary_dir, "identity_pairs.csv"))
    _write_openings_csv(open_rows, os.path.join(out_summary_dir, "openings.csv"))
    _write_openings_grouped_csv(opening_groups,
                                os.path.join(out_summary_dir, "openings_grouped.csv"))
    _write_top_prefixes_csv(top_prefixes, n_pref_total,
                            os.path.join(out_summary_dir, "top_prefixes.csv"))
    return summary


def _write_identity_pairs_csv(rows, path):
    if not rows:
        return
    cols = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_openings_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["prefix_length", "n_games_used", "unique_prefixes",
                    "top1_share", "top4_share"])
        for r in rows:
            w.writerow([r.get("prefix_length"), r.get("n_games_used", 0),
                        r.get("unique", 0), r.get("top1_share", ""),
                        r.get("top4_share", "")])


def _write_openings_grouped_csv(groups, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["group", "n_games", "prefix_length", "n_games_used",
                    "unique_prefixes", "top1_share", "top4_share"])
        for g in groups:
            for ps in g["prefix_stats"]:
                w.writerow([g["group"], g["n_games"], ps.get("prefix_length"),
                            ps.get("n_games_used", 0), ps.get("unique", 0),
                            ps.get("top1_share", ""), ps.get("top4_share", "")])


def _write_top_prefixes_csv(ranked, total, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "prefix", "count", "share"])
        for rank, (p, c) in enumerate(ranked, start=1):
            w.writerow([rank, list(p), c, (c / total if total else "")])
