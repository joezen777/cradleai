#!/usr/bin/env python3
"""
Generate Z-Image Turbo Prompts and Images for Book Cast Members
- Phase 1: Local LLM Prompt Optimization (using ZIMAGE_TURBO_GUIDANCE)
- Phase 2: Sequential ComfyUI Z-Image Turbo Generation (1 image per cast member)
Strict VRAM release between phases and JSONL persistence after every step.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BOOKCAST_PATH = ROOT / "bookcast.jsonl"
OUTPUT_DIR = ROOT / "output/bookcast_character_images"
WORKFLOW_FILE = ROOT / "zimageturbo_cinematic.json"
COMFY_ENDPOINT = "http://127.0.0.1:8188"
MODEL_PATH = ROOT / "models/Qwen3-VL-8B-Instruct"  # Fallback to local model dir if needed

# Z-Image Turbo Guidance for prompt optimization
ZIMAGE_TURBO_GUIDANCE = """
Rewrite the character visual description into one dense, highly descriptive 120-180 word positive prompt paragraph for ComfyUI Z-Image Turbo.
The prompt must produce a polished, cinematic, live-action character portrait still—never a cartoon, drawing, illustration, or anime frame.
Return ONLY the prompt text paragraph.
Begin with: A eye-level medium close-up portrait shot of [character name], [species/object type], [composition/pose].
Preserve and bind every color, facial feature, skin tone, hair style, wardrobe item, accessory, posture, and action explicitly to its noun.
Translate any missing or vague features into plausible Cradle-fantasy physical materials and details.
Specify coherent key-light direction, subtle rim lighting, a 50mm prime lens at f/2.0 aperture, sharp focus on the eyes, smooth natural background blur, and subtle 35mm film grain.
Use concrete, positive language only. Omit quality buzzwords, markdown tags, bullet points, explanations, and negative prompting.
""".strip()


def load_bookcast() -> list[dict[str, Any]]:
    if not BOOKCAST_PATH.is_file():
        raise FileNotFoundError(f"Bookcast file not found: {BOOKCAST_PATH}")
    records = []
    with BOOKCAST_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def save_bookcast(records: list[dict[str, Any]]) -> None:
    temp_path = BOOKCAST_PATH.with_suffix(".jsonl.tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    temp_path.replace(BOOKCAST_PATH)


def norm_name(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def get_existing_image_path(record: dict[str, Any]) -> str | None:
    # 1. Direct record check
    direct = record.get("gen_character_image") or record.get("primary_image_url")
    if direct and os.path.exists(direct):
        return direct
    for gen in record.get("image_generations", []):
        img_path = gen.get("gen_character_image")
        if img_path and os.path.exists(img_path):
            return img_path
    
    # 2. Check output/bookcast_character_images/{identity_key}.png
    ikey = record.get("identity_key") or norm_name(record.get("canonical_name", ""))
    custom_path = OUTPUT_DIR / f"{ikey}.png"
    if custom_path.is_file():
        return str(custom_path)
    return None


def construct_optimization_instruction(record: dict[str, Any]) -> str:
    name = record.get("canonical_name", "Unknown Character")
    species = record.get("species_or_object_type", "human")
    entity_type = record.get("entity_type", "individual person")
    portrait_desc = record.get("portrait_description", "")
    face = record.get("face")
    skin = record.get("skin_tone")
    eyes = record.get("eyes")
    hair = record.get("hair")
    build = record.get("build")
    clothing = record.get("clothing")
    wardrobe = record.get("wardrobe")
    accessories = record.get("accessories")
    posture = record.get("posture")
    action = record.get("action")
    fighting_move = record.get("fighting_move")
    color_info = record.get("color_information")

    attributes = []
    if face and "not specified" not in str(face).lower():
        attributes.append(f"Face: {face}")
    if skin and "not specified" not in str(skin).lower():
        attributes.append(f"Skin tone/surface: {skin}")
    if eyes and "not specified" not in str(eyes).lower():
        attributes.append(f"Eyes: {eyes}")
    if hair and "not specified" not in str(hair).lower():
        attributes.append(f"Hair: {hair}")
    if build and "not specified" not in str(build).lower():
        attributes.append(f"Build: {build}")
    if (clothing or wardrobe) and "not specified" not in str(clothing or wardrobe).lower():
        attributes.append(f"Clothing/Wardrobe: {clothing or wardrobe}")
    if accessories and "not specified" not in str(accessories).lower():
        attributes.append(f"Accessories/Equipment: {accessories}")
    if posture and "not specified" not in str(posture).lower():
        attributes.append(f"Posture: {posture}")
    if action and "not specified" not in str(action).lower():
        attributes.append(f"Action: {action}")
    if fighting_move and "not specified" not in str(fighting_move).lower():
        attributes.append(f"Fighting move: {fighting_move}")
    if color_info and "not specified" not in str(color_info).lower():
        attributes.append(f"Color information: {color_info}")

    attr_str = "\n".join(attributes) if attributes else "No extra specific visual attributes cited."

    instruction = f"""{ZIMAGE_TURBO_GUIDANCE}

