from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from loredb.materialize import entity_id, slug
from loredb.util import read_jsonl


def unique(values):
    seen = set()
    output = []
    for value in values:
        marker = json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, dict) else value
        if marker not in seen:
            seen.add(marker); output.append(value)
    return output


def normalize_identifier(label: str, stable_id: str) -> str:
    base = slug(label)
    if ":passage:" in stable_id:
        # Passage-local unnamed entities can share the same ordinal in many
        # chapters.  A digest of the full stable ID keeps this deterministic
        # without leaking an unwieldy internal identifier into tool results.
        suffix = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:8]
        return f"{base}-{suffix}"
    return base


def is_portable_story_item(row: dict) -> bool:
    """Keep wardrobe and movable/story objects; reject obvious set fixtures."""
    if str(row.get("item_type") or "").casefold() == "wardrobe":
        return True
    name = str(row.get("name") or "").casefold()
    fixture_terms = (
        "wall", "floor", "ceiling", "doorway", "window", "staircase",
        "stairs", "roof", "building", "house", "room", "road", "path",
        "bridge", "mountain", "valley", "river", "tree", "forest",
    )
    return not any(term in name for term in fixture_terms)


VISUAL_TERMS = (
    "fur", "tail", "eye", "face", "hair", "skin", "scar", "robe", "clothes",
    "wearing", "wore", "dressed", "tall", "short", "bushy", "muzzle", "snout",
    "wing", "badge", "mask", "wrap", "color", "white", "black", "red", "gold",
)


def adjacent_source_visuals(row: dict, passages: dict[str, dict]) -> list[dict]:
    aliases = [row.get("canonical_name"), row.get("stable_label"), *row.get("aliases", [])]
    aliases = [str(value).casefold() for value in aliases if value]
    output = []
    for appearance in row.get("appearances", []):
        passage = passages.get(appearance.get("passage_id"))
        if not passage:
            continue
        paragraphs = [part.strip() for part in passage["text"].split("\n\n") if part.strip()]
        anchors = [i for i, part in enumerate(paragraphs) if any(alias in part.casefold() for alias in aliases)]
        for anchor in anchors:
            for index in range(max(0, anchor - 1), min(len(paragraphs), anchor + 3)):
                paragraph = paragraphs[index]
                if any(term in paragraph.casefold() for term in VISUAL_TERMS):
                    output.append({
                        "exact_quote": paragraph,
                        "normalized_description": paragraph,
                        "book_id": passage["book_id"],
                        "chapter_id": passage["chapter_id"],
                        "chapter_number": passage["chapter_number"],
                        "chapter_label": passage["chapter_label"],
                        "passage_id": passage["passage_id"],
                        "page_start": passage["page_start"],
                        "page_end": passage["page_end"],
                        "evidence_method": "adjacent-source-paragraph",
                    })
    return unique(output)


def location_stub(passage: dict, books: dict, treatments: dict, confidence: float = 1.0) -> dict:
    treatment = treatments.get(passage["chapter_id"], {})
    summary = treatment.get("treatment") or treatment.get("logline") or ""
    return {
        "book_id": passage["book_id"],
        "book_title": books[passage["book_id"]]["title"],
        "chapter_number": passage["chapter_number"],
        "chapter_label": passage["chapter_label"],
        "passage_id": passage["passage_id"],
        "page_start": passage["page_start"],
        "page_end": passage["page_end"],
        "surrounding_paragraph": passage["text"],
        "chapter_summary": summary,
        "confidence_rating": confidence,
    }


