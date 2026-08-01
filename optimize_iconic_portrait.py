#!/usr/bin/env python3
"""Isolated prompt optimizer for one iconic character image; never edits metadata."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

from zimageturbo_batch_generator import ComfyUIWorkflowProcessor


ROOT = Path(__file__).resolve().parent
DEFAULT_REFERENCE = ROOT / "output/frames/scene_514_first_frame.png"
DEFAULT_OUTPUT = ROOT / "output/iconic_portrait_optimization/scene_514_first"
DEFAULT_PROMPT = """A horizontal 16:9 eye-level medium close-up shot captures a resolute hooded guard, positioned prominently in the left-center foreground, their form slightly turned right. Their face is largely obscured by a tightly wrapped, textured dark sand-colored cotton headscarf, revealing intense, piercing dark brown eyes with subtle subsurface scattering. A heavy, flowing dark olive green linen robe drapes their body, featuring natural creases and subtle dust textures from active use. A sturdy, polished dark wooden spear with a sharp, gleaming steel leaf-shaped head is firmly gripped by a weathered hand, positioned diagonally across the left frame. The background presents a softly blurred, neutral cool grey concrete corridor, featuring subtle vertical structural lines of an interior, enclosed space. A bright, cool white key light from the upper-left, 6000K, illuminates the figure, casting soft, diagonal shadows toward the bottom right and subtle specular highlights on the spearhead. Gentle bounce light enhances three-dimensional depth. Shot on a 50mm prime lens at f/2.2 aperture, focusing sharply on the eyes and spear, the image displays natural background bokeh and subtle 35mm film grain."""
REQUIREMENTS = """The character is Jai Long. His head, lower face, and neck are wrapped in overlapping deep crimson-red cloth strips. Dark handwritten script and irregular symbols are visibly inked across every band. Only his eyes show through one narrow, irregular horizontal opening. Loose ends of the layered wrapping trail over his shoulders and chest. The material looks like soft, individually layered textile strips—not a smooth balaclava, helmet, phantom mask, featureless face covering, or sand-colored scarf. Preserve the reference's medium close-up, slight right turn, intense eyes, dark robe, and spear at frame left."""

SAMPLE_REQUIREMENTS = {
    (30, "first"): """Use the canonical name Wei Shi Lindon, spelled exactly this way. He has short black hair. Preserve one youthful East Asian male seated contemplatively on the thick tree branch, centered in a medium shot with his body angled slightly right. Preserve the branch crossing the lower frame, the visible trunk and foliage, and the open sky. Do not add another person or change the seated pose.""",
    (108, "last"): """Use the canonical name Wei Shi Lindon, never Linden. Preserve the tight eye-level face close-up, his head slightly right of center, determined gaze, short messy black hair, and the foreshortened forearm entering from the bottom-left foreground. Preserve the direction of his face and the simple blurred interior background.""",
    (152, "last"): """The character is Wei Shi Lindon, not Lindon Arelius. Preserve the high-angle close-up with his body and head lying diagonally across the rocky ground, his surprised expression, and his dark layered clothing. His small rectangular wooden Unsouled badge hangs from a cord around his neck and rests visibly on his upper chest. It is not hexagonal, attached by a brass buckle, pinned to his shoulder, or worn on a belt.""",
    (194, "last"): """Preserve both people and their exact left-right arrangement: Wei Shi Lindon stands in the left foreground facing slightly right, while the second figure is seen from behind in the right midground holding a pole with a small triangular flag. Lindon's small rectangular wooden Unsouled badge hangs from a cord around his neck and rests on his chest. It is not held by a sash or belt. Preserve the ship railing, deck, and cloudy sky.""",
    (576, "first"): """Preserve exactly one long-haired man walking forward in the center of an eye-level medium shot. Preserve his determined stride, high-collared white coat over a dark fitted shirt, visible hands, narrow alley walls, overhead wires, and distant banners. Do not convert the walking pose into a static portrait or close-up.""",
    (767, "last"): """Preserve exactly one woman in a full dynamic attack pose, centered slightly right, with both arms raising a long-handled scythe overhead. Preserve the sweeping skirt and sash, pale blue energy traveling in from frame left, the carved rune platform along the bottom, and the dark wall. Keep the entire weapon, action silhouette, and energy direction legible.""",
    (514, "first"): REQUIREMENTS,
}


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=int, default=514)
    parser.add_argument("--frame", choices=("first", "last"), default="first")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--iterations", type=int, default=4)
    parser.add_argument("--seed", type=int, default=514030)
    parser.add_argument("--model", default="Qwen/Qwen2.5-VL-3B-Instruct")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8188")
    parser.add_argument(
        "--initial-critic-result", type=Path,
        help="Resume from the revised_prompt in a previous critic JSON result",
    )
    return parser.parse_args()


