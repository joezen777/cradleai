#!/usr/bin/env python3
"""Enrich thin bookcast.jsonl records with a fixed MCP follow-up interview.

Loads Qwen once, then for each selected character resolves the source row in
service_index.json, walks nearby passages, asks the lore MCP server follow-up
questions (locate_character_context / locate_scenery_context /
locate_prop_context), and records each answer as cited or inferred. See
tasks-c.md for the full design and bookcast_interview.py for the ladder
itself. Requires the lore server running at --mcp-url; does not touch
ComfyUI, so it is safe to run while the lore server (not ComfyUI) is up.
"""

from __future__ import annotations

import argparse
import gc
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from bookcast_evidence import resolve_anchor_passage, resolve_character
from bookcast_interview import DEFAULT_LORE_MCP_URL, compose_enriched, needs_enrichment, run_interview

ROOT = Path(__file__).resolve().parent
BOOKCAST_PATH = ROOT / "bookcast.jsonl"
INDEX_PATH = ROOT / "lore_graph" / "data" / "service_index.json"


def load_bookcast(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_bookcast(path: Path, records: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(path)


def load_local_model():
    import sys
    sys.path.insert(0, str(ROOT / "lore_graph"))
    from loredb.local_model import LocalLoreModel

    model_target = ROOT / "models/Qwen3-VL-8B-Instruct"
    if not model_target.exists():
        model_target = Path("Qwen/Qwen2.5-VL-3B-Instruct")
    print(f"Loading local model from: {model_target} ...", flush=True)
    return LocalLoreModel(model_target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bookcast", type=Path, default=BOOKCAST_PATH)
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--progress", type=Path)
    parser.add_argument("--mcp-url", default=DEFAULT_LORE_MCP_URL)
    parser.add_argument("--only", help="Interview a single record by identity_key")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start-after", help="Skip identity_keys up to and including this one")
    parser.add_argument("--dry-run", action="store_true", help="Print the transcript; write nothing")
    return parser.parse_args()


def select_records(records: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.only:
        return [r for r in records if r.get("identity_key") == args.only]
    selected = []
    started = args.start_after is None
    for r in records:
        if not started:
            started = r.get("identity_key") == args.start_after
            continue
        if needs_enrichment(r):
            selected.append(r)
        if args.limit and len(selected) >= args.limit:
            break
    return selected


def load_progress(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            done.add(json.loads(line)["identity_key"])
    return done


def main() -> int:
    args = parse_args()
    progress_path = args.progress or args.bookcast.with_suffix(".enrichment_progress.jsonl")
    index = json.loads(args.index.read_text(encoding="utf-8"))
    records = load_bookcast(args.bookcast)

    targets = select_records(records, args)
    if not args.dry_run and not args.only:
        completed = load_progress(progress_path)
        targets = [r for r in targets if r.get("identity_key") not in completed]

    if not targets:
        print("No unfinished records need enrichment.", flush=True)
        return 0

    print(f"{len(targets)} record(s) selected for enrichment.", flush=True)

    model = load_local_model()
    try:
        progress_handle = None
        if not args.dry_run:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_handle = progress_path.open("a", encoding="utf-8", buffering=1)

        for ordinal, record in enumerate(targets, 1):
            key = record.get("identity_key", "?")
            name = record.get("canonical_name", key)
            print(f"[{ordinal}/{len(targets)}] {name} ({key}): resolving character", flush=True)
            try:
                character_id, character = resolve_character(index, record)
                if character is None:
                    print(f"  ✗ could not resolve character in service_index.json", flush=True)
                    continue
                anchor_pid = resolve_anchor_passage(record, character)
                if not anchor_pid:
                    print(f"  ✗ no anchor passage available", flush=True)
                    continue

                answers = run_interview(model, args.mcp_url, index, character_id, character, anchor_pid, record)

                if args.dry_run:
                    print(f"  branch anchor_pid={anchor_pid}")
                    for a in answers:
                        tag = a["source"].upper()
                        print(f"  [{a['question_id']:>3}][{tag:>8}] Q: {a['question']}")
                        print(f"           A: {a['answer'] or '(empty)'}")
                    print(f"  --- composed enriched description ---")
                    preview = dict(record)
                    preview["enrichment"] = {"version": "interview-v1", "answers": answers}
                    print(f"  {compose_enriched(preview, answers)}")
                    print()
                    continue

                record["enrichment"] = {
                    "version": "interview-v1",
                    "branch": None,
                    "answers": answers,
                    "interviewed_at": datetime.now().isoformat(),
                }
                record["portrait_description_enriched"] = compose_enriched(record, answers)
                save_bookcast(args.bookcast, records)
                progress_handle.write(json.dumps({"identity_key": key}) + "\n")
                print(f"  ✓ {sum(1 for a in answers if a['answer'])}/{len(answers)} questions answered, written", flush=True)
            except Exception as exc:
                print(f"  ✗ ERROR {type(exc).__name__}: {exc}", flush=True)
            finally:
                gc.collect()
                if getattr(model, "torch", None) is not None and model.torch.cuda.is_available():
                    model.torch.cuda.empty_cache()

        if progress_handle:
            progress_handle.close()
    finally:
        print("Closing local model and clearing CUDA memory...", flush=True)
        model.close()
        del model
        gc.collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
