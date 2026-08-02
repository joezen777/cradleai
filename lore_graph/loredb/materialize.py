from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .graph_store import GraphStore
from .util import read_jsonl


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "unknown"


def entity_id(kind: str, label: str, passage_id: str, named: bool = True) -> str:
    scope = "" if named else passage_id + ":"
    return f"{kind}:{scope}{slug(label)}"


def digest_id(prefix: str, *parts: str) -> str:
    value = "\x1f".join(parts)
    return f"{prefix}:{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def q(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def materialize(root: Path) -> None:
    store = GraphStore(root)
    store.initialize()
    # Derived graph nodes are reproducible from JSONL. Clear them before a
    # rebuild so corrected/retried extractions cannot leave stale entities or
    # relationships behind. Source Book/Chapter/Passage nodes and indexes stay.
    for label in ("Description", "Appearance", "Character", "Item", "Setting"):
        store.conn.execute(f"MATCH (n:{label}) DETACH DELETE n")
    extractions = [
        row for row in read_jsonl(root / "data" / "passage_extractions.jsonl")
        if str(row.get("status") or "").startswith("success")
    ]
    passages = {row["passage_id"]: row for row in read_jsonl(root / "data" / "passages.jsonl")}
    alias_lookup = {}
    for resolution in read_jsonl(root / "data" / "character_aliases.jsonl"):
        for alias in resolution.get("normalized_aliases", []):
            alias_lookup[alias] = resolution["canonical_name"]
    chapter_mentions: dict[tuple[str, str], int] = Counter()
    created_characters: set[str] = set()
    created_settings: set[str] = set()
    created_items: set[str] = set()
    created_appearances: set[str] = set()
    created_descriptions: set[str] = set()
    for extraction_index, extraction in enumerate(extractions, 1):
        passage_id = extraction["passage_id"]
        passage = passages[passage_id]
        settings: dict[str, str] = {}
        for setting in extraction.get("settings", []):
            label = str(setting.get("name_or_label") or "unnamed setting").strip()
            sid = entity_id("setting", label, passage_id, named=not label.casefold().startswith("unnamed"))
            settings[label.casefold()] = sid
            if sid not in created_settings:
                store.conn.execute(
                    """CREATE (n:Setting {setting_id:$id, canonical_name:$name,
                    setting_type:$type, notes:$notes})""",
                    {"id": sid, "name": label, "type": str(setting.get("setting_type") or "unknown"), "notes": "none"},
                )
                created_settings.add(sid)
            add_descriptions(store, passage_id, "setting", sid, setting.get("visual_descriptions", []), created_descriptions)
        for ordinal, character in enumerate(extraction.get("characters", []), 1):
            label = str(character.get("name_or_label") or f"unnamed character {ordinal}").strip()
            named = bool(character.get("named"))
            if named:
                label = alias_lookup.get(
                    re.sub(r"[^a-z0-9]+", " ", label.casefold()).strip(), label
                )
            cid = entity_id("character", label, passage_id, named=named)
            aliases = [str(x) for x in character.get("aliases_seen", []) if str(x).strip()]
            if cid not in created_characters:
                store.conn.execute(
                    """CREATE (n:Character {character_id:$id,
                    canonical_name:$name, stable_label:$label, named:$named,
                    aliases:$aliases, confidence:$confidence, notes:$notes})""",
                    {"id": cid, "name": label if named else label, "label": label, "named": named,
                     "aliases": " | ".join(aliases) or "none", "confidence": "source-extracted", "notes": "none"},
                )
                created_characters.add(cid)
            chapter_mentions[(cid, passage["chapter_id"])] += 1
            appearance_id = digest_id("appearance", cid, passage_id)
            if appearance_id not in created_appearances:
                store.conn.execute(
                    """CREATE (a:Appearance {appearance_id:$id, ordinal:$ordinal,
                    visually_present:$visible, action_summary:$action})""",
                    {"id": appearance_id, "ordinal": ordinal, "visible": bool(character.get("visually_present")),
                     "action": str(character.get("action_summary") or "none")},
                )
                created_appearances.add(appearance_id)
            store.conn.execute(
                """MATCH (c:Character {character_id:$cid}), (a:Appearance {appearance_id:$aid}),
                (p:Passage {passage_id:$pid}) MERGE (c)-[:CharacterAppearance]->(a)
                MERGE (a)-[:AppearancePassage]->(p)""",
                {"cid": cid, "aid": appearance_id, "pid": passage_id},
            )
            for setting_ref in character.get("setting_refs", []):
                sid = settings.get(str(setting_ref).casefold())
                if sid:
                    store.conn.execute(
                        """MATCH (a:Appearance {appearance_id:$aid}), (s:Setting {setting_id:$sid})
                        MERGE (a)-[:AppearanceSetting]->(s)""",
                        {"aid": appearance_id, "sid": sid},
                    )
            add_descriptions(store, passage_id, "character", cid, character.get("visual_descriptions", []), created_descriptions)
        for item in extraction.get("items", []):
            label = str(item.get("name_or_label") or "unnamed item").strip()
            iid = entity_id("item", label, passage_id, named=not label.casefold().startswith("unnamed"))
            if iid not in created_items:
                store.conn.execute(
                    """CREATE (n:Item {item_id:$id, canonical_name:$name,
                    item_type:$type, notes:$notes})""",
                    {"id": iid, "name": label, "type": str(item.get("item_type") or "prop"), "notes": "none"},
                )
                created_items.add(iid)
            store.conn.execute(
                """MATCH (i:Item {item_id:$iid}), (c:Chapter {chapter_id:$chapter})
                MERGE (i)-[:ItemMentionedIn]->(c)""",
                {"iid": iid, "chapter": passage["chapter_id"]},
            )
            add_descriptions(store, passage_id, "item", iid, item.get("visual_descriptions", []), created_descriptions)
            for setting_ref in item.get("setting_refs", []):
                sid = settings.get(str(setting_ref).casefold())
                if sid:
                    store.conn.execute(
                        """MATCH (i:Item {item_id:$iid}), (s:Setting {setting_id:$sid})
                        MERGE (i)-[:ItemFoundAt]->(s)""", {"iid": iid, "sid": sid}
                    )
            cref = str(item.get("character_ref") or "").strip()
            if cref:
                character_named = not cref.casefold().startswith("unnamed")
                resolved_cref = cref
                if character_named:
                    resolved_cref = alias_lookup.get(
                        re.sub(r"[^a-z0-9]+", " ", cref.casefold()).strip(), cref
                    )
                cid = entity_id("character", resolved_cref, passage_id, named=character_named)
                store.conn.execute(
                    """MATCH (c:Character {character_id:$cid}), (i:Item {item_id:$iid})
                    MERGE (c)-[r:CharacterItem {passage_id:$pid}]->(i)
                    SET r.relationship=$relationship""",
                    {"cid": cid, "iid": iid, "pid": passage_id,
                     "relationship": str(item.get("relationship") or "none")},
                )
        if extraction_index % 25 == 0:
            print(f"Materialized {extraction_index}/{len(extractions)} passages", flush=True)
            store.close()
            store = GraphStore(root)
    for (cid, chapter_id), count in chapter_mentions.items():
        store.conn.execute(
            """MATCH (c:Character {character_id:$cid}), (h:Chapter {chapter_id:$chapter})
            MERGE (c)-[r:MentionedIn]->(h) SET r.mention_count=$count""",
            {"cid": cid, "chapter": chapter_id, "count": count},
        )
    for treatment in read_jsonl(root / "data" / "chapter_treatments.jsonl"):
        if treatment.get("status") == "success":
            store.conn.execute(
                """MATCH (c:Chapter {chapter_id:$id}) SET c.treatment=$text,
                c.treatment_status='success'""",
                {"id": treatment["chapter_id"], "text": treatment["treatment"]},
            )
    store.export_counts()
    store.close()
    print(f"Materialized {len(extractions)}/{len(extractions)} passages", flush=True)


