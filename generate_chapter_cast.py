#!/usr/bin/env python3
"""Generate resumable Gemini character references from Pegasus chapters."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from google.oauth2 import service_account
from pydantic import BaseModel, ConfigDict, Field


DEFAULT_CHAPTERS = Path("output/pegasus_chapter_metadata.jsonl")
DEFAULT_OUTPUT = Path("output/gemini_chapter_cast.jsonl")
DEFAULT_CREDENTIALS = Path(".credentials.json")
DEFAULT_MODEL = "gemini-2.5-flash"
CAST_PROMPT_VERSION = 2
SPECIAL_EQUIPMENT_IDENTITIES = (
    "yerin",
    "jai long",
    "sword sage",
    "timaias",
    "suriel",
    "li markuth",
    "eithan",
    "kral",
    "gokren",
)

CHARACTER_PROMPT = """
You are an expert Generative AI Character Designer and Lead Prompt Engineer. Your task is to generate a comprehensive, full-body visual description prompt for the fictional character [CHARACTER_NAME] as they appear in the book Unsouled or Soulsmith from Will Wight's Cradle series.

### SOURCE MATERIAL & KNOWLEDGE HIERARCHY
1. **Primary Canon:** Strictly utilize explicit physical details from Unsouled or Soulsmith (e.g., badges, clan robes, hair length, Remnant additions/limbs, facial structure, weapons, scars).
2. **Lore Interpolation:** Fill in missing details using your established knowledge of the Cradle universe (e.g., Madra path aesthetics, sacred artist attire norms, clan crests).
3. **Creative Visual Synthesis:** For any remaining visual gaps, apply grounded creative license that fits the high-fantasy martial arts/xianxia tone of Cradle without contradicting canon.

---

### PROMPT ENGINEERING & VISUAL DIRECTIVES
You must structure the final visual description using high-precision generative AI standards. Strictly follow these guidelines:

1. **Spatial Anchoring & Full-Body Framing:**
   - Force a full-length, unclipped head-to-toe frame.
   - Describe explicit footwear and physical ground surface contact (e.g., cloth-wrapped boots standing on damp earth/flagstone).
   - Require minimal empty vertical margins to prevent torso-cropping.

2. **Anatomical & Epidermal Precision:**
   - Detail skin tone using explicit pigments and undertones (e.g., bronze with golden undertones, weathered tan, pale porcelain).
   - Specify epidermal physics: pore texture, subtle scars, subsurface light scattering.
   - Define underlying facial/skull geometry: jawline, cheekbones, eye shape, iris/limbal rings, and eyebrow structure.

3. **Hair Volumetrics & Dynamics:**
   - Define exact length, termination point, style, strands, and physical interaction (e.g., tied with hemp cord, flying strands caught in wind).

