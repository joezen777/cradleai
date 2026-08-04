#!/usr/bin/env python3
"""Add the tree-Remnant and hornet(-wasp)-Remnant as standalone bookcast
records.

Both scenes are real and well-documented in the corpus (Unsouled ch.2 and
ch.7/9), but corpus extraction bucketed every Remnant appearance across both
books into one generic character:remnant node (27 unrelated appearances —
tree, hornet swarm, a sandviper Remnant, a liquid-steel Remnant, etc. all
blended together), which is why they never surfaced as distinct cast members
and why the existing "remnant" bookcast record reads as a confused
amalgamation ("Drinks madra from the swords" + a green arrow that belongs to
a different scene entirely).

This script hand-curates the passage-scoped evidence (this is the same
"character-scoped evidence, not the whole multi-character blob" principle
Track B applied everywhere else — see generate_bookcast_qwen.py) for exactly
these two scenes, then runs it through the identical sanitize_result()
validation and compose_portrait() every other character went through. No
model call is required or used: the candidate trait values below are read
directly from the cited passages, and sanitize_result() is the same
safety-net validation that would reject anything unsupported.
"""

from __future__ import annotations

import json
from pathlib import Path

from bookcast_evidence import build_first_mention, descriptive_phrases
from bookcast_fields import normalize_for_dedup
from generate_bookcast_qwen import compact_dossier, sanitize_result

ROOT = Path(__file__).resolve().parent
BOOKCAST_PATH = ROOT / "bookcast.jsonl"
INDEX_PATH = ROOT / "lore_graph" / "data" / "service_index.json"


