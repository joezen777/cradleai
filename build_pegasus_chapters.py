#!/usr/bin/env python3
"""Create <=5-minute scene aggregates and resumable Pegasus chapter metadata."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from build_pegasus_metadata import (
    DEFAULT_METADATA,
    format_timecode,
    load_scenes,
)
from describe_clips_twelvelabs import (
    API_URL,
    ClipDescriptionError,
    DEFAULT_CREDENTIALS,
    MODEL,
    load_credential,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_CLIPS = ROOT / "output" / "clips"
DEFAULT_CHAPTERS = ROOT / "output" / "pegasus_chapters"
DEFAULT_TRANSCRIPT = ROOT / "output" / "audiotranscript.jsonl"
DEFAULT_OUTPUT = ROOT / "output" / "pegasus_chapter_metadata.jsonl"
DEFAULT_INDIVIDUAL_RESULTS = ROOT / "output" / "pegasus_metadata.jsonl"
API_KEY_NAME = "TWELVELABS_API_KEY"
PROMPT_VERSION = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def partition_scenes(
    scenes: list[dict[str, Any]],
    maximum_seconds: float,
) -> list[list[dict[str, Any]]]:
    chapters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_duration = 0.0
    for scene in scenes:
        duration = float(scene["duration"])
        if current and current_duration + duration > maximum_seconds:
            chapters.append(current)
            current = []
            current_duration = 0.0
        current.append(scene)
        current_duration += duration
    if current:
        chapters.append(current)
    return chapters


def run_checked(command: list[str], error_message: str) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or "")[-1000:]
        raise RuntimeError(f"{error_message}: {detail}") from exc


def create_chapter_video(
    chapter_path: Path,
    chapter_scenes: list[dict[str, Any]],
    clips_dir: Path,
) -> None:
    """Concatenate scene clips losslessly and replace the target atomically."""
    if chapter_path.is_file() and chapter_path.stat().st_size:
        return
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"{chapter_path.stem}_",
        dir=chapter_path.parent,
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        concat_file = temporary_root / "concat.txt"
        temporary_video = temporary_root / chapter_path.name
        lines = []
        for scene in chapter_scenes:
            clip = clips_dir / Path(
                scene["clip_file"].replace("\\", "/")
            ).name
            if not clip.is_file():
                raise FileNotFoundError(f"Missing source clip: {clip}")
            escaped = str(clip.resolve()).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        run_checked(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-map",
                "0:v?",
                "-map",
                "0:a?",
                "-c",
                "copy",
                str(temporary_video),
            ],
            f"Could not create {chapter_path.name}",
        )
        os.replace(temporary_video, chapter_path)


def load_transcript_items(transcript_path: Path) -> list[dict[str, Any]]:
    items = []
    with transcript_path.open("r", encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if record.get("record_type") == "timed_item":
                items.append(record)
    return items


def transcript_turns(
    items: list[dict[str, Any]],
    start_time: float,
    end_time: float,
) -> list[dict[str, Any]]:
    selected = [
        item
        for item in items
        if isinstance(item.get("start"), (int, float))
        and isinstance(item.get("end"), (int, float))
        and item["end"] >= start_time
        and item["start"] < end_time
    ]
    turns: list[dict[str, Any]] = []
    for item in selected:
        speaker = (
            "audio_event"
            if item.get("type") == "audio_event"
            else item.get("speaker_id") or "unknown"
        )
        if (
            not turns
            or turns[-1]["speaker_id"] != speaker
            or item["start"] - turns[-1]["end_time_seconds"] > 2.0
        ):
            turns.append(
                {
                    "speaker_id": speaker,
                    "start_time_seconds": item["start"],
                    "end_time_seconds": item["end"],
                    "text": item.get("text", ""),
                }
            )
        else:
            turns[-1]["text"] += item.get("text", "")
            turns[-1]["end_time_seconds"] = item["end"]
    for turn in turns:
        turn["text"] = re.sub(r"\s+", " ", turn["text"]).strip()
        turn["start_timecode"] = format_timecode(
            turn["start_time_seconds"]
        )
        turn["end_timecode"] = format_timecode(turn["end_time_seconds"])
    return [turn for turn in turns if turn["text"]]


def representative_speaker_sentences(
    turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Choose the longest available sentence for each diarized speaker."""
    representatives: dict[str, dict[str, Any]] = {}
    for turn in turns:
        speaker_id = turn["speaker_id"]
        if speaker_id == "audio_event" or not speaker_id.startswith("speaker_"):
            continue
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", turn["text"])
            if sentence.strip()
        ]
        for sentence in sentences:
            candidate = {
                "speaker_id": speaker_id,
                "start_time_seconds": turn["start_time_seconds"],
                "end_time_seconds": turn["end_time_seconds"],
                "start_timecode": turn["start_timecode"],
                "end_timecode": turn["end_timecode"],
                "text": sentence,
                "word_count": len(sentence.split()),
                "character_count": len(sentence),
            }
            existing = representatives.get(speaker_id)
            if existing is None or (
                candidate["word_count"],
                candidate["character_count"],
            ) > (
                existing["word_count"],
                existing["character_count"],
            ):
                representatives[speaker_id] = candidate
    return sorted(
        representatives.values(),
        key=lambda sentence: (
            sentence["start_time_seconds"],
            sentence["speaker_id"],
        ),
    )


