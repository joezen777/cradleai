from __future__ import annotations

import base64
import gc
import hashlib
import io
import threading
from pathlib import Path

from PIL import Image

from .cache import PersistentCache


class ImageInterpreter:
    def __init__(self, project_root: Path, cache: PersistentCache):
        self.project_root = project_root.resolve(); self.cache = cache
        self.model = self.processor = self.torch = None
        self.lock = threading.RLock()

    def _image(self, value: str) -> tuple[Image.Image, str]:
        if value.startswith("data:"):
            encoded = value.split(",", 1)[1]; raw = base64.b64decode(encoded, validate=True)
        elif value.startswith("base64:"):
            raw = base64.b64decode(value.split(":", 1)[1], validate=True)
        else:
            candidate = Path(value)
            if not candidate.is_absolute(): candidate = self.project_root / candidate
            candidate = candidate.resolve()
            if not candidate.is_relative_to(self.project_root):
                raise ValueError("frame path must remain within the project directory")
            try:
                raw = candidate.read_bytes()
            except (FileNotFoundError, OSError):
                try:
                    raw = base64.b64decode(value, validate=True)
                except Exception as exc:
                    raise ValueError(
                        "frame_image must be an existing project-local path or valid base64 image"
                    ) from exc
        if len(raw) > 20 * 1024 * 1024: raise ValueError("frame image exceeds 20 MB")
        return Image.open(io.BytesIO(raw)).convert("RGB"), hashlib.sha256(raw).hexdigest()

    def _load(self):
        if self.model is not None: return
        import torch
        from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration
        self.torch = torch
        name = "Qwen/Qwen2.5-VL-3B-Instruct"
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            name, device_map="auto", dtype=torch.bfloat16, local_files_only=True,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            ),
        )
        self.processor = AutoProcessor.from_pretrained(name, local_files_only=True)

    def describe(self, value: str) -> str:
        image, digest = self._image(value)
        cached = self.cache.get("frame_description", digest, version=1)
        if cached is not None: return str(cached)
        with self.lock:
            cached = self.cache.get("frame_description", digest, version=1)
            if cached is not None: return str(cached)
            self._load()
            instruction = (
                "Describe this storyboard frame for matching it to a passage in a novel. "
                "Record character count, visible anatomy/clothes/items, arrangement, pose, "
                "gaze, expression, action, scenery, architecture, weather, lighting, and "
                "camera framing. Do not identify characters or invent lore. Return one dense paragraph."
            )
            messages = [{"role":"user","content":[{"type":"image"},{"type":"text","text":instruction}]}]
            rendered = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.processor(text=[rendered], images=[image], return_tensors="pt").to(self.model.device)
            with self.torch.inference_mode():
                output = self.model.generate(**inputs, max_new_tokens=420, do_sample=False)
            text = self.processor.batch_decode(output[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0].strip()
            self.cache.put("frame_description", digest, text, version=1)
            del inputs, output; gc.collect(); self.torch.cuda.empty_cache()
            return text
