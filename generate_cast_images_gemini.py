#!/usr/bin/env python3
"""Generate one Gemini image for every cast record and update its JSONL path."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from google.oauth2 import service_account

from cast_metadata_store import load_records, upsert_image_generation

DEFAULT_METADATA = Path("output/gemini_chapter_cast.jsonl")
DEFAULT_OUTPUT_DIR = Path("output/gemini_character_images")
DEFAULT_CREDENTIALS = Path(".credentials.json")
DEFAULT_MODEL = "gemini-3.1-flash-image"


def create_client(credentials_path: Path) -> genai.Client:
    with credentials_path.open("r", encoding="utf-8") as source:
        credentials_data = json.load(source)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_data,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return genai.Client(
        vertexai=True,
        credentials=credentials,
        project=credentials_data["project_id"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        http_options=types.HttpOptions(api_version="v1", timeout=300_000),
    )


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return slug[:60] or "unknown_character"


def image_bytes(response: Any) -> bytes:
    for candidate in response.candidates or []:
        for part in candidate.content.parts or []:
            inline_data = getattr(part, "inline_data", None)
            data = getattr(inline_data, "data", None)
            if data:
                return data
    raise RuntimeError("Gemini returned no generated image")


def generate_image(
    client: genai.Client,
    model: str,
    prompt: str,
    max_retries: int,
) -> bytes:
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio="2:3",
                        image_size="1K",
                        output_mime_type="image/png",
                    ),
                ),
            )
            return image_bytes(response)
        except Exception as exc:
            status = getattr(exc, "code", None)
            if attempt + 1 == max_retries or status not in {
                408,
                429,
                500,
                502,
                503,
                504,
            }:
                raise
            delay = (
                min(60 * (attempt + 1), 300)
                if status == 429
                else min(2**attempt, 60)
            )
            print(f"Retryable Gemini error ({status}); retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError("Gemini retry loop exited unexpectedly")


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
    parser.add_argument(
        "--genaimodel",
        default="gemini",
        help="Stable model-family label stored with the generated image.",
    )
    parser.add_argument("--chapter", type=int)
    parser.add_argument("--max-images", type=int)
    parser.add_argument("--max-retries", type=int, default=20)
    parser.add_argument(
        "--cooldown",
        type=float,
        default=30.0,
        help="Seconds to wait after each successful image call.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = load_records(args.metadata)
    client = create_client(args.credentials)
    generated_count = 0

    for chapter in records:
        chapter_number = int(chapter["chapter_number"])
        if args.chapter is not None and chapter_number != args.chapter:
            continue
        for cast_offset, cast in enumerate(chapter.get("cast", [])):
            cast_index = cast_offset + 1
            generations = cast.setdefault("image_generations", [])
            existing_generation = next(
                (
                    generation
                    for generation in generations
                    if generation.get("genaimodel") == args.genaimodel
                ),
                None,
            )
            existing = (
                existing_generation.get("gen_character_image")
                if existing_generation
                else None
            )
            if existing and Path(existing).is_file():
                continue
            if (
                args.max_images is not None
                and generated_count >= args.max_images
            ):
                return 0

            character_name = str(cast["character_name"])
            image_path = args.output_dir / (
                f"chapter_{chapter_number:03d}_cast_{cast_index:03d}_"
                f"{slugify(character_name)}_{slugify(args.genaimodel)}.png"
            )
            print(
                f"Generating chapter {chapter_number}, cast {cast_index}: "
                f"{character_name}",
                flush=True,
            )
            data = generate_image(
                client,
                args.model,
                str(cast["character_genprompt"]),
                args.max_retries,
            )
            save_image(image_path, data)
            generation_record = {
                "genaimodel": args.genaimodel,
                "gen_character_image": str(image_path),
            }
            upsert_image_generation(
                args.metadata,
                chapter_number,
                cast_offset,
                generation_record,
            )
            if existing_generation is None:
                generations.append(generation_record)
            else:
                existing_generation.update(generation_record)
            generated_count += 1
            print(f"Saved {image_path}", flush=True)
            if args.cooldown > 0:
                time.sleep(args.cooldown)

    print(f"Generated {generated_count} new cast images.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
