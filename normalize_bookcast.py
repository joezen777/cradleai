#!/usr/bin/env python3
"""Final deterministic quality pass for the MCP/Qwen book-cast artifact.

Re-validates every trait field against the source corpus (service_index.json)
using the same evidence-scoped logic generate_bookcast_qwen.py uses for new
records — not just reformatting whatever was already stored. That is what
actually removes cross-character contamination (a color from a different
character's paragraph in the same passage, previously miscited onto e.g.
snowfox) rather than merely re-displaying it more briefly. Blank means
unknown (never a filler sentence), and portrait_description is composed from
only the grounded fields via the shared bookcast_fields.compose_portrait —
brief, deduplicated, no tautologies. No GPU or MCP server required: this
reuses only the deterministic evidence/validation functions.
"""

import json
import re
from pathlib import Path
from typing import Any

from bookcast_evidence import resolve_character
from bookcast_fields import compose_portrait, normalize_trait
from generate_bookcast_qwen import compact_dossier, sanitize_result

PATH = Path(__file__).with_name("bookcast.jsonl")
INDEX_PATH = Path(__file__).with_name("lore_graph") / "data" / "service_index.json"

PREFERRED_NAMES = {
    "eithan-arelius": "Eithan Arelius",
    "wei-shi-lindon": "Wei Shi Lindon",
    "wei-shi-seisha": "Wei Shi Seisha",
    "wei-shi-jaran": "Wei Shi Jaran",
    "wei-shi-kelsa": "Wei Shi Kelsa",
    "wei-mon-keth": "Wei Mon Keth",
    "wei-mon-teris": "Wei Mon Teris",
    "wei-mon-eri": "Wei Mon Eri",
    "wei-jin-sairus": "Wei Jin Sairus",
    "sword-sage": "Sword Sage",
    "tree-remnant": "Tree Remnant",
    "hornet-remnant": "Hornet Remnant",
}

NONHUMAN = {
    "wei-shi-seisha-drudge": ("construct", "Soulsmith drudge"),
    "elder-whisper": ("sacred beast", "snowfox sacred beast"),
    "fisher-s-remnant": ("Remnant", "Fisher Remnant"),
    "presence": ("sentient construct", "Abidan Presence"),
    "razor": ("artifact", "Abidan weapon called the Razor"),
    "remnant": ("spirit", "Remnant"),
    "tree-remnant": ("spirit", "Remnant"),
    "hornet-remnant": ("spirit", "Remnant"),
    "suriel-s-ghost": ("projection", "projection of Suriel"),
    "sylvan": ("spirit", "Sylvan Riverseed"),
    "sylvan-riverseed": ("spirit", "Sylvan Riverseed"),
    "snowfox": ("sacred beast", "snowfox"),
    "unnamed-snowfox": ("sacred beast", "snowfox"),
    "blue-rabbit": ("nonhuman entity", "blue rabbit-shaped entity"),
    "brown-and-black-mass": ("nonhuman entity", "brown-and-black creature or mass"),
}

# identity_key sometimes carries a trailing extraction-node hash
# ("unnamed-snowfox-3f5ceea0") that an exact NONHUMAN lookup misses, silently
# falling through to the human/individual-person default for a literal
# animal. Strip it and retry before giving up.
_HASH_SUFFIX = re.compile(r"-[0-9a-f]{6,10}$")


def resolve_nonhuman(key: str) -> tuple[str, str] | None:
    if key in NONHUMAN:
        return NONHUMAN[key]
    stripped = _HASH_SUFFIX.sub("", key)
    if stripped != key and stripped in NONHUMAN:
        return NONHUMAN[stripped]
    return None


ACCESSORY_OVERRIDES = {
    "wei-shi-lindon": "wooden Empty badge, Suriel's blue marble, parasite ring, pack, halfsilver dagger, scripted tools",
    "yerin": "white sword inherited from her master, gold badge, silver blade-like Goldsign, red belt, pack",
    "eithan-arelius": "scissors, pipe, intricately filigreed golden badge",
    "wei-shi-seisha": "Soulsmith drudge, portable slate, Soulsmith tools",
    "wei-shi-jaran": "cane, sacred-artist badge",
    "wei-shi-kelsa": "sword, sacred-artist badge",
    "suriel": "white armor, the Razor, Mantle, green-lit display",
}

