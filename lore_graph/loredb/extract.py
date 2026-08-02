from __future__ import annotations

import argparse
import json
from pathlib import Path

from .local_model import LocalLoreModel
from .util import load_config, read_jsonl, write_jsonl_atomic

EXTRACTION_VERSION = 1

EXTRACTION_PROMPT = """Extract a source-grounded visual knowledge graph from the
provided passage of a novel. Use ONLY the passage. Do not use memory of the book,
infer facts from later events, or improve descriptions. Include every mentioned
character/person/creature/humanoid spirit, including unnamed people, crowds,
background figures, non-speakers, and characters mentioned but not physically
present. Distinguish `mentioned` from `visually_present`.

Return only JSON with exactly these top-level arrays:
- `characters`: objects with `name_or_label`, `named`, `aliases_seen`,
  `mentioned`, `visually_present`, `action_summary`, `setting_refs`, and
  `visual_descriptions`.
- `settings`: objects with `name_or_label`, `setting_type`, and
  `visual_descriptions`.
- `items`: props and wardrobe objects with `name_or_label`, `item_type` (prop or
  wardrobe), `character_ref` or null, `relationship` (wears/carries/uses/owns/
  near/none), `setting_refs`, and `visual_descriptions`.

Each `visual_descriptions` value is an array of objects containing `exact_quote`
and `normalized_description`. Copy `exact_quote` exactly from the supplied
passage and keep it to the smallest sentence or clause that supports the visual
fact. A visual description covers visible anatomy, face, expression, gaze,
posture, movement, clothing, covering, accessory, material, color, shape,
lighting, architecture, landscape, spatial arrangement, or prop appearance.
Do not treat personality, history, power level, dialogue, or invisible thoughts
as visual description. `setting_refs` must match a setting `name_or_label` in
the same response. Use stable descriptive labels for unnamed characters, such
as `unnamed Wei clan elder`, without merging distinct people. Empty arrays are
valid. Passage metadata and text follow:\n"""


def sanitize_extraction(result: dict, source_text: str) -> list[str]:
    rejected: list[str] = []
    for key in ("characters", "settings", "items"):
        if not isinstance(result.get(key), list):
            raise ValueError(f"missing array: {key}")
        valid_entities = []
        for entity in result[key]:
            if not isinstance(entity, dict):
                rejected.append(f"{key}: malformed non-object entity")
                continue
            descriptions = entity.get("visual_descriptions", [])
            if not isinstance(descriptions, list):
                rejected.append(f"{key}: visual_descriptions is not an array")
                entity["visual_descriptions"] = []
                valid_entities.append(entity)
                continue
            supported = []
            for description in descriptions:
                if not isinstance(description, dict):
                    rejected.append(f"{key}: malformed non-object description")
                    continue
                quote = str(description.get("exact_quote") or "").strip()
                if quote and quote in source_text:
                    supported.append(description)
                else:
                    rejected.append(f"{key}: {quote[:160]}")
            entity["visual_descriptions"] = supported
            valid_entities.append(entity)
        result[key] = valid_entities
    return rejected


def run(root: Path, max_passages: int | None = None, batch_size: int = 4) -> None:
    config = load_config(root)
    passages = read_jsonl(root / "data" / "passages.jsonl")
    output = root / "data" / "passage_extractions.jsonl"
    existing = {row["passage_id"]: row for row in read_jsonl(output)}
    pending = [
        row for row in passages
        if not str(existing.get(row["passage_id"], {}).get("status") or "").startswith("success")
        or existing.get(row["passage_id"], {}).get("extraction_version") != EXTRACTION_VERSION
        or existing.get(row["passage_id"], {}).get("source_sha256") != row["sha256"]
    ]
    if max_passages is not None:
        pending = pending[:max_passages]
    if not pending:
        print("All passage extractions are already complete.", flush=True)
        return
    extraction_model = config["extraction_model"]
    model_path = Path(extraction_model)
    if not extraction_model.startswith("Qwen/"):
        model_path = (root / extraction_model).resolve()
    model = LocalLoreModel(model_path)
    try:
        for batch_start in range(0, len(pending), batch_size):
            batch = pending[batch_start:batch_start + batch_size]
            instructions = []
            for passage in batch:
                grounding = {key: passage[key] for key in (
                    "passage_id", "book_id", "chapter_id", "chapter_label",
                    "page_start", "page_end", "text"
                )}
                instructions.append(
                    EXTRACTION_PROMPT + json.dumps(grounding, ensure_ascii=False)
                )
            if batch_size == 1:
                try:
                    results = [model.generate_json(instructions[0], max_new_tokens=1800)]
                except Exception as exc:
                    results = [exc]
            else:
                results = model.generate_json_batch(instructions)
            for offset, (passage, result) in enumerate(zip(batch, results), 1):
                try:
                    if isinstance(result, Exception):
                        raise result
                    rejected = sanitize_extraction(result, passage["text"])
                    record = {
                        "passage_id": passage["passage_id"],
                        "chapter_id": passage["chapter_id"],
                        "book_id": passage["book_id"],
                        "source_sha256": passage["sha256"],
                        "extraction_version": EXTRACTION_VERSION,
                        "status": "success_with_warnings" if rejected else "success",
                        "evidence_rejections": rejected,
                        **result,
                    }
                except Exception as exc:
                    record = {
                        "passage_id": passage["passage_id"],
                        "chapter_id": passage["chapter_id"],
                        "book_id": passage["book_id"],
                        "source_sha256": passage["sha256"],
                        "extraction_version": EXTRACTION_VERSION,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                existing[passage["passage_id"]] = record
                write_jsonl_atomic(output, (existing[key] for key in sorted(existing)))
                index = batch_start + offset
                print(f"Extracted {index}/{len(pending)} {passage['passage_id']} [{record['status']}]", flush=True)
    finally:
        model.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--max-passages", type=int)
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()
    run(args.root.resolve(), args.max_passages, args.batch_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
