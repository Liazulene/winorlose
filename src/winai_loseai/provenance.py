"""Content-addressed experimental source lock (UTF-8, LF-normalised).

All package Python sources and the entry point are included. Analysis outside
the package, reports and tests can evolve without changing the experiment.
The import-time lock identifies loaded code; a fresh disk check before writes
also prevents continuing after an on-disk edit during a running batch.
"""
import hashlib
import json
import platform
from pathlib import Path

from . import CODE_VERSION, SCHEMA_VERSION


def source_inventory(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    paths = [root / "run.py", *sorted((root / "src/winai_loseai").rglob("*.py"))]
    return {p.relative_to(root).as_posix(): hashlib.sha256(
        p.read_text(encoding="utf-8").encode("utf-8")).hexdigest() for p in paths}


def fingerprint(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


SOURCE_FILES = source_inventory()
SOURCE_FINGERPRINT = fingerprint(SOURCE_FILES)


def current_provenance():
    if fingerprint(source_inventory()) != SOURCE_FINGERPRINT:
        raise RuntimeError("experiment source changed during this process; use a fresh version/directory")
    return {"code_version": CODE_VERSION, "schema_version": SCHEMA_VERSION,
            "source_fingerprint": SOURCE_FINGERPRINT,
            "python_version": platform.python_version()}


def source_lock():
    return {**current_provenance(), "algorithm": "sha256-utf8-lf-path-map-v1",
            "files": dict(SOURCE_FILES)}