4. **Complete Wardrobe Architecture & Layering:**
   - Do NOT just describe top and footwear. You MUST detail every layer from inside out:
     - Inner garment (tunics, undertops, undershirts)
     - Main attire (kimono/haori styles, robes, martial arts gi, fitted jackets, dresses/gowns)
     - Waist architecture (sashes, leather belts, brass buckles, hanging clan badges e.g., Wooden/Copper "Unsouled" badge)
     - Lower garments (wide-leg trousers, breeches, pleated skirts, leg wraps)
     - Outerwear (dusters, traveling cloaks, long coats)
     - Footwear & ankle wraps
     - Accessories & Remnant appendages (e.g., Yerin's spider-like metallic sword-arms extending from the back)
   - Specify fabric weave, weight, texture, and light reflection (e.g., coarse woven linen, heavy embroidered silk, matte leather).

5. **Ergonomics & Micro-Expressions:**
   - Describe posture and weight distribution (e.g., contrapposto, wide martial stance, stooped craftsperson pose).
   - Specify micro-expressions using specific facial muscle cues rather than abstract emotion words (e.g., a permanent slight scowl with narrowed eyes, or a subtle tight-lipped smirk).
   - NO generic buzzwords like "hyperrealistic", "masterpiece", or "photorealistic". Use descriptive visual physical facts.

---

### OUTPUT FORMAT

Provide your response in two distinct sections:

#### SECTION 1: Canon Extraction Summary
A brief, bulleted overview detailing:
- Canonical facts directly retrieved from Unsouled or Soulsmith.
- Inferred Cradle lore details added.
- Creative choices made to complete the full-body specification.

#### SECTION 2: Structured JSON Image Generation Prompt
A clean key-value JSON block optimized for Gemini/Diffusion image generation, following this structure:

{
  "generation_target": "Full-body character reference sheet",
  "subject_profile": {
    "character_name": "[CHARACTER_NAME]",
    "apparent_age": "...",
    "ethnicity_skin_tone": "...",
    "facial_structure_and_features": "...",
    "micro_expression": "..."
  },
  "hair_specification": {
    "length_and_style": "...",
    "color_and_texture": "..."
  },
  "wardrobe_and_layering": {
    "inner_garment": "...",
    "main_attire": "...",
    "waist_and_badge": "...",
    "bottom_garments": "...",
    "footwear_and_lower_anchors": "...",
    "fabric_textures_and_materials": "...",
    "special_appendages_or_weapons": "..."
  },
  "pose_and_composition": {
    "framing": "Full-length wide shot, head-to-toe fully visible",
    "posture": "...",
    "ground_surface_contact": "...",
    "lighting_and_atmosphere": "..."
  }
}

#### SECTION 3: Continuous Master Text Prompt
A dense, 150-200 word prose prompt incorporating all above parameters for direct copy-pasting into text-to-image interfaces (Flux / zTurbo / Gemini Image Generation).
""".strip()


class SubjectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_name: str
    apparent_age: str
    ethnicity_skin_tone: str
    facial_structure_and_features: str
    micro_expression: str


class HairSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    length_and_style: str
    color_and_texture: str


class WardrobeAndLayering(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inner_garment: str
    main_attire: str
    waist_and_badge: str
    bottom_garments: str
    footwear_and_lower_anchors: str
    fabric_textures_and_materials: str
    special_appendages_or_weapons: str | None = Field(
        default=None,
        description=(
            "Include only when a weapon or special appendage applies to this "
            "character and is supported by canon or strong chapter evidence"
        ),
    )


class PoseAndComposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framing: str
    posture: str
    ground_surface_contact: str
    lighting_and_atmosphere: str


class CharacterDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_target: str
    subject_profile: SubjectProfile
    hair_specification: HairSpecification
    wardrobe_and_layering: WardrobeAndLayering
    pose_and_composition: PoseAndComposition


class CharacterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_name: str = Field(
        description="Canonical Cradle character name, or the best stable label"
    )
    character_description: str = Field(
        description="Section 1 canon extraction summary with concise bullets"
    )
    character_details: CharacterDetails = Field(
        description="The complete Section 2 structured image-generation object"
    )
    character_genprompt: str = Field(
        description="Section 3 continuous 150-200 word master prompt"
    )


def load_chapters(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        records = [json.loads(line) for line in source if line.strip()]
    return [record for record in records if record.get("status") == "success"]


def load_output(path: Path) -> dict[int, dict[str, Any]]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as source:
        records = {
            int(record["chapter_number"]): record
            for line in source
            if line.strip()
            for record in [json.loads(line)]
        }
    for record in records.values():
        for character in record.get("cast", []):
            name = str(character.get("character_name") or "").casefold()
            if not any(
                identity in name for identity in SPECIAL_EQUIPMENT_IDENTITIES
            ):
                wardrobe = (
                    character.get("character_details", {})
                    .get("wardrobe_and_layering", {})
                )
                wardrobe.pop("special_appendages_or_weapons", None)
    return records


def persist_output(path: Path, records: dict[int, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as destination:
        temporary_path = Path(destination.name)
        for chapter_number in sorted(records):
            destination.write(
                json.dumps(records[chapter_number], ensure_ascii=False) + "\n"
            )
    os.replace(temporary_path, path)


def speaker_mapping(chapter: dict[str, Any]) -> dict[str, str]:
    return {
        str(guess["speaker_id"]): str(guess["character_name_guess"]).strip()
        for guess in chapter.get("speaker_name_guesses", [])
        if guess.get("speaker_id") and guess.get("character_name_guess")
    }


def in_memory_transcript(chapter: dict[str, Any]) -> str:
    """Substitute speaker names and omit all timecodes without source mutation."""
    names = speaker_mapping(chapter)
    lines = []
    for turn in chapter.get("transcript_turns", []):
        text = re.sub(r"\s+", " ", str(turn.get("text") or "")).strip()
        if not text:
            continue
        speaker_id = str(turn.get("speaker_id") or "unknown")
        if speaker_id == "audio_event":
            label = "Sound"
        else:
            label = names.get(speaker_id, speaker_id)
        lines.append(f"{label}: {text}")
    return "\n".join(lines)


def character_targets(chapter: dict[str, Any]) -> list[dict[str, str]]:
    """Return unique named guesses while keeping unknown speakers distinct."""
    targets = []
    seen = set()
    for guess in chapter.get("speaker_name_guesses", []):
        speaker_id = str(guess.get("speaker_id") or "").strip()
        name = str(guess.get("character_name_guess") or "").strip()
        if not speaker_id or not name or name.casefold() == "narrator":
            continue
        is_unknown = name.casefold() in {"unknown", "unknown speaker"}
        key = speaker_id.casefold() if is_unknown else name.casefold()
        if key in seen:
            continue
        seen.add(key)
        target = f"Unknown ({speaker_id})" if is_unknown else name
        targets.append({"speaker_id": speaker_id, "target_name": target})

    # Pegasus sometimes names a visible character in its summary even when
    # diarization did not assign that character a useful speaker label.
    summary = str(chapter.get("chapter_summary") or "")
    explicitly_named = re.findall(
        r"\b(?:named|called|identified as)\s+([A-Z][A-Za-z'-]+)",
        summary,
        flags=re.IGNORECASE,
    )
    for name in explicitly_named:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            {
                "speaker_id": f"summary:{name}",
                "target_name": name,
            }
        )
    return targets


def build_prompt(
    target_name: str,
    chapter_number: int,
    chapter_summary: str,
    transcript: str,
) -> str:
    prompt = CHARACTER_PROMPT.replace("[CHARACTER_NAME]", target_name)
    return f"""
{prompt}

Return one JSON object matching the supplied response schema. Map Section 1 to
character_description, the complete Section 2 object to character_details, and
Section 3 to character_genprompt. Return the canonical identity in
character_name. The requested character label may be a Pegasus guess; correct
it only when the chapter evidence and Cradle canon strongly support the
canonical identity. Do not describe a different character merely because that
character also appears in the chapter.

APPLICABILITY AND ANTI-INVENTION RULES:
- Omit an optional property when its concept does not apply to this character.
- In particular, omit special_appendages_or_weapons unless canon or strong
  chapter evidence establishes a weapon, Goldsign, Remnant appendage, prosthetic
  feature, or other special addition for this character at this point in the
  story.
- Do not invent weapons, badges, scars, clan crests, Remnant parts, accessories,
  or outerwear merely to fill a field or make the design more elaborate.
- A question about an item, another character possessing it, or a generic lore
  possibility is not evidence that this character possesses it.
- When a required property needs creative synthesis, keep it visually grounded
  and do not present the creative choice as canon.

CHAPTER NUMBER:
{chapter_number}

CHAPTER SUMMARY:
{chapter_summary}

CHAPTER TRANSCRIPT:
{transcript}
""".strip()


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
        http_options=types.HttpOptions(api_version="v1", timeout=180_000),
    )


def call_gemini(
    client: genai.Client,
    model: str,
    prompt: str,
    thinking_budget: int,
    max_retries: int,
) -> tuple[CharacterResult, dict[str, Any]]:
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CharacterResult,
                    temperature=0.2,
                    thinking_config=types.ThinkingConfig(
                        thinking_budget=thinking_budget
                    ),
                ),
            )
            if not response.text:
                raise RuntimeError("Gemini returned no text")
            usage = response.usage_metadata
            return CharacterResult.model_validate_json(response.text), {
                "prompt_tokens": getattr(usage, "prompt_token_count", None),
                "output_tokens": getattr(usage, "candidates_token_count", None),
                "thinking_tokens": getattr(usage, "thoughts_token_count", None),
                "total_tokens": getattr(usage, "total_token_count", None),
            }
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
            time.sleep(min(2**attempt, 60))
    raise RuntimeError("Gemini retry loop exited unexpectedly")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapters", type=Path, default=DEFAULT_CHAPTERS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--chapter", type=int)
    parser.add_argument("--max-characters", type=int)
    parser.add_argument("--thinking-budget", type=int, default=2048)
    parser.add_argument("--max-retries", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    chapters = load_chapters(args.chapters)
    if args.chapter is not None:
        chapters = [
            chapter
            for chapter in chapters
            if int(chapter["chapter_index"]) == args.chapter
        ]
        if not chapters:
            raise ValueError(f"Successful chapter {args.chapter} was not found")

    records = load_output(args.output)
    client = create_client(args.credentials)
    calls_made = 0

    for chapter in chapters:
        chapter_number = int(chapter["chapter_index"])
        targets = character_targets(chapter)
        record = records.setdefault(
            chapter_number,
            {
                "chapter_number": chapter_number,
                "movie_start_time_seconds": chapter["movie_start_time_seconds"],
                "movie_end_time_seconds": chapter["movie_end_time_seconds"],
                "scene_indices": chapter["scene_indices"],
                "cast": [],
                "processed_targets": [],
                "status": "partial",
                "cast_prompt_version": CAST_PROMPT_VERSION,
            },
        )
        if record.get("cast_prompt_version") != CAST_PROMPT_VERSION:
            record["cast"] = []
            record["processed_targets"] = []
            record["status"] = "partial"
            record["cast_prompt_version"] = CAST_PROMPT_VERSION
        completed = {
            (item["speaker_id"], item["target_name"])
            for item in record.get("processed_targets", [])
        }
        transcript = in_memory_transcript(chapter)

        for target in targets:
            completion_key = (target["speaker_id"], target["target_name"])
            if completion_key in completed:
                continue
            if (
                args.max_characters is not None
                and calls_made >= args.max_characters
            ):
                persist_output(args.output, records)
                return 0
            prompt = build_prompt(
                target["target_name"],
                chapter_number,
                chapter["chapter_summary"],
                transcript,
            )
            result, usage = call_gemini(
                client,
                args.model,
                prompt,
                args.thinking_budget,
                args.max_retries,
            )
            result_name = result.character_name.casefold()
            if not any(
                identity in result_name
                for identity in SPECIAL_EQUIPMENT_IDENTITIES
            ):
                result.character_details.wardrobe_and_layering.special_appendages_or_weapons = None
            cast_item = result.model_dump(exclude_none=True)
            cast_item["chapter_number"] = chapter_number
            record["cast"].append(cast_item)
            record["processed_targets"].append(
                {
                    "speaker_id": target["speaker_id"],
                    "target_name": target["target_name"],
                    "canonical_character_name": result.character_name,
                    "usage": usage,
                }
            )
            completed.add(completion_key)
            calls_made += 1
            persist_output(args.output, records)
            print(
                f"Chapter {chapter_number}: {target['target_name']} -> "
                f"{result.character_name}"
            )

        expected = {
            (target["speaker_id"], target["target_name"]) for target in targets
        }
        record["status"] = (
            "complete" if expected.issubset(completed) else "partial"
        )
        persist_output(args.output, records)

    print(f"Cast metadata written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
