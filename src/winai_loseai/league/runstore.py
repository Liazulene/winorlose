"""Persistent, resumable batch-run store.

Long formal batches are no longer buffered in memory until the end.  A run
directory owns:

* ``plan.json``        the full ordered job plan (index, seed, both specs);
* ``manifest.json``    live status / progress (running|completed|interrupted|failed);
* ``game_seeds.json``  (index, game_seed) mirror of the plan;
* ``games.jsonl``      one compact metadata line per *completed* game (append);
* ``games/<id>.json``  full record, written to ``.tmp`` then atomically renamed.

Rules enforced here:

* each full game file is written atomically (tmp + ``os.replace``), so a crash
  never leaves a half game under its final name;
* a JSONL line is appended (with flush) only once per game id;
* completion is decided on resume from *disk* (valid file + matching JSONL
  line), never from a stale in-memory counter -- corrupt/temp files are simply
  re-run;
* resume validates that the requested batch matches the stored one (batch,
  board, komi, seed, agent plan, planned count) before touching anything;
* summary/replay integrity helpers refuse to proceed when the JSONL, game
  files and manifest disagree.
"""

from __future__ import annotations

import json
import os

from datetime import datetime, timezone

from .. import SCHEMA_VERSION, CODE_VERSION
from ..provenance import current_provenance, source_lock
from ..spec import AgentSpec
from ..game.scoring import ruleset_name, validate_komi
from .storage import prepare_out_dir, read_metadata, _metadata_line

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_INTERRUPTED = "interrupted"
STATUS_FAILED = "failed"
STATUS_VALIDATION_FAILED = "validation_failed"


class RunError(Exception):
    pass


class NotARunDirectory(RunError):
    pass


class ConfigMismatch(RunError):
    pass


class RunInconsistent(RunError):
    pass


class MetadataCorrupt(RunError):
    """games.jsonl is damaged beyond the auto-recoverable trailing line."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _load_json_safe(path):
    """Like ``_load_json`` but returns None on any read/parse error."""
    try:
        return _load_json(path)
    except (OSError, ValueError, TypeError):
        return None


def _write_json_atomic(path, obj):
    """Write ``obj`` to ``path`` via a same-directory temp file + rename."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.flush()
    os.replace(tmp, path)


