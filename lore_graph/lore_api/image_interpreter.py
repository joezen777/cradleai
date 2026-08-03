from __future__ import annotations

import base64
import gc
import hashlib
import io
import json
import os
import re
import sysconfig
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
        # Recent Torch builds may JIT a tiny Triton driver extension. Minimal
        # runtime images often omit Python.h; use the stable eager kernels in
        # that environment instead of failing during the first vision call.
        include_dir = Path(sysconfig.get_paths().get("include", ""))
        if not (include_dir / "Python.h").is_file():
            os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")
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

    def inspect(self, value: str, reference_description: str | None = None) -> dict:
        """Return immutable, lore-neutral facts that downstream stages must preserve."""
        image, digest = self._image(value)
        cache_key = {"image": digest, "reference": reference_description or ""}
        cached = self.cache.get("frame_visual_inventory", cache_key, version=5)
        if cached is not None:
            return dict(cached)
        with self.lock:
            cached = self.cache.get("frame_visual_inventory", cache_key, version=5)
            if cached is not None:
                return dict(cached)
            self._load()
            instruction = f"""
Inspect only what is physically visible in this storyboard frame. Do not infer
people, places, objects, colors, or actions from lore. Return one JSON object
with these keys: composition, visible_human_count, visible_figures,
visible_objects, visible_background, setting_visible, style_and_lighting,
uncertainties, camera_and_framing, subject_positions, posture_gaze_and_action,
visible_appearance, support_and_contact, background_geometry, source_medium.
Arrays must contain precise concrete observations. Record horizontal/vertical
orientation, shot size and camera angle; every subject's screen position; exact
posture, head direction, eye direction, expression and action; visible skin
tone, face, hair and clothing; what each object touches or rests upon; and the
background's spatial geometry. Never identify a person or setting from lore.
The optional REFERENCE DESCRIPTION was produced by a larger local vision model.
Use it to recover detail, but keep only claims compatible with the image.
REFERENCE DESCRIPTION:
{reference_description or "None supplied"}
Count only visible human or humanoid bodies. A close-up prop with no body has a
count of zero. JSON only.
""".strip()
            messages = [{"role":"user","content":[{"type":"image"},{"type":"text","text":instruction}]}]
            rendered = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.processor(text=[rendered], images=[image], return_tensors="pt").to(self.model.device)
            with self.torch.inference_mode():
                output = self.model.generate(**inputs, max_new_tokens=520, do_sample=False)
            raw = self.processor.batch_decode(
                output[:, inputs.input_ids.shape[1]:], skip_special_tokens=True
            )[0].strip()
            match = re.search(r"\{.*\}", raw, flags=re.S)
            if not match:
                raise RuntimeError("Vision model did not return a visual-inventory JSON object")
            data = json.loads(match.group(0))
            defaults = {
                "composition": "", "visible_human_count": 0, "visible_figures": [],
                "visible_objects": [], "visible_background": [], "setting_visible": False,
                "style_and_lighting": "", "uncertainties": [],
                "camera_and_framing": "", "subject_positions": [],
                "posture_gaze_and_action": [], "visible_appearance": [],
                "support_and_contact": [], "background_geometry": [],
                "source_medium": "",
            }
            inventory = {key: data.get(key, default) for key, default in defaults.items()}
            inventory["visible_human_count"] = max(0, int(inventory["visible_human_count"]))
            for key in (
                "visible_figures", "visible_objects", "visible_background",
                "uncertainties", "subject_positions", "posture_gaze_and_action",
                "visible_appearance", "support_and_contact", "background_geometry",
            ):
                value = inventory[key]
                if value is None:
                    inventory[key] = []
                elif not isinstance(value, list):
                    inventory[key] = [str(value)]
                else:
                    inventory[key] = [
                        item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
                        for item in value
                    ]
            for key in (
                "composition", "style_and_lighting", "camera_and_framing",
                "source_medium",
            ):
                if not isinstance(inventory[key], str):
                    inventory[key] = json.dumps(inventory[key], ensure_ascii=False)
            if inventory["visible_human_count"] == 0:
                inventory["visible_figures"] = []
            self.cache.put("frame_visual_inventory", cache_key, inventory, version=5)
            del inputs, output
            gc.collect(); self.torch.cuda.empty_cache()
            return inventory

    def close(self) -> None:
        with self.lock:
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
