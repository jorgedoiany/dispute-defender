"""Freeze hashes for the T-007 evaluation (ADR-011).

Before the live run, `scripts/run_evaluation.py freeze` records hashes of the scenarios,
the scoring rules, the prompt and schema, and the pipeline in `evaluation/frozen.json`.
A live run refuses to start unless the current hashes equal the last freeze, and every
raw result line carries the hashes it ran with, so a change after a first run shows in
the report.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .scenarios import EVAL_DIR, REPO_ROOT, SCENARIO_DIR, scenario_files

FROZEN_PATH = EVAL_DIR / "frozen.json"
_PKG = REPO_ROOT / "dispute_defender"

HASHED_FILES: dict[str, list[Path]] = {
    "scoring": [_PKG / "evaluation" / "scoring.py"],
    "prompt": [_PKG / "drafter" / "prompt.py", _PKG / "drafter" / "schema.py"],
    "pipeline": [
        _PKG / "claims" / "verifier.py", _PKG / "drafter" / "drafter.py", _PKG / "response" / "render.py",
        _PKG / "response" / "send.py", _PKG / "response" / "carriers.py", _PKG / "evaluation" / "pipeline.py",
    ],
}


def _digest(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(paths):
        name = path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path.name
        h.update(name.encode() + b"\0")
        h.update(path.read_bytes() + b"\0")
    return h.hexdigest()


def current_hashes(scenario_dir: Path = SCENARIO_DIR) -> dict[str, str]:
    groups = {"scenarios": scenario_files(scenario_dir), **HASHED_FILES}
    return {name: _digest(paths) for name, paths in groups.items()}


def load_freezes(path: Path = FROZEN_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("freezes", []))


def freeze(now: datetime, path: Path = FROZEN_PATH, scenario_dir: Path = SCENARIO_DIR) -> dict[str, Any]:
    freezes = load_freezes(path)
    entry = {"frozen_at": now.isoformat(timespec="seconds"), "hashes": current_hashes(scenario_dir)}
    freezes.append(entry)
    path.write_text(json.dumps({
        "notice": "Hashes recorded before the T-007 live run (ADR-011). Each later freeze is a declared change.",
        "freezes": freezes,
    }, indent=2) + "\n", encoding="utf-8")
    return entry


def freeze_status(path: Path = FROZEN_PATH, scenario_dir: Path = SCENARIO_DIR) -> tuple[str, dict[str, Any] | None]:
    """('missing', None), ('match', last) or ('differs', last)."""
    freezes = load_freezes(path)
    if not freezes:
        return "missing", None
    last = freezes[-1]
    return ("match" if last["hashes"] == current_hashes(scenario_dir) else "differs"), last
