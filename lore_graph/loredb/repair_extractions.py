from __future__ import annotations

import argparse
import json
from pathlib import Path

from .extract import EXTRACTION_PROMPT, EXTRACTION_VERSION, sanitize_extraction
from .local_model import LocalLoreModel
from .util import load_config, read_jsonl, write_jsonl_atomic


def paragraph_chunks(text: str, count: int) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    target = max(1, sum(len(part.split()) for part in paragraphs) // count)
    chunks: list[list[str]] = [[]]
    words = 0
    for paragraph in paragraphs:
        size = len(paragraph.split())
        if chunks[-1] and words + size > target and len(chunks) < count:
            chunks.append([]); words = 0
        chunks[-1].append(paragraph); words += size
    return ["\n\n".join(chunk) for chunk in chunks if chunk]


def run(root: Path) -> None:
    config = load_config(root)
    passages = {row["passage_id"]: row for row in read_jsonl(root / "data" / "passages.jsonl")}
    output = root / "data" / "passage_extractions.jsonl"
    existing = {row["passage_id"]: row for row in read_jsonl(output)}
    pending = [
        passages[pid] for pid, row in existing.items()
        if not str(row.get("status") or "").startswith("success")
    ]
    model_name = config["extraction_model"]
    model_path = Path(model_name) if model_name.startswith("Qwen/") else (root / model_name).resolve()
    model = LocalLoreModel(model_path)
    try:
        for index, passage in enumerate(pending, 1):
            last_error: Exception | None = None
            for chunk_count in (2, 3, 4):
                merged = {"characters": [], "settings": [], "items": []}
                try:
                    for chunk_index, chunk in enumerate(paragraph_chunks(passage["text"], chunk_count), 1):
                        grounding = {key: passage[key] for key in (
                            "passage_id", "book_id", "chapter_id", "chapter_label",
                            "page_start", "page_end",
                        )}
                        grounding.update({
                            "chunk": f"{chunk_index}/{chunk_count}",
                            "text": chunk,
                        })
                        result = model.generate_json(
                            EXTRACTION_PROMPT + json.dumps(grounding, ensure_ascii=False),
                            max_new_tokens=1400,
                        )
                        for key in merged:
                            if not isinstance(result.get(key), list):
                                raise ValueError(f"chunk missing array: {key}")
                            merged[key].extend(result[key])
                    rejected = sanitize_extraction(merged, passage["text"])
                    record = {
                        "passage_id": passage["passage_id"],
                        "chapter_id": passage["chapter_id"],
                        "book_id": passage["book_id"],
                        "source_sha256": passage["sha256"],
                        "extraction_version": EXTRACTION_VERSION,
                        "repair_method": f"paragraph_chunks_{chunk_count}",
                        "status": "success_with_warnings" if rejected else "success",
                        "evidence_rejections": rejected,
                        **merged,
                    }
                    existing[passage["passage_id"]] = record
                    write_jsonl_atomic(output, (existing[key] for key in sorted(existing)))
                    print(f"Repaired {index}/{len(pending)} {passage['passage_id']} [{record['status']}]", flush=True)
                    break
                except Exception as exc:
                    last_error = exc
            else:
                print(f"Unrepaired {passage['passage_id']}: {type(last_error).__name__}: {last_error}", flush=True)
    finally:
        model.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(); run(args.root.resolve()); return 0


if __name__ == "__main__":
    raise SystemExit(main())