def load_bookcast(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_bookcast(path: Path, records: list[dict]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(path)


TREE_REMNANT_SOURCE = {
    "character_id": "character:tree-remnant-manual",
    "canonical_name": "Tree Remnant",
    "stable_label": "Tree Remnant",
    "named": False,
    "aliases": ["tree-Remnant", "the Remnant of the ancestral tree", "the purple tree"],
    "character_name_normalized": "tree-remnant-manual",
    "chapters": [{"book_id": "unsouled", "chapter_id": "unsouled:chapter:2", "chapter_number": 2, "label": "Chapter 2"}],
    "appearances": [
        {
            "passage_id": "unsouled:chapter:2:passage:006", "page_start": 16, "page_end": 17,
            "action_summary": "Struck Wei Mon Teris after his punch landed on the orus tree, tearing his clothes.",
        },
        {
            "passage_id": "unsouled:chapter:2:passage:007", "page_start": 17, "page_end": 18,
            "action_summary": "Rages, its fury sounding like snapping twigs and the crunch of splintered logs.",
        },
        {
            "passage_id": "unsouled:chapter:2:passage:008", "page_start": 18, "page_end": 19,
            "action_summary": "Lunged at Lindon, who leapt onto its back and clung to its branches.",
        },
    ],
    "visual_descriptions": [
        {
            "passage_id": "unsouled:chapter:2:passage:007", "page_start": 17, "page_end": 18,
            "exact_quote": (
                "On the highest of the Remnant’s purple branches, a single spot of "
                "white. As the Remnant raged, it was not silent. Its fury sounded like "
                "snapping twigs, like the crunch of splintered logs. It was at least three "
                "times Lindon’s height, crowned by that single spot of white."
            ),
        },
        {
            "passage_id": "unsouled:chapter:2:passage:008", "page_start": 18, "page_end": 19,
            "exact_quote": (
                "The purple tree turned to him as though it could smell the energy... "
                "It felt more like clinging to slick, oily bone than wood."
            ),
        },
        {
            "passage_id": "unsouled:chapter:2:passage:006", "page_start": 16, "page_end": 17,
            "exact_quote": (
                "Wei Mon Teris’ clothes tore where the tree-Remnant had struck him, "
                "but he was on his feet and stumbling away within seconds."
            ),
        },
    ],
    "item_ids": [],
}

HORNET_REMNANT_SOURCE = {
    "character_id": "character:hornet-remnant-manual",
    "canonical_name": "Hornet Remnant",
    "stable_label": "Hornet Remnant Hive",
    "named": False,
    "aliases": ["hornet Remnants", "the hive", "wasp Remnant"],
    "character_name_normalized": "hornet-remnant-manual",
    "chapters": [{"book_id": "unsouled", "chapter_id": "unsouled:chapter:7", "chapter_number": 7, "label": "Chapter 7"}],
    "appearances": [
        {
            "passage_id": "unsouled:chapter:7:passage:006", "page_start": 79, "page_end": 80,
            "action_summary": "Buzzed out of their nest after Lindon threw a rock at it, swarming with stingers ready.",
        },
        {
            "passage_id": "unsouled:chapter:7:passage:008", "page_start": 81, "page_end": 82,
            "action_summary": "Spoke in a harsh, monotone buzzing voice and agreed to enter the jar in exchange for an offering of Lindon's spirit.",
            "combat_relevance": True,
        },
        {
            "passage_id": "unsouled:chapter:9:passage:005", "page_start": 94, "page_end": 95,
            "action_summary": "Sealed in a jar and buried beneath the tournament stage as Lindon's hidden weapon.",
        },
    ],
    "visual_descriptions": [
        {
            "passage_id": "unsouled:chapter:7:passage:006", "page_start": 79, "page_end": 80,
            "exact_quote": (
                "Hornets buzzed out an instant later, furious and seeking vengeance…"
                "but not living hornets. Remnants. They were made of bright emerald "
                "color, as though some artist had dipped her brush in a jar of green "
                "ink and painted them onto the world. Rather than accurate depictions "
                "of the hornets they’d been in life, these Remnants were mere "
                "sketches. Outlines, swirls of lines and shape that somehow suggested "
                "hornets. The swarm flitted around Lindon’s circle, stingers at "
                "the ready."
            ),
        },
        {
            "passage_id": "unsouled:chapter:7:passage:008", "page_start": 81, "page_end": 82,
            "exact_quote": (
                "A buzzing interrupted him, forming a voice, harsh and monotone. "
                "A cluster of hornet Remnants, like sketches of green paint, climbed "
                "all over each other at the bottom."
            ),
        },
        {
            "passage_id": "unsouled:chapter:9:passage:005", "page_start": 94, "page_end": 95,
            "exact_quote": "His hidden weapon, sealed in a jar and buried beneath the stage, would stay hidden.",
        },
    ],
    "item_ids": [],
}


def build_record(source: dict, identity_key: str, entity_type: str, species: str, action: str, index: dict) -> dict:
    dossier = compact_dossier(source, [])
    # These are read directly from the cited passages above, not guessed —
    # sanitize_result() is the same validation every generated character's
    # candidate values pass through; it will blank anything it can't
    # corroborate in the evidence built from this source's own quotes.
    candidate = {
        "canonical_name": source["canonical_name"],
        "entity_type": entity_type,
        "species_or_object_type": species,
        "face": "",
        "skin_tone": "",
        "eyes": "",
        "hair": "",
        "build": "at least three times Lindon's height" if identity_key == "tree-remnant" else "",
        "posture": "",
        "emotion": "",
        "action": action,
        "fighting_move": "",
        "clothing": "",
        "wardrobe": "",
        "accessories": "",
        "color_information": "",
        "confidence": "high",
    }
    result = sanitize_result(candidate, source, dossier)
    result["identity_key"] = identity_key
    result["source_character_ids"] = [source["character_id"]]
    result["source_normalized_names"] = [source["character_name_normalized"]]
    result["books"] = ["unsouled"]
    result["qwen_model"] = "manual-curation"
    result["lore_transport"] = "hand-verified passage citation (source_character_ids not present in service_index.json — corpus extraction bucketed this scene under the generic character:remnant node; see add_remnant_characters.py)"
    result["record_version"] = "bookcast-v2"

    # Track A's first_mention/descriptive_phrases: resolve_character() can't
    # find these synthetic character_ids in service_index.json, so build them
    # directly against the real passage_context for the chosen anchor passage.
    # The generic name-matcher in first_mention_sentence() is unreliable here
    # — "Remnant" vs. "Remnants" trips its word-boundary check, and it fell
    # back to an unrelated sentence in the hornet passage — so the anchor
    # passage and its introducing sentence are hand-verified against the
    # actual book text instead of auto-derived.
    anchor_pid, sentence = _HAND_VERIFIED_FIRST_MENTION[identity_key]
    result["first_mention"] = build_first_mention(index, anchor_pid, sentence)
    # The scene spans three passages; descriptive_phrases() only pulls quotes
    # tied to one exact passage_id, and the richest visual detail isn't
    # necessarily on the passage chosen as the first-mention anchor above (for
    # the tree-Remnant it's on the *next* passage). Merge across every source
    # passage instead of just the anchor.
    seen_phrase_keys: set[str] = set()
    merged_phrases: list[dict] = []
    for appearance in source["appearances"]:
        for phrase in descriptive_phrases(source, appearance["passage_id"]):
            key = normalize_for_dedup(phrase["text"])
            if key and key not in seen_phrase_keys:
                seen_phrase_keys.add(key)
                merged_phrases.append(phrase)
    result["descriptive_phrases"] = merged_phrases[:6]

    return result


_HAND_VERIFIED_FIRST_MENTION = {
    "tree-remnant": (
        "unsouled:chapter:2:passage:006",
        "Wei Mon Teris’ clothes tore where the tree-Remnant had struck him, "
        "but he was on his feet and stumbling away within seconds.",
    ),
    "hornet-remnant": (
        "unsouled:chapter:7:passage:006",
        "Then he threw a rock at the hornet’s nest.",
    ),
}


def main() -> int:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    records = load_bookcast(BOOKCAST_PATH)
    existing_keys = {r["identity_key"] for r in records}

    new_records = []
    for source, key, entity_type, species, action in [
        (
            TREE_REMNANT_SOURCE, "tree-remnant", "spirit", "Remnant",
            "Struck Wei Mon Teris after his punch landed on it, then lunged at Lindon, who leapt onto its back and clung to its branches.",
        ),
        (
            HORNET_REMNANT_SOURCE, "hornet-remnant", "spirit", "Remnant",
            "Swarmed out of its nest with stingers ready after Lindon threw a rock at it, then spoke in a harsh monotone buzzing voice and agreed to enter his jar in exchange for an offering of his spirit.",
        ),
    ]:
        if key in existing_keys:
            print(f"skip {key}: already present in bookcast.jsonl")
            continue
        record = build_record(source, key, entity_type, species, action, index)
        print(f"built {key}: {record['portrait_description']}")
        new_records.append(record)

    if not new_records:
        print("Nothing to add.")
        return 0

    records.extend(new_records)
    save_bookcast(BOOKCAST_PATH, records)
    print(f"Wrote {BOOKCAST_PATH} ({len(records)} total records, +{len(new_records)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