def chapter_prompt(
    representative_sentences: list[dict[str, Any]],
) -> str:
    transcript = "\n".join(
        f"[{sentence['start_timecode']}-{sentence['end_timecode']}] "
        f"{sentence['speaker_id']}: {sentence['text']}"
        for sentence in representative_sentences
    )
    return f"""
Analyze this approximately five-minute chapter assembled from consecutive
animatic scenes. Use the supplied representative ElevenLabs dialogue samples as
evidence alongside the video. Each speaker has only their single longest
sentence from this chapter; the samples are identity clues, not a complete
transcript. Return ONLY valid JSON with exactly these keys:

"chapter_summary": a visually grounded chronological summary of approximately
300-600 words describing characters, actions, interactions, important objects,
scenery, lighting, visual effects, and useful shot/camera transitions. Every
sentence MUST begin with its applicable GLOBAL MOVIE time range in square
brackets, exactly like "[00:04:26.083-00:04:48.500] The character enters the
room." Put a bracketed time range between every pair of sentences so each
sentence can be connected back to the source scenes. Use the closest accurate
range visible in the video, not merely the dialogue sample time. Do not invent
names or lore.

"speaker_name_guesses": an array containing one object for every speaker_N tag
present below. Each object must contain "speaker_id", "character_name_guess",
"confidence" ("high", "medium", or "low"), and "evidence". Correlate the sample
timing with visible lip movement, screen position, names spoken by other
characters, and continuity. Use "unknown" when evidence is insufficient.

The diarization system may reuse one speaker tag for multiple characters across
the movie. Make guesses only for this chapter. Transcript spellings of proper
names may be wrong.

REPRESENTATIVE DIALOGUE — ONE LONGEST SENTENCE PER SPEAKER:
{transcript}
""".strip()


def parse_api_response(response: requests.Response) -> tuple[str, dict[str, Any]]:
    try:
        body = response.json()
        text = str(body.get("data") or "")
        metadata = {
            "response_id": body.get("id"),
            "finish_reason": body.get("finish_reason"),
            "usage": body.get("usage"),
        }
    except requests.JSONDecodeError:
        fragments: list[str] = []
        end_event: dict[str, Any] = {}
        for line in response.text.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event_type") == "text_generation":
                fragments.append(str(event.get("text") or ""))
            elif event.get("event_type") == "stream_end":
                end_event = event
        text = "".join(fragments)
        metadata = {
            "response_id": (end_event.get("metadata") or {}).get(
                "generation_id"
            ),
            "finish_reason": end_event.get("finish_reason"),
            "usage": (end_event.get("metadata") or {}).get("usage"),
        }
    return text.strip(), metadata


def analyze_chapter(
    chapter_path: Path,
    representative_sentences: list[dict[str, Any]],
    api_key: str,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "model_name": MODEL,
        "video": {
            "type": "base64_string",
            "base64_string": base64.b64encode(
                chapter_path.read_bytes()
            ).decode("ascii"),
        },
        "prompt": chapter_prompt(representative_sentences),
        "temperature": 0.1,
        "max_tokens": 2400,
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
            timeout=(60, timeout),
        )
    except requests.RequestException as exc:
        raise ClipDescriptionError(
            f"Chapter request failed: {type(exc).__name__}"
        ) from exc
    if not response.ok:
        detail = response.text[:1000].replace(api_key, "[REDACTED]")
        raise ClipDescriptionError(
            f"TwelveLabs returned HTTP {response.status_code}: {detail}"
        )
    raw_text, api_metadata = parse_api_response(response)
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        raw_text,
        flags=re.IGNORECASE,
    )
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ClipDescriptionError(
            "Pegasus chapter response was not valid JSON"
        ) from exc
    if not isinstance(result.get("chapter_summary"), str) or not isinstance(
        result.get("speaker_name_guesses"), list
    ):
        raise ClipDescriptionError(
            "Pegasus chapter response is missing required fields"
        )
    result["chapter_summary"] = re.sub(
        r"\s+", " ", result["chapter_summary"]
    ).strip()
    timecode_markers = re.findall(
        r"\[\d{2}:\d{2}:\d{2}\.\d{3}-\d{2}:\d{2}:\d{2}\.\d{3}\]",
        result["chapter_summary"],
    )
    if len(timecode_markers) < 2:
        raise ClipDescriptionError(
            "Pegasus chapter summary did not include sentence timecodes"
        )
    return result, api_metadata


