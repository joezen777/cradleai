from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

from .materialize import entity_id
from .util import read_jsonl, write_jsonl_atomic


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def export(root: Path) -> None:
    passages = {row["passage_id"]: row for row in read_jsonl(root / "data" / "passages.jsonl")}
    chapters = {row["chapter_id"]: row for row in read_jsonl(root / "data" / "chapters.jsonl")}
    aliases = {}
    for row in read_jsonl(root / "data" / "character_aliases.jsonl"):
        for alias in row["normalized_aliases"]:
            aliases[alias] = row
    characters: dict[str, dict] = {}
    settings: dict[str, dict] = {}
    items: dict[str, dict] = {}
    for extraction in read_jsonl(root / "data" / "passage_extractions.jsonl"):
        if not str(extraction.get("status") or "").startswith("success"):
            continue
        passage = passages[extraction["passage_id"]]
        citation = {
            "book_id": passage["book_id"],
            "chapter_id": passage["chapter_id"],
            "chapter_number": passage["chapter_number"],
            "chapter_label": passage["chapter_label"],
            "passage_id": passage["passage_id"],
            "page_start": passage["page_start"],
            "page_end": passage["page_end"],
        }
        local_settings = {}
        for setting in extraction.get("settings", []):
            label = str(setting.get("name_or_label") or "unnamed setting").strip()
            sid = entity_id("setting", label, passage["passage_id"], not label.casefold().startswith("unnamed"))
            local_settings[norm(label)] = sid
            record = settings.setdefault(sid, {
                "setting_id": sid, "name": label,
                "setting_type": setting.get("setting_type") or "unknown",
                "chapters": {}, "passages": {}, "visual_descriptions": [],
                "character_ids": set(), "item_ids": set(),
            })
            record["chapters"][passage["chapter_id"]] = chapters[passage["chapter_id"]]
            record["passages"][passage["passage_id"]] = citation
            for description in setting.get("visual_descriptions", []):
                record["visual_descriptions"].append({**description, **citation})
        local_characters = {}
        for ordinal, character in enumerate(extraction.get("characters", []), 1):
            original = str(character.get("name_or_label") or f"unnamed character {ordinal}").strip()
            named = bool(character.get("named"))
            resolution = aliases.get(norm(original)) if named else None
            label = resolution["canonical_name"] if resolution else original
            cid = entity_id("character", label, passage["passage_id"], named)
            local_characters[norm(original)] = cid
            record = characters.setdefault(cid, {
                "character_id": cid, "canonical_name": label if named else None,
                "stable_label": label, "named": named,
                "aliases": set(resolution["aliases"] if resolution else [original]),
                "chapters": {}, "appearances": [], "visual_descriptions": [],
                "item_ids": set(),
            })
            record["chapters"][passage["chapter_id"]] = chapters[passage["chapter_id"]]
            setting_ids = [local_settings[norm(x)] for x in character.get("setting_refs", []) if norm(x) in local_settings]
            record["appearances"].append({
                **citation,
                "mentioned": bool(character.get("mentioned", True)),
                "visually_present": bool(character.get("visually_present")),
                "action_summary": character.get("action_summary") or "",
                "setting_ids": setting_ids,
            })
            for sid in setting_ids:
                settings[sid]["character_ids"].add(cid)
            for description in character.get("visual_descriptions", []):
                record["visual_descriptions"].append({**description, **citation})
        for item in extraction.get("items", []):
            label = str(item.get("name_or_label") or "unnamed item").strip()
            iid = entity_id("item", label, passage["passage_id"], not label.casefold().startswith("unnamed"))
            record = items.setdefault(iid, {
                "item_id": iid, "name": label,
                "item_type": item.get("item_type") or "prop",
                "chapters": {}, "passages": {}, "visual_descriptions": [],
                "character_links": [], "setting_ids": set(),
            })
            record["chapters"][passage["chapter_id"]] = chapters[passage["chapter_id"]]
            record["passages"][passage["passage_id"]] = citation
            for description in item.get("visual_descriptions", []):
                record["visual_descriptions"].append({**description, **citation})
            for ref in item.get("setting_refs", []):
                sid = local_settings.get(norm(str(ref)))
                if sid:
                    record["setting_ids"].add(sid)
                    settings[sid]["item_ids"].add(iid)
            cref = norm(str(item.get("character_ref") or ""))
            cid = local_characters.get(cref)
            if cid:
                link = {"character_id": cid, "relationship": item.get("relationship") or "none", **citation}
                record["character_links"].append(link)
                characters[cid]["item_ids"].add(iid)
    def finalize(record: dict) -> dict:
        output = {}
        for key, value in record.items():
            if isinstance(value, set):
                output[key] = sorted(value)
            elif key in {"chapters", "passages"}:
                output[key] = [value[item] for item in sorted(value)]
            else:
                output[key] = value
        return output
    destination = root / "output"
    write_jsonl_atomic(destination / "cast.jsonl", (finalize(characters[key]) for key in sorted(characters)))
    write_jsonl_atomic(destination / "settings.jsonl", (finalize(settings[key]) for key in sorted(settings)))
    write_jsonl_atomic(destination / "props_wardrobe.jsonl", (finalize(items[key]) for key in sorted(items)))
    write_jsonl_atomic(destination / "chapter_treatments.jsonl", read_jsonl(root / "data" / "chapter_treatments.jsonl"))
    print(f"Exported {len(characters)} cast entries, {len(settings)} settings, and {len(items)} props/wardrobe entries")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    export(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
