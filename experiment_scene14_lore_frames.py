#!/usr/bin/env python3
"""Generate lore-guided Gemini prompts and ComfyUI candidates for scene 14."""

import json
import os
import random
import tempfile
from datetime import datetime
from pathlib import Path

from gcp_vision_prompt import DEFAULT_PROMPT, GCPVisionPrompter
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor


SCENE_INDEX = 14
NUM_GENERATIONS = 10
FRAME_FILES = (
    "frames/scene_014_first_frame.png",
    "frames/scene_014_last_frame.png",
)
OUTPUT_DIR = Path("output/frames/scene_014_lore_context")
RESULTS_PATH = Path("output/scene_014_lore_context_experiment.json")

SCENE_14_LORE = {
    "video_description": (
        "The clip opens with a static, close-up shot of two bare hands, "
        "depicted in a simple animatic style, submerged in light blue water. "
        "The hands are positioned in the center of the frame, with ripples "
        "emanating from around them, indicating movement or disturbance in "
        "the water. The background is black, offering no further visual "
        "context. A splashing sound is audible."
    ),
    "dialog": [],
    "characters_lore": [
        {
            "name": "Lindon",
            "screen_position": "center",
            "visible_description": (
                "Two bare hands with a light gray skin tone, depicted in a "
                "simple animatic style, submerged in light blue water."
            ),
            "lore_guidance": (
                "Young Lindon, approximately 11-12 years old, undergoing the "
                "spiritual origin test. His hands should appear youthful and "
                "unblemished."
            ),
            "confidence": "medium",
        }
    ],
    "scenery_lore": (
        "The visible scenery consists solely of light blue water with "
        "concentric ripples, suggesting a contained body of water. The "
        "background is black, providing no further visual context for the "
        "container or environment. Lore-wise, this is the Soulfire water used "
        "for the spiritual origin test in Sacred Valley, contained within a "
        "stone basin or bowl in the Ancestor's Temple. The basin should be "
        "made of ancient, weathered stone, and the overall environment should "
        "be solemn and ritualistic."
    ),
    "magic_lore": (
        "The water is light blue and shows physical ripples caused by the "
        "hands entering it. There is no visible magical glow, clinging effect, "
        "or color change from the water itself. Lore-wise, this water is "
        "Soulfire water, a magical medium used in Sacred Valley's spiritual "
        "origin test. While it typically reacts to a person's spiritual "
        "affinity by glowing, clinging to the skin, or changing color, in this "
        "instance, the water shows no such magical reaction to Lindon's hands. "
        "This lack of magical response is the significant event, indicating "
        "his 'unsouled' status. The water itself should have a subtle, "
        "inherent blue glow, but this glow does not intensify or change in "
        "response to Lindon."
    ),
}


def save_results(results: dict) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=RESULTS_PATH.parent,
        prefix=f".{RESULTS_PATH.name}.",
        delete=False,
    ) as destination:
        temporary_path = Path(destination.name)
        json.dump(results, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    os.replace(temporary_path, RESULTS_PATH)


def load_results() -> dict:
    if RESULTS_PATH.is_file():
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    return {
        "scene_index": SCENE_INDEX,
        "lore_context": SCENE_14_LORE,
        "frames": {},
    }


def contextual_prompt() -> str:
    return (
        DEFAULT_PROMPT
        + "\n\nUse the below json to also inform your description of the image: "
        + json.dumps(SCENE_14_LORE, ensure_ascii=False)
    )


def main() -> int:
    results = load_results()
    prompter = GCPVisionPrompter()
    comfy = ComfyUIWorkflowProcessor()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for frame_file in FRAME_FILES:
        frame_path = Path("output") / frame_file
        frame_record = results["frames"].setdefault(
            frame_file,
            {"prompt_text": None, "generations": []},
        )
        if not frame_record["prompt_text"]:
            response = prompter.generate_prompt(
                frame_path,
                prompt=contextual_prompt(),
            )
            if not response["success"]:
                raise RuntimeError(response["error"])
            frame_record["prompt_text"] = response["response_text"].strip()
            frame_record["prompt_generated_at"] = datetime.now().isoformat()
            save_results(results)

        print(f"\n{frame_file}\n{frame_record['prompt_text']}\n", flush=True)
        completed = {
            int(item["gen_sequence"])
            for item in frame_record["generations"]
            if item.get("gen_filename")
        }
        queued = []
        for sequence in range(1, NUM_GENERATIONS + 1):
            if sequence in completed:
                continue
            seed = random.randint(0, 2**32 - 1)
            job = comfy.queue_image(
                prompt_text=frame_record["prompt_text"],
                seed=seed,
                output_dir=str(OUTPUT_DIR),
                gen_sequence=sequence,
            )
            record = {
                "gen_sequence": sequence,
                "seed": seed,
                "prompt_id": job["prompt_id"],
                "gen_filename": None,
                "queued_at": datetime.now().isoformat(),
            }
            frame_record["generations"].append(record)
            queued.append((record, job))
            save_results(results)
            print(
                f"Queued {frame_file} sequence {sequence}: {job['prompt_id']}",
                flush=True,
            )

        for record, job in queued:
            generated = comfy.collect_queued_image(job)
            record["gen_filename"] = generated["gen_filename"]
            record["completed_at"] = datetime.now().isoformat()
            save_results(results)
            print(f"Generated {generated['gen_filename']}", flush=True)

    comfy.release_comfy_vram()
    total = sum(
        1
        for frame in results["frames"].values()
        for generation in frame["generations"]
        if generation.get("gen_filename")
    )
    print(f"\nCompleted {total}/{len(FRAME_FILES) * NUM_GENERATIONS} images.")
    print(f"Experiment metadata: {RESULTS_PATH}")
    return 0 if total == len(FRAME_FILES) * NUM_GENERATIONS else 1


if __name__ == "__main__":
    raise SystemExit(main())