def load_source_prompt(scene: int, frame: str) -> str:
    metadata = ROOT / "output/metadatagen.jsonl"
    frame_type = f"{frame}_frame_file"
    with metadata.open("r", encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if int(record.get("scene_index", -1)) == scene and record.get("frame_type") == frame_type:
                prompt = record.get("prompt_text")
                if prompt:
                    return prompt
    raise SystemExit(f"No source prompt for scene {scene:03d} {frame} in {metadata}")


def write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def run_critic(args: argparse.Namespace, candidate: Path, prompt_path: Path, requirements_path: Path) -> dict:
    command = [
        sys.executable, str(ROOT / "iconic_portrait_critic.py"),
        "--reference", str(args.reference), "--candidate", str(candidate),
        "--prompt-file", str(prompt_path), "--requirements-file", str(requirements_path),
        "--model", args.model,
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(
            "Local visual critic failed:\n" + (completed.stderr or completed.stdout)[-6000:]
        )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def main() -> None:
    args = arguments()
    if args.iterations < 1:
        raise SystemExit("--iterations must be at least 1")
    if args.reference is None:
        args.reference = ROOT / f"output/frames/scene_{args.scene:03d}_{args.frame}_frame.png"
    if args.output_dir is None:
        args.output_dir = ROOT / (
            f"output/iconic_portrait_optimization/scene_{args.scene:03d}_{args.frame}"
        )
    args.reference = args.reference.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if not args.reference.is_file():
        raise SystemExit(f"Reference image not found: {args.reference}")
    requests.get(f"{args.endpoint}/system_stats", timeout=10).raise_for_status()

    requirements_path = args.output_dir / "canonical_requirements.txt"
    requirements = SAMPLE_REQUIREMENTS.get(
        (args.scene, args.frame),
        "Preserve the reference image's people, composition, pose, framing, props, and background geometry.",
    )
    write_text(requirements_path, requirements + "\n")
    history_path = args.output_dir / "history.jsonl"
    prompt = DEFAULT_PROMPT if (args.scene, args.frame) == (514, "first") else load_source_prompt(
        args.scene, args.frame
    )
    if args.initial_critic_result:
        prompt = json.loads(
            args.initial_critic_result.read_text(encoding="utf-8")
        )["revised_prompt"].strip()
    processor = ComfyUIWorkflowProcessor(endpoint=args.endpoint)
    best: dict | None = None

    with history_path.open("a", encoding="utf-8", buffering=1) as history:
        for iteration in range(args.iterations):
            prompt_path = args.output_dir / f"prompt_{iteration:02d}.txt"
            write_text(prompt_path, prompt + "\n")
            print(f"Iteration {iteration + 1}/{args.iterations}: generating with fixed seed {args.seed}", flush=True)
            result = processor.generate_image(prompt, args.seed, str(args.output_dir), iteration)
            if not result.get("success"):
                raise RuntimeError(result.get("error", "ComfyUI generation failed"))
            image = Path(result["gen_filename"]).resolve()

            processor.release_comfy_vram()
            edge_score = processor.calculate_similarity(str(args.reference), str(image))
            processor.release_similarity_models()
            print(f"  structural edge score: {edge_score:.2f}", flush=True)

            critic = run_critic(args, image, prompt_path, requirements_path)
            visual = float(critic["visual_match_score"])
            canonical = float(critic["canonical_match_score"])
            objective = round(0.35 * edge_score + 0.30 * visual + 0.35 * canonical, 3)
            record = {
                "iteration": iteration, "timestamp": time.time(), "seed": args.seed,
                "reference": str(args.reference), "image": str(image), "prompt": prompt,
                "edge_score": edge_score, "visual_match_score": visual,
                "canonical_match_score": canonical, "objective_score": objective,
                "strengths": critic.get("strengths", []), "mismatches": critic.get("mismatches", []),
                "revised_prompt": critic["revised_prompt"],
            }
            history.write(json.dumps(record, ensure_ascii=False) + "\n")
            if best is None or objective > best["objective_score"]:
                best = record
                write_text(args.output_dir / "best_prompt.txt", prompt + "\n")
                write_text(args.output_dir / "best_result.json", json.dumps(record, indent=2) + "\n")
            print(f"  objective: {objective:.2f}; critic is revising the next prompt", flush=True)
            prompt = critic["revised_prompt"].strip()

    print(f"Best iteration: {best['iteration']} ({best['objective_score']:.2f})")
    print(f"Results: {args.output_dir}")


if __name__ == "__main__":
    main()
