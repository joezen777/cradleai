#!/usr/bin/env python3
"""Validate checkpoints and resume every unfinished lore build stage."""

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
PYTHON = PROJECT / ".venv" / "bin" / "python"


def validate_jsonl(path: Path) -> Counter:
    statuses: Counter = Counter()
    if not path.exists():
        return statuses
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                statuses[json.loads(line).get("status")] += 1
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid checkpoint {path}:{line_number}: {exc}") from exc
    return statuses


def main() -> int:
    if not PYTHON.is_file():
        raise SystemExit(f"Virtualenv Python is missing: {PYTHON}")
    extraction = validate_jsonl(ROOT / "data" / "passage_extractions.jsonl")
    treatments = validate_jsonl(ROOT / "data" / "chapter_treatments.jsonl")
    print(f"Extraction checkpoint: {dict(extraction)}", flush=True)
    print(f"Treatment checkpoint: {dict(treatments)}", flush=True)
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [str(PYTHON), str(ROOT / "finish_processing.py")],
        cwd=PROJECT,
        env=environment,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
