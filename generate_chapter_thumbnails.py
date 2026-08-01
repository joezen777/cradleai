#!/usr/bin/env python3
"""Generate five-second chapter thumbnails and update chapter metadata."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_METADATA = ROOT / "output" / "pegasus_chapter_metadata.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "pegasus_chapter_thumbnails"


def persist(path: Path, records: list[dict]) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as destination:
        temporary = Path(destination.name)
        for record in records:
            destination.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    records = [
        json.loads(line)
        for line in args.metadata.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        chapter = int(record["chapter_index"])
        relative_video = record["aggregate_clip_file"].replace("\\", "/")
        if relative_video.startswith("output/"):
            relative_video = relative_video[7:]
        video = ROOT / "output" / Path(relative_video)
        thumbnail = args.output_dir / f"chapter_{chapter:03d}.jpg"
        seek = min(5.0, max(0.0, float(record["duration_seconds"]) / 2))
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str(seek),
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(thumbnail),
            ],
            check=True,
        )
        record["thumbnail"] = str(
            thumbnail.relative_to(ROOT / "output")
        ).replace("/", "\\")
        print(f"Chapter {chapter}: {thumbnail.name}")
    persist(args.metadata, records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
