#!/usr/bin/env python3
"""Generate lore- and cast-guided frame prompts without changing source data."""

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from gcp_vision_prompt import DEFAULT_PROMPT, GCPVisionPrompter
from retrieve_clip_lore_context import (
    build_grounded_prompt,
    create_vertex_client,
    find_scene,
    load_clip_transcript,
    load_metadata,
    load_related_chapter,
    prepare_chapter_summary,
    resolve_clip_path,
    retrieve_context,
)


DEFAULT_SCENES = (12, 14, 15)
DEFAULT_METADATA = Path("output/metadata.jsonl")
DEFAULT_CHAPTERS = Path("output/pegasus_chapter_metadata.jsonl")
DEFAULT_CAST = Path("output/gemini_chapter_cast.jsonl")
DEFAULT_TRANSCRIPT = Path("output/audiotranscript.jsonl")
DEFAULT_CREDENTIALS = Path(".credentials.json")
DEFAULT_OUTPUT = Path("output/cast_guided_frame_prompt_experiment.json")
CAST_INSTRUCTION = (
    "Take into account character descriptions from the below JSON body "
    "describing the main characters in the scene—where relevant."
)


def load_cast_records(path: Path) -> dict[int, dict[str, Any]]:
    with path.open("r", encoding="utf-8") as source:
        return {
            int(record["chapter_number"]): record
            for line in source
            if line.strip()
            for record in [json.loads(line)]
        }


def load_results(path: Path) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"scenes": {}}


def save_results(path: Path, results: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as destination:
        temporary_path = Path(destination.name)
        json.dump(results, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    os.replace(temporary_path, path)


def cast_payload(record: dict[str, Any]) -> dict[str, Any]:
    """Return only the user-facing nested cast content."""
    return {
        "chapter_number": record["chapter_number"],
        "cast": record.get("cast", []),
    }


def frame_prompt(lore_context: dict[str, Any], cast: dict[str, Any]) -> str:
    return (
        DEFAULT_PROMPT
        + "\n\nUse the below json to also inform your description of the image: "
        + json.dumps(lore_context, ensure_ascii=False)
        + "\n\n"
        + CAST_INSTRUCTION
        + "\n"
        + json.dumps(cast, ensure_ascii=False)
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenes", type=int, nargs="+", default=DEFAULT_SCENES)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--chapters", type=Path, default=DEFAULT_CHAPTERS)
    parser.add_argument("--cast", type=Path, default=DEFAULT_CAST)
    parser.add_argument("--transcript", type=Path, default=DEFAULT_TRANSCRIPT)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--thinking-budget", type=int, default=2048)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _, scenes = load_metadata(args.metadata)
    cast_records = load_cast_records(args.cast)
    results = load_results(args.output)
    lore_client = create_vertex_client(args.credentials)
    image_prompter = GCPVisionPrompter(str(args.credentials))

    for scene_index in args.scenes:
        scene = find_scene(scenes, scene_index)
        chapter = load_related_chapter(args.chapters, scene_index)
        chapter_number = int(chapter["chapter_index"])
        if chapter_number not in cast_records:
            raise ValueError(
                f"No cast output exists for chapter {chapter_number}"
            )
        summary = prepare_chapter_summary(
            chapter["chapter_summary"],
            float(scene["start_time"]),
            float(scene["end_time"]),
        )
        speaker_names = {
            guess["speaker_id"]: guess["character_name_guess"]
            for guess in chapter.get("speaker_name_guesses", [])
            if guess.get("speaker_id") and guess.get("character_name_guess")
        }
        transcript = load_clip_transcript(
            args.transcript,
            float(scene["start_time"]),
            float(scene["end_time"]),
            speaker_names,
        )
        lore_prompt = build_grounded_prompt(summary, transcript)
        clip_path = resolve_clip_path(args.metadata, scene["clip_file"])
        lore, _ = retrieve_context(
            lore_client,
            clip_path,
            lore_prompt,
            args.model,
            args.thinking_budget,
        )
        lore_json = lore.model_dump()
        cast_json = cast_payload(cast_records[chapter_number])
        prompt = frame_prompt(lore_json, cast_json)

        scene_record = {
            "scene_index": scene_index,
            "chapter_number": chapter_number,
            "clip_file": scene["clip_file"],
            "lore_context": lore_json,
            "cast_context": cast_json,
            "frames": {},
        }
        for frame_type in ("first_frame_file", "last_frame_file"):
            frame_file = scene[frame_type]
            frame_path = args.metadata.parent / Path(
                frame_file.replace("\\", "/")
            )
            response = image_prompter.generate_prompt(
                frame_path,
                prompt=prompt,
                model=args.model,
            )
            if not response["success"]:
                raise RuntimeError(
                    f"Scene {scene_index} {frame_type}: {response['error']}"
                )
            scene_record["frames"][frame_type] = {
                "frame_file": frame_file,
                "prompt_text": response["response_text"].strip(),
            }
            print(
                f"\nScene {scene_index} {frame_type}:\n"
                f"{response['response_text'].strip()}\n",
                flush=True,
            )
            results["scenes"][str(scene_index)] = scene_record
            save_results(args.output, results)

    print(f"Saved experiment results to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
