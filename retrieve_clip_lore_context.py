#!/usr/bin/env python3
"""Retrieve structured visual and lore context for one Cradle video clip."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from google import genai
from google.genai import types
from google.oauth2 import service_account
from pydantic import BaseModel, ConfigDict, Field


LORE_FIELDS = (
    "video_description",
    "dialog",
    "characters_lore",
    "scenery_lore",
    "magic_lore",
)

DEFAULT_CHAPTER_METADATA = Path("output/pegasus_chapter_metadata.jsonl")
DEFAULT_TRANSCRIPT = Path("output/audiotranscript.jsonl")
SUMMARY_SEGMENT_PATTERN = re.compile(
    r"\[(\d{2}:\d{2}:\d{2}\.\d{3})-(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*"
    r"(.*?)(?=\s*\[\d{2}:\d{2}:\d{2}\.\d{3}-|\Z)",
    re.DOTALL,
)

LORE_CONTEXT_PROMPT = """
Analyze this short animatic clip from a proposed screen adaptation of Will
Wight's Cradle series. The clip is expected to draw from Book 1, Unsouled, or
Book 2, Soulsmith. Produce production-reference context that can later guide a
video-generation model using only the scene's first and last frames.

Return exactly the five fields defined by the response schema.

VIDEO_DESCRIPTION
- Describe only visible actions, changes, interactions, expressions, blocking,
  entrances, exits, props, and cause-and-effect across the clip.
- Describe composition, shot size, camera angle/movement, focus/depth cues, and
  a plausible lens-range hint when visually inferable.
- Track screen direction and positions such as screen-left, center, background,
  or right foreground. Describe the full progression, not merely one frame.
- Separate direct observation from inference. Never invent an unseen action.

DIALOG
- Transcribe only intelligible speech actually audible in this clip.
- Create one item per continuous utterance, in temporal order.
- Identify the speaker by character name only when supported by the clip and
  Cradle lore; otherwise use a neutral visual label such as "young man in the
  center." Include the speaker's general screen position.
- If speech is unclear, preserve only reliable words and mark the rest
  "[unclear]". Do not reconstruct dialogue from memory of the novels.
- Return an empty list when there is no intelligible dialogue.

CHARACTERS_LORE
- Include every visible character, using a stable visual label when a canonical
  identity is uncertain.
- Give a canonical name only when evidence is strong. Describe visible traits,
  approximate age, build, hair, clothing, accessories, condition, pose, and
  screen position.
- Add concise lore-accurate appearance and clothing guidance appropriate to the
  most likely moment in Unsouled or Soulsmith. Do not replace visible evidence
  with lore. State uncertainty and offer at most one likely alternative.

SCENERY_LORE
- Describe the visible setting, layout, architecture, terrain, materials,
  weather, lighting, atmosphere, and spatial relationship to the characters.
- Then add concise lore-accurate production guidance for the most likely
  location and moment in Unsouled or Soulsmith.
- If the book/location cannot be identified reliably, say that it is uncertain
  and give visually compatible guidance without asserting a chapter or event.

MAGIC_LORE
- Describe only visible or strongly action-implied fantastical elements that
  would require VFX: aura, madra, techniques, scripts, remnants, sacred beasts,
  impossible movement, supernatural damage, or related effects.
- Explain their motion, color only when supported, illumination, interaction
  with bodies/environment, and lore-accurate Cradle presentation.
- Do not turn ordinary motion, lighting, dust, or editing artifacts into magic.
- Return an empty string when no fantastical element is present or supportable.

ACCURACY RULES
- The clip is primary evidence. Book knowledge is secondary production context.
- Do not claim an exact book, chapter, character, technique, or location merely
  because it seems plausible.
