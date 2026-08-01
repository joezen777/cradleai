#!/usr/bin/env python3
"""Interactive CUDA chatbot for Qwen2.5-VL with relative media references."""

from __future__ import annotations

import argparse
import gc
import os
import shlex
import sys
from pathlib import Path
from typing import Any

# Avoid optional Triton JIT compilation that requires system Python headers.
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")

IMAGE_EXTENSIONS = {
    ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp",
}
VIDEO_EXTENSIONS = {
    ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chat with local Qwen2.5-VL on CUDA and attach relative media paths."
    )
    parser.add_argument("--model", default="Qwen/Qwen2.5-VL-3B-Instruct")
    parser.add_argument(
        "--media-root",
        type=Path,
        default=Path.cwd(),
        help="Directory against which relative media paths are resolved (default: cwd)",
    )
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument(
        "--max-history-turns",
        type=int,
        default=8,
        help="Maximum user/assistant pairs retained in context",
    )
    parser.add_argument(
        "--no-4bit",
        action="store_true",
        help="Load BF16 instead of 4-bit; normally unsuitable for a 12 GB GPU",
    )
    parser.add_argument(
        "--system-prompt",
        default=(
            "You are a candid, careful multimodal assistant. Analyze attached images and "
            "videos directly. If evidence is missing or uncertain, say so rather than "
            "inventing details."
        ),
    )
    return parser.parse_args()


def resolve_media(token: str, root: Path) -> tuple[str, Path] | None:
    """Resolve an @path or an existing bare media path beneath media-root."""
    explicit = token.startswith("@")
    raw_path = token[1:] if explicit else token
    suffix = Path(raw_path).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        if explicit:
            raise ValueError(f"Unsupported media extension: {raw_path}")
        return None
    candidate = Path(raw_path)
    if candidate.is_absolute():
        if explicit:
            raise ValueError("Media references must be relative paths")
        return None
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Media path leaves --media-root: {raw_path}")
    if not resolved.is_file():
        if explicit:
            raise FileNotFoundError(f"Media file not found: {raw_path}")
        return None
    media_type = "image" if suffix in IMAGE_EXTENSIONS else "video"
    return media_type, resolved


def parse_user_input(line: str, root: Path) -> tuple[str, list[tuple[str, Path]]]:
    """Extract relative media references while retaining ordinary prompt text."""
    try:
        tokens = shlex.split(line)
    except ValueError as exc:
        raise ValueError(f"Could not parse input: {exc}") from exc

    text_tokens: list[str] = []
    media: list[tuple[str, Path]] = []
    for token in tokens:
        resolved = resolve_media(token, root)
        if resolved is None:
            text_tokens.append(token)
        else:
            media.append(resolved)
    text = " ".join(text_tokens).strip()
    if not text and media:
        text = "Describe and analyze the attached media."
    return text, media


def trim_history(messages: list[dict[str, Any]], max_turns: int) -> list[dict[str, Any]]:
    """Retain the system message and the most recent complete conversation turns."""
    if max_turns < 1:
        return messages[:1]
    limit = 1 + max_turns * 2
    return messages if len(messages) <= limit else [messages[0], *messages[-max_turns * 2 :]]


def release_turn_memory(torch_module: Any, *objects: Any) -> None:
    """Drop turn-local tensors while keeping the chat model loaded."""
    del objects
    gc.collect()
    if torch_module.cuda.is_available():
        torch_module.cuda.empty_cache()


def release_all_memory(torch_module: Any, model: Any, processor: Any) -> None:
    """Best-effort model teardown used by every exit path."""
    print("\nReleasing Qwen and CUDA memory...", flush=True)
    try:
        if model is not None:
            model.to("cpu")
    except Exception:
        pass
    del model
    del processor
    gc.collect()
    if torch_module is not None and torch_module.cuda.is_available():
        torch_module.cuda.empty_cache()
        try:
            torch_module.cuda.ipc_collect()
        except Exception:
            pass
    print("Shutdown complete.", flush=True)