def _write_text_atomic(path, text: str):
    """Write raw ``text`` to ``path`` via a same-directory temp file + rename."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
    os.replace(tmp, path)


def job_to_entry(job: dict) -> dict:
    return {
        "index": int(job["index"]),
        "game_seed": int(job["game_seed"]),
        "black": job["black"].to_dict(),
        "white": job["white"].to_dict(),
        **({"pass_min_ply":job["pass_min_ply"]} if "pass_min_ply" in job else {}),
        **({"komi":validate_komi(job["komi"])} if "komi" in job else {}),
        **({"ruleset":job["ruleset"]} if "ruleset" in job else {}),
    }


def entry_to_job(entry: dict, batch_id: str) -> dict:
    return {
        "index": int(entry["index"]),
        "game_seed": int(entry["game_seed"]),
        "batch_id": batch_id,
        "black": AgentSpec.from_dict(entry["black"]),
        "white": AgentSpec.from_dict(entry["white"]),
        **({"pass_min_ply":entry["pass_min_ply"]} if "pass_min_ply" in entry else {}),
        **({"komi":validate_komi(entry["komi"])} if "komi" in entry else {}),
        **({"ruleset":entry["ruleset"]} if "ruleset" in entry else {}),
    }


def expected_game_id(batch_id: str, index: int) -> str:
    return f"{batch_id}-g{index:06d}"


def _configuration_matches(record, entry, manifest, *, metadata=False):
    """Check the resolved per-job scoring configuration without mutation."""
    expected_komi = entry.get("komi", manifest.get("komi"))
    try:
        validate_komi(expected_komi)
        validate_komi(record.get("komi"))
    except ValueError:
        return False
    if (record.get("game_seed") != entry["game_seed"]
            or record.get("board_size") != manifest.get("board_size")
            or record.get("komi") != expected_komi
            or ("pass_min_ply" in entry and
                (type(record.get("pass_min_ply")) is not int or
                 record["pass_min_ply"] != entry["pass_min_ply"]))):
        return False
    if not metadata and (record.get("black") != entry["black"]
                         or record.get("white") != entry["white"]):
        return False
    if "komi" in entry:
        # New per-job arms must name the complete scoring/pass definition.
        expected_ruleset = ruleset_name(entry.get("pass_min_ply", 0), expected_komi)
        if record.get("ruleset") != expected_ruleset:
            return False
    if "ruleset" in entry and record.get("ruleset") != entry["ruleset"]:
        return False
    return True


# --------------------------------------------------------------------------
# Robust games.jsonl parsing / repair.
# --------------------------------------------------------------------------
def _split_metadata_lines(text: str):
    """Return ``(valid_lines, bad_line_numbers)``.

    ``valid_lines`` is a list of ``(line_number, dict)`` for lines that parse.
    Whitespace-only lines are ignored.  Lines that do not parse go into
    ``bad_line_numbers``; the caller decides whether they form a trailing torn
    tail (repairable) or are mid-file corruption (must be reported).
    """
    valid = []
    bad = []
    for lineno, raw in enumerate(text.split("\n")):
        if not raw.strip():
            continue
        try:
            valid.append((lineno, json.loads(raw)))
        except (ValueError, TypeError):
            bad.append(lineno)
    return valid, bad


def repair_metadata(out_dir: str):
    """Normalise ``games.jsonl`` and return repair stats.

    * drops a trailing torn line (a crash mid-append) -- the only auto-repair;
    * rebuilds a missing metadata line from an atomically-saved, valid game
      JSON when the game file exists and matches the plan;
    * never produces duplicate game ids (the whole file is rewritten in
      ``game_index`` order when anything changed);
    * raises :class:`MetadataCorrupt` if a non-terminal line is damaged or a
      duplicate / unknown game id is present -- it never "fixes" those.

    Returns ``{"tail_removed", "rebuilt", "rewritten"}``.
    """
    manifest = _load_json(os.path.join(out_dir, "manifest.json"), {})
    entries = _load_json(os.path.join(out_dir, "plan.json"), [])
    if not manifest or not entries:
        raise NotARunDirectory(
            f"cannot repair metadata without manifest.json/plan.json: {out_dir!r}"
        )
    batch_id = manifest.get("batch_id")
    meta_path = os.path.join(out_dir, "games.jsonl")

    text = ""
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as fh:
            text = fh.read()
    valid, bad = _split_metadata_lines(text)

    tail_torn = len(bad) > 0
    if bad:
        last_valid = max((ln for ln, _ in valid), default=-1)
        if any(ln <= last_valid for ln in bad):
            raise MetadataCorrupt(
                f"games.jsonl has a corrupt NON-terminal line (line numbers "
                f"{sorted(bad)}); refusing to auto-repair -- inspect the file."
            )

    # Existing valid lines must be unique and belong to this run's plan.
    existing = {}          # game_id -> dict
    existing_index = {}    # game_id -> declared game_index
    for _ln, line in valid:
        gid = line.get("game_id")
        if gid in existing:
            raise MetadataCorrupt(f"duplicate game_id in games.jsonl: {gid!r}")
        existing[gid] = line
        existing_index[gid] = line.get("game_index")
    expected_ids = {expected_game_id(batch_id, int(e["index"])): e
                    for e in entries}
    for gid in existing:
        if gid not in expected_ids:
            raise MetadataCorrupt(
                f"games.jsonl contains game_id {gid!r} which is not in plan.json"
            )

    merged = []
    rebuilt = 0
    for e in sorted(entries, key=lambda e: int(e["index"])):
        idx = int(e["index"])
        gid = expected_game_id(batch_id, idx)
        if gid in existing:
            if int(existing_index[gid]) != idx:
                raise MetadataCorrupt(
                    f"game_id {gid!r} metadata declares game_index "
                    f"{existing_index[gid]} but plan expects {idx}"
                )
            merged.append(existing[gid])
            continue
        rec = _load_json_safe(os.path.join(out_dir, "games", f"{gid}.json"))
        if (isinstance(rec, dict) and rec.get("game_id") == gid
                and rec.get("game_index") == idx):
            merged.append(_metadata_line(rec))
            rebuilt += 1

    new_text = "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in merged)
    rewritten = new_text != text
    if rewritten:
        _write_text_atomic(meta_path, new_text)
    return {
        "tail_removed": tail_torn,
        "rebuilt": rebuilt,
        "rewritten": rewritten,
    }


def update_status(out_dir: str, status: str, error=None):
    """Set ``manifest.status`` (and optional error) without recomputing counts."""
    path = os.path.join(out_dir, "manifest.json")
    doc = _load_json(path)
    if not isinstance(doc, dict):
        raise NotARunDirectory(f"missing manifest.json: {out_dir!r}")
    doc["status"] = status
    if error is not None:
        doc["error"] = error
    doc["last_updated"] = _now()
    _write_json_atomic(path, doc)


# --------------------------------------------------------------------------
class RunStore:
    def __init__(self, out_dir: str):
        self.out_dir = os.path.abspath(out_dir)
        self.batch_id = None
        self.cfg = {}
        self.entries = []       # plan entries (dicts)
        self.completed = set()  # completed *game indexes*
        self._seen_meta = set()  # game ids already present in games.jsonl
        self.created_at = None

    # -- layout ------------------------------------------------------------
    @property
    def plan_path(self):
        return os.path.join(self.out_dir, "plan.json")

    @property
    def manifest_path(self):
        return os.path.join(self.out_dir, "manifest.json")

    @property
    def seeds_path(self):
        return os.path.join(self.out_dir, "game_seeds.json")

    @property
    def meta_path(self):
        return os.path.join(self.out_dir, "games.jsonl")

    @property
    def games_dir(self):
        return os.path.join(self.out_dir, "games")

    def game_path(self, game_id: str):
        return os.path.join(self.games_dir, f"{game_id}.json")

    def is_run(self) -> bool:
        return os.path.isfile(self.manifest_path) and os.path.isfile(self.plan_path)

    # -- manifest ----------------------------------------------------------
    def _manifest_doc(self, status: str, error=None):
        return {
            **self.provenance,
            "schema_version": SCHEMA_VERSION,
            "code_version": CODE_VERSION,
            "batch_id": self.cfg.get("batch_id"),
            "kind": self.cfg.get("kind"),
            "status": status,
            "requested_games": self.cfg.get("requested_games"),
            "planned_game_count": len(self.entries),
            "board_size": self.cfg.get("board_size"),
            "komi": self.cfg.get("komi"),
            "batch_seed": self.cfg.get("batch_seed"),
            "concurrency": self.cfg.get("concurrency"),
            **{k:self.cfg[k] for k in ("pass_min_plies","komis","budget","schedule_seed") if k in self.cfg},
            "completed_game_count": len(self.completed),
            "completed_indexes": sorted(self.completed),
            "created_at": self.created_at,
            "last_updated": _now(),
            "agents": self._agent_list(),
            "error": error,
        }

    def _agent_list(self):
        seen = {}
        for e in self.entries:
            for key in ("black", "white"):
                spec = e[key]
                seen.setdefault(spec["agent_id"], spec)
        return list(seen.values())

    def _write_manifest(self, status: str, error=None):
        _write_json_atomic(self.manifest_path, self._manifest_doc(status, error=error))

    # -- lifecycle ---------------------------------------------------------
    def start(self, jobs, cfg, overwrite: bool = False):
        """Begin a fresh run: refuse/clear the dir, write plan + manifest."""
        self.provenance = current_provenance()
        prepare_out_dir(self.out_dir, overwrite=overwrite)
        self.cfg = dict(cfg)
        self.batch_id = cfg["batch_id"]
        self.entries = [job_to_entry(j) for j in jobs]
        self.completed = set()
        self._seen_meta = set()
        self.created_at = _now()

        os.makedirs(self.games_dir, exist_ok=True)
        _write_json_atomic(os.path.join(self.out_dir, "source_lock.json"), source_lock())
        _write_json_atomic(self.plan_path, self.entries)
        _write_json_atomic(
            self.seeds_path,
            [{"index": e["index"], "game_seed": e["game_seed"]} for e in self.entries],
        )
        self._write_manifest(STATUS_RUNNING)
        return self

    def open_for_resume(self, jobs, cfg):
        """Validate and reopen a previous run, skipping already-saved games."""
        if not self.is_run():
            raise NotARunDirectory(
                f"not a resumable run directory (no plan.json / manifest.json): "
                f"{self.out_dir!r}"
            )
        stored_manifest = _load_json(self.manifest_path, {})
        stored_entries = _load_json(self.plan_path, [])

        new_entries = [job_to_entry(j) for j in jobs]
        self._validate_resume(stored_manifest, stored_entries, new_entries, cfg)
        self.provenance = current_provenance()
        planned = {expected_game_id(cfg["batch_id"], e["index"]): e
                   for e in stored_entries}
        def check_configuration(rec, *, metadata=False):
            entry = planned.get(rec.get("game_id"))
            if entry is not None and not _configuration_matches(
                    rec, entry, stored_manifest, metadata=metadata):
                raise ConfigMismatch(
                    f"cannot resume: game {entry['index']} configuration differs from plan")
        # Inspect every parseable saved record before ANY repair or mutation.
        candidates, _ = _split_metadata_lines(
            open(self.meta_path, encoding="utf-8").read()
            if os.path.exists(self.meta_path) else "")
        for _, rec in candidates:
            self._check_provenance(rec)
            check_configuration(rec, metadata=True)
        for name in os.listdir(self.games_dir):
            if name.endswith(".json"):
                rec = _load_json_safe(os.path.join(self.games_dir, name))
                if isinstance(rec, dict):
                    self._check_provenance(rec)
                    check_configuration(rec)

        self.cfg = dict(cfg)
        self.batch_id = cfg["batch_id"]
        self.entries = stored_entries
        self.created_at = stored_manifest.get("created_at") or _now()

        # Normalise games.jsonl first: drop a torn trailing line (crash during
        # append), rebuild metadata missing from an otherwise valid game file.
        # A corrupt mid-file line raises MetadataCorrupt instead of being fixed.
        repair_metadata(self.out_dir)

        self._seen_meta = {line["game_id"] for line in read_metadata(self.out_dir)}
        self.completed = self._completed_on_disk()
        # Note: we deliberately do *not* touch the manifest here.  The caller
        # marks the run "running" only when there is actually work to do, so a
        # second --resume of an already-completed run leaves every file intact.
        return self

    def manifest_status(self):
        doc = _load_json(self.manifest_path, {})
        return doc.get("status")

    def _validate_resume(self, stored_manifest, stored_entries, new_entries, cfg):
        self.provenance = current_provenance()
        self._check_provenance(stored_manifest)
        lock = _load_json_safe(os.path.join(self.out_dir, "source_lock.json"))
        if lock != source_lock():
            raise ConfigMismatch("cannot resume: source_lock.json differs or is missing")
        if not stored_entries:
            raise ConfigMismatch("stored plan is empty/corrupt; cannot resume")

        for field in ("batch_id", "kind", "requested_games",
                      "batch_seed", "board_size", "komi", "komis", "pass_min_plies", "budget", "schedule_seed"):
            if stored_manifest.get(field) != cfg.get(field):
                raise ConfigMismatch(
                    f"cannot resume: stored {field}={stored_manifest.get(field)!r} "
                    f"!= requested {cfg.get(field)!r}"
                )
        if int(stored_manifest.get("planned_game_count", -1)) != len(stored_entries):
            raise ConfigMismatch("stored plan length disagrees with manifest")
        if new_entries != stored_entries:
            raise ConfigMismatch(
                "cannot resume: the regenerated job plan differs from the stored "
                "plan (batch/agents/seeds/count changed). Use a fresh directory."
            )

    def _check_provenance(self, record):
        for key, value in self.provenance.items():
            if record.get(key) != value:
                raise ConfigMismatch(f"cannot resume/write: {key} mismatch; use a fresh directory")

    # -- completion detection ----------------------------------------------
    def _completed_on_disk(self):
        """Indexes whose full file AND JSONL line exist and are consistent."""
        meta = read_metadata(self.out_dir)
        meta_index = {line.get("game_id"): line.get("game_index") for line in meta}
        done = set()
        for e in self.entries:
            idx = int(e["index"])
            gid = expected_game_id(self.batch_id, idx)
            if meta_index.get(gid) != idx:
                continue
            rec = _load_json_safe(self.game_path(gid))
            if not isinstance(rec, dict):
                continue
            if rec.get("game_id") != gid or rec.get("game_index") != idx:
                continue
            done.add(idx)
        return done

    # -- per-game persistence ----------------------------------------------
    def write_game(self, record: dict):
        """Atomically persist one finished game and append its JSONL once."""
        current_provenance()
        self._check_provenance(record)
        gid = record["game_id"]
        index = int(record["game_index"])
        entry = next((e for e in self.entries if e["index"] == index), None)
        if (entry is None or gid != expected_game_id(self.batch_id, index)
                or not _configuration_matches(record, entry, self.cfg)):
            raise ConfigMismatch(f"cannot write: game {index} configuration differs from plan")
        _write_json_atomic(self.game_path(gid), record)
        if gid not in self._seen_meta:
            with open(self.meta_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(_metadata_line(record), ensure_ascii=False) + "\n")
                fh.flush()
            self._seen_meta.add(gid)
        self.completed.add(index)

    def update(self, status: str = STATUS_RUNNING, error=None):
        self._write_manifest(status, error=error)

    def finish(self):
        """Mark the run completed (all planned games persisted)."""
        self._write_manifest(STATUS_COMPLETED)

    # -- summary-relevant state --------------------------------------------
    def pending_indexes(self):
        return sorted(idx for e in self.entries
                      if (idx := int(e["index"])) not in self.completed)


# --------------------------------------------------------------------------
# Integrity helpers used before summary / replay.
# --------------------------------------------------------------------------
def load_manifest(out_dir: str) -> dict:
    path = os.path.join(out_dir, "manifest.json")
    doc = _load_json(path)
    if not isinstance(doc, dict):
        raise NotARunDirectory(f"missing manifest.json: {out_dir!r}")
    return doc


def integrity_problems(out_dir: str):
    """List inconsistencies between plan, manifest, JSONL and game files."""
    problems = []
    manifest = _load_json(os.path.join(out_dir, "manifest.json"), {})
    entries = _load_json(os.path.join(out_dir, "plan.json"), [])
    if not manifest or not entries:
        return ["missing manifest.json or plan.json"]
    planned = int(manifest.get("planned_game_count", -1))
    if planned != len(entries):
        problems.append(
            f"planned_game_count={planned} != plan length {len(entries)}"
        )

    meta = read_metadata(out_dir)
    meta_ids = [line.get("game_id") for line in meta]
    if len(meta_ids) != len(set(meta_ids)):
        problems.append("games.jsonl contains duplicate game ids")
    meta_index = {line.get("game_id"): line.get("game_index") for line in meta}

    expected_ids = set()
    locked = bool(manifest.get("source_fingerprint"))
    meta_by_id = {line.get("game_id"): line for line in meta}
    if locked:
        indexes = [line.get("game_index") for line in meta]
        if indexes != sorted(set(indexes)):
            problems.append("games.jsonl is not strictly ascending by game_index")
        lock = _load_json_safe(os.path.join(out_dir, "source_lock.json"))
        from ..provenance import fingerprint
        if not isinstance(lock, dict) or fingerprint(lock.get("files", {})) != manifest["source_fingerprint"]:
            problems.append("source lock missing or inconsistent")
    for e in entries:
        gid = expected_game_id(manifest.get("batch_id"), int(e["index"]))
        expected_ids.add(gid)
        rec = _load_json_safe(os.path.join(out_dir, "games", f"{gid}.json"))
        ok = (isinstance(rec, dict)
              and rec.get("game_id") == gid
              and rec.get("game_index") == int(e["index"])
              and meta_index.get(gid) == int(e["index"]))
        if not ok:
            problems.append(f"game {int(e['index'])} not fully saved/consistent")
        elif locked:
            for key in ("code_version", "schema_version", "source_fingerprint", "python_version"):
                if rec.get(key) != manifest.get(key) or meta_by_id[gid].get(key) != manifest.get(key):
                    problems.append(f"game {e['index']} provenance mismatch: {key}")
            if not _configuration_matches(rec, e, manifest):
                problems.append(f"game {e['index']} configuration differs from plan")
            if not _configuration_matches(meta_by_id[gid], e, manifest, metadata=True):
                problems.append(f"game {e['index']} metadata configuration differs from plan")

    # any extra game files not in the plan?
    games_dir = os.path.join(out_dir, "games")
    if os.path.isdir(games_dir):
        for name in os.listdir(games_dir):
            if name.endswith(".json"):
                if name[:-5] not in expected_ids:
                    problems.append(f"unexpected game file {name}")
            elif not name.endswith(".tmp"):
                problems.append(f"unexpected file in games/: {name}")

    status = manifest.get("status")
    if status == STATUS_COMPLETED:
        if len(meta) != planned:
            problems.append(
                f"completed run: games.jsonl has {len(meta)} lines, planned {planned}"
            )
        if manifest.get("completed_game_count") != planned:
            problems.append(
                f"completed run: manifest completed_game_count="
                f"{manifest.get('completed_game_count')} != planned {planned}"
            )
    return problems
