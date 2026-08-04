#!/usr/bin/env python3
"""Backfill first_mention and descriptive_phrases into bookcast.jsonl.

Purely deterministic — reads lore_graph/data/service_index.json and mutates
existing bookcast.jsonl records in place, preserving every field the record
already carries (evidence resolution logic lives in bookcast_evidence.py so
it stays shared with the enrichment interview in Track C).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bookcast_evidence import (
    build_first_mention,
    descriptive_phrases,
    first_mention_sentence,
    resolve_anchor_passage,
    resolve_character,
)

ROOT = Path(__file__).resolve().parent
BOOKCAST_PATH = ROOT / "bookcast.jsonl"
INDEX_PATH = ROOT / "lore_graph" / "data" / "service_index.json"


def load_bookcast(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def save_bookcast(path: Path, records: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(path)


def backfill_record(index: dict[str, Any], record: dict[str, Any]) -> str:
    """Mutate record in place. Returns a short status string for reporting."""
    character_id, character = resolve_character(index, record)
    if character is None:
        record["first_mention"] = None
        record["descriptive_phrases"] = []
        return "unresolved"

    passage_id = resolve_anchor_passage(record, character)
    if not passage_id:
        record["first_mention"] = None
        record["descriptive_phrases"] = []
        return "no-anchor-passage"

    location = index.get("passage_context", {}).get(passage_id, {}).get("location", {})
    names = [character.get("canonical_name") or character.get("stable_label") or ""]
    names.extend(character.get("aliases") or [])
    sentence = first_mention_sentence(location.get("surrounding_paragraph", ""), names)

    record["first_mention"] = build_first_mention(index, passage_id, sentence)
    record["descriptive_phrases"] = descriptive_phrases(character, passage_id)
    record["_resolved_character_id"] = character_id
    return "ok" if sentence else "empty-sentence"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bookcast", type=Path, default=BOOKCAST_PATH)
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index = json.loads(args.index.read_text(encoding="utf-8"))
    records = load_bookcast(args.bookcast)

    targets = records[: args.limit] if args.limit else records
    statuses: dict[str, int] = {}
    for i, record in enumerate(targets):
        status = backfill_record(index, record)
        statuses[status] = statuses.get(status, 0) + 1
        if args.dry_run:
            name = record.get("canonical_name", "?")
            fm = (record.get("first_mention") or {}).get("sentence", "")
            phrases = record.get("descriptive_phrases", [])
            print(f"[{i+1}/{len(targets)}] {name} ({status})")
            print(f"    first_mention: {fm[:120]}")
            for p in phrases[:3]:
                print(f"    phrase: {p['text'][:100]}")
            print()

    print(f"Processed {len(targets)} records: {statuses}")
    if not args.dry_run:
        # _resolved_character_id was only for the report above; strip it so
        # the persisted schema stays free of debug scaffolding.
        for record in records:
            record.pop("_resolved_character_id", None)
        save_bookcast(args.bookcast, records)
        print(f"Wrote {args.bookcast}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