- Prefer concise, visually actionable language over plot summary.
- Explicitly use "uncertain" or "not visually determinable" when warranted.
""".strip()


class DialogLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: str = Field(description="Canonical name or neutral visual label")
    transcript: str = Field(description="Only words reliably audible in the clip")
    screen_position: str


class CharacterLore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Canonical name or stable visual label")
    screen_position: str
    visible_description: str
    lore_guidance: str
    confidence: Literal["high", "medium", "low"]


class ClipLoreContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_description: str
    dialog: list[DialogLine]
    characters_lore: list[CharacterLore]
    scenery_lore: str
    magic_lore: str


def load_metadata(metadata_path: Path) -> tuple[dict, list[dict]]:
    with metadata_path.open("r", encoding="utf-8") as source:
        records = [json.loads(line) for line in source if line.strip()]
    if not records:
        raise ValueError(f"Metadata file is empty: {metadata_path}")
    return records[0], records[1:]


def find_scene(scenes: list[dict], scene_index: int) -> dict:
    try:
        return next(row for row in scenes if row.get("scene_index") == scene_index)
    except StopIteration as exc:
        raise ValueError(f"Scene {scene_index} was not found") from exc


def resolve_clip_path(metadata_path: Path, clip_file: str) -> Path:
    relative = Path(clip_file.replace("\\", "/"))
    clip_path = metadata_path.parent / relative
    if not clip_path.is_file():
        raise FileNotFoundError(f"Clip does not exist: {clip_path}")
    return clip_path


def parse_timecode(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def format_timecode(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"
    )


def load_related_chapter(chapter_path: Path, scene_index: int) -> dict:
    with chapter_path.open("r", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            chapter = json.loads(line)
            if scene_index in chapter.get("scene_indices", []):
                return chapter
    raise ValueError(
        f"No Pegasus chapter in {chapter_path} contains scene {scene_index}"
    )


def prepare_chapter_summary(
    chapter_summary: str,
    scene_start: float,
    scene_end: float,
    timecode_offset: float = 0.0,
) -> str:
    """Remove timecodes and mark summary segments overlapping the clip."""
    parsed_segments = []
    for match in SUMMARY_SEGMENT_PATTERN.finditer(chapter_summary):
        segment_start = parse_timecode(match.group(1)) + timecode_offset
        segment_end = parse_timecode(match.group(2)) + timecode_offset
        text = re.sub(r"\s+", " ", match.group(3)).strip()
        overlaps = segment_end >= scene_start and segment_start < scene_end
        distance = max(
            scene_start - segment_end,
            segment_start - scene_end,
            0,
        )
        parsed_segments.append(
            {
                "text": text,
                "overlaps": overlaps,
                "distance": distance,
            }
        )
    if not parsed_segments:
        raise ValueError("The related chapter summary has no timecoded segments")
    if not any(segment["overlaps"] for segment in parsed_segments):
        closest = min(parsed_segments, key=lambda segment: segment["distance"])
        closest["overlaps"] = True
    return " ".join(
        f"||{segment['text']}||"
        if segment["overlaps"]
        else segment["text"]
        for segment in parsed_segments
    )


def load_clip_transcript(
    transcript_path: Path,
    scene_start: float,
    scene_end: float,
    speaker_names: dict[str, str],
    transcript_items: list[dict] | None = None,
) -> str:
    """Create an in-memory, character-labeled transcript for one clip."""
    if transcript_items is None:
        with transcript_path.open("r", encoding="utf-8") as source:
            transcript_items = [
                json.loads(line) for line in source if line.strip()
            ]
    selected = [
        item
        for item in transcript_items
        if (
            item.get("record_type") == "timed_item"
            and isinstance(item.get("start"), (int, float))
            and isinstance(item.get("end"), (int, float))
            and item["end"] >= scene_start
            and item["start"] < scene_end
        )
    ]

    turns: list[dict] = []
    for item in selected:
        is_audio_event = item.get("type") == "audio_event"
        speaker_id = "audio_event" if is_audio_event else (
            item.get("speaker_id") or "unknown"
        )
        if (
            not turns
            or turns[-1]["speaker_id"] != speaker_id
            or item["start"] - turns[-1]["end"] > 2.0
        ):
            turns.append(
                {
                    "speaker_id": speaker_id,
                    "start": item["start"],
                    "end": item["end"],
                    "text": item.get("text", ""),
                }
            )
        else:
            turns[-1]["end"] = item["end"]
            turns[-1]["text"] += item.get("text", "")

    lines = []
    for turn in turns:
        text = re.sub(r"\s+", " ", turn["text"]).strip()
        if not text:
            continue
        label = (
            "Sound"
            if turn["speaker_id"] == "audio_event"
            else speaker_names.get(turn["speaker_id"], turn["speaker_id"])
        )
        lines.append(
            f"[{format_timecode(turn['start'])}-{format_timecode(turn['end'])}] "
            f"{label}: {text}"
        )
    return "\n".join(lines) if lines else "(No transcript items overlap this clip.)"


def build_grounded_prompt(
    chapter_summary: str,
    clip_transcript: str,
) -> str:
    return f"""
{LORE_CONTEXT_PROMPT}

