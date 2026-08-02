#!/usr/bin/env python3
"""Create grounded Cradle lore notes from Pegasus chapters using local Mistral."""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import tempfile
from pathlib import Path

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")
ROOT = Path(__file__).resolve().parent
LORE_VERSION = 2


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    return json.loads(text[text.find("{"):text.rfind("}") + 1])


def persist(path: Path, rows: list[dict]) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as out:
        temp = Path(out.name)
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapters", type=Path, default=ROOT / "output/pegasus_chapter_metadata.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "output/mistral_chapter_lore.jsonl")
    parser.add_argument("--model", type=Path, default=ROOT / "models/Mistral-Nemo-Instruct-2407-bnb-4bit")
    parser.add_argument("--max-chapters", type=int)
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    chapters = [json.loads(x) for x in args.chapters.open() if x.strip()]
    existing = {}
    if args.output.exists():
        existing = {int(x["chapter_number"]): x for x in (json.loads(line) for line in args.output.open() if line.strip())}
    model = AutoModelForCausalLM.from_pretrained(args.model, device_map="auto", dtype=torch.bfloat16)
    tokenizer = AutoTokenizer.from_pretrained(args.model, fix_mistral_regex=True)
    done = 0
    try:
        for chapter in chapters:
            number = int(chapter["chapter_index"])
            source_prompt_version = chapter.get("prompt_version")
            cached = existing.get(number, {})
            if (
                cached.get("lore_version") == LORE_VERSION
                and cached.get("source_pegasus_prompt_version") == source_prompt_version
            ):
                continue
            if args.max_chapters is not None and done >= args.max_chapters:
                break
            grounding = {
                "chapter_summary": chapter.get("chapter_summary"),
                "speaker_name_guesses": chapter.get("speaker_name_guesses"),
                "representative_dialogue": chapter.get("representative_speaker_sentences"),
            }
            instruction = """You are adding cautious canonical Cradle-series lore to a visually grounded Pegasus analysis. Return only JSON with keys `characters` (array) and `name_corrections` (array). Each character object must contain canonical_name, aliases_seen, canonical_visual_facts, face_covering, neck_worn_objects, and confidence. Do not rewrite visible pose, gaze, expression, character count, or scenery. Do not invent lore when uncertain. Canonical hard rule: Wei Shi Lindon's Unsouled badge is a circular wooden badge on a cord around his neck, marked with the Chinese character meaning empty. It is never on his belt or sash and is not rectangular or hexagonal. Jai Long's face covering consists of layered cloth wrapping rather than a smooth phantom-style mask. Grounding follows:\n""" + json.dumps(grounding, ensure_ascii=False)
            result = None
            inputs = output = None
            repair_note = ""
            for attempt in range(3):
                messages = [{"role": "user", "content": instruction + repair_note}]
                inputs = tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True,
                    return_dict=True,
                    return_tensors="pt",
                ).to(model.device)
                with torch.inference_mode():
                    output = model.generate(**inputs, max_new_tokens=900, do_sample=False)
                raw = tokenizer.decode(
                    output[0][inputs.input_ids.shape[-1]:],
                    skip_special_tokens=True,
                )
                try:
                    result = parse_json(raw)
                    break
                except (json.JSONDecodeError, ValueError) as exc:
                    print(
                        f"Lore chapter {number}: invalid JSON attempt "
                        f"{attempt + 1}/3 ({exc})",
                        flush=True,
                    )
                    repair_note = (
                        "\nYour prior response was invalid or truncated JSON. "
                        "Return a shorter response with strict JSON syntax, double-quoted "
                        "keys and strings, and no prose or Markdown."
                    )
                    del inputs, output
                    inputs = output = None
                    gc.collect(); torch.cuda.empty_cache()
            if result is None:
                raise RuntimeError(
                    f"Mistral failed to return valid JSON for chapter {number} after 3 attempts"
                )
            existing[number] = {
                "chapter_number": number,
                "scene_indices": chapter.get("scene_indices", []),
                "lore_version": LORE_VERSION,
                "source_pegasus_prompt_version": source_prompt_version,
                "provider": "mistral-nemo-12b-local",
                **result,
            }
            persist(args.output, [existing[key] for key in sorted(existing)])
            done += 1
            print(f"Lore chapter {number}/{len(chapters)}", flush=True)
            del inputs, output
            gc.collect(); torch.cuda.empty_cache()
    finally:
        try: model.to("cpu")
        except Exception: pass
        del model, tokenizer
        gc.collect(); torch.cuda.empty_cache(); torch.cuda.ipc_collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