FIGHT_OVERRIDES = {
    "wei-shi-lindon": "Drives an Empty Palm into an opponent to disrupt the opponent's madra.",
    "yerin": "Sweeps her white blade through a sword strike, with her silver blade-like Goldsign poised behind her.",
}

_TRAIT_FIELDS = (
    "face", "skin_tone", "eyes", "hair", "build", "posture", "emotion",
    "action", "clothing", "wardrobe", "color_information",
)


def clean_accessories(value: str) -> str:
    value = normalize_trait(value)
    if not value:
        return ""
    reject = {"madra", "skin", "weapon", "item", "unspecified", "not specified"}
    pieces = []
    for raw in value.split(","):
        item = raw.strip()
        if not item or item.lower() in reject or ":" in item:
            continue
        if item.lower() not in {x.lower() for x in pieces}:
            pieces.append(item)
    return ", ".join(pieces[:12])


_COMBAT_WORDS = re.compile(
    r"\b(attack|punch|kick|slash|stab|strike|swing|thrust|cut|block|dodge|"
    r"deflect|lunge|shoot|launch|empty palm)\w*\b", re.I,
)


def normalize_records(raw_lines: list[str], index: dict[str, Any] | None = None) -> list[dict]:
    records = []
    unresolved: list[str] = []
    for line in raw_lines:
        if not line.strip():
            continue
        r = json.loads(line)
        key = r["identity_key"]
        if key == "greatfather":
            continue

        # Legacy records (and anything the generation model wrote) may still
        # carry the old filler sentence in any field — normalize first so a
        # rebuild is safe regardless of which generation produced the record.
        for field in _TRAIT_FIELDS + ("accessories", "fighting_move"):
            if field in r:
                r[field] = normalize_trait(r[field])

        if index is not None:
            character_id, source = resolve_character(index, r)
            if source is not None:
                # Re-validates every trait already on r against this
                # character's own evidence (not the raw multi-character
                # passage blob), recomputing color_information, accessories,
                # action/posture, and portrait_description from scratch. This
                # can only remove unsupported content or recover text the
                # old, narrower anchor set wrongly rejected — it never adds
                # anything the record didn't already claim.
                r = sanitize_result(r, source, compact_dossier(source, []))
            else:
                unresolved.append(key)

        r["canonical_name"] = PREFERRED_NAMES.get(key, r["canonical_name"])
        nonhuman = resolve_nonhuman(key)
        if nonhuman:
            r["entity_type"], r["species_or_object_type"] = nonhuman
        else:
            r["entity_type"] = "individual person"
            r["species_or_object_type"] = "human"

        if key == "elder-whisper":
            r["clothing"] = r["wardrobe"] = ""
            r["hair"] = "white fox fur"
        if key == "wei-shi-seisha":
            r["face"] = ""
            r["action"] = r["posture"] = "Examines and discusses the recovered spirit-fruit with her family."

        r["accessories"] = ACCESSORY_OVERRIDES.get(key, clean_accessories(r.get("accessories", "")))
        move = r.get("fighting_move", "")
        if key in FIGHT_OVERRIDES:
            move = FIGHT_OVERRIDES[key]
        elif move and not _COMBAT_WORDS.search(move):
            move = ""
        r["fighting_move"] = move

        # posture and action, once independently validated upstream, can
        # still collide for records generated before that fix — collapse.
        if r.get("posture") and r.get("posture") == r.get("action"):
            r["posture"] = ""

        for field in _TRAIT_FIELDS:
            r.setdefault(field, "")
        r.setdefault("confidence", "medium")
        r.setdefault("evidence_notes", {"note": "See MCP-grounded source identity and books fields."})
        r["record_version"] = "bookcast-v2"
        r["portrait_description"] = compose_portrait(r)
        records.append(r)
    if unresolved:
        print(f"warning: {len(unresolved)} record(s) could not be matched to "
              f"service_index.json and were only reformatted, not re-validated: "
              f"{unresolved}")
    return records


def main(path: Path = PATH, index_path: Path = INDEX_PATH) -> int:
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else None
    if index is None:
        print(f"warning: {index_path} not found; records will only be reformatted, not re-validated")
    records = normalize_records(path.read_text().splitlines(), index)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    tmp.replace(path)
    print(f"normalized {len(records)} unique cast records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
