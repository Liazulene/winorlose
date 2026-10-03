"""On-disk layout for a batch.

::

    <out_dir>/
        manifest.json        batch-level configuration (re-run metadata)
        games.jsonl          one compact JSON per game (no per-move data)
        games/<game_id>.json full replayable record (moves + search stats)
        game_seeds.json      explicit per-game seeds (written by the CLI)

The full record JSON is what replay and the per-move analyses read; the JSONL
gives cheap bulk access to game-level fields for summaries.

Overwrite policy (see README / AMBIGUITIES):

* by default, an output directory that already contains any experiment data is
  **refused** (``OutputDirExists``) -- stale games can no longer pollute a new
  batch's summary or replay;
* pass ``overwrite=True`` to *deliberately* clear only this experiment's own
  artifacts (``games/``, ``games.jsonl``, ``manifest.json``,
  ``game_seeds.json``, ``summary/``).  Nothing outside ``out_dir`` and no
  unrelated file inside it is ever touched.
"""

from __future__ import annotations

import json
import os
import shutil

OPENING_K = 12  # number of leading actions kept in the JSONL for prefix stats

# Experiment artifacts owned by a batch run (nothing else is ever deleted).
_EXPERIMENT_PATHS = (
    "source_lock.json",
    "games.jsonl",
    "manifest.json",
    "game_seeds.json",
    "plan.json",
    "games",
    "summary",
)


class OutputDirExists(Exception):
    """Raised when a run would overwrite existing experiment data."""


def has_existing_data(out_dir: str) -> bool:
    """True if ``out_dir`` already contains data produced by a previous run."""
    if not os.path.isdir(out_dir):
        return False
    for name in _EXPERIMENT_PATHS:
        path = os.path.join(out_dir, name)
        if os.path.isfile(path):
            return True
        if os.path.isdir(path) and os.listdir(path):
            return True
    return False


def clear_experiment_artifacts(out_dir: str):
    """Remove only the artifacts owned by previous runs inside ``out_dir``."""
    for name in _EXPERIMENT_PATHS:
        path = os.path.join(out_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)


def prepare_out_dir(out_dir: str, overwrite: bool = False):
    """Check/clear ``out_dir`` before a run.

    Raises :class:`OutputDirExists` if the directory already holds experiment
    data and ``overwrite`` is False.  Otherwise clears that data and creates
    the (empty) directory.  Never touches files outside ``out_dir``.
    """
    if has_existing_data(out_dir):
        if not overwrite:
            raise OutputDirExists(
                f"output directory already contains data from a previous run: "
                f"{out_dir!r}\n"
                "choose a fresh directory or pass --overwrite to replace it."
            )
        clear_experiment_artifacts(out_dir)
    os.makedirs(out_dir, exist_ok=True)


def _metadata_line(record: dict) -> dict:
    """Compact JSONL representation of one game (drops moves/search data)."""
    line = {k: v for k, v in record.items() if k not in ("moves", "black", "white")}
    actions = [m["action"] for m in record["moves"][:OPENING_K]]
    line["opening_actions"] = actions
    line["game_file"] = os.path.join("games", f"{record['game_id']}.json").replace("\\", "/")
    return line


def write_records(out_dir: str, batch_id: str, records,
                  manifest: dict | None = None, overwrite: bool = False):
    """Write one full JSON + one JSONL line per game, plus a manifest.

    Refuses to overwrite an existing non-empty batch directory unless
    ``overwrite=True`` (see :func:`prepare_out_dir`).
    """
    prepare_out_dir(out_dir, overwrite=overwrite)
    games_dir = os.path.join(out_dir, "games")
    os.makedirs(games_dir, exist_ok=True)
    meta_path = os.path.join(out_dir, "games.jsonl")
    written = []
    with open(meta_path, "w", encoding="utf-8") as fh:
        for rec in records:
            path = os.path.join(games_dir, f"{rec['game_id']}.json")
            with open(path, "w", encoding="utf-8") as g:
                json.dump(rec, g, ensure_ascii=False, indent=1)
            fh.write(json.dumps(_metadata_line(rec), ensure_ascii=False) + "\n")
            written.append(rec["game_id"])
    if manifest is not None:
        manifest.setdefault("batch_id", batch_id)
        manifest.setdefault("game_count", len(records))
        manifest.setdefault("schema_version", records[0]["schema_version"] if records else None)
        with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=1)
    return written


def read_metadata(out_dir: str):
    """Read the JSONL into a list of dicts (metadata lines only)."""
    path = os.path.join(out_dir, "games.jsonl")
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_game(out_dir: str, game_id: str) -> dict:
    path = os.path.join(out_dir, "games", f"{game_id}.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def iter_game_files(out_dir: str):
    """Yield full records for every saved game in ``out_dir`` (in file order)."""
    games_dir = os.path.join(out_dir, "games")
    if not os.path.isdir(games_dir):
        return
    names = sorted(f for f in os.listdir(games_dir) if f.endswith(".json"))
    for name in names:
        with open(os.path.join(games_dir, name), encoding="utf-8") as fh:
            yield json.load(fh)


def write_manifest(out_dir: str, manifest: dict):
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
