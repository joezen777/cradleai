#!/usr/bin/env python3
"""Finish all resumable lore stages, optionally after another worker exits."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
PYTHON = PROJECT / ".venv" / "bin" / "python"
ENV = {**os.environ, "PYTHONPATH": str(ROOT)}


def run(*args: str) -> None:
    print("Running:", " ".join(args), flush=True)
    subprocess.run(args, cwd=PROJECT, env=ENV, check=True)


def statuses(filename: str) -> Counter:
    path = ROOT / "data" / filename
    if not path.is_file():
        return Counter()
    return Counter(
        json.loads(line).get("status")
        for line in path.open(encoding="utf-8") if line.strip()
    )


def wait_for_pid(pid: int) -> None:
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        print(f"Waiting for extraction worker PID {pid}...", flush=True)
        time.sleep(30)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-pid", type=int)
    args = parser.parse_args()
    complete_marker = ROOT / "data" / "processing_complete.json"
    complete_marker.unlink(missing_ok=True)
    if args.wait_pid:
        wait_for_pid(args.wait_pid)

    # Broad pass handles anything left if the preceding worker stopped early.
    run(str(PYTHON), "-m", "loredb.extract", "--batch-size", "8")
    for attempt in range(1, 4):
        extraction = statuses("passage_extractions.jsonl")
        if sum(count for status, count in extraction.items() if not str(status).startswith("success")) == 0:
            break
        print(f"Single-passage extraction retry {attempt}/3", flush=True)
        run(str(PYTHON), "-m", "loredb.extract", "--batch-size", "1")
    extraction = statuses("passage_extractions.jsonl")
    if sum(count for status, count in extraction.items() if not str(status).startswith("success")):
        print("Repairing stubborn passages with paragraph-safe chunking", flush=True)
        run(str(PYTHON), "-m", "loredb.repair_extractions")

    for attempt in range(1, 4):
        run(str(PYTHON), "-m", "loredb.treatments")
        treatment = statuses("chapter_treatments.jsonl")
        if treatment.get("success", 0) == 40:
            break
        print(f"Treatment retry {attempt}/3 incomplete: {dict(treatment)}", flush=True)

    run(str(PYTHON), "-m", "loredb.resolve_aliases")
    run(str(PYTHON), "-m", "loredb.rebuild_graph")
    run(str(PYTHON), "-m", "loredb.export_catalog")
    run(str(PYTHON), "-m", "lore_api.build_indexes")
    run(str(PYTHON), "-m", "loredb.validate")
    index = json.loads((ROOT / "data" / "service_index.json").read_text(encoding="utf-8"))
    complete_marker.write_text(json.dumps({
        "status": "complete",
        "completed_at_epoch": time.time(),
        "corpus_fingerprint": index["corpus_fingerprint"],
        "passage_count": len(index["passage_context"]),
        "character_count": len(index["characters"]),
        "setting_count": len(index["settings"]),
        "prop_count": len(index["props"]),
    }, indent=2) + "\n", encoding="utf-8")
    print("Lore ingestion and processing complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