def load_results(path: Path) -> dict[int, dict[str, Any]]:
    if not path.exists():
        return {}
    results = {}
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            results[int(record["chapter_index"])] = record
    return results


def persist(path: Path, results: dict[int, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as destination:
        temporary = Path(destination.name)
        for chapter_index in sorted(results):
            destination.write(
                json.dumps(results[chapter_index], ensure_ascii=False) + "\n"
            )
    os.replace(temporary, path)


def individual_run_complete(path: Path, total_scenes: int) -> bool:
    if not path.is_file():
        return False
    with path.open("r", encoding="utf-8") as source:
        processed = {
            int(record["scene_index"])
            for line in source
            if line.strip()
            for record in [json.loads(line)]
            if record.get("status") in {"success", "terminal_error"}
        }
    return len(processed) == total_scenes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--clips-dir", type=Path, default=DEFAULT_CLIPS)
    parser.add_argument("--chapters-dir", type=Path, default=DEFAULT_CHAPTERS)
    parser.add_argument("--transcript", type=Path, default=DEFAULT_TRANSCRIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--individual-results",
        type=Path,
        default=DEFAULT_INDIVIDUAL_RESULTS,
    )
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--maximum-seconds", type=float, default=300.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--max-chapters", type=int)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--allow-incomplete-individual-run",
        action="store_true",
        help="Bypass the safety gate intended for testing only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scenes = load_scenes(args.metadata)
    if (
        not args.allow_incomplete_individual_run
        and not individual_run_complete(args.individual_results, len(scenes))
    ):
        raise RuntimeError(
            "Individual Pegasus processing is not complete; chapter work "
            "must wait."
        )

    chapters = partition_scenes(scenes, args.maximum_seconds)
    transcript_items = load_transcript_items(args.transcript)
    results = load_results(args.output)
    api_key = None if args.prepare_only else load_credential(
        args.credentials, API_KEY_NAME
    )
    processed_this_run = 0

    for chapter_index, chapter_scenes in enumerate(chapters, 1):
        chapter_path = args.chapters_dir / f"chapter_{chapter_index:03d}.webm"
        create_chapter_video(chapter_path, chapter_scenes, args.clips_dir)
        start_time = float(chapter_scenes[0]["start_time"])
        end_time = float(chapter_scenes[-1]["end_time"])
        turns = transcript_turns(transcript_items, start_time, end_time)
        representatives = representative_speaker_sentences(turns)
        base = {
            "chapter_index": chapter_index,
            "aggregate_clip_file": str(
                chapter_path.relative_to(ROOT).as_posix()
            ),
            "movie_start_time_seconds": start_time,
            "movie_end_time_seconds": end_time,
            "movie_start_timecode": format_timecode(start_time),
            "movie_end_timecode": format_timecode(end_time),
            "duration_seconds": end_time - start_time,
            "first_scene_index": chapter_scenes[0]["scene_index"],
            "last_scene_index": chapter_scenes[-1]["scene_index"],
            "scene_indices": [
                scene["scene_index"] for scene in chapter_scenes
            ],
            "transcript_turns": turns,
            "representative_speaker_sentences": representatives,
            "model": MODEL,
            "prompt_version": PROMPT_VERSION,
        }
        existing = results.get(chapter_index)
        if (
            existing
            and existing.get("status") == "success"
            and existing.get("prompt_version") == PROMPT_VERSION
        ):
            continue
        if args.prepare_only:
            results[chapter_index] = {
                **base,
                "status": "prepared",
                "updated_at": utc_now(),
            }
            persist(args.output, results)
            continue
        if args.max_chapters is not None and (
            processed_this_run >= args.max_chapters
        ):
            break

        print(
            f"Analyzing chapter {chapter_index}/{len(chapters)} "
            f"({format_timecode(start_time)}-{format_timecode(end_time)})",
            flush=True,
        )
        try:
            analysis, api_metadata = analyze_chapter(
                chapter_path,
                representatives,
                api_key,
                args.timeout,
            )
        except ClipDescriptionError as exc:
            results[chapter_index] = {
                **base,
                "status": "retryable_error",
                "error": str(exc),
                "updated_at": utc_now(),
            }
            persist(args.output, results)
            print(
                "Chapter failure saved; rerun to resume.",
                flush=True,
            )
            return 2
        results[chapter_index] = {
            **base,
            **analysis,
            **api_metadata,
            "status": "success",
            "updated_at": utc_now(),
        }
        persist(args.output, results)
        processed_this_run += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
