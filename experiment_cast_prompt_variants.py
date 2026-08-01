#!/usr/bin/env python3
"""Create two reduced-cast Gemini prompt_text experiment variants."""

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from gcp_vision_prompt import DEFAULT_PROMPT, GCPVisionPrompter


BASE_EXPERIMENT = Path("output/cast_guided_frame_prompt_experiment.json")
CAST_FILE = Path("output/gemini_chapter_cast.jsonl")
VARIANTS = {
    "description_genprompt": {
        "output": Path(
            "output/cast_description_genprompt_frame_experiment.json"
        ),
        "instruction": (
            "Take into account the character descriptions and character "
            "generation prompts from the below JSON body describing the main "
            "characters in the scene—where relevant."
        ),
    },
    "details_no_pose": {
        "output": Path(
            "output/cast_details_no_pose_frame_experiment.json"
        ),
        "instruction": (
            "Take into account the structured character details from the "
            "below JSON body describing the main characters in the scene—"
            "where relevant. The pose_and_composition property is "
            "intentionally omitted; preserve composition, pose, framing, and "
            "camera angle from the attached source image."
        ),
    },
}


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as destination:
        temporary_path = Path(destination.name)
        json.dump(value, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    os.replace(temporary_path, path)


def load_cast() -> dict[int, list[dict[str, Any]]]:
    with CAST_FILE.open("r", encoding="utf-8") as source:
        return {
            int(record["chapter_number"]): record.get("cast", [])
            for line in source
            if line.strip()
            for record in [json.loads(line)]
        }


def reduced_cast(
    cast: list[dict[str, Any]],
    variant: str,
) -> list[dict[str, Any]]:
    reduced = []
    for character in cast:
        if variant == "description_genprompt":
            reduced.append(
                {
                    "character_name": character["character_name"],
                    "character_description": character[
                        "character_description"
                    ],
                    "character_genprompt": character["character_genprompt"],
                }
            )
        else:
            details = copy.deepcopy(character["character_details"])
            details.pop("pose_and_composition", None)
            reduced.append(
                {
                    "character_name": character["character_name"],
                    "character_details": details,
                }
            )
    return reduced


def main() -> int:
    base = json.loads(BASE_EXPERIMENT.read_text(encoding="utf-8"))
    cast_by_chapter = load_cast()
    prompter = GCPVisionPrompter()

    for variant, settings in VARIANTS.items():
        result = {"variant": variant, "scenes": {}}
        for scene_key in sorted(base["scenes"], key=int):
            source_scene = base["scenes"][scene_key]
            chapter_number = int(source_scene["chapter_number"])
            cast = reduced_cast(cast_by_chapter[chapter_number], variant)
            scene_result = {
                "scene_index": int(scene_key),
                "chapter_number": chapter_number,
                "clip_file": source_scene["clip_file"],
                "lore_context": source_scene["lore_context"],
                "cast_context": {
                    "chapter_number": chapter_number,
                    "cast": cast,
                },
                "frames": {},
            }
            image_prompt = (
                DEFAULT_PROMPT
                + "\n\nUse the below json to also inform your description "
                "of the image: "
                + json.dumps(
                    source_scene["lore_context"],
                    ensure_ascii=False,
                )
                + "\n\n"
                + settings["instruction"]
                + "\n"
                + json.dumps(
                    {"chapter_number": chapter_number, "cast": cast},
                    ensure_ascii=False,
                )
            )
            for frame_type in ("first_frame_file", "last_frame_file"):
                source_frame = source_scene["frames"][frame_type]
                frame_file = source_frame["frame_file"]
                frame_path = Path("output") / Path(
                    frame_file.replace("\\", "/")
                )
                response = prompter.generate_prompt(
                    frame_path,
                    prompt=image_prompt,
                )
                if not response["success"]:
                    raise RuntimeError(
                        f"{variant} scene {scene_key} {frame_type}: "
                        f"{response['error']}"
                    )
                prompt_text = response["response_text"].strip()
                scene_result["frames"][frame_type] = {
                    "frame_file": frame_file,
                    "prompt_text": prompt_text,
                }
                result["scenes"][scene_key] = scene_result
                save(settings["output"], result)
                print(
                    f"\n{variant} scene {scene_key} {frame_type}:\n"
                    f"{prompt_text}\n",
                    flush=True,
                )
        print(f"Saved {variant} to {settings['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