GROUNDING CONTEXT
For returning the most accurate descriptions grounded in Will Wight's source
material and the book Unsouled, use the transcript and chapter summary below.
The sentence or sentences surrounded by double pipes (||) are the portion of
the chapter summary that relates to this clip. Use the surrounding chapter
summary only for continuity and identification. The video remains primary
evidence. Transcript spellings and chapter name guesses may be wrong; correct
proper names to their canonical Cradle spellings when the correction is
well-established (for example, use "Lindon," not "Linden").

CHAPTER SUMMARY:
{chapter_summary}

TRANSCRIPT FOR THIS CLIP:
{clip_transcript}
""".strip()


def create_vertex_client(credentials_path: Path) -> genai.Client:
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


def retrieve_context(
    client: genai.Client,
    clip_path: Path,
    prompt: str,
    model: str,
    thinking_budget: int,
) -> tuple[ClipLoreContext, object]:
    video_part = types.Part.from_bytes(
        data=clip_path.read_bytes(),
        mime_type="video/webm",
    )
    response = client.models.generate_content(
        model=model,
        contents=[prompt, video_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ClipLoreContext,
            temperature=0.2,
            thinking_config=types.ThinkingConfig(
                thinking_budget=thinking_budget,
            ),
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned no text")
    return ClipLoreContext.model_validate_json(response.text), response.usage_metadata


def write_scene_context(
    metadata_path: Path,
    main_record: dict,
    scenes: list[dict],
    scene_index: int,
    context: ClipLoreContext,
) -> None:
    values = context.model_dump()
    scene = find_scene(scenes, scene_index)
    scene.update(values)

    embedded_scenes = main_record.get("scenes", [])
    embedded_scene = find_scene(embedded_scenes, scene_index)
    embedded_scene.update(values)

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=metadata_path.parent,
        prefix=f".{metadata_path.name}.",
        delete=False,
    ) as destination:
        temporary_path = Path(destination.name)
        for record in [main_record, *scenes]:
            destination.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temporary_path, metadata_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retrieve Gemini video/lore context for one metadata scene."
    )
    parser.add_argument("--scene", type=int, default=293)
    parser.add_argument("--metadata", type=Path, default=Path("output/metadata.jsonl"))
    parser.add_argument(
        "--chapter-metadata",
        type=Path,
        default=DEFAULT_CHAPTER_METADATA,
    )
    parser.add_argument("--transcript", type=Path, default=DEFAULT_TRANSCRIPT)
    parser.add_argument("--credentials", type=Path, default=Path(".credentials.json"))
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument(
        "--thinking-budget",
        type=int,
        default=2048,
        help="Maximum Gemini thinking tokens; use 0 to disable thinking.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the five properties to both scene representations in metadata.",
    )
    args = parser.parse_args()

    main_record, scenes = load_metadata(args.metadata)
    scene = find_scene(scenes, args.scene)
    clip_path = resolve_clip_path(args.metadata, scene["clip_file"])
    chapter = load_related_chapter(args.chapter_metadata, args.scene)
    chapter_summary = prepare_chapter_summary(
        chapter["chapter_summary"],
        float(scene["start_time"]),
        float(scene["end_time"]),
        timecode_offset=float(chapter.get("movie_start_time_seconds") or 0),
    )
    speaker_names = {
        guess["speaker_id"]: guess["character_name_guess"]
        for guess in chapter.get("speaker_name_guesses", [])
        if guess.get("speaker_id") and guess.get("character_name_guess")
    }
    clip_transcript = load_clip_transcript(
        args.transcript,
        float(scene["start_time"]),
        float(scene["end_time"]),
        speaker_names,
    )
    prompt = build_grounded_prompt(chapter_summary, clip_transcript)
    client = create_vertex_client(args.credentials)
    context, usage = retrieve_context(
        client,
        clip_path,
        prompt,
        args.model,
        args.thinking_budget,
    )

    print(context.model_dump_json(indent=2))
    if usage is not None:
        print(
            "Token usage: "
            f"prompt={getattr(usage, 'prompt_token_count', None)}, "
            f"output={getattr(usage, 'candidates_token_count', None)}, "
            f"thinking={getattr(usage, 'thoughts_token_count', None)}, "
            f"total={getattr(usage, 'total_token_count', None)}",
            file=os.sys.stderr,
        )

    if args.write:
        write_scene_context(
            args.metadata,
            main_record,
            scenes,
            args.scene,
            context,
        )
        print(f"Updated scene {args.scene} in {args.metadata}", file=os.sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
