#!/usr/bin/env python3
"""Shared trait-value and portrait-composition helpers for the book cast
pipeline. Blank means unknown — never a filler sentence — and the portrait
composer emits only what is actually grounded, deduplicated, briefly.
"""

from __future__ import annotations

import re
from typing import Any

# The Qwen generation step (generate_bookcast_qwen.py) and older records both
# produce several spellings of "nothing here." Catch them all in one place so
# "not specified", "unspecified", "n/a", etc. all collapse to "" instead of a
# sentence that then has to be filtered out downstream, over and over.
_FILLER_PATTERN = re.compile(
    r"^\s*(not[\s-]specified|unspecified|unknown|n/?a|none|not[\s-]stated|"
    r"not[\s-]mentioned)\b",
    re.IGNORECASE,
)


def normalize_trait(value: Any) -> str:
    """Collapse any legacy or model-produced "unknown" spelling to ""."""
    text = str(value or "").strip()
    if not text or _FILLER_PATTERN.match(text):
        return ""
    return text


def has_value(value: Any) -> bool:
    """True when a trait carries real, cited information."""
    return bool(normalize_trait(value))


def normalize_for_dedup(text: str) -> str:
    """Loose key for detecting near-duplicate statements."""
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


_VOWEL_SOUND = re.compile(r"^[aeiou]", re.IGNORECASE)


def _article(noun: str) -> str:
    return "an" if _VOWEL_SOUND.match(noun.strip()) else "a"


_FIELD_LABELS = {
    "face": "face",
    "skin_tone": "skin",
    "eyes": "eyes",
    "hair": "hair",
    "build": "build",
}


def compose_portrait(record: dict[str, Any]) -> str:
    """Build a brief portrait description from only the grounded fields on
    `record`. Empty fields are skipped entirely — no label, no placeholder.
    Identical or near-identical statements are collapsed once. A character
    with little grounded evidence gets a correspondingly short description,
    including "" when nothing is grounded at all.
    """
    name = (record.get("canonical_name") or "").strip()
    species = normalize_trait(record.get("species_or_object_type"))
    entity_type = normalize_trait(record.get("entity_type"))

    clauses: list[str] = []
    seen: set[str] = set()

    def add(clause: str) -> None:
        clause = clause.strip().rstrip(".")
        if not clause:
            return
        key = normalize_for_dedup(clause)
        if not key or key in seen:
            return
        seen.add(key)
        clauses.append(clause)

    # Skip the identity clause when it says nothing: species repeating the
    # name exactly ("snowfox is a snowfox") or as a substring of it ("unnamed
    # snowfox is a snowfox"), or an ordinary named human where "individual
    # person" / "human" adds no visual information.
    is_generic_person = (
        species.casefold() in {"human", ""} and entity_type.casefold() in {"individual person", ""}
    )
    name_key, species_key = normalize_for_dedup(name), normalize_for_dedup(species)
    is_tautological = bool(species_key) and (species_key == name_key or species_key in name_key)
    if species and name and not is_tautological and not is_generic_person:
        add(f"{name} is {_article(species)} {species}")

    for field, label in _FIELD_LABELS.items():
        value = normalize_trait(record.get(field))
        if value:
            add(f"{label}: {value}")

    clothing = normalize_trait(record.get("clothing") or record.get("wardrobe"))
    if clothing:
        add(f"wears {clothing}")
    accessories = normalize_trait(record.get("accessories"))
    if accessories:
        add(f"carries {accessories}")

    posture = normalize_trait(record.get("posture"))
    action = normalize_trait(record.get("action"))
    fighting_move = normalize_trait(record.get("fighting_move"))
    emotion = normalize_trait(record.get("emotion"))
    if posture:
        add(posture)
    if action and normalize_for_dedup(action) != normalize_for_dedup(posture):
        add(action)
    if fighting_move and normalize_for_dedup(fighting_move) not in (
        normalize_for_dedup(action), normalize_for_dedup(posture)
    ):
        add(f"signature move: {fighting_move}")
    if emotion:
        add(f"expression: {emotion}")

    color = normalize_trait(record.get("color_information"))
    if color:
        add(color)

    if not clauses:
        return ""
    return ". ".join(clauses) + "."
