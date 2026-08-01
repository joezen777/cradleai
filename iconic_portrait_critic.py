#!/usr/bin/env python3
"""One-shot local visual critic for the isolated iconic-portrait optimizer."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

# This machine's PyTorch build otherwise attempts to JIT-compile optional
# Triton-native kernels and requires system Python development headers.
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--requirements-file", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen2.5-VL-3B-Instruct")
    return parser.parse_args()


def extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"Visual critic returned no JSON object: {text[:500]}")
    return json.loads(text[start : end + 1])


def main() -> None:
    args = parse_args()
    import torch
    from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration
    from qwen_vl_utils import process_vision_info

    prompt = args.prompt_file.read_text(encoding="utf-8")
    requirements = args.requirements_file.read_text(encoding="utf-8")
    instruction = f"""
You are the visual critic in a controlled text-to-image optimization experiment.
Image 1 is the target storyboard/reference. Image 2 is the latest generated candidate.
Compare composition, pose, silhouette, camera framing, clothing, face covering, colors,
and identity-defining details. The following canonical requirements override ambiguity:

{requirements}

The prompt used for Image 2 was:
{prompt}

Return ONLY one JSON object with these keys:
{{
  "visual_match_score": integer 0-100,
  "canonical_match_score": integer 0-100,
  "strengths": [short strings],
  "mismatches": [short strings ordered by importance]
}}
""".strip()

    messages = [{"role": "user", "content": [
        {"type": "image", "image": str(args.reference.resolve())},
        {"type": "image", "image": str(args.candidate.resolve())},
        {"type": "text", "text": instruction},
    ]}]
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        args.model,
        device_map="auto",
        dtype=torch.bfloat16,
        quantization_config=quantization,
    )
    processor = AutoProcessor.from_pretrained(args.model)

    def generate(active_messages: list[dict], max_tokens: int) -> str:
        rendered = processor.apply_chat_template(
            active_messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(active_messages)
        inputs = processor(
            text=[rendered], images=image_inputs, videos=video_inputs,
            padding=True, return_tensors="pt",
        ).to(model.device)
        with torch.inference_mode():
            generated = model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False)
        generated = [output[len(source):] for source, output in zip(inputs.input_ids, generated)]
        return processor.batch_decode(generated, skip_special_tokens=True)[0].strip()

    result = extract_json(generate(messages, 350))
    rewrite_instruction = f"""Write only the complete replacement text-to-image prompt—no
heading, preface, quotes, JSON, or commentary. Use 120-190 words. Preserve the target reference's
composition, pose, camera framing, and spear placement while explicitly depicting all of these
authoritative character requirements:

{requirements}

Describe only what should be visible in the finished image using positive, concrete language.
Begin with: A horizontal 16:9 medium close-up
"""
    rewrite_messages = [{"role": "user", "content": [
        {"type": "image", "image": str(args.reference.resolve())},
        {"type": "text", "text": rewrite_instruction},
    ]}]
    revised_prompt = generate(rewrite_messages, 420)
    if len(revised_prompt.split()) < 40:
        raise ValueError(f"Visual critic produced an incomplete prompt: {revised_prompt}")
    result["revised_prompt"] = revised_prompt
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
