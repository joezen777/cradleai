from __future__ import annotations

import gc
import json
import os
import re
from pathlib import Path
from typing import Any

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def parse_json_object(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("response contains no complete JSON object")
    return json.loads(text[start:end + 1])


class LocalLoreModel:
    def __init__(self, model_path: Path):
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoProcessor,
            AutoTokenizer,
            BitsAndBytesConfig,
            Qwen2_5_VLForConditionalGeneration,
            Qwen3VLForConditionalGeneration,
        )

        self.torch = torch
        model_name = str(model_path)
        if "Qwen3-VL" in model_name or "qwen3_vl" in model_name:
            resolved = str(model_path.resolve()) if model_path.exists() else model_name
            self.model = Qwen3VLForConditionalGeneration.from_pretrained(
                resolved,
                device_map="auto",
                dtype=torch.bfloat16,
                quantization_config=BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.bfloat16,
                ),
            )
            self.tokenizer = AutoProcessor.from_pretrained(resolved)
        elif "Qwen2.5-VL" in model_name or model_name == "Qwen/Qwen2.5-VL-3B-Instruct":
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                model_name,
                local_files_only=True,
                device_map="auto",
                dtype=torch.bfloat16,
                quantization_config=BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.bfloat16,
                ),
            )
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_name, local_files_only=True, fix_mistral_regex=False
            )
        else:
            resolved = str(model_path.resolve())
            self.model = AutoModelForCausalLM.from_pretrained(
                resolved, device_map="auto", dtype=torch.bfloat16
            )
            self.tokenizer = AutoTokenizer.from_pretrained(
                resolved, fix_mistral_regex=True
            )
        if hasattr(self.tokenizer, "padding_side"):
            self.tokenizer.padding_side = "left"
            if getattr(self.tokenizer, "pad_token_id", None) is None and hasattr(self.tokenizer, "eos_token"):
                self.tokenizer.pad_token = self.tokenizer.eos_token
        if hasattr(self.tokenizer, "tokenizer"):
            self.tokenizer.tokenizer.padding_side = "left"
            if getattr(self.tokenizer.tokenizer, "pad_token_id", None) is None:
                self.tokenizer.tokenizer.pad_token = self.tokenizer.tokenizer.eos_token

    def generate_json_batch(
        self, instructions: list[str], max_new_tokens: int = 1600
    ) -> list[dict | Exception]:
        """Generate several independent JSON responses in one CUDA batch."""
        rendered = [
            self.tokenizer.apply_chat_template(
                [{"role": "user", "content": instruction}],
                tokenize=False,
                add_generation_prompt=True,
            )
            for instruction in instructions
        ]
        inputs = self.tokenizer(
            rendered, padding=True, return_tensors="pt"
        ).to(self.model.device)
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False
            )
        continuation = output[:, inputs.input_ids.shape[1]:]
        raw_results = self.tokenizer.batch_decode(
            continuation, skip_special_tokens=True
        )
        results: list[dict | Exception] = []
        for instruction, raw in zip(instructions, raw_results):
            try:
                results.append(parse_json_object(raw))
            except Exception as exc:
                # Preserve valid batch members immediately. Failed/truncated
                # members remain resumable and are retried later in batch 1.
                results.append(exc)
        del inputs, output, continuation
        gc.collect(); self.torch.cuda.empty_cache()
        return results

    def _format_messages(self, text: str) -> list[dict]:
        if "Processor" in type(self.tokenizer).__name__ or hasattr(self.tokenizer, "image_processor"):
            return [{"role": "user", "content": [{"type": "text", "text": text}]}]
        return [{"role": "user", "content": text}]

    def generate_json(self, instruction: str, max_new_tokens: int = 1800) -> dict:
        repair = ""
        for attempt in range(3):
            messages = self._format_messages(instruction + repair)
            inputs = output = None
            try:
                inputs = self.tokenizer.apply_chat_template(
                    messages, tokenize=True, add_generation_prompt=True,
                    return_dict=True, return_tensors="pt"
                ).to(self.model.device)
                with self.torch.inference_mode():
                    output = self.model.generate(
                        **inputs, max_new_tokens=max_new_tokens, do_sample=False
                    )
                input_ids = inputs["input_ids"] if isinstance(inputs, dict) or "input_ids" in inputs else inputs.input_ids
                raw = self.tokenizer.decode(
                    output[0][input_ids.shape[-1]:], skip_special_tokens=True
                )
                return parse_json_object(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                if attempt == 2:
                    raise
                repair = (
                    "\nYour previous response was invalid JSON. Return a shorter, complete "
                    "JSON object with double-quoted keys/strings, no trailing commas, and no "
                    "Markdown or commentary."
                )
            finally:
                inputs = output = None
                gc.collect()
                self.torch.cuda.empty_cache()
        raise RuntimeError("unreachable")

    def generate_text(self, instruction: str, max_new_tokens: int = 1800) -> str:
        messages = self._format_messages(instruction)
        inputs = self.tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors="pt"
        ).to(self.model.device)
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False
            )
        input_ids = inputs["input_ids"] if isinstance(inputs, dict) or "input_ids" in inputs else inputs.input_ids
        text = self.tokenizer.decode(
            output[0][input_ids.shape[-1]:], skip_special_tokens=True
        ).strip()
        del inputs, output
        gc.collect(); self.torch.cuda.empty_cache()
        return text

    def generate_text_batch(
        self, instructions: list[str], max_new_tokens: int = 500
    ) -> list[str]:
        rendered = [
            self.tokenizer.apply_chat_template(
                self._format_messages(inst),
                tokenize=False,
                add_generation_prompt=True,
            )
            for inst in instructions
        ]
        inputs = self.tokenizer(
            text=rendered, padding=True, return_tensors="pt"
        ).to(self.model.device)
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False
            )
        input_ids = inputs["input_ids"] if isinstance(inputs, dict) or "input_ids" in inputs else inputs.input_ids
        continuation = output[:, input_ids.shape[1]:]
        raw_results = self.tokenizer.batch_decode(
            continuation, skip_special_tokens=True
        )
        results = [raw.strip() for raw in raw_results]
        del inputs, output, continuation
        gc.collect(); self.torch.cuda.empty_cache()
        return results

    def close(self) -> None:
        try:
            self.model.to("cpu")
        except Exception:
            pass
        self.model = self.tokenizer = None
        gc.collect()
        if self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()
            try:
                self.torch.cuda.ipc_collect()
            except Exception:
                pass
