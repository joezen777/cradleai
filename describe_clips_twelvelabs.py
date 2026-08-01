#!/usr/bin/env python3
"""Describe short video clips with TwelveLabs Pegasus 1.5.

The output is JSON Lines: one object per successfully analyzed clip. Credentials
are read locally and are never printed or included in output records.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parent
DEFAULT_CREDENTIALS = ROOT / ".credentials"
DEFAULT_CLIPS_DIR = ROOT / "output" / "clips"
DEFAULT_OUTPUT = ROOT / "output" / "twelvelabs_clip_descriptions.jsonl"
API_URL = "https://api.twelvelabs.io/v1.3/analyze"
MODEL = "pegasus1.5"
PROMPT = """Describe only what is visibly happening in this video clip. Write one
continuous paragraph of 200 to 500 words with no heading, bullets, JSON, or
other formatting. Give a clear chronological account of the visible characters
or people, their appearance and general screen position, their actions and
interactions, objects or props they use, and the general scenery, setting,
lighting, and important visual effects. Mention camera framing or movement only
when it helps explain what is shown. Do not identify characters by name, infer
story lore, transcribe dialogue, speculate about motives, or claim details that
are not visually supported. If an element is unclear, describe it cautiously in
ordinary visual terms. This description will become context for another model
that sees this clip and the clips immediately before and after it."""


class ClipDescriptionError(RuntimeError):
    """A safe-to-display error that never contains credentials."""


def load_credential(path: Path, name: str) -> str:
    """Load a key=value credential without logging its value."""
    if not path.is_file():
        raise ClipDescriptionError(f"Credentials file not found: {path}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            secret = value.strip().strip("\"'")
            if not secret:
                break
            return secret
    raise ClipDescriptionError(f"{name} is missing or empty in {path}")


def normalize_paragraph(text: str) -> str:
    """Collapse model output into unstructured, single-paragraph prose."""
    text = text.strip()
    text = re.sub(r"^```(?:text)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def video_duration(clip: Path) -> float:
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(clip),
    ]
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ClipDescriptionError(f"Could not read duration of {clip.name}") from exc


def ensure_decodable_video(clip: Path) -> None:
    command = [
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames",
        "-of", "default=noprint_wrappers=1:nokey=1", str(clip),
    ]
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=60
        )
        frame_count = int(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ClipDescriptionError(
            f"{clip.name} has no readable video frame count"
        ) from exc
    if frame_count < 1:
        raise ClipDescriptionError(
            f"{clip.name} contains no decodable video frames"
        )


def api_video_bytes(clip: Path) -> tuple[bytes, float, bool]:
    """Return API-ready bytes, padding clips below Pegasus's four-second floor."""
    ensure_decodable_video(clip)
    duration = video_duration(clip)
    if duration >= 4.0:
        return clip.read_bytes(), duration, False

    # Keep the original untouched. Repeating its final frame only satisfies the
    # service's minimum duration and introduces no new visible event.
    with tempfile.TemporaryDirectory(prefix="twelvelabs_clip_") as directory:
        padded = Path(directory) / "padded.mp4"
        command = [
            "ffmpeg", "-v", "error", "-y", "-i", str(clip),
            "-vf", f"tpad=stop_mode=clone:stop_duration={4.1 - duration:.3f}",
            "-an", "-t", "4.1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(padded),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ClipDescriptionError(
                f"Could not prepare short clip {clip.name} for analysis"
            ) from exc
        return padded.read_bytes(), duration, True


def describe_clip(clip: Path, api_key: str, timeout: float) -> tuple[str, dict[str, Any]]:
    video_bytes, duration, padded = api_video_bytes(clip)
    encoded = base64.b64encode(video_bytes).decode("ascii")
    payload = {
        "model_name": MODEL,
        "video": {"type": "base64_string", "base64_string": encoded},
        "prompt": PROMPT,
        "temperature": 0.1,
        "max_tokens": 900,
    }
    try:
        response = requests.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ClipDescriptionError(
            f"Request failed for {clip.name}: {type(exc).__name__}"
        ) from exc

    if not response.ok:
        # The response body can contain useful API diagnostics, but sanitize it
        # defensively before displaying it.
        detail = response.text[:1000].replace(api_key, "[REDACTED]")
        raise ClipDescriptionError(
            f"TwelveLabs returned HTTP {response.status_code} for "
            f"{clip.name}: {detail}"
        )

    body: dict[str, Any]
    fragments: list[str] = []
    stream_end: dict[str, Any] = {}
    try:
        body = response.json()
    except requests.JSONDecodeError:
        # The endpoint may return newline-delimited streaming events even for a
        # non-streaming HTTP request.
        body = {}
        try:
            for line in response.text.splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("event_type") == "text_generation":
                    fragments.append(str(event.get("text") or ""))
                elif event.get("event_type") == "stream_end":
                    stream_end = event
        except (json.JSONDecodeError, AttributeError) as exc:
            raise ClipDescriptionError(
                f"TwelveLabs returned an unreadable response for {clip.name}"
            ) from exc

    description = normalize_paragraph(
        str(body.get("data") or "") if body else "".join(fragments)
    )
    if not description:
        raise ClipDescriptionError(f"TwelveLabs returned no description for {clip.name}")
    stream_metadata = stream_end.get("metadata", {})
    usage_value = body.get("usage") if body else stream_metadata.get("usage")
    usage = usage_value if isinstance(usage_value, dict) else {}
    metadata = {
        "response_id": body.get("id") if body else stream_metadata.get("generation_id"),
        "finish_reason": (
            body.get("finish_reason") if body else stream_end.get("finish_reason")
        ),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "source_duration_seconds": duration,
        "minimum_duration_padding_applied": padded,
    }
    return description, metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenes",
        nargs="+",
        type=int,
        default=[200, 201, 202, 203],
        help="Scene numbers to analyze (default: 200 201 202 203)",
    )
    parser.add_argument("--clips-dir", type=Path, default=DEFAULT_CLIPS_DIR)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = load_credential(args.credentials, "TWELVELABS_API_KEY")
    records: list[dict[str, Any]] = []

    for scene in args.scenes:
        clip = args.clips_dir / f"scene_{scene}.webm"
        if not clip.is_file():
            raise ClipDescriptionError(f"Clip not found: {clip}")
        print(f"Analyzing scene {scene}: {clip.name}", flush=True)
        try:
            description, api_metadata = describe_clip(clip, api_key, args.timeout)
            records.append(
                {
                    "scene_id": scene,
                    "clip_filename": clip.name,
                    "status": "success",
                    "description": description,
                    "word_count": len(description.split()),
                    "model": MODEL,
                    **api_metadata,
                }
            )
        except ClipDescriptionError as exc:
            print(f"Scene {scene} failed: {exc}", file=sys.stderr, flush=True)
            records.append(
                {
                    "scene_id": scene,
                    "clip_filename": clip.name,
                    "status": "error",
                    "description": None,
                    "word_count": 0,
                    "model": MODEL,
                    "error": str(exc),
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temporary, args.output)
    print(f"Saved {len(records)} descriptions to {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ClipDescriptionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
