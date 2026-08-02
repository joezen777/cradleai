from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .graph_store import GraphStore
from .util import read_jsonl


def validate(root: Path) -> dict:
    chapters = read_jsonl(root / "data" / "chapters.jsonl")
    passages = read_jsonl(root / "data" / "passages.jsonl")
    source = {row["passage_id"]: row for row in passages}
    extractions = read_jsonl(root / "data" / "passage_extractions.jsonl")
    treatments = read_jsonl(root / "data" / "chapter_treatments.jsonl")
    errors = []
    if len(chapters) != 40:
        errors.append(f"expected 40 chapters including prologue; found {len(chapters)}")
    successful_extractions = {
        row["passage_id"] for row in extractions
        if str(row.get("status") or "").startswith("success")
    }
    missing_extractions = sorted(set(source) - successful_extractions)
    if missing_extractions:
        errors.append(f"{len(missing_extractions)} passages lack successful extraction")
    successful_treatments = {
        row["chapter_id"] for row in treatments if row.get("status") == "success"
    }
    missing_treatments = sorted(set(row["chapter_id"] for row in chapters) - successful_treatments)
    if missing_treatments:
        errors.append(f"{len(missing_treatments)} chapters lack successful treatments")
    for row in extractions:
        if str(row.get("status") or "").startswith("success"):
            passage_text = source[row["passage_id"]]["text"]
            for kind in ("characters", "settings", "items"):
                for entity in row.get(kind, []):
                    for description in entity.get("visual_descriptions", []):
                        if description.get("exact_quote") not in passage_text:
                            errors.append(f"unsupported quote: {row['passage_id']}")
    with GraphStore(root, read_only=True) as store:
        graph_counts = store.counts()
    report = {
        "books": 2,
        "chapters": len(chapters),
        "passages": len(passages),
        "passage_words": sum(row["word_count"] for row in passages),
        "extractions": Counter(row.get("status") for row in extractions),
        "treatments": Counter(row.get("status") for row in treatments),
        "graph": graph_counts,
        "errors": errors,
        "missing_extraction_passage_ids": missing_extractions,
        "missing_treatment_chapter_ids": missing_treatments,
        "valid": not errors,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = validate(args.root.resolve())
    print(json.dumps(report, indent=2, default=dict))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
