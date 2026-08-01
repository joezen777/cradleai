#!/usr/bin/env python3
"""Atomically clear generated fields before a complete pipeline rerun."""

import argparse
import json
import os
import tempfile
from pathlib import Path


CLEAR_FIELDS = (
    "prompt_text",
    "gen_filename",
    "timestamp",
    "gcp_success",
    "gcp_error",
    "similarity_score",
    "generation_timestamp",
    "generation_error",
    "generaation_timestamp",
    "seed",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("output/metadatagen_full.jsonl"),
    )
    args = parser.parse_args()

    with args.metadata.open("r", encoding="utf-8") as source:
        records = [json.loads(line) for line in source if line.strip()]
    if not records:
        raise ValueError(f"Metadata is empty: {args.metadata}")

    for record in records:
        for field in CLEAR_FIELDS:
            record[field] = ""

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=args.metadata.parent,
        prefix=f".{args.metadata.name}.",
        delete=False,
    ) as destination:
        temporary_path = Path(destination.name)
        for record in records:
            destination.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )
    os.replace(temporary_path, args.metadata)
    print(
        f"Cleared {len(CLEAR_FIELDS)} fields in {len(records)} records: "
        f"{args.metadata}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
