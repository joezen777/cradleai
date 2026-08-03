#!/usr/bin/env python3
"""Compare legacy and ground-enhanced prompts for any scene frame in ComfyUI."""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import requests

from generate_prompts_from_metadata import PromptGenerationPhase1
from prompt_variations import apply_variation
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor


ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=int, default=66)
    parser.add_argument("--frame", choices=("first", "last"), default="first")
    parser.add_argument("--metadata", default="output/metadata.jsonl")
    parser.add_argument("--legacy-metadatagen", default="output/metadatagen.jsonl")
    parser.add_argument(
        "--grounding-confirmations",
        default="lore_graph/grounding_confirmations.json",
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:8188")
    parser.add_argument("--workflow", default="zimageturbo_cinematic.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/frames/ground_enhance_comparison"),
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--discover-only", action="store_true",
        help="Run only lore-location discovery and print candidates without ComfyUI",
    )
    parser.add_argument("--prepare-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--variation-sequence", type=int, default=1,
        help="Controlled render variation used for new_prompt_text",
    )
    return parser.parse_args()


def normalized_path(value: str) -> str:
    return value.replace("\\", "/")


def load_scene(metadata_path: Path, scene_index: int) -> dict:
    with metadata_path.open("r", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            if isinstance(record, dict) and int(record.get("scene_index", -1)) == scene_index:
                return record
    raise ValueError(f"Scene {scene_index} was not found in {metadata_path}")


def load_legacy_prompt(path: Path, frame_file: str) -> str:
    target = normalized_path(frame_file)
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            if (
                normalized_path(str(record.get("frame_file") or "")) == target
                and int(record.get("gen_sequence") or 0) == 1
                and str(record.get("prompt_text") or "").strip()
            ):
                return str(record["prompt_text"]).strip()
    raise ValueError(f"No legacy sequence-1 prompt found for {target} in {path}")


def resolve_frame_path(frame_file: str) -> Path:
    normalized = normalized_path(frame_file)
    candidates = (ROOT / "output" / normalized, ROOT / normalized)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Frame image not found: {frame_file}")


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def add_watermark(path: Path, variable_name: str, scene: int, frame: str) -> None:
    with Image.open(path).convert("RGBA") as source:
        overlay = Image.new("RGBA", source.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font_size = max(24, source.width // 42)
        font = load_font(font_size)
        frame_number = 1 if frame == "first" else 2
        label = f"{variable_name}\nscene {scene:03d} · frame {frame_number} ({frame})"
        padding = max(14, font_size // 2)
        margin = max(18, font_size // 2)
        spacing = max(5, font_size // 5)
        left, top, right, bottom = draw.multiline_textbbox(
            (0, 0), label, font=font, spacing=spacing
        )
        box_width = right - left + padding * 2
        box_height = bottom - top + padding * 2
        box = (
            margin,
            source.height - margin - box_height,
            margin + box_width,
            source.height - margin,
        )
        draw.rounded_rectangle(box, radius=padding // 2, fill=(12, 12, 12, 235))
        draw.multiline_text(
            (box[0] + padding, box[1] + padding - top),
            label,
            font=font,
            fill=(255, 255, 255, 255),
            spacing=spacing,
        )
        Image.alpha_composite(source, overlay).convert("RGB").save(path, quality=95)


def unload_comfy_models(endpoint: str) -> None:
    response = requests.post(
        f"{endpoint.rstrip('/')}/free",
        json={"unload_models": True, "free_memory": True},
        timeout=30,
    )
    response.raise_for_status()
    print("ComfyUI cached models unloaded before lore grounding", flush=True)


def ground_prompts(
    args: argparse.Namespace,
    scene: dict,
    frame_file: str,
    frame_path: Path,
    visual_reference_description: str,
) -> tuple[str, str, dict]:
    phase = PromptGenerationPhase1(
        metadata_file=args.metadata,
        ground_enhance=True,
        grounding_confirmations_file=args.grounding_confirmations,
        num_copies=1,
    )
    try:
        result = phase._ground_enhance_prompt(
            frame_path, frame_file, scene, visual_reference_description
        )
    finally:
        phase.close()
    if not result.get("success"):
        raise RuntimeError(str(result.get("error") or "ground_enhance failed"))
    grounding = result["grounding"]
    grounded = str(grounding.get("grounded_enhanced_description") or "").strip()
    base = str(result.get("response_text") or "").strip()
    if not grounded or not base:
        raise RuntimeError("ground_enhance returned incomplete comparison text")
    return grounded, base, grounding


def discover_locations(args: argparse.Namespace, scene: dict, frame_file: str, frame_path: Path) -> dict:
    phase = PromptGenerationPhase1(
        metadata_file=args.metadata,
        ground_enhance=True,
        grounding_confirmations_file="/tmp/no-grounding-confirmations.json",
        num_copies=1,
    )
    try:
        result = phase._ground_enhance_prompt(frame_path, frame_file, scene)
    finally:
        phase.close()
    return result


def main() -> int:
    args = parse_args()
    job_started = datetime.now().astimezone()
    timestamp = job_started.strftime("%Y%m%d_%H%M%S")
    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    scene = load_scene(Path(args.metadata), args.scene)
    frame_key = f"{args.frame}_frame_file"
    frame_file = str(scene.get(frame_key) or "")
    if not frame_file:
        raise ValueError(f"Scene {args.scene} has no {args.frame} frame")
    frame_path = resolve_frame_path(frame_file)

    if args.discover_only:
        print(json.dumps(
            discover_locations(args, scene, frame_file, frame_path), indent=2
        ))
        return 0

    if args.prepare_output:
        old_prompt = load_legacy_prompt(Path(args.legacy_metadatagen), frame_file)
        grounded, base_prompt, grounding = ground_prompts(
            args, scene, frame_file, frame_path, old_prompt
        )
        new_prompt, variation_id = apply_variation(
            base_prompt, args.variation_sequence
        )
        args.prepare_output.write_text(json.dumps({
            "prompts": {
                "old_prompt_text": old_prompt,
                "grounded_enhanced_description": grounded,
                "base_prompt_text": base_prompt,
                "new_prompt_text": new_prompt,
            },
            "variation_id": variation_id,
            "ground_enhance": grounding,
        }, indent=2), encoding="utf-8")
        print(f"Prepared prompts in {args.prepare_output}; lore child exiting", flush=True)
        return 0

    with tempfile.NamedTemporaryFile(
        prefix=f"scene_{args.scene:03d}_{args.frame}_ground_",
        suffix=".json",
        dir="/tmp",
        delete=False,
    ) as temporary:
        prepared_path = Path(temporary.name)
    prepare_command = [
        sys.executable, str(Path(__file__).resolve()),
        "--scene", str(args.scene),
        "--frame", args.frame,
        "--metadata", args.metadata,
        "--legacy-metadatagen", args.legacy_metadatagen,
        "--grounding-confirmations", args.grounding_confirmations,
        "--variation-sequence", str(args.variation_sequence),
        "--prepare-output", str(prepared_path),
    ]
    try:
        unload_comfy_models(args.endpoint)
        print("Starting isolated lore-grounding child process", flush=True)
        subprocess.run(prepare_command, cwd=ROOT, env=os.environ.copy(), check=True)
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    finally:
        prepared_path.unlink(missing_ok=True)
    print("Lore-grounding child exited; connecting to ComfyUI", flush=True)
    prompts = prepared["prompts"]
    grounding = prepared["ground_enhance"]
    variation_id = prepared["variation_id"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    processor = ComfyUIWorkflowProcessor(
        workflow_file=args.workflow,
        endpoint=args.endpoint,
    )
    queued = []
    for sequence, (variable_name, prompt) in enumerate(prompts.items(), 1):
        print(f"Queueing {variable_name} with seed {seed}", flush=True)
        job = processor.queue_image(
            prompt_text=prompt,
            seed=seed,
            output_dir=str(args.output_dir),
            gen_sequence=sequence,
        )
        queued.append((variable_name, prompt, job))

    records = []
    for variable_name, prompt, job in queued:
        result = processor.collect_queued_image(job)
        generated_path = Path(result["gen_filename"])
        destination = args.output_dir / f"{variable_name}_{timestamp}{generated_path.suffix}"
        generated_path.replace(destination)
        add_watermark(destination, variable_name, args.scene, args.frame)
        records.append({
            "variable_name": variable_name,
            "scene_index": args.scene,
            "frame": args.frame,
            "source_frame": normalized_path(frame_file),
            "job_started": job_started.isoformat(),
            "seed": seed,
            "variation_id": variation_id if variable_name == "new_prompt_text" else None,
            "prompt_id": job["prompt_id"],
            "prompt_text": prompt,
            "image": str(destination),
        })
        print(f"Saved watermarked {destination}", flush=True)

    manifest = args.output_dir / f"scene_{args.scene:03d}_{args.frame}_comparison_{timestamp}.json"
    manifest.write_text(json.dumps({
        "ground_enhance": grounding,
        "generations": records,
    }, indent=2), encoding="utf-8")
    print(f"Saved manifest {manifest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
