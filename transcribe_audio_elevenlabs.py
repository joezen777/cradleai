#!/usr/bin/env python3
"""Transcribe the full Cradle audio track with ElevenLabs Scribe v2."""

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import requests


API_URL = "https://api.elevenlabs.io/v1/speech-to-text"
API_KEY_NAME = "ELEVENLABS_API_SPEECH_TO_TEXT"


def load_secret(credentials_path: Path, key_name: str) -> str:
    """Read one key=value secret without logging credentials or their values."""
    if not credentials_path.is_file():
        raise FileNotFoundError(f"Credentials file not found: {credentials_path}")

    values: dict[str, str] = {}
    with credentials_path.open("r", encoding="utf-8") as source:
        for raw_line in source:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

    secret = values.get(key_name)
    if not secret:
        raise ValueError(f"Required credential {key_name} is missing or empty")
    return secret


def request_transcript(
    audio_path: Path,
    api_key: str,
    model_id: str,
    language_code: str | None,
    diarization_threshold: float | None,
) -> dict[str, Any]:
    """Upload an audio file and return the complete ElevenLabs response."""
    form_data: dict[str, str] = {
        "model_id": model_id,
        "diarize": "true",
        "tag_audio_events": "true",
        "timestamps_granularity": "word",
    }
    if language_code:
        form_data["language_code"] = language_code
    if diarization_threshold is not None:
        form_data["diarization_threshold"] = str(diarization_threshold)

    with audio_path.open("rb") as audio:
        response = requests.post(
            API_URL,
            headers={"xi-api-key": api_key},
            data=form_data,
            files={"file": (audio_path.name, audio, "audio/wav")},
            timeout=(60, 14_400),
        )

    if not response.ok:
        # Do not include request headers or other potentially sensitive state.
        try:
            error = response.json()
        except ValueError:
            error = {"message": response.text[:1000]}
        raise RuntimeError(
            f"ElevenLabs returned HTTP {response.status_code}: "
            f"{json.dumps(error, ensure_ascii=False)}"
        )
    return response.json()


def write_jsonl(
    output_path: Path,
    transcript: dict[str, Any],
    audio_path: Path,
    model_id: str,
) -> None:
    """Atomically write the transcript summary and all timed items as JSONL."""
    words = transcript.get("words") or []
    transcript_record = {
        "record_type": "transcript",
        "source_audio": str(audio_path),
        "model_id": model_id,
        "language_code": transcript.get("language_code"),
        "language_probability": transcript.get("language_probability"),
        "text": transcript.get("text", ""),
        "word_event_count": len(words),
        "response_metadata": {
            key: value
            for key, value in transcript.items()
            if key not in {"text", "words"}
        },
    }

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
            destination.write(
                json.dumps(transcript_record, ensure_ascii=False) + "\n"
            )
            for sequence, item in enumerate(words):
                item_record = {
                    "record_type": "timed_item",
                    "sequence": sequence,
                    **item,
                }
                destination.write(
                    json.dumps(item_record, ensure_ascii=False) + "\n"
                )
        os.replace(temporary_path, output_path)
    except BaseException:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribe output/audio.wav with ElevenLabs diarization."
    )
    parser.add_argument("--audio", type=Path, default=Path("output/audio.wav"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/audiotranscript.jsonl"),
    )
    parser.add_argument("--credentials", type=Path, default=Path(".credentials"))
    parser.add_argument("--model", default="scribe_v2")
    parser.add_argument(
        "--language",
        default="eng",
        help="ISO language code; pass an empty string for automatic detection.",
    )
    parser.add_argument(
        "--diarization-threshold",
        type=float,
        default=None,
        help="Optional threshold from 0.1 to 0.4; provider default is normally 0.22.",
    )
    args = parser.parse_args()

    if not args.audio.is_file():
        raise FileNotFoundError(f"Audio file not found: {args.audio}")
    if args.diarization_threshold is not None and not (
        0.1 <= args.diarization_threshold <= 0.4
    ):
        raise ValueError("--diarization-threshold must be between 0.1 and 0.4")

    api_key = load_secret(args.credentials, API_KEY_NAME)
    print(
        f"Uploading {args.audio} to ElevenLabs for diarized transcription...",
        flush=True,
    )
    transcript = request_transcript(
        args.audio,
        api_key,
        args.model,
        args.language or None,
        args.diarization_threshold,
    )
    write_jsonl(args.output, transcript, args.audio, args.model)
    print(
        f"Saved {1 + len(transcript.get('words') or [])} JSONL records "
        f"to {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
