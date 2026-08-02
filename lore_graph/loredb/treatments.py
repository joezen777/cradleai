from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .local_model import LocalLoreModel
from .util import load_config, read_jsonl, write_jsonl_atomic

TREATMENT_VERSION = 1

TREATMENT_PROMPT = """Write a screenwriter's treatment of the supplied novel
chapter using only the supplied source passages. Return only JSON with keys
`logline`, `treatment`, `principal_characters`, `principal_settings`, and
`visual_continuity`. The treatment should be 700-1200 words, present tense,
chronological, cinematic prose rather than screenplay formatting, and cover all
major beats, reversals, motivations, conflict, emotional progression, setting
changes, and ending hook. Clearly distinguish internal narration from filmable
action. Preserve canonical names and concrete visual details. Do not invent
dialogue, appearances, lore, or events. `principal_characters`,
`principal_settings`, and `visual_continuity` are arrays of concise strings.
Source follows:\n"""


def run(root: Path, max_chapters: int | None = None) -> None:
    config = load_config(root)
    chapters = read_jsonl(root / "data" / "chapters.jsonl")
    passages_by_chapter: dict[str, list[dict]] = defaultdict(list)
    for row in read_jsonl(root / "data" / "passages.jsonl"):
        passages_by_chapter[row["chapter_id"]].append(row)
    output = root / "data" / "chapter_treatments.jsonl"
    existing = {row["chapter_id"]: row for row in read_jsonl(output)}
    pending = [
        chapter for chapter in chapters
        if existing.get(chapter["chapter_id"], {}).get("status") != "success"
        or existing.get(chapter["chapter_id"], {}).get("treatment_version") != TREATMENT_VERSION
    ]
    if max_chapters is not None:
        pending = pending[:max_chapters]
    if not pending:
        print("All chapter treatments are already complete.", flush=True)
        return
    model = LocalLoreModel((root / config["local_lore_model"]).resolve())
    try:
        for index, chapter in enumerate(pending, 1):
            source = {
                "book_id": chapter["book_id"],
                "chapter_id": chapter["chapter_id"],
                "chapter_label": chapter["label"],
                "passages": [
                    {
                        "passage_id": row["passage_id"],
                        "pages": [row["page_start"], row["page_end"]],
                        "text": row["text"],
                    }
                    for row in sorted(passages_by_chapter[chapter["chapter_id"]], key=lambda x: x["sequence"])
                ],
            }
            try:
                result = model.generate_json(
                    TREATMENT_PROMPT + json.dumps(source, ensure_ascii=False),
                    max_new_tokens=2400,
                )
                if not str(result.get("treatment") or "").strip():
                    raise ValueError("empty treatment")
                record = {
                    **chapter,
                    "treatment_version": TREATMENT_VERSION,
                    "status": "success",
                    **result,
                }
            except Exception as exc:
                record = {
                    **chapter,
                    "treatment_version": TREATMENT_VERSION,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            existing[chapter["chapter_id"]] = record
            write_jsonl_atomic(output, (existing[key] for key in sorted(existing)))
            print(f"Treatment {index}/{len(pending)} {chapter['chapter_id']} [{record['status']}]", flush=True)
    finally:
        model.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--max-chapters", type=int)
    args = parser.parse_args()
    run(args.root.resolve(), args.max_chapters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
