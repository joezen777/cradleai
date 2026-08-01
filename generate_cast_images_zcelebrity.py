#!/usr/bin/env python3
"""Generate one celebrity-cast Z-Image Turbo image per chapter cast prompt."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from cast_metadata_store import load_records, upsert_image_generation
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor


DEFAULT_METADATA = Path("output/gemini_chapter_cast.jsonl")
DEFAULT_OUTPUT_DIR = Path("output/zcelebrity_character_images")
DEFAULT_WORKFLOW = Path("zimageturbo_cinematic.json")
DEFAULT_ENDPOINT = "http://127.0.0.1:8188"
DEFAULT_CREDENTIALS = Path(".credentials")
DEFAULT_LLM_MODEL = "gpt-5.6-terra"
GENAI_MODEL = "zcelebrity"


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


def select_celebrity(
    client: OpenAI,
    model: str,
    cast: dict[str, Any],
    max_retries: int,
) -> str:
    prompt = f"""Choose the single most popular live-action celebrity casting
suggestion for this Cradle character who is also a globally recognizable
public figure likely to be represented reliably by a general text-to-image
model such as Z-Image Turbo.

Consider the character's apparent age, gender presentation, ethnicity,
physical presence, personality, and the supplied description. Prefer a
widely photographed actor whose name a text-to-image model is especially
likely to recognize. If the character label is generic or unknown, infer the
best casting from the description.

Character name:
{cast.get("character_name") or "Unknown"}

Character description:
{cast.get("character_description") or "No description available."}

Return exactly one celebrity's commonly used full name. Do not add commentary,
punctuation, alternatives, labels, or formatting."""

    for attempt in range(1, max_retries + 1):
        try:
            response = client.responses.create(model=model, input=prompt)
            name = response.output_text.strip().strip("\"'").splitlines()[0].strip()
            name = re.sub(r"^[*-]\s*", "", name)
            if (
                2 <= len(name) <= 80
                and re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ž'’. -]+", name)
            ):
                return name
            raise ValueError("LLM did not return one clean celebrity name")
        except Exception as exc:
            print(
                f"  Celebrity selection attempt {attempt}/{max_retries} "
                f"failed: {type(exc).__name__}",
                flush=True,
            )
            if attempt < max_retries:
                time.sleep(min(5 * attempt, 30))
    raise RuntimeError("Celebrity selection failed after all retries")


def celebrity_image_prompt(celebrity_name: str, cast: dict[str, Any]) -> str:
    return f"""Celebrity casting reference: {celebrity_name}.
Depict this fictional character as portrayed by {celebrity_name}. Preserve a
clearly recognizable facial likeness and stable facial identity while applying
the character-specific age, physique, hair, wardrobe, equipment, pose,
lighting, and setting described below. This is a cinematic fictional character
portrait, not a photograph from a real event.

{cast["character_genprompt"]}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--chapter", type=int)
    parser.add_argument("--max-images", type=int)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--cooldown", type=float, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = load_records(args.metadata)
    llm_client = OpenAI(api_key=load_api_key(args.credentials), timeout=300)
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
                f"Selecting celebrity for chapter {chapter_number}, "
                f"cast {cast_index}: {character_name}",
                flush=True,
            )
            try:
                celebrity_name = (
                    str(existing.get("celebrity_name")).strip()
                    if existing and existing.get("celebrity_name")
                    else select_celebrity(
                        llm_client,
                        args.llm_model,
                        cast,
                        args.max_retries,
                    )
                )
            except Exception as exc:
                failed_count += 1
                print(f"  Selection failed: {type(exc).__name__}", flush=True)
                continue

            print(f"  Cast as {celebrity_name}", flush=True)
            result = None
            for attempt in range(1, args.max_retries + 1):
                seed = random.randint(0, 2**32 - 1)
                result = processor.generate_image(
                    prompt_text=celebrity_image_prompt(celebrity_name, cast),
                    seed=seed,
                    output_dir=str(args.output_dir),
                    gen_sequence=1,
                )
                if result["success"]:
                    break
                print(
                    f"  Image attempt {attempt}/{args.max_retries} failed: "
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
                "celebrity_name": celebrity_name,
                "llm_model": args.llm_model,
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
        f"Generated {generated_count} celebrity-cast images; "
        f"{failed_count} failed.",
        flush=True,
    )
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
