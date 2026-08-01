"""Concurrency-safe updates for chapter cast image generation metadata."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_records(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def persist_records(path: Path, records: list[dict[str, Any]]) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as destination:
        temporary_path = Path(destination.name)
        for record in records:
            destination.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temporary_path, path)


def upsert_image_generation(
    path: Path,
    chapter_number: int,
    cast_index: int,
    generation_record: dict[str, Any],
) -> None:
    """Merge one provider result into the latest JSONL under an exclusive lock."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = load_records(path)
        chapter = next(
            record
            for record in records
            if int(record["chapter_number"]) == chapter_number
        )
        cast = chapter["cast"][cast_index]
        generations = cast.setdefault("image_generations", [])
        existing = next(
            (
                generation
                for generation in generations
                if generation.get("genaimodel")
                == generation_record["genaimodel"]
            ),
            None,
        )
        if existing is None:
            generations.append(generation_record)
        else:
            existing.update(generation_record)
        persist_records(path, records)
        fcntl.flock(lock, fcntl.LOCK_UN)
