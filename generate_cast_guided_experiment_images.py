#!/usr/bin/env python3
"""Generate resumable ComfyUI images for cast-guided frame prompts."""

import argparse
import json
import os
import random
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from zimageturbo_batch_generator import ComfyUIWorkflowProcessor


DEFAULT_EXPERIMENT = Path("output/cast_guided_frame_prompt_experiment.json")
DEFAULT_OUTPUT_DIR = Path("output/frames/cast_guided_prompt_experiment")


def save_results(path: Path, results: dict[str, Any]) -> None:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--num-generations", type=int, default=10)
    parser.add_argument("--workflow", default="zimageturbo_cinematic.json")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8188")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = json.loads(args.experiment.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    comfy = ComfyUIWorkflowProcessor(
        workflow_file=args.workflow,
        endpoint=args.endpoint,
    )

    for scene_key in sorted(results["scenes"], key=int):
        scene = results["scenes"][scene_key]
        for frame_type in ("first_frame_file", "last_frame_file"):
            frame = scene["frames"][frame_type]
            generations = frame.setdefault("generations", [])
            completed = {
                int(item["gen_sequence"])
                for item in generations
                if item.get("gen_filename")
                and Path(item["gen_filename"]).is_file()
            }
            existing_by_sequence = {
                int(item["gen_sequence"]): item for item in generations
            }
            queued = []
            for sequence in range(1, args.num_generations + 1):
                if sequence in completed:
                    continue
                previous = existing_by_sequence.get(sequence)
                if previous and previous.get("prompt_id"):
                    job = {
                        "prompt_id": previous["prompt_id"],
                        "seed": previous["seed"],
                        "gen_sequence": sequence,
                        "output_dir": str(args.output_dir),
                        "timeout": 1800,
                    }
                    queued.append((previous, job))
                    continue
                seed = random.randint(0, 2**32 - 1)
                job = comfy.queue_image(
                    prompt_text=frame["prompt_text"],
                    seed=seed,
                    output_dir=str(args.output_dir),
                    gen_sequence=sequence,
                )
                job["timeout"] = 1800
                record = {
                    "gen_sequence": sequence,
                    "seed": seed,
                    "prompt_id": job["prompt_id"],
                    "gen_filename": None,
                    "queued_at": datetime.now().isoformat(),
                }
                generations.append(record)
                queued.append((record, job))
                save_results(args.experiment, results)
                print(
                    f"Queued scene {scene_key} {frame_type} "
                    f"sequence {sequence}: {job['prompt_id']}",
                    flush=True,
                )

            for record, job in queued:
                generated = comfy.collect_queued_image(job)
                record["gen_filename"] = generated["gen_filename"]
                record["completed_at"] = datetime.now().isoformat()
                save_results(args.experiment, results)
                print(
                    f"Generated scene {scene_key} {frame_type}: "
                    f"{generated['gen_filename']}",
                    flush=True,
                )

    comfy.release_comfy_vram()
    total = sum(
        1
        for scene in results["scenes"].values()
        for frame in scene["frames"].values()
        for generation in frame.get("generations", [])
        if generation.get("gen_filename")
    )
    expected = (
        len(results["scenes"]) * 2 * args.num_generations
    )
    print(f"Completed {total}/{expected} cast-guided experiment images")
    return 0 if total == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
