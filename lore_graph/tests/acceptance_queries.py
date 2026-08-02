#!/usr/bin/env python3
"""Source-grounded semantic acceptance tests supplied during development."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lore_api.schemas import CharacterLookupRequest, LocateLoreRequest, PropLookupRequest, SceneryLookupRequest
from lore_api.service import LoreService


def flattened(value) -> str:
    return json.dumps(value, ensure_ascii=False).casefold()


def require_any(label: str, text: str, terms: tuple[str, ...]) -> None:
    missing = [term for term in terms if term.casefold() not in text]
    if missing:
        raise AssertionError(f"{label}: missing expected source concepts {missing}")


def main() -> int:
    service = LoreService(ROOT)

    badge = service.locate_props(PropLookupRequest(
        description="the badge Lindon wears around his neck", max_results=10,
    ))
    require_any("Lindon badge prop", flattened([x.model_dump() for x in badge]), ("wood", "empty"))

    whisper = service.locate_characters(CharacterLookupRequest(
        description="Elder Whisper in the tower", max_results=5,
    ))
    require_any("Elder Whisper character", flattened([x.model_dump() for x in whisper]), ("fox", "tail"))

    orchard = service.locate_scenery(SceneryLookupRequest(
        description="Kelsa and Lindon practice the Empty Palm", max_results=10,
    ))
    scenery_text = flattened([x.model_dump() for x in orchard])
    require_any("Empty Palm scenery", scenery_text, ("garden", "mountain roses", "cloudbell", "grass"))

    location = service.locate_lore(LocateLoreRequest(
        description="Kelsa and Lindon practice the Empty Palm in the Shi family gardens among blue mountain roses and cloudbell",
        max_locations=3,
    ))
    if not location.matches:
        raise AssertionError("locate_lore_context returned no source locations")

    print("PASS: badge prop is wooden and marked empty")
    print("PASS: Elder Whisper is identified as a many-tailed fox")
    print("PASS: Empty Palm practice scenery includes the source-grounded garden flowers and grass")
    print("PASS: locate_lore_context returned cited source locations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
