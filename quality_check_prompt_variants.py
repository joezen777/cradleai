#!/usr/bin/env python3
"""Manual-review gate for prompt variation and Lindon's canonical badge."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

FORBIDDEN_BADGE = re.compile(r"\b(rectangular|hexagonal|belt|buckle|sash|shoulder|pinned)\b", re.I)


def badge_errors(text: str) -> list[str]:
    lowered = text.casefold()
    if "lindon" not in lowered or "badge" not in lowered:
        return []
    errors = []
    required = {
        "circular wooden badge": "circular wooden badge",
        "neck cord": "cord around his neck",
        "Chinese character": "chinese character",
        "meaning empty": "empty",
    }
    for label, phrase in required.items():
        if phrase not in lowered:
            errors.append(f"missing {label}")
    forbidden = sorted(set(match.group(0).lower() for match in FORBIDDEN_BADGE.finditer(text)))
    if forbidden:
        errors.append("forbidden badge description: " + ", ".join(forbidden))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=Path("output/metadatagen_variants.jsonl"))
    parser.add_argument("--scenes", nargs="*", type=int)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.metadata.open() if line.strip()]
    if args.scenes:
        rows = [row for row in rows if int(row.get("scene_index", -1)) in args.scenes]
    groups = defaultdict(list)
    errors = []
    for row in rows:
        groups[row.get("frame_file")].append(row)
        for error in badge_errors(str(row.get("prompt_text") or "")):
            errors.append(f"{row.get('frame_file')} sequence {row.get('gen_sequence')}: {error}")
    for frame, entries in groups.items():
        entries.sort(key=lambda row: int(row.get("gen_sequence", 0)))
        prompts = {str(row.get("prompt_text") or "").strip() for row in entries}
        variations = {row.get("variation_id") for row in entries}
        bases = {str(row.get("base_prompt_text") or "").strip() for row in entries}
        if len(entries) != 10:
            errors.append(f"{frame}: expected 10 entries, found {len(entries)}")
        if len(prompts) != len(entries):
            errors.append(f"{frame}: prompt texts are not all unique")
        if len(variations) != len(entries):
            errors.append(f"{frame}: variation IDs are not all unique")
        if len(bases) != 1 or not next(iter(bases), ""):
            errors.append(f"{frame}: variants do not share exactly one non-empty locked base prompt")
    print(f"Reviewed {len(rows)} prompts across {len(groups)} frames")
    if errors:
        print("QUALITY CHECK FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("QUALITY CHECK PASSED")
    print("Lindon badge rule: circular wooden badge on a neck cord, marked with the Chinese character meaning empty.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
