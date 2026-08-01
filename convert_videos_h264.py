#!/usr/bin/env python3
"""Convert project AV1 videos to H.264 MP4 and update JSONL references."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = PROJECT_ROOT / "output"
METADATA_FILES = (
    OUTPUT_ROOT / "metadata.jsonl",
    OUTPUT_ROOT / "metadatagen.jsonl",
    OUTPUT_ROOT / "metadatagen_full.jsonl",
    OUTPUT_ROOT / "pegasus_chapter_metadata.jsonl",
    OUTPUT_ROOT / "pegasus_metadata.jsonl",
    OUTPUT_ROOT / "twelvelabs_clip_descriptions.jsonl",
)


def run_json(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(result.stdout)


def probe(path: Path, *, packets: bool = False) -> dict[str, Any]:
    command = ["ffprobe", "-v", "error"]
    if packets:
        command.extend(
            [
                "-select_streams",
                "v:0",
                "-show_entries",
                "packet=size",
                "-show_packets",
            ]
        )
    else:
        command.extend(
            [
                "-show_entries",
                (
                    "format=duration,size,bit_rate:"
                    "stream=index,codec_type,codec_name,width,height,"
                    "sample_aspect_ratio,display_aspect_ratio,avg_frame_rate"
                ),
            ]
        )
    command.extend(["-of", "json", str(path)])
    return run_json(command)


def video_stream(info: dict[str, Any]) -> dict[str, Any]:
    return next(
        stream
        for stream in info.get("streams", [])
        if stream.get("codec_type") == "video"
    )


def audio_codecs(info: dict[str, Any]) -> list[str]:
    return [
        str(stream.get("codec_name"))
        for stream in info.get("streams", [])
        if stream.get("codec_type") == "audio"
    ]


@lru_cache(maxsize=None)
def measured_video_bitrate(path: Path) -> int:
    basic_info = probe(path)
    packet_info = probe(path, packets=True)
    video_bytes = sum(
        int(packet.get("size") or 0)
        for packet in packet_info.get("packets", [])
    )
    duration = float(basic_info["format"]["duration"])
    if video_bytes <= 0 or duration <= 0:
        raise RuntimeError(f"Could not measure video bitrate for {path}")
    return max(1, round(video_bytes * 8 / duration))


@lru_cache(maxsize=1)
def scene_ranges() -> dict[int, tuple[float, float]]:
    ranges = {}
    with (OUTPUT_ROOT / "metadata.jsonl").open("r", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            if not all(
                field in record
                for field in ("scene_index", "start_time", "duration")
            ):
                continue
            ranges[int(record["scene_index"])] = (
                float(record["start_time"]),
                float(record["duration"]),
            )
    return ranges


def original_slice(source: Path) -> tuple[Path, float, float]:
    if source.parent != OUTPUT_ROOT / "clips":
        raise RuntimeError(f"Unreadable video stream in {source}")
    try:
        scene_index = int(source.stem.removeprefix("scene_"))
        start_time, duration = scene_ranges()[scene_index]
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f"No original-movie timing found for {source}") from exc
    return PROJECT_ROOT / "CradleAnimatic.webm", start_time, duration


def target_for(source: Path) -> Path:
    if source.name == "reconstructed_video.mp4":
        return source.with_name("reconstructed_video_h264.mp4")
    return source.with_suffix(".mp4")


def inventory() -> list[Path]:
    sources = sorted(OUTPUT_ROOT.rglob("*.webm"))
    sources.append(PROJECT_ROOT / "CradleAnimatic.webm")
    reconstructed = PROJECT_ROOT / "reconstructed_video.mp4"
    if reconstructed.is_file():
        info = probe(reconstructed)
        if video_stream(info).get("codec_name") != "h264":
            sources.append(reconstructed)
    return [source for source in sources if source.is_file()]


def validated_existing(source: Path, target: Path) -> bool:
    if not target.is_file() or target.stat().st_size == 0:
        return False
    try:
        source_info = probe(source)
        target_info = probe(target)
        source_video = video_stream(source_info)
        target_video = video_stream(target_info)
        source_duration = float(source_info["format"]["duration"])
        target_duration = float(target_info["format"]["duration"])
        return (
            target_video.get("codec_name") == "h264"
            and target_video.get("width") == source_video.get("width")
            and target_video.get("height") == source_video.get("height")
            and target_video.get("sample_aspect_ratio")
            == source_video.get("sample_aspect_ratio")
            and audio_codecs(target_info) == audio_codecs(source_info)
            and abs(target_duration - source_duration) <= 0.15
        )
    except (OSError, KeyError, ValueError, subprocess.SubprocessError):
        return False


def transcode(source: Path, target: Path) -> None:
    source = source.resolve()
    target = target.resolve()
    if validated_existing(source, target):
        print(f"SKIP {target.relative_to(PROJECT_ROOT)}", flush=True)
        return

    source_info = probe(source)
    actual_input = source
    input_slice: tuple[float, float] | None = None
    try:
        bitrate = measured_video_bitrate(source)
    except RuntimeError:
        actual_input, start_time, duration = original_slice(source)
        input_slice = (start_time, duration)
        bitrate = measured_video_bitrate(actual_input)
        print(
            f"REBUILD {source.relative_to(PROJECT_ROOT)} from original movie "
            f"at {start_time:.3f}s for {duration:.3f}s",
            flush=True,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.converting.mp4")
    temporary.unlink(missing_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-stats",
        "-y",
    ]
    if input_slice:
        command.extend(["-ss", str(input_slice[0])])
    command.extend(
        [
        "-i",
        str(actual_input),
        ]
    )
    if input_slice:
        command.extend(["-t", str(input_slice[1])])
    command.extend(
        [
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-map_metadata",
        "0",
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p7",
        "-tune",
        "hq",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-rc",
        "cbr",
        "-b:v",
        str(bitrate),
        "-maxrate",
        str(bitrate),
        "-bufsize",
        str(bitrate * 2),
        "-multipass",
        "fullres",
        "-spatial_aq",
        "1",
        "-temporal_aq",
        "1",
        "-c:a",
        "copy",
        "-tag:v",
        "avc1",
        "-movflags",
        "+faststart",
        "-strict",
        "experimental",
        str(temporary),
        ]
    )
    print(
        f"ENCODE {source.relative_to(PROJECT_ROOT)} -> "
        f"{target.relative_to(PROJECT_ROOT)} "
        f"({bitrate / 1000:.0f} kb/s video)",
        flush=True,
    )
    subprocess.run(command, check=True)
    os.replace(temporary, target)
    if not validated_existing(source, target):
        raise RuntimeError(f"Validation failed for {target}")


def replace_webm_reference(value: Any) -> tuple[Any, int]:
    if isinstance(value, dict):
        changed = 0
        result = {}
        for key, item in value.items():
            result[key], item_changed = replace_webm_reference(item)
            changed += item_changed
        return result, changed
    if isinstance(value, list):
        changed = 0
        result = []
        for item in value:
            replacement, item_changed = replace_webm_reference(item)
            result.append(replacement)
            changed += item_changed
        return result, changed
    if isinstance(value, str) and value.casefold().endswith(".webm"):
        return value[:-5] + ".mp4", 1
    return value, 0


def update_jsonl(path: Path) -> int:
    if not path.is_file():
        return 0
    records = []
    changed = 0
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            record, record_changed = replace_webm_reference(json.loads(line))
            records.append(record)
            changed += record_changed
    if changed == 0:
        return 0
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as destination:
        temporary = Path(destination.name)
        for record in records:
            destination.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(temporary, path)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-metadata",
        action="store_true",
        help="Convert and validate videos without updating JSONL references.",
    )
    args = parser.parse_args()

    sources = inventory()
    print(f"Found {len(sources)} videos to convert.", flush=True)
    for index, source in enumerate(sources, 1):
        print(f"[{index}/{len(sources)}]", flush=True)
        transcode(source, target_for(source))

    if not args.skip_metadata:
        total_changes = 0
        for metadata_file in METADATA_FILES:
            changes = update_jsonl(metadata_file)
            total_changes += changes
            print(
                f"METADATA {metadata_file.relative_to(PROJECT_ROOT)}: "
                f"{changes} references updated",
                flush=True,
            )
        print(f"Updated {total_changes} metadata references.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
