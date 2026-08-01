#!/usr/bin/env python3
"""Build resumable Pegasus descriptions for every scene clip."""

from __future__ import annotations

import argparse
import json
import os
import random
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from describe_clips_twelvelabs import (
    ClipDescriptionError,
    DEFAULT_CLIPS_DIR,
    DEFAULT_CREDENTIALS,
    MODEL,
    describe_clip,
    load_credential,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_METADATA = ROOT / "output" / "metadata.jsonl"
DEFAULT_OUTPUT = ROOT / "output" / "pegasus_metadata.jsonl"
DEFAULT_TEST_RESULTS = (
    ROOT / "output" / "twelvelabs_clip_descriptions.jsonl"
)
API_KEY_NAME = "TWELVELABS_API_KEY"
RETRYABLE_MARKERS = (
    "description exceeds",
    "http 408",
    "http 409",
    "http 425",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "connectionerror",
    "connecttimeout",
    "readtimeout",
    "request failed",
    "timed out",
    "timeout",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_timecode(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remaining:06.3f}"


def load_scenes(metadata_path: Path) -> list[dict[str, Any]]:
    """Load the canonical per-scene JSONL records, excluding line-one summary."""
    scenes: list[dict[str, Any]] = []
    with metadata_path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if "scene_index" in record:
                scenes.append(record)
            elif line_number != 1:
                raise ValueError(
                    f"Unexpected non-scene record at {metadata_path}:{line_number}"
                )
    if not scenes:
        raise ValueError(f"No scene records found in {metadata_path}")
    return sorted(scenes, key=lambda record: record["scene_index"])


def load_results(output_path: Path) -> dict[int, dict[str, Any]]:
    """Load the latest valid record for every scene from an existing JSONL."""
    results: dict[int, dict[str, Any]] = {}
    if not output_path.exists():
        return results
    with output_path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                scene_index = int(record["scene_index"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid result at {output_path}:{line_number}"
                ) from exc
            results[scene_index] = record
    return results


def persist_results(
    output_path: Path,
    results: dict[int, dict[str, Any]],
) -> None:
    """Atomically replace the JSONL so interruption cannot corrupt progress."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as destination:
            temporary_path = Path(destination.name)
            for scene_index in sorted(results):
                destination.write(
                    json.dumps(results[scene_index], ensure_ascii=False) + "\n"
                )
        os.replace(temporary_path, output_path)
    except BaseException:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
        raise


def base_record(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_index": scene["scene_index"],
        "clip_file": scene["clip_file"].replace("\\", "/"),
        "movie_start_time_seconds": scene["start_time"],
        "movie_end_time_seconds": scene["end_time"],
        "movie_start_timecode": format_timecode(scene["start_time"]),
        "movie_end_timecode": format_timecode(scene["end_time"]),
        "duration_seconds": scene["duration"],
        "start_frame": scene.get("start_frame"),
        "end_frame": scene.get("end_frame"),
        "model": MODEL,
    }


def import_test_results(
    test_results_path: Path,
    scenes_by_index: dict[int, dict[str, Any]],
    results: dict[int, dict[str, Any]],
) -> int:
    """Reuse earlier paid test calls instead of submitting duplicate requests."""
    if not test_results_path.is_file():
        return 0

    imported = 0
    with test_results_path.open("r", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            old = json.loads(line)
            scene_index = int(old["scene_id"])
            if scene_index not in scenes_by_index or scene_index in results:
                continue

            status = old.get("status")
            if status == "success":
                record = {
                    **base_record(scenes_by_index[scene_index]),
                    **{
                        key: value
                        for key, value in old.items()
                        if key
                        not in {
                            "scene_id",
                            "clip_filename",
                            "status",
                            "model",
                        }
                    },
                    "status": "success",
                    "attempt_count": 1,
                    "updated_at": utc_now(),
                    "imported_from": str(test_results_path),
                }
            else:
                # A broken source file is permanent; other provider failures
                # remain pending and should be attempted by this batch runner.
                error = str(old.get("error") or "")
                if (
                    "video_file_broken" not in error
                    and "no decodable video frames" not in error
                ):
                    continue
                record = {
                    **base_record(scenes_by_index[scene_index]),
                    "status": "terminal_error",
                    "description": None,
                    "word_count": 0,
                    "error": error,
                    "attempt_count": 1,
                    "updated_at": utc_now(),
                    "imported_from": str(test_results_path),
                }
            results[scene_index] = record
            imported += 1
    return imported


def is_retryable(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in RETRYABLE_MARKERS)


def is_complete(record: dict[str, Any] | None) -> bool:
    return bool(
        record
        and record.get("status") in {"success", "terminal_error"}
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--clips-dir", type=Path, default=DEFAULT_CLIPS_DIR)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--import-results",
        type=Path,
        default=DEFAULT_TEST_RESULTS,
        help="Existing four-scene test JSONL to reuse; pass a missing path to skip.",
    )
    parser.add_argument("--start-scene", type=int)
    parser.add_argument("--end-scene", type=int)
    parser.add_argument(
        "--max-scenes",
        type=int,
        help="Maximum pending scenes to attempt during this invocation.",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--retry-attempts", type=int, default=3)
    parser.add_argument("--retry-base-delay", type=float, default=15.0)
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Retry terminal errors too; successful records are still preserved.",
    )
    parser.add_argument(
        "--initialize-only",
        action="store_true",
        help="Import existing test results and exit without API calls.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.retry_attempts < 1:
        raise ValueError("--retry-attempts must be at least 1")
    if args.max_scenes is not None and args.max_scenes < 1:
        raise ValueError("--max-scenes must be at least 1")

    scenes = load_scenes(args.metadata)
    scenes_by_index = {scene["scene_index"]: scene for scene in scenes}
    results = load_results(args.output)
    imported = import_test_results(
        args.import_results,
        scenes_by_index,
        results,
    )
    normalized = False
    for scene_index, record in list(results.items()):
        scene = scenes_by_index.get(scene_index)
        if scene is None:
            continue
        refreshed = {**base_record(scene), **record}
        if refreshed != record:
            results[scene_index] = refreshed
            normalized = True
    if imported or normalized or not args.output.exists():
        persist_results(args.output, results)
    print(
        f"Loaded {len(scenes)} scenes and {len(results)} persisted results "
        f"({imported} newly imported).",
        flush=True,
    )

    if args.initialize_only:
        return 0

    selected = [
        scene
        for scene in scenes
        if (args.start_scene is None or scene["scene_index"] >= args.start_scene)
        and (args.end_scene is None or scene["scene_index"] <= args.end_scene)
        and (results.get(scene["scene_index"]) or {}).get("status") != "success"
        and (
            args.retry_errors
            or (results.get(scene["scene_index"]) or {}).get("status")
            != "terminal_error"
        )
    ]
    if args.max_scenes is not None:
        selected = selected[: args.max_scenes]
    if not selected:
        print("No pending scenes in the selected range.", flush=True)
        return 0

    api_key = load_credential(args.credentials, API_KEY_NAME)
    attempted = 0
    succeeded = 0
    terminal_errors = 0

    for position, scene in enumerate(selected, 1):
        scene_index = scene["scene_index"]
        clip_path = args.clips_dir / f"scene_{scene_index:03d}.webm"
        previous_attempts = int(
            (results.get(scene_index) or {}).get("attempt_count", 0)
        )
        print(
            f"[{position}/{len(selected)}] Scene {scene_index}: "
            f"{clip_path.name}",
            flush=True,
        )

        if not clip_path.is_file():
            results[scene_index] = {
                **base_record(scene),
                "status": "terminal_error",
                "description": None,
                "word_count": 0,
                "error": f"Clip not found: {clip_path}",
                "attempt_count": previous_attempts,
                "updated_at": utc_now(),
            }
            persist_results(args.output, results)
            terminal_errors += 1
            continue

        retryable_failure: ClipDescriptionError | None = None
        for local_attempt in range(1, args.retry_attempts + 1):
            attempted += 1
            try:
                description, api_metadata = describe_clip(
                    clip_path,
                    api_key,
                    args.timeout,
                )
                word_count = len(description.split())
                if word_count > 500:
                    raise ClipDescriptionError(
                        f"Description exceeds 500 words ({word_count})"
                    )
                results[scene_index] = {
                    **base_record(scene),
                    "status": "success",
                    "description": description,
                    "word_count": word_count,
                    "description_length_status": (
                        "within_target" if word_count >= 200 else "below_target"
                    ),
                    **api_metadata,
                    "attempt_count": previous_attempts + local_attempt,
                    "updated_at": utc_now(),
                }
                persist_results(args.output, results)
                succeeded += 1
                retryable_failure = None
                break
            except ClipDescriptionError as exc:
                if not is_retryable(exc):
                    results[scene_index] = {
                        **base_record(scene),
                        "status": "terminal_error",
                        "description": None,
                        "word_count": 0,
                        "error": str(exc),
                        "attempt_count": previous_attempts + local_attempt,
                        "updated_at": utc_now(),
                    }
                    persist_results(args.output, results)
                    terminal_errors += 1
                    retryable_failure = None
                    print(
                        f"  Permanent failure saved: {exc}",
                        flush=True,
                    )
                    break

                retryable_failure = exc
                if local_attempt < args.retry_attempts:
                    delay = (
                        args.retry_base_delay * (2 ** (local_attempt - 1))
                        + random.uniform(0, 2)
                    )
                    print(
                        f"  Temporary failure; retrying in {delay:.1f}s.",
                        flush=True,
                    )
                    time.sleep(delay)

        if retryable_failure is not None:
            results[scene_index] = {
                **base_record(scene),
                "status": "retryable_error",
                "description": None,
                "word_count": 0,
                "error": str(retryable_failure),
                "attempt_count": previous_attempts + args.retry_attempts,
                "updated_at": utc_now(),
            }
            persist_results(args.output, results)
            print(
                "Temporary provider/rate-limit failure saved. Stop now and "
                "rerun the same command to resume.",
                flush=True,
            )
            return 2

    print(
        f"Run complete: {succeeded} succeeded, "
        f"{terminal_errors} terminal errors, {attempted} API attempts. "
        f"Total persisted records: {len(results)}.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
