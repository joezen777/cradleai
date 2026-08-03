#!/usr/bin/env python3
"""Final deterministic quality pass for the MCP/Qwen book-cast artifact."""

import json
import re
from pathlib import Path


PATH = Path(__file__).with_name("bookcast.jsonl")
UNKNOWN = "not specified in the cited text"

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
}

NONHUMAN = {
    "wei-shi-seisha-drudge": ("construct", "Soulsmith drudge"),
    "elder-whisper": ("sacred beast", "snowfox sacred beast"),
    "fisher-s-remnant": ("Remnant", "Fisher Remnant"),
    "presence": ("sentient construct", "Abidan Presence"),
    "razor": ("artifact", "Abidan weapon called the Razor"),
    "remnant": ("spirit", "Remnant"),
    "suriel-s-ghost": ("projection", "projection of Suriel"),
    "sylvan": ("spirit", "Sylvan Riverseed"),
    "sylvan-riverseed": ("spirit", "Sylvan Riverseed"),
    "snowfox": ("sacred beast", "snowfox"),
    "unnamed-snowfox": ("sacred beast", "snowfox"),
    "blue-rabbit": ("nonhuman entity", "blue rabbit-shaped entity"),
    "brown-and-black-mass": ("nonhuman entity", "brown-and-black creature or mass"),
}

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


def clean_accessories(value: str) -> str:
    if not value or value == UNKNOWN:
        return UNKNOWN
    reject = {"madra", "skin", "weapon", "item", "unspecified", "not specified"}
    pieces = []
    for raw in value.split(","):
        item = raw.strip()
        if not item or item.lower() in reject or ":" in item:
            continue
        if item.lower() not in {x.lower() for x in pieces}:
            pieces.append(item)
    return ", ".join(pieces[:12]) or UNKNOWN


def portrait(record: dict) -> str:
    name = record["canonical_name"]
    kind = record["species_or_object_type"]
    move = record["fighting_move"]
    pose = (f"Their portrait uses their best-supported combat action: {move}"
            if move != UNKNOWN else
            f"No distinctive fighting move is stated in the cited passages; pose them in this supported scene action: {record['action']}")
    return (
        f"{name} is a {kind}. Face: {record['face']}. Skin tone or surface: {record['skin_tone']}. "
        f"Eyes: {record['eyes']}. Hair or outer covering: {record['hair']}. Build: {record['build']}. "
        f"Clothing and wardrobe: {record['clothing']}. Accessories and identifying objects: {record['accessories']}. "
        f"Posture: {record['posture']}. Expression or emotion: {record['emotion']}. {pose}. "
        f"Color information grounded in the cited context: {record['color_information']}. "
        "Any feature marked as not specified should remain visually neutral rather than being invented."
    )


records = []
for line in PATH.read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    key = r["identity_key"]
    if key == "greatfather":
        continue

    r["canonical_name"] = PREFERRED_NAMES.get(key, r["canonical_name"])
    if key in NONHUMAN:
        r["entity_type"], r["species_or_object_type"] = NONHUMAN[key]
    else:
        r["entity_type"] = "individual person"
        r["species_or_object_type"] = "human"

    if key == "elder-whisper":
        r["clothing"] = r["wardrobe"] = UNKNOWN
        r["hair"] = "white fox fur"
    if key == "wei-shi-seisha":
        r["face"] = UNKNOWN
        r["action"] = r["posture"] = "Examines and discusses the recovered spirit-fruit with her family."

    r["accessories"] = ACCESSORY_OVERRIDES.get(key, clean_accessories(r.get("accessories", UNKNOWN)))
    move = r.get("fighting_move", UNKNOWN)
    combat = re.compile(r"\b(attack|punch|kick|slash|stab|strike|swing|thrust|cut|block|dodge|deflect|lunge|shoot|launch|empty palm)\w*\b", re.I)
    if key in FIGHT_OVERRIDES:
        move = FIGHT_OVERRIDES[key]
    elif move != UNKNOWN and not combat.search(move):
        move = UNKNOWN
    r["fighting_move"] = move

    for field in ("face", "skin_tone", "eyes", "hair", "build", "posture", "emotion", "action", "clothing", "wardrobe", "color_information"):
        r[field] = r.get(field) or UNKNOWN
    r.setdefault("confidence", "medium")
    r.setdefault("evidence_notes", {"note": "See MCP-grounded source identity and books fields."})
    r["record_version"] = "bookcast-v1"
    r["portrait_description"] = portrait(r)
    records.append(r)

tmp = PATH.with_suffix(".jsonl.tmp")
tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
tmp.replace(PATH)
print(f"normalized {len(records)} unique cast records")