def classify_scenery(label: str, descriptions: list[str], source: str) -> dict:
    text = " ".join([label, *descriptions, source]).casefold()
    interior_words = ("room", "hall", "house", "hut", "tent", "inside", "interior", "chamber", "cabin")
    exterior_words = ("forest", "valley", "mountain", "road", "path", "field", "outside", "sky", "street", "desert")
    if any(word in text for word in interior_words): setting = "interior"
    elif any(word in text for word in exterior_words): setting = "exterior"
    elif "void" in text or "outer space" in text: setting = "space"
    elif "black screen" in text or "total darkness" in text: setting = "black"
    else: setting = "unknown"
    weather_terms = [word for word in ("rain", "snow", "wind", "storm", "cloud", "sunny", "mist", "fog") if word in text]
    time_terms = [word for word in ("dawn", "morning", "noon", "afternoon", "dusk", "evening", "night", "midnight") if word in text]
    climate_terms = [word for word in ("tropical", "arid", "humid", "cold", "temperate", "alpine", "desert", "forest") if word in text]
    backdrop = ""
    if setting != "interior":
        backdrop = " ".join(value for value in descriptions if any(
            word in value.casefold() for word in ("distance", "background", "horizon", "sky", "mountain", "forest", "behind")
        ))
    return {
        "weather": ", ".join(weather_terms) or "unknown",
        "time_of_day": ", ".join(time_terms) or "unknown",
        "climate": ", ".join(climate_terms) or "unknown",
        "setting": setting,
        "backdrop": backdrop,
    }


def attributed_dialog(source: str, character_labels: dict[str, str]) -> dict[str, list[str]]:
    output = {cid: [] for cid in character_labels}
    quotes = list(re.finditer(r"[“\"]([^”\"]{2,500})[”\"]", source))
    for match in quotes:
        window = source[max(0, match.start() - 140):min(len(source), match.end() + 140)].casefold()
        candidates = [
            cid for cid, label in character_labels.items()
            if label.casefold() in window
        ]
        if len(candidates) == 1 and re.search(r"\b(said|asked|replied|answered|shouted|whispered|called|continued|added|told)\b", window):
            output[candidates[0]].append(match.group(1).strip())
    return {key: unique(value) for key, value in output.items()}


def sacred_valley_macro(passages: dict, books: dict, treatments: dict) -> dict:
    passage_ids = (
        "unsouled:chapter:2:passage:002",
        "unsouled:chapter:4:passage:009",
        "unsouled:chapter:7:passage:006",
        "unsouled:chapter:11:passage:009",
    )
    visual_terms = ("mountain", "peak", "forest", "snowfox", "orus tree", "valley")
    descriptions = []
    locations = []
    for pid in passage_ids:
        passage = passages.get(pid)
        if not passage:
            continue
        locations.append(location_stub(passage, books, treatments))
        descriptions.extend(
            part.strip() for part in passage["text"].split("\n\n")
            if any(term in part.casefold() for term in visual_terms)
        )
    return {
        "region_name": "Sacred Valley",
        "region_name_normalized": "sacred-valley",
        "aggregate_region_description": (
            "A broad inhabited valley enclosed by major mountains and forested wilderness, "
            "including Mount Samara and the four great peaks; native orus trees and multi-tailed "
            "snowfoxes are characteristic of the region."
        ),
        "inherited_backdrop": (
            "For exterior establishing views in Sacred Valley, mountains and forested slopes may "
            "form the distant regional background; Mount Samara and its luminous ring dominate "
            "appropriate east-facing Wei-clan views."
        ),
        "source_descriptions": unique(descriptions),
        "source_locations": locations,
        "applicability": (
            "Regional context, not proof that mountains are visible in a specific camera angle. "
            "Do not apply as a visible backdrop to interiors unless the scene looks outdoors."
        ),
    }


