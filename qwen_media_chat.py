#!/usr/bin/env python3
"""Interactive multi-model CUDA chatbot with relative media references."""

from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import os
import re
import sys
import threading
import time
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

MODEL_SPECS = {
    "qwen2.5-vl-3b": {
        "path": "Qwen/Qwen2.5-VL-3B-Instruct",
        "family": "qwen2_5_vl",
        "media": {"image", "video"},
        "description": "Qwen2.5-VL 3B (original visual model)",
    },
    "qwen3-vl-8b": {
        "path": "models/Qwen3-VL-8B-Instruct",
        "family": "qwen3_vl",
        "media": {"image", "video"},
        "description": "Qwen3-VL 8B (visual, loaded in 4-bit)",
    },
    "gemma3-12b": {
        "path": "models/gemma-3-12b-it-bnb-4bit",
        "family": "gemma3",
        "media": {"image"},
        "description": "Gemma 3 12B (visual, pre-quantized 4-bit)",
    },
    "qwen3-14b": {
        "path": "models/Qwen3-14B-bnb-4bit",
        "family": "text",
        "media": set(),
        "description": "Qwen3 14B (text-only, pre-quantized 4-bit)",
    },
    "mistral-nemo-12b": {
        "path": "models/Mistral-Nemo-Instruct-2407-bnb-4bit",
        "family": "text",
        "media": set(),
        "description": "Mistral NeMo 12B (text-only, pre-quantized 4-bit)",
    },
}

MEDIA_REFERENCE = re.compile(
    r"(?<!\S)@(?:\"(?:[^\"\\]|\\.)*\"?|"
    r"'(?:[^'\\]|\\.)*'?|(?:\\.|[^\s])+)",
)

DEFAULT_LORE_MCP_URL = "http://127.0.0.1:8765/mcp/"
DEFAULT_LORE_CONTEXT_CHARS = 24_000

CLIP_LORE_RESPONSE_PROMPT = """
Return one valid JSON object with exactly these five keys:
{
  "video_description": "visible evidence only",
  "dialog": [{"speaker": "name or visual label", "transcript": "audible words", "screen_position": "position"}],
  "characters_lore": [{"name": "name or visual label", "screen_position": "position", "visible_description": "visible facts", "lore_guidance": "source-grounded production guidance", "confidence": "high|medium|low"}],
  "scenery_lore": "visible setting followed by source-grounded guidance",
  "magic_lore": "visible or strongly supported fantastical elements, otherwise empty"
}
Do not add Markdown fences or commentary outside the JSON object. The attached
media is primary evidence and MCP passages are secondary lore guidance. Never
replace visible evidence with lore. For a still image, return an empty dialog
list because no speech is audible. Do not call an object a pumpkin when the MCP
identifies it as an orus fruit; describe visible shape separately from its
source-grounded identity. Do not invent colors, materials, lenses, lighting,
characters, actions, or locations that are not visible or cited.
""".strip()


