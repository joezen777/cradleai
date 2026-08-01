#!/usr/bin/env python3
"""Generate one resumable Z-Image Turbo image for every chapter cast prompt."""

from __future__ import annotations

import argparse
import random
import time
from datetime import datetime
from pathlib import Path

from cast_metadata_store import load_records, upsert_image_generation
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor


DEFAULT_METADATA = Path("output/gemini_chapter_cast.jsonl")
DEFAULT_OUTPUT_DIR = Path("output/zimageturbo_character_images")
DEFAULT_WORKFLOW = Path("zimageturbo_cinematic.json")
DEFAULT_ENDPOINT = "http://127.0.0.1:8188"
GENAI_MODEL = "zimageturbo"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--chapter", type=int)
    parser.add_argument("--max-images", type=int)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--cooldown", type=float, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = load_records(args.metadata)
    processor = ComfyUIWorkflowProcessor(
        workflow_file=str(args.workflow),
        endpoint=args.endpoint,
    )
    generated_count = 0
    failed_count = 0

    for chapter in records:
        chapter_number = int(chapter["chapter_number"])
        if args.chapter is not None and chapter_number != args.chapter:
            continue

        for cast_offset, cast in enumerate(chapter.get("cast", [])):
            cast_index = cast_offset + 1
            generations = cast.setdefault("image_generations", [])
            existing = next(
                (
                    generation
                    for generation in generations
                    if generation.get("genaimodel") == GENAI_MODEL
                ),
                None,
            )
            existing_path = existing.get("gen_character_image") if existing else None
            if existing_path and Path(existing_path).is_file():
                continue
            if args.max_images is not None and generated_count >= args.max_images:
                print(f"Generated {generated_count}; stopping at --max-images.")
                return 0 if failed_count == 0 else 1

            character_name = str(cast["character_name"])
            print(
                f"Generating chapter {chapter_number}, cast {cast_index}: "
                f"{character_name}",
                flush=True,
            )

            result = None
            for attempt in range(1, args.max_retries + 1):
                seed = random.randint(0, 2**32 - 1)
                result = processor.generate_image(
                    prompt_text=str(cast["character_genprompt"]),
                    seed=seed,
                    output_dir=str(args.output_dir),
                    gen_sequence=1,
                )
                if result["success"]:
                    break
                print(
                    f"  Attempt {attempt}/{args.max_retries} failed: "
                    f"{result.get('error', 'Unknown error')}",
                    flush=True,
                )
                if attempt < args.max_retries:
                    time.sleep(min(5 * attempt, 30))

            if not result or not result["success"]:
                failed_count += 1
                continue

            generation_record = {
                "genaimodel": GENAI_MODEL,
                "gen_character_image": result["gen_filename"],
                "seed": result["seed"],
                "generated_at": datetime.now().isoformat(),
            }
            upsert_image_generation(
                args.metadata,
                chapter_number,
                cast_offset,
                generation_record,
            )
            if existing is None:
                generations.append(generation_record)
            else:
                existing.update(generation_record)
            generated_count += 1
            print(f"  Saved {result['gen_filename']}", flush=True)
            if args.cooldown > 0:
                time.sleep(args.cooldown)

    print(
        f"Generated {generated_count} Z-Image Turbo cast images; "
        f"{failed_count} failed.",
        flush=True,
    )
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