def build(root: Path) -> dict:
    data = root / "data"; output_dir = root / "output"
    books = {row["book_id"]: row for row in read_jsonl(data / "books.jsonl")}
    passages = {row["passage_id"]: row for row in read_jsonl(data / "passages.jsonl")}
    treatments = {row["chapter_id"]: row for row in read_jsonl(data / "chapter_treatments.jsonl") if row.get("status") == "success"}
    cast = {row["character_id"]: row for row in read_jsonl(output_dir / "cast.jsonl")}
    settings = {row["setting_id"]: row for row in read_jsonl(output_dir / "settings.jsonl")}
    props = {
        row["item_id"]: row
        for row in read_jsonl(output_dir / "props_wardrobe.jsonl")
        if is_portable_story_item(row)
    }

    for cid, row in cast.items():
        row["character_name_normalized"] = normalize_identifier(row["stable_label"], cid)
        row["visual_descriptions"] = unique([
            *row.get("visual_descriptions", []),
            *adjacent_source_visuals(row, passages),
        ])
        normalized = unique(
            desc.get("normalized_description") or desc.get("exact_quote", "")
            for desc in row.get("visual_descriptions", [])
        )
        row["appearance_changes"] = unique(
            f"{desc['chapter_label']}: {desc.get('normalized_description') or desc.get('exact_quote','')}"
            for desc in row.get("visual_descriptions", [])
        )
        overview = " ".join(normalized)
        progression = " ".join(row["appearance_changes"])
        row["aggregate_character_visual_description"] = (
            overview + (" Appearance progression: " + progression if progression else "")
        ).strip()
    for sid, row in settings.items():
        row["location_name_normalized"] = normalize_identifier(row["name"], sid)
        sacred_terms = ("wei", "shi", "sacred valley", "samara", "heaven's glory", "garden", "tower")
        row["macro_scenery_ids"] = (
            ["sacred-valley"] if any(term in row["name"].casefold() for term in sacred_terms) else []
        )
    for iid, row in props.items():
        row["prop_name_normalized"] = normalize_identifier(row["name"], iid)

    passage_context = {}
    extractions = {
        row["passage_id"]: row for row in read_jsonl(data / "passage_extractions.jsonl")
        if str(row.get("status") or "").startswith("success")
    }
    alias_lookup = {}
    for row in read_jsonl(data / "character_aliases.jsonl"):
        for alias in row["normalized_aliases"]:
            alias_lookup[alias] = row["canonical_name"]
    for pid, extraction in extractions.items():
        passage = passages[pid]
        local_characters = {}
        character_labels = {}
        for ordinal, character in enumerate(extraction.get("characters", []), 1):
            original = str(character.get("name_or_label") or f"unnamed character {ordinal}")
            named = bool(character.get("named"))
            label = alias_lookup.get(re.sub(r"[^a-z0-9]+", " ", original.casefold()).strip(), original) if named else original
            cid = entity_id("character", label, pid, named)
            if cid in cast:
                local_characters[cid] = character
                character_labels[cid] = label
        dialogs = attributed_dialog(passage["text"], character_labels)
        local_settings = {}
        for setting in extraction.get("settings", []):
            label = str(setting.get("name_or_label") or "unnamed setting")
            sid = entity_id("setting", label, pid, not label.casefold().startswith("unnamed"))
            if sid in settings: local_settings[sid] = setting
        local_props = {}
        for item in extraction.get("items", []):
            label = str(item.get("name_or_label") or "unnamed item")
            iid = entity_id("item", label, pid, not label.casefold().startswith("unnamed"))
            if iid in props: local_props[iid] = item
        passage_context[pid] = {
            "location": location_stub(passage, books, treatments),
            "character_ids": sorted(local_characters),
            "setting_ids": sorted(local_settings),
            "prop_ids": sorted(local_props),
            "dialogs": dialogs,
        }
    fingerprint = hashlib.sha256()
    fingerprint.update(b"service-index-v3-macro-scenery")
    for source_path in (
        data / "passages.jsonl", data / "passage_extractions.jsonl",
        data / "chapter_treatments.jsonl", output_dir / "cast.jsonl",
        output_dir / "settings.jsonl", output_dir / "props_wardrobe.jsonl",
    ):
        if source_path.is_file():
            fingerprint.update(source_path.name.encode("utf-8"))
            fingerprint.update(source_path.read_bytes())
    macro_scenery = {"sacred-valley": sacred_valley_macro(passages, books, treatments)}
    index = {
        "version": 3,
        "corpus_fingerprint": fingerprint.hexdigest(),
        "books": books,
        "passages": passages,
        "treatments": treatments,
        "characters": cast,
        "settings": settings,
        "macro_scenery": macro_scenery,
        "props": props,
        "passage_context": passage_context,
    }
    path = data / "service_index.json"
    path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"Built service index: {len(cast)} characters, {len(settings)} settings, {len(props)} props, {len(passage_context)} passages")
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(); build(args.root.resolve()); return 0


if __name__ == "__main__": raise SystemExit(main())