CHARACTER METADATA:
Name: {name}
Entity Type: {entity_type}
Species / Type: {species}
Grounded Portrait Summary: {portrait_desc}

KEY ATTRIBUTES:
{attr_str}
""".strip()
    return instruction


def run_prompt_optimization_phase(records: list[dict[str, Any]]) -> int:
    print("=" * 80)
    print("PHASE 1: Local LLM Z-Image Turbo Prompt Optimization")
    print("=" * 80)

    # Find records needing prompt optimization
    unprompted = [
        (i, r) for i, r in enumerate(records)
        if not r.get("zimageturbo_prompt")
    ]
    print(f"Total bookcast members: {len(records)}")
    print(f"Records needing prompt optimization: {len(unprompted)}")

    if not unprompted:
        print("All records already have optimized zimageturbo_prompt strings!")
        return 0

    # Load local model
    sys.path.insert(0, str(ROOT / "lore_graph"))
    from loredb.local_model import LocalLoreModel

    model_target = ROOT / "models/Qwen3-VL-8B-Instruct"
    if not model_target.exists():
        model_target = Path("Qwen/Qwen2.5-VL-3B-Instruct")

    print(f"Loading local model from: {model_target} ...")
    model = LocalLoreModel(model_target)
    optimized_count = 0

    BATCH_SIZE = 8
    try:
        for i in range(0, len(unprompted), BATCH_SIZE):
            batch_items = unprompted[i : i + BATCH_SIZE]
            print(f"[{i+1}-{min(i+BATCH_SIZE, len(unprompted))}/{len(unprompted)}] Optimizing prompt batch ({len(batch_items)} items)...", flush=True)
            instructions = [construct_optimization_instruction(r) for _, r in batch_items]
            try:
                raw_prompts = model.generate_text_batch(instructions, max_new_tokens=400)
                import re
                for (original_idx, record), raw_p in zip(batch_items, raw_prompts):
                    name = record.get("canonical_name", "Unknown")
                    cleaned = re.sub(r"^```(?:text)?\s*|\s*```$", "", raw_p.strip(), flags=re.I).strip()
                    cleaned = re.sub(r"^\s*\*{0,2}prompt\*{0,2}\s*:\s*", "", cleaned, flags=re.I).strip()
                    records[original_idx]["zimageturbo_prompt"] = cleaned
                    records[original_idx]["prompt_optimized_at"] = datetime.now().isoformat()
                    optimized_count += 1
                    print(f"  ✓ {name}: {len(cleaned)} chars / {len(cleaned.split())} words")
                save_bookcast(records)
            except Exception as exc:
                print(f"  ✗ Batch failed: {type(exc).__name__}: {exc}. Retrying single items...")
                for original_idx, record in batch_items:
                    name = record.get("canonical_name", "Unknown")
                    try:
                        raw_p = model.generate_text(construct_optimization_instruction(record), max_new_tokens=400)
                        cleaned = re.sub(r"^```(?:text)?\s*|\s*```$", "", raw_p.strip(), flags=re.I).strip()
                        cleaned = re.sub(r"^\s*\*{0,2}prompt\*{0,2}\s*:\s*", "", cleaned, flags=re.I).strip()
                        records[original_idx]["zimageturbo_prompt"] = cleaned
                        records[original_idx]["prompt_optimized_at"] = datetime.now().isoformat()
                        save_bookcast(records)
                        optimized_count += 1
                        print(f"  ✓ {name}: {len(cleaned)} chars")
                    except Exception as e2:
                        print(f"  ✗ Single item failed for {name}: {e2}")

    finally:
        print("Closing local model and clearing CUDA memory...", flush=True)
        model.close()
        del model
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass
        print("✓ Model unloaded and VRAM released!")

    return optimized_count


def run_image_generation_phase(records: list[dict[str, Any]], endpoint: str = COMFY_ENDPOINT) -> int:
    print("\n" + "=" * 80)
    print("PHASE 2: ComfyUI Z-Image Turbo Image Generation")
    print("=" * 80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Check ComfyUI server availability
    import requests
    try:
        res = requests.get(f"{endpoint}/system_stats", timeout=10)
        res.raise_for_status()
        print(f"✓ Connected to ComfyUI at {endpoint}")
    except Exception as exc:
        print(f"❌ Could not connect to ComfyUI at {endpoint}: {exc}")
        print("Please verify ComfyUI is running on port 8188.")
        return 0

    from zimageturbo_batch_generator import ComfyUIWorkflowProcessor
    processor = ComfyUIWorkflowProcessor(
        workflow_file=str(WORKFLOW_FILE),
        endpoint=endpoint
    )

    # Find records needing image generation
    unrendered = []
    for i, r in enumerate(records):
        existing_img = get_existing_image_path(r)
        if not existing_img:
            unrendered.append((i, r))

    print(f"Total bookcast members: {len(records)}")
    print(f"Records needing image generation: {len(unrendered)}")

    if not unrendered:
        print("All bookcast members already have character images!")
        return 0

    generated_count = 0
    failed_count = 0

    for idx, (original_idx, record) in enumerate(unrendered, 1):
        name = record.get("canonical_name", "Unknown")
        ikey = record.get("identity_key") or norm_name(name)
        prompt = record.get("zimageturbo_prompt") or record.get("portrait_description") or name
        seed = random.randint(0, 2**32 - 1)

        print(f"\n[{idx}/{len(unrendered)}] Generating image for: {name} (key: {ikey})...", flush=True)
        print(f"  Seed: {seed}")
        print(f"  Prompt ({len(prompt)} chars): {prompt[:100]}...")

        try:
            result = processor.generate_image(
                prompt_text=prompt,
                seed=seed,
                output_dir=str(OUTPUT_DIR),
                gen_sequence=1,
            )

            if result and result.get("success"):
                gen_file = result["gen_filename"]
                print(f"  ✓ Image generated: {gen_file}")

                # Update record
                gen_record = {
                    "genaimodel": "zimageturbo",
                    "gen_character_image": gen_file,
                    "seed": seed,
                    "generated_at": datetime.now().isoformat()
                }

                records[original_idx]["gen_character_image"] = gen_file
                records[original_idx]["primary_image_url"] = gen_file
                if "image_generations" not in records[original_idx]:
                    records[original_idx]["image_generations"] = []
                records[original_idx]["image_generations"].append(gen_record)

                # Save immediately after each image generation
                save_bookcast(records)
                generated_count += 1

                # Request ComfyUI VRAM release
                processor.release_comfy_vram()
            else:
                err = result.get("error", "Unknown error") if result else "No result returned"
                print(f"  ✗ ComfyUI generation failed: {err}")
                failed_count += 1

        except Exception as exc:
            print(f"  ✗ Exception during image generation: {type(exc).__name__}: {exc}")
            failed_count += 1

    print("\n" + "=" * 80)
    print(f"Phase 2 Complete: {generated_count} images generated, {failed_count} failed.")
    print("=" * 80)
    return generated_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prompt", "image", "all"), default="all")
    parser.add_argument("--endpoint", default=COMFY_ENDPOINT)
    args = parser.parse_args()

    records = load_bookcast()

    if args.phase in ("prompt", "all"):
        run_prompt_optimization_phase(records)
        # Reload records from disk to ensure fresh state
        records = load_bookcast()

    if args.phase in ("image", "all"):
        run_image_generation_phase(records, endpoint=args.endpoint)

    return 0


if __name__ == "__main__":
    sys.exit(main())
