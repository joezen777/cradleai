#!/usr/bin/env python3
"""Generate one resumable GPT Image 2 image for every chapter cast prompt."""

from __future__ import annotations

import argparse
import base64
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from cast_metadata_store import load_records, upsert_image_generation


DEFAULT_METADATA = Path("output/gemini_chapter_cast.jsonl")
DEFAULT_OUTPUT_DIR = Path("output/openai_character_images")
DEFAULT_CREDENTIALS = Path(".credentials")
DEFAULT_MODEL = "gpt-image-2"


def load_api_key(path: Path) -> str:
    environment_key = os.environ.get("OPENAI_API_KEY") or os.environ.get(
        "OPEN_API_KEY"
    )
    if environment_key:
        return environment_key
    with path.open("r", encoding="utf-8") as source:
        for raw_line in source:
            if "=" not in raw_line or raw_line.lstrip().startswith("#"):
                continue
            key, value = raw_line.split("=", 1)
            if key.strip() in {"OPENAI_API_KEY", "OPEN_API_KEY"}:
                secret = value.strip().strip("\"'")
                if secret:
                    return secret
    raise RuntimeError(
        "OPENAI_API_KEY or OPEN_API_KEY is missing from the environment "
        f"and {path}"
    )


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return slug[:60] or "unknown_character"


def save_image(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as destination:
        temporary_path = Path(destination.name)
        destination.write(data)
    os.replace(temporary_path, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--size", default="1024x1536")
    parser.add_argument("--quality", default="medium")
    parser.add_argument("--chapter", type=int)
    parser.add_argument("--max-images", type=int)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--cooldown", type=float, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = load_records(args.metadata)
    client = OpenAI(api_key=load_api_key(args.credentials), timeout=3600)
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
                    if generation.get("genaimodel") == args.model
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
            image_path = args.output_dir / (
                f"chapter_{chapter_number:03d}_cast_{cast_index:03d}_"
                f"{slugify(character_name)}_{slugify(args.model)}.png"
            )
            print(
                f"Generating chapter {chapter_number}, cast {cast_index}: "
                f"{character_name}",
                flush=True,
            )

            image_data = None
            for attempt in range(1, args.max_retries + 1):
                try:
                    response = client.images.generate(
                        model=args.model,
                        prompt=str(cast["character_genprompt"]),
                        n=1,
                        size=args.size,
                        quality=args.quality,
                        output_format="png",
                    )
                    image_data = base64.b64decode(response.data[0].b64_json)
                    break
                except Exception as exc:
                    print(
                        f"  Attempt {attempt}/{args.max_retries} failed: "
                        f"{type(exc).__name__}",
                        flush=True,
                    )
                    if attempt < args.max_retries:
                        time.sleep(min(15 * attempt, 60))

            if image_data is None:
                failed_count += 1
                continue

            save_image(image_path, image_data)
            generation_record = {
                "genaimodel": args.model,
                "gen_character_image": str(image_path),
                "generated_at": datetime.now().isoformat(),
                "size": args.size,
                "quality": args.quality,
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
            print(f"  Saved {image_path}", flush=True)
            if args.cooldown > 0:
                time.sleep(args.cooldown)

    print(
        f"Generated {generated_count} GPT Image cast images; "
        f"{failed_count} failed.",
        flush=True,
    )
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