def call_lore_mcp(url: str, description: str, max_locations: int = 3) -> dict[str, Any]:
    """Call the lore server through its Streamable HTTP MCP transport."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def call() -> dict[str, Any]:
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "locate_lore_context",
                    {"description": description, "max_locations": max_locations},
                )
                if result.isError:
                    detail = "\n".join(
                        getattr(item, "text", str(item)) for item in result.content
                    )
                    raise RuntimeError(detail or "locate_lore_context failed")
                if result.structuredContent is not None:
                    structured = result.structuredContent
                    if set(structured) == {"result"} and isinstance(structured["result"], dict):
                        return structured["result"]
                    return structured
                for item in result.content:
                    item_text = getattr(item, "text", None)
                    if item_text:
                        return json.loads(item_text)
                raise RuntimeError("Lore MCP returned no structured or textual result")

    return asyncio.run(call())


def _trim_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def compact_lore_context(
    result: dict[str, Any], max_chars: int = DEFAULT_LORE_CONTEXT_CHARS
) -> dict[str, Any]:
    """Keep cited scene evidence while dropping recursive dossier expansion.

    A full lore result can contain aggregate character histories and repeated
    first-mention passages hundreds of thousands of characters long. Those are
    useful in the API but counterproductive in a model prompt.
    """
    compact: dict[str, Any] = {
        "query_interpretation": _trim_text(result.get("query_interpretation"), 1000),
        "matches": [],
    }
    for match in result.get("matches", []):
        location = match.get("location_in_book") or {}
        row: dict[str, Any] = {
            "citation": {
                key: location.get(key)
                for key in (
                    "book_title", "chapter_label", "page_start", "page_end",
                    "passage_id", "confidence_rating",
                )
                if location.get(key) is not None
            },
            "source_passage": _trim_text(location.get("surrounding_paragraph"), 7000),
            "characters": [],
            "scenery": [],
            "props": [],
        }
        for character in (match.get("characters") or {}).values():
            quotes = [
                _trim_text(value, 700)
                for value in character.get("visual_description_source", [])[:6]
                if value
            ]
            interactions = [
                _trim_text(value, 500)
                for value in character.get("character_interactions", [])[:4]
                if value
            ]
            if quotes or interactions:
                row["characters"].append({
                    "name": character.get("character_name"),
                    "normalized_name": character.get("character_name_normalized"),
                    "source_descriptions": quotes,
                    "scene_interactions": interactions,
                })
        for scenery in (match.get("scenery_source") or {}).values():
            quotes = [
                _trim_text(value, 700)
                for value in scenery.get("visual_description_source", [])[:6]
                if value
            ]
            row["scenery"].append({
                "normalized_name": scenery.get("location_name_normalized"),
                "source_descriptions": quotes,
            })
        for prop in (match.get("props") or [])[:12]:
            row["props"].append({
                "name": prop.get("prop_name"),
                "placement": prop.get("placement"),
                "source_descriptions": [
                    _trim_text(value, 700)
                    for value in prop.get("source_description", [])[:6]
                    if value
                ],
            })
        compact["matches"].append(row)

    encoded = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > max_chars:
        # Source passages carry the citation-level evidence. Trim them evenly
        # before sacrificing entity names and exact visual-description quotes.
        matches = compact["matches"]
        allowance = max(1000, max_chars // max(1, len(matches)) // 2)
        for row in matches:
            row["source_passage"] = _trim_text(row.get("source_passage"), allowance)
    return compact


def format_lore_context(
    result: dict[str, Any], max_chars: int = DEFAULT_LORE_CONTEXT_CHARS
) -> str:
    """Label compact MCP evidence before supplying it to the local model."""
    compact = compact_lore_context(result, max_chars=max_chars)
    encoded = json.dumps(compact, ensure_ascii=False, indent=2)
    return (
        "SOURCE-GROUNDED CRADLE LORE CONTEXT FROM THE LOCAL MCP SERVER:\n"
        f"{encoded}\n\n"
        "Use this context as authoritative for Unsouled and Soulsmith. Cite its book, "
        "chapter, page, or passage identifiers when useful. Distinguish exact source "
        "descriptions from macro scenery and from your own inference."
    )


class ProgressSpinner:
    """Display a small animated status until generation finishes."""

    def __init__(self, label: str = "Thinking") -> None:
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _animate(self) -> None:
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        index = 0
        while not self._stop.wait(0.1):
            print(f"\r{self.label} {frames[index % len(frames)]}", end="", flush=True)
            index += 1

    def start(self) -> None:
        print(f"\r{self.label} …", end="", flush=True)
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        print("\r" + " " * (len(self.label) + 4) + "\r", end="", flush=True)


def _unescape_reference(value: str) -> str:
    """Remove optional reference quotes and simple backslash escaping."""
    if value and value[0] in {'"', "'"}:
        quote = value[0]
        value = value[1:]
        if value.endswith(quote):
            value = value[:-1]
    return re.sub(r"\\(.)", r"\1", value)


def history_path_for(cwd: Path) -> Path:
    """Return a stable history file dedicated to the launch directory."""
    state_root = Path(
        os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
    ) / "cradleai" / "qwen_media_chat"
    folder_id = hashlib.sha256(str(cwd.resolve()).encode("utf-8")).hexdigest()[:16]
    return state_root / f"{folder_id}.history"


def configure_readline(root: Path, launch_cwd: Path):
    """Enable persistent Up-arrow history and Bash-like @path completion."""
    try:
        import readline
    except ImportError:
        return None, None

    history_path = history_path_for(launch_cwd)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        readline.read_history_file(history_path)
    except FileNotFoundError:
        pass
    readline.set_history_length(2000)
    readline.set_completer_delims(" \t\n")

    matches: list[str] = []

    def completer(text: str, state: int) -> str | None:
        nonlocal matches
        if state == 0:
            matches = []
            if not text.startswith("@"):
                return None
            typed = _unescape_reference(text[1:])
            candidate = Path(typed)
            parent_text = str(candidate.parent)
            parent = root if parent_text == "." else (root / candidate.parent).resolve()
            if not parent.is_relative_to(root) or not parent.is_dir():
                return None
            prefix = candidate.name
            for child in sorted(parent.iterdir(), key=lambda item: item.name.casefold()):
                if child.name.startswith(prefix):
                    relative = child.relative_to(root).as_posix()
                    escaped = relative.replace(" ", "\\ ")
                    matches.append("@" + escaped + ("/" if child.is_dir() else ""))
        return matches[state] if state < len(matches) else None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    return readline, history_path


def save_readline_history(readline_module: Any, history_path: Path | None) -> None:
    if readline_module is None or history_path is None:
        return
    readline_module.write_history_file(history_path)
    try:
        history_path.chmod(0o600)
    except OSError:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chat with five local CUDA models and attach relative media paths."
    )
    parser.add_argument(
        "--model",
        choices=tuple(MODEL_SPECS),
        default="qwen2.5-vl-3b",
        help="Model alias to load initially",
    )
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
        "--lore-mcp-url",
        default=DEFAULT_LORE_MCP_URL,
        help=f"Streamable HTTP Cradle lore MCP endpoint (default: {DEFAULT_LORE_MCP_URL})",
    )
    parser.add_argument(
        "--no-lore",
        action="store_true",
        help="Start without automatically grounding questions through the lore MCP server",
    )
    parser.add_argument(
        "--lore-max-locations",
        type=int,
        choices=range(1, 11),
        default=3,
        metavar="1-10",
        help="Maximum cited book locations retrieved for each question",
    )
    parser.add_argument(
        "--lore-context-chars",
        type=int,
        default=DEFAULT_LORE_CONTEXT_CHARS,
        help="Maximum approximate characters of compact MCP evidence sent to the model",
    )
    parser.add_argument(
        "--response-mode",
        choices=("chat", "clip-lore"),
        default="chat",
        help="Use clip-lore for Gemini-compatible five-field production JSON",
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
    """Extract @media without parsing ordinary prose as shell syntax.

    Quotes and apostrophes in the question are therefore always accepted,
    including unmatched ones. Only text immediately following an ``@`` is
    interpreted as a path reference.
    """
    media: list[tuple[str, Path]] = []
    spans: list[tuple[int, int]] = []
    for match in MEDIA_REFERENCE.finditer(line):
        token = "@" + _unescape_reference(match.group(0)[1:])
        resolved = resolve_media(token, root)
        if resolved is not None:
            media.append(resolved)
            spans.append(match.span())
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(line[cursor:start])
        pieces.append(" ")
        cursor = end
    pieces.append(line[cursor:])
    text = re.sub(r"\s+", " ", "".join(pieces)).strip()
    if not text and media:
        text = "Describe and analyze the attached media."
    return text, media


def trim_history(messages: list[dict[str, Any]], max_turns: int) -> list[dict[str, Any]]:
    """Retain the system message and the most recent complete conversation turns."""
    system_count = int(bool(messages) and messages[0].get("role") == "system")
    if max_turns < 1:
        return messages[:system_count]
    limit = system_count + max_turns * 2
    if len(messages) <= limit:
        return messages
    prefix = messages[:system_count]
    return [*prefix, *messages[-max_turns * 2 :]]


def release_turn_memory(torch_module: Any, *objects: Any) -> None:
    """Drop turn-local tensors while keeping the chat model loaded."""
    del objects
    gc.collect()
    if torch_module.cuda.is_available():
        torch_module.cuda.empty_cache()


def unload_model(torch_module: Any, model: Any, processor: Any) -> tuple[None, None]:
    """Fully release one model before loading another or exiting."""
    print("Releasing model and CUDA memory...", flush=True)
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
    return None, None


def load_model(
    alias: str, torch_module: Any, no_4bit: bool
) -> tuple[Any, Any, dict[str, Any]]:
    """Load one configured model and its matching processor/tokenizer."""
    from transformers import (
        AutoModelForCausalLM,
        AutoProcessor,
        AutoTokenizer,
        BitsAndBytesConfig,
        Gemma3ForConditionalGeneration,
        Qwen2_5_VLForConditionalGeneration,
        Qwen3VLForConditionalGeneration,
    )

    spec = MODEL_SPECS[alias]
    model_path = str((Path(__file__).resolve().parent / spec["path"]).resolve()) \
        if spec["path"].startswith("models/") else spec["path"]
    print(f"Loading {alias}: {spec['description']}", flush=True)
    options: dict[str, Any] = {"device_map": "auto", "dtype": torch_module.bfloat16}
    # The two Qwen VL repositories contain full weights. The other local
    # repositories already contain their own 4-bit quantization configuration.
    if spec["family"] in {"qwen2_5_vl", "qwen3_vl"} and not no_4bit:
        options["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch_module.bfloat16,
        )

    if spec["family"] == "qwen2_5_vl":
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(model_path, **options)
        processor = AutoProcessor.from_pretrained(model_path)
    elif spec["family"] == "qwen3_vl":
        model = Qwen3VLForConditionalGeneration.from_pretrained(model_path, **options)
        processor = AutoProcessor.from_pretrained(model_path)
    elif spec["family"] == "gemma3":
        model = Gemma3ForConditionalGeneration.from_pretrained(model_path, **options)
        processor = AutoProcessor.from_pretrained(model_path)
    else:
        model = AutoModelForCausalLM.from_pretrained(model_path, **options)
        tokenizer_options = {"fix_mistral_regex": True} if alias == "mistral-nemo-12b" else {}
        processor = AutoTokenizer.from_pretrained(model_path, **tokenizer_options)
    return model, processor, spec


def initial_history(system_prompt: str, family: str) -> list[dict[str, Any]]:
    """Create model-compatible history; Gemma does not accept a system role."""
    if family == "gemma3":
        return []
    return [{"role": "system", "content": system_prompt}]


def print_models(active: str) -> None:
    print("Available models:")
    for alias, spec in MODEL_SPECS.items():
        marker = "*" if alias == active else " "
        print(f" {marker} {alias:<18} {spec['description']}")


def main() -> int:
    launch_cwd = Path.cwd().resolve()
    args = parse_args()
    root = args.media_root.resolve()
    if not root.is_dir():
        print(f"Media root is not a directory: {root}", file=sys.stderr)
        return 2

    import torch
    from qwen_vl_utils import process_vision_info

    if not torch.cuda.is_available():
        print("CUDA is required, but torch.cuda.is_available() is false.", file=sys.stderr)
        return 2

    model = None
    processor = None
    active_alias = args.model
    active_spec = MODEL_SPECS[active_alias]
    lore_enabled = not args.no_lore
    readline_module, history_path = configure_readline(root, launch_cwd)
    try:
        print(f"CUDA device: {torch.cuda.get_device_name(0)}", flush=True)
        model, processor, active_spec = load_model(active_alias, torch, args.no_4bit)
        messages = initial_history(args.system_prompt, active_spec["family"])

        print(f"Media root: {root}")
        print("Attach media with @relative/path.png or @'path with spaces/video.mp4'.")
        if history_path is not None:
            print(f"Input history: {history_path} (Up arrow recalls earlier questions)")
        print("Type @ and part of a relative path, then press Tab to complete it.")
        print(f"Lore MCP: {'on' if lore_enabled else 'off'} ({args.lore_mcp_url})")
        print("Commands: /model, /model <name>, /lore, /lore on|off|<query>, /clear, /help, /quit")

        while True:
            try:
                line = input("\nyou> ").strip()
                save_readline_history(readline_module, history_path)
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
                messages = initial_history(args.system_prompt, active_spec["family"])
                release_turn_memory(torch)
                print("Conversation history cleared.")
                continue
            if command == "/model":
                print_models(active_alias)
                continue
            if command.startswith("/model "):
                requested = command.split(maxsplit=1)[1].strip()
                if requested not in MODEL_SPECS:
                    print(f"Unknown model: {requested}")
                    print_models(active_alias)
                    continue
                if requested == active_alias:
                    print(f"{requested} is already loaded.")
                    continue
                old_alias = active_alias
                model, processor = unload_model(torch, model, processor)
                try:
                    model, processor, active_spec = load_model(
                        requested, torch, args.no_4bit
                    )
                    active_alias = requested
                    messages = initial_history(args.system_prompt, active_spec["family"])
                    print(f"Switched from {old_alias} to {active_alias}; history cleared.")
                except Exception as exc:
                    print(f"Could not load {requested}: {type(exc).__name__}: {exc}")
                    print(f"Reloading {old_alias}...")
                    model, processor, active_spec = load_model(
                        old_alias, torch, args.no_4bit
                    )
                    active_alias = old_alias
                    messages = initial_history(args.system_prompt, active_spec["family"])
                continue
            if command == "/lore":
                print(
                    f"Lore MCP is {'on' if lore_enabled else 'off'}: "
                    f"{args.lore_mcp_url}"
                )
                print("Use /lore <question> for direct retrieval or /lore on|off.")
                continue
            if command in {"/lore on", "/lore off"}:
                lore_enabled = command.endswith("on")
                print(f"Automatic lore grounding {'enabled' if lore_enabled else 'disabled'}.")
                continue
            if command.startswith("/lore "):
                lore_query = line.split(maxsplit=1)[1].strip()
                spinner = ProgressSpinner("Querying lore MCP")
                try:
                    spinner.start()
                    lore_result = call_lore_mcp(
                        args.lore_mcp_url, lore_query, args.lore_max_locations
                    )
                    spinner.stop()
                    print(json.dumps(lore_result, ensure_ascii=False, indent=2))
                except Exception as exc:
                    spinner.stop()
                    print(f"Lore MCP error: {type(exc).__name__}: {exc}")
                continue
            if command == "/help":
                print("Use: What is shown here? @output/frames/scene_514_first_frame.png")
                print("Paths containing spaces: @'media/my clip.mp4'")
                print("Press Up/Down for persistent history; use Tab after @ to complete paths.")
                print("Switch models: /model or /model qwen3-vl-8b")
                print("Lore: /lore, /lore on, /lore off, or /lore <question>")
                print("Commands: /model, /lore, /clear, /help, /quit")
                continue

            try:
                prompt, media = parse_user_input(line, root)
            except (ValueError, FileNotFoundError) as exc:
                print(f"Input error: {exc}")
                continue
            if not prompt:
                print("Enter a question, optionally with one or more media references.")
                continue

            model_prompt = prompt
            if lore_enabled:
                spinner = ProgressSpinner("Querying lore MCP")
                try:
                    spinner.start()
                    lore_result = call_lore_mcp(
                        args.lore_mcp_url, prompt, args.lore_max_locations
                    )
                    spinner.stop()
                    model_prompt = (
                        f"{format_lore_context(lore_result, args.lore_context_chars)}"
                        f"\n\nUSER QUESTION:\n{prompt}"
                    )
                    print(
                        f"Lore context attached ({len(lore_result.get('matches', []))} "
                        "location matches)."
                    )
                except Exception as exc:
                    spinner.stop()
                    print(
                        f"Lore MCP unavailable ({type(exc).__name__}: {exc}); "
                        "continuing without lore context."
                    )

            if args.response_mode == "clip-lore":
                model_prompt = f"{model_prompt}\n\nRESPONSE CONTRACT:\n{CLIP_LORE_RESPONSE_PROMPT}"

            unsupported = {kind for kind, _ in media} - active_spec["media"]
            if unsupported:
                supported = ", ".join(sorted(active_spec["media"])) or "text only"
                print(
                    f"{active_alias} does not accept {', '.join(sorted(unsupported))}; "
                    f"supported input: {supported}."
                )
                continue

            if active_spec["family"] == "text":
                content: Any = model_prompt
            else:
                content = []
                for media_type, path in media:
                    item: dict[str, Any] = {"type": media_type, media_type: str(path)}
                    if media_type == "image":
                        item.update({"min_pixels": 256 * 28 * 28, "max_pixels": 1024 * 28 * 28})
                    else:
                        item.update({"max_pixels": 512 * 28 * 28, "fps": 1.0})
                    content.append(item)
                    print(f"Attached {media_type}: {path.relative_to(root)}")
                text = model_prompt
                if active_spec["family"] == "gemma3" and not messages:
                    text = f"{args.system_prompt}\n\n{text}"
                content.append({"type": "text", "text": text})
            messages.append({"role": "user", "content": content})
            messages = trim_history(messages, args.max_history_turns)

            inputs = None
            generated = None
            continuation = None
            spinner: ProgressSpinner | None = ProgressSpinner(f"{active_alias} thinking")
            try:
                spinner.start()
                if active_spec["family"] == "text":
                    inputs = processor.apply_chat_template(
                        messages,
                        tokenize=True,
                        add_generation_prompt=True,
                        return_dict=True,
                        return_tensors="pt",
                    ).to(model.device)
                else:
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
                spinner.stop()
                spinner = None
                continuation = generated[:, inputs.input_ids.shape[1] :]
                answer = processor.batch_decode(
                    continuation, skip_special_tokens=True
                )[0].strip()
                print(f"\n{active_alias}> {answer}")
                messages.append({"role": "assistant", "content": answer})
                messages = trim_history(messages, args.max_history_turns)
            except KeyboardInterrupt:
                if spinner is not None:
                    spinner.stop()
                    spinner = None
                print("\nGeneration interrupted; returning to the prompt.")
                messages.pop()
            except Exception as exc:
                if spinner is not None:
                    spinner.stop()
                    spinner = None
                print(f"Generation error: {type(exc).__name__}: {exc}")
                messages.pop()
            finally:
                if spinner is not None:
                    spinner.stop()
                inputs = None
                generated = None
                continuation = None
                release_turn_memory(torch)
        return 0
    finally:
        save_readline_history(readline_module, history_path)
        print()
        model, processor = unload_model(torch, model, processor)
        print("Shutdown complete.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
