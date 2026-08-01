#!/usr/bin/env python3
"""Supervise resumable one-at-a-time Gemini cast image generation."""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
METADATA = ROOT / "output" / "gemini_chapter_cast.jsonl"
LOG = ROOT / "output" / "gemini_cast_image_supervisor.log"
WORKER = ROOT / "generate_cast_images_gemini.py"
PYTHON = ROOT / ".venv" / "bin" / "python"


def progress() -> tuple[int, int]:
    records = [
        json.loads(line)
        for line in METADATA.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cast = [item for record in records for item in record.get("cast", [])]
    return (
        sum(
            any(
                generation.get("gen_character_image")
                for generation in item.get("image_generations", [])
            )
            for item in cast
        ),
        len(cast),
    )


def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    with LOG.open("a", encoding="utf-8") as destination:
        destination.write(f"{timestamp} {message}\n")


def main() -> int:
    while True:
        completed, total = progress()
        log(f"progress={completed}/{total}")
        if completed >= total:
            log("complete")
            return 0
        result = subprocess.run(
            [
                str(PYTHON),
                str(WORKER),
                "--max-images",
                "1",
                "--max-retries",
                "1",
                "--cooldown",
                "0",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        detail = " ".join((result.stdout + result.stderr).splitlines())[-2000:]
        log(f"worker_exit={result.returncode} {detail}")
        time.sleep(30 if result.returncode == 0 else 60)


if __name__ == "__main__":
    raise SystemExit(main())