def add_descriptions(
    store: GraphStore, passage_id: str, kind: str, target_id: str,
    descriptions: list[dict], created_descriptions: set[str],
) -> None:
    label = {"character": "Character", "setting": "Setting", "item": "Item"}[kind]
    rel = {"character": "DescribesCharacter", "setting": "DescribesSetting", "item": "DescribesItem"}[kind]
    key = {"character": "character_id", "setting": "setting_id", "item": "item_id"}[kind]
    for description in descriptions:
        quote = str(description.get("exact_quote") or "").strip()
        normalized = str(description.get("normalized_description") or quote).strip()
        did = digest_id("description", passage_id, target_id, quote, normalized)
        if did not in created_descriptions:
            store.conn.execute(
                """CREATE (d:Description {description_id:$id, description_type:$type,
                exact_quote:$quote, normalized_description:$normalized,
                confidence:'direct-source'})""",
                {"id": did, "type": kind, "quote": quote, "normalized": normalized},
            )
            created_descriptions.add(did)
        store.conn.execute(
            f"""MATCH (d:Description {{description_id:$did}}),
            (p:Passage {{passage_id:$pid}}), (n:{label} {{{key}:$target}})
            MERGE (d)-[:DescriptionSource]->(p) MERGE (d)-[:{rel}]->(n)""",
            {"did": did, "pid": passage_id, "target": target_id},
        )