def main() -> int:
    args = parse_args()
    root = args.media_root.resolve()
    if not root.is_dir():
        print(f"Media root is not a directory: {root}", file=sys.stderr)
        return 2

    import torch
    from qwen_vl_utils import process_vision_info
    from transformers import (
        AutoProcessor,
        BitsAndBytesConfig,
        Qwen2_5_VLForConditionalGeneration,
    )

    if not torch.cuda.is_available():
        print("CUDA is required, but torch.cuda.is_available() is false.", file=sys.stderr)
        return 2

    model = None
    processor = None
    try:
        print(f"Loading {args.model} on {torch.cuda.get_device_name(0)}...", flush=True)
        load_options: dict[str, Any] = {
            "device_map": "auto",
            "dtype": torch.bfloat16,
        }
        if not args.no_4bit:
            load_options["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            args.model, **load_options
        )
        processor = AutoProcessor.from_pretrained(args.model)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": args.system_prompt}
        ]

        print(f"Media root: {root}")
        print("Attach media with @relative/path.png or @'path with spaces/video.mp4'.")
        print("Commands: /clear, /help, /quit (Ctrl-C and Ctrl-D also exit).")

        while True:
            try:
                line = input("\nyou> ").strip()
            except EOFError:
                print("\nEnd of input received.")
                break
            except KeyboardInterrupt:
                print("\nInterrupt received.")
                break

            if not line:
                continue
            command = line.lower()
            if command in {"/quit", "/exit", "/q"}:
                break
            if command == "/clear":
                messages = messages[:1]
                release_turn_memory(torch)
                print("Conversation history cleared.")
                continue
            if command == "/help":
                print("Use: What is shown here? @output/frames/scene_514_first_frame.png")
                print("Paths containing spaces: @'media/my clip.mp4'")
                print("Commands: /clear, /help, /quit")
                continue

            try:
                prompt, media = parse_user_input(line, root)
            except (ValueError, FileNotFoundError) as exc:
                print(f"Input error: {exc}")
                continue
            if not prompt:
                print("Enter a question, optionally with one or more media references.")
                continue

            content: list[dict[str, Any]] = []
            for media_type, path in media:
                item: dict[str, Any] = {"type": media_type, media_type: str(path)}
                if media_type == "image":
                    item.update({"min_pixels": 256 * 28 * 28, "max_pixels": 1024 * 28 * 28})
                else:
                    item.update({"max_pixels": 512 * 28 * 28, "fps": 1.0})
                content.append(item)
                print(f"Attached {media_type}: {path.relative_to(root)}")
            content.append({"type": "text", "text": prompt})
            messages.append({"role": "user", "content": content})
            messages = trim_history(messages, args.max_history_turns)

            inputs = None
            generated = None
            continuation = None
            try:
                rendered = processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                image_inputs, video_inputs = process_vision_info(messages)
                inputs = processor(
                    text=[rendered],
                    images=image_inputs,
                    videos=video_inputs,
                    padding=True,
                    return_tensors="pt",
                ).to(model.device)
                with torch.inference_mode():
                    generated = model.generate(
                        **inputs,
                        max_new_tokens=args.max_new_tokens,
                        do_sample=False,
                    )
                continuation = generated[:, inputs.input_ids.shape[1] :]
                answer = processor.batch_decode(
                    continuation, skip_special_tokens=True
                )[0].strip()
                print(f"\nqwen> {answer}")
                messages.append({"role": "assistant", "content": answer})
                messages = trim_history(messages, args.max_history_turns)
            except KeyboardInterrupt:
                print("\nGeneration interrupted; returning to the prompt.")
                messages.pop()
            except Exception as exc:
                print(f"Generation error: {type(exc).__name__}: {exc}")
                messages.pop()
            finally:
                inputs = None
                generated = None
                continuation = None
                release_turn_memory(torch)
        return 0
    finally:
        release_all_memory(torch, model, processor)


if __name__ == "__main__":
    raise SystemExit(main())
