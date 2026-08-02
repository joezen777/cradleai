#!/usr/bin/env python3
"""Local Qwen3-VL frame-to-prompt provider; no external API calls."""

from __future__ import annotations

import gc
import os
import re
from pathlib import Path
from typing import Any

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")

DEFAULT_PROMPT = """Create one dense 160-230 word positive prompt for Z-Image
Turbo that recreates the attached storyboard frame as a polished cinematic
live-action still. Return only the prompt. Preserve exact character count,
left-right arrangement, framing, camera angle, body posture, limb and hand
positions, head direction, eye direction, nuanced facial expression, facial
coverings, neck-worn objects, props, and background geometry. Treat the drawing
as a key pose in continuous motion, not as a motionless person. The grounding
context may clarify identity, intended motion, clothing, colors, and lore, but
must never add an off-screen person or override visible composition. Describe
desired features positively and concretely. Avoid generic masks when layered
wrapping is intended. Never move a necklace or badge to a belt or sash."""

LINDON_BADGE_RULE = """ If the visible character is Wei Shi Lindon and his
badge is visible, describe it exactly as a circular wooden badge hanging from a
cord around his neck and marked with the Chinese character meaning empty. Never
describe Lindon's badge as rectangular, hexagonal, buckled, pinned, or attached
to a belt, sash, or shoulder."""


class LocalFramePrompter:
    def __init__(self, model_path: str = "models/Qwen3-VL-8B-Instruct"):
        self.model_path = str((Path(__file__).resolve().parent / model_path).resolve())
        self.model: Any = None
        self.processor: Any = None
        self.torch: Any = None

    def _load(self) -> None:
        if self.model is not None:
            return
        import torch
        from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration

        self.torch = torch
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            self.model_path,
            device_map="auto",
            dtype=torch.bfloat16,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            ),
        )
        self.processor = AutoProcessor.from_pretrained(self.model_path)

    def generate_prompt(self, image_path: str, prompt: str = DEFAULT_PROMPT) -> dict[str, Any]:
        self._load()
        prompt = prompt + LINDON_BADGE_RULE
        messages = [{"role": "user", "content": [
            {"type": "image", "image": str(Path(image_path).resolve()), "max_pixels": 1024 * 28 * 28},
            {"type": "text", "text": prompt},
        ]}]
        inputs = output = None
        try:
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            ).to(self.model.device)
            with self.torch.inference_mode():
                output = self.model.generate(**inputs, max_new_tokens=420, do_sample=False)
            text = self.processor.decode(
                output[0][inputs.input_ids.shape[-1]:], skip_special_tokens=True
            ).strip()
            text = re.sub(r"^```(?:text)?\s*|\s*```$", "", text, flags=re.I).strip()
            if len(text.split()) < 80:
                raise RuntimeError(f"Local model returned an incomplete prompt ({len(text.split())} words)")
            return {"success": True, "response_text": text, "provider": "qwen3-vl-8b-local"}
        except Exception as exc:
            return {"success": False, "error": f"{type(exc).__name__}: {exc}", "retryable": True}
        finally:
            inputs = output = None
            gc.collect()
            self.torch.cuda.empty_cache()

    def close(self) -> None:
        try:
            if self.model is not None:
                self.model.to("cpu")
        except Exception:
            pass
        self.model = self.processor = None
        gc.collect()
        if self.torch is not None and self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()
            try:
                self.torch.cuda.ipc_collect()
            except Exception:
                pass
