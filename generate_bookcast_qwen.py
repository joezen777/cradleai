#!/usr/bin/env python3
"""Build a resumable, deduplicated two-book portrait cast with Qwen + lore MCP."""

from __future__ import annotations

import argparse
import gc
import json
import re
from pathlib import Path
from typing import Any

from qwen_media_chat import (
    DEFAULT_LORE_MCP_URL,
    call_character_mcp,
    load_model,
)
from bookcast_evidence import descriptive_phrases, split_sentences, true_first_appearance
from bookcast_fields import compose_portrait, normalize_for_dedup, normalize_trait


ROOT = Path(__file__).resolve().parent
DEFAULT_INDEX = ROOT / "lore_graph" / "data" / "service_index.json"
DEFAULT_OUTPUT = ROOT / "bookcast.jsonl"

FIGHT_WORDS = re.compile(
    r"\b(fight|attack|strike|kick|punch|slash|stab|cut|sword|spear|blade|"
    r"technique|madra|foxfire|palm|kill|battle|duel|block|dodge|deflect|"
    r"remnant|enforcer|forg(?:e|ed|er)|ruler|striker)\b",
    re.IGNORECASE,
)

NON_CHARACTER_TERMS = re.compile(
    r"\b(arm|badge|blood|bone|cradle|finger|fingers|foxfire|goldsign|"
    r"madra|mantle|mountain|path|rib|section|stage|technique|tomb|venom|swirls?|"
    r"village|valley|wound|eye|legs?)\b",
    re.IGNORECASE,
)
GROUP_TERMS = re.compile(
    r"\b(adults|clan|clansmen|couple|family|families|crowd|disciples|elders|"
    r"enforcers|fishers|forgers|golds|jades|miners|parents|prisoners|remnants|"
    r"rulers|sacred artists|sandvipers|strikers|subordinates|warriors)\b",
    re.IGNORECASE,
)
SPECIFIC_NONHUMANS = {
    "drudge", "elder-whisper", "fisher-s-remnant", "presence", "razor",
    "remnant", "snowfox", "suriel-s-ghost", "sylvan", "sylvan-riverseed",
}
NON_CHARACTER_EXACT = {
    "arelius-family", "broken-fingers", "broken-legs", "children", "copper",
    "copper-stage", "cracked-rib", "cradle", "cradle-suriel", "disciple",
    "disciples", "dog", "dogs", "dreadgods", "elder", "enforcer-technique",
    "enforcers", "father", "fisher", "fishers", "forging-scales", "foxfire",
    "gold", "goldsign", "he", "his-daughter", "his-son", "his-wife", "hive",
    "human-madra", "iron-disciples", "iron-stage", "jade", "jade-stage",
    "jades", "jointed-purple-madra", "mantle", "master", "mother",
    "mothers-and-fathers", "new-voice", "path-of-twin-stars", "patriarch",
    "prisoners", "remnants", "ruler", "rulers", "sacred-artists",
    "sacred-valley", "sandviper", "sandvipers", "self", "she",
    "swollen-eye", "sword-madra", "underlord", "unsouled", "venom",
    "vivid-green-madra", "yoma-mountain", "kazan", "li", "mount-venture",
    "samara", "unspecified-bf53d311", "wei", "iron-e967178e", "iron-65c5bb3a",
}

# Extraction created separate nodes for several explicit aliases. This map is
# intentionally conservative: ambiguous generic labels remain separate.
KNOWN_IDENTITIES = {
    "eithan": "eithan-arelius", "eithan-arelius": "eithan-arelius",
    "unnamed-eithan": "eithan-arelius",
    "yerin": "yerin", "unnamed-yerin": "yerin",
    "yerin-disciple-of-the-sword-sage": "yerin",
    "lindon": "wei-shi-lindon", "unsouled-lindon": "wei-shi-lindon",
    "lindon-arelius": "wei-shi-lindon",
    "gesha": "fisher-gesha", "fisher-gesha": "fisher-gesha",
    "the-old-soulsmith": "fisher-gesha", "the-old-woman": "fisher-gesha",
    "ragahn": "fisher-ragahn", "fisher-ragahn": "fisher-ragahn",
    "fisher-raghn": "fisher-ragahn",
    "jaran": "wei-shi-jaran", "shi-jaran": "wei-shi-jaran",
    "wei-shi-jaran": "wei-shi-jaran", "lindon-s-father": "wei-shi-jaran",
    "kelsa": "wei-shi-kelsa", "wei-shi-kelsa": "wei-shi-kelsa",
    "seisha": "wei-shi-seisha", "wei-shi-seisha": "wei-shi-seisha",
    "lindon-s-mother": "wei-shi-seisha",
    "keth": "wei-mon-keth", "mon-keth": "wei-mon-keth",
    "wei-mon-keth": "wei-mon-keth", "mon-family-head": "wei-mon-keth",
    "teris": "wei-mon-teris", "wei-mon-teris": "wei-mon-teris",
    "eri": "wei-mon-eri", "mon-eri": "wei-mon-eri",
    "wei-mon-eri": "wei-mon-eri",
    "sairus": "wei-jin-sairus", "patriarch-sairus": "wei-jin-sairus",
    "wei-jin-sairus": "wei-jin-sairus", "wei-patriarch": "wei-jin-sairus",
    "patriarch-of-the-wei-clan": "wei-jin-sairus",
    "markuth": "li-markuth", "li-markuth": "li-markuth",
    "anses": "elder-anses", "elder-anses": "elder-anses",
    "sword-sage": "sword-sage", "sage-of-the-endless-sword": "sword-sage",
    "elder-whisper": "elder-whisper", "whisper": "elder-whisper",
    "kral": "kral", "unnamed-kral": "kral",
    "jai-long": "jai-long", "unnamed-jai-long": "jai-long",
    "masked-stranger": "jai-long",
    "deret-ee864c00": "kazan-ma-deret", "kazan-ma-deret": "kazan-ma-deret",
    "elder-whitehall-ddf965a7": "whitehall", "whitehall": "whitehall",
    "yerin-70fb0102": "yerin", "yerin-3b0ad233": "yerin",
    "eithan-41891b3a": "eithan-arelius",
    "lindon-s-mother-9b4216e8": "wei-shi-seisha",
    "unnamed-wei-patriarch": "wei-jin-sairus",
    "drudge": "wei-shi-seisha-drudge",
    "her-drudge-ee8caba6": "wei-shi-seisha-drudge",
    "drudge-f703f468": "wei-shi-seisha-drudge",
    "bandit": "the-bandit", "the-bandit": "the-bandit",
    "sage": "sword-sage",
}

PROMPT = """
You are creating a definitive portrait cast catalog for Will Wight's Unsouled
and Soulsmith. Use only the supplied source-grounded lore dossier.

First decide whether this node is a real cast member: an individual person,
specific creature, specific spirit/Remnant, named Presence, or individually
depicted construct. Exclude body parts, advancement stages, techniques,
locations, clans/families/groups, substances, generic plural crowds, and other
extraction mistakes. A distinct unnamed individual is valid.

Return exactly one JSON object and no Markdown. Required keys:
is_cast_member (boolean), canonical_name, identity_key, entity_type,
species_or_object_type, portrait_description, face, skin_tone, eyes, hair,
build, posture, emotion, action, fighting_move, clothing, wardrobe,
accessories, color_information, evidence_notes, confidence.

portrait_description must be a cohesive 100-180 word, visually actionable
portrait description. Put the character in their best-supported signature
combat move when the dossier supports one; otherwise use a cited scene action
and emotion. Describe only supported visual facts. For every absent trait use
"not specified in the cited text" rather than inventing it. Do not infer skin,
eye, or hair color from ethnicity or genre. Preserve uncertainty. Accessories
must include badges, weapons, Goldsigns, tools, jewelry, masks, packs, or
constructs when supported. color_information must distinguish cited colors
from unspecified colors. evidence_notes must name the cited book, chapter,
pages, and passage IDs used. confidence is high, medium, or low.
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--progress", type=Path)
    parser.add_argument("--mcp-url", default=DEFAULT_LORE_MCP_URL)
    parser.add_argument("--model", default="qwen3-14b")
    parser.add_argument("--max-new-tokens", type=int, default=850)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start-after")
    return parser.parse_args()


def identity_key(row: dict[str, Any]) -> str:
    normalized = row.get("character_name_normalized") or row.get("character_id", "")
    return KNOWN_IDENTITIES.get(normalized, normalized)


def obvious_non_character(row: dict[str, Any]) -> bool:
    normalized = row.get("character_name_normalized") or ""
    if normalized in NON_CHARACTER_EXACT:
        return True
    if normalized in SPECIFIC_NONHUMANS:
        return False
    name = str(row.get("canonical_name") or row.get("stable_label") or normalized)
    return bool(NON_CHARACTER_TERMS.search(name) or GROUP_TERMS.search(name))


def choose_actions(row: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    for appearance in row.get("appearances", []):
        summary = str(appearance.get("action_summary") or "").strip()
        if summary:
            actions.append({
                "passage_id": appearance.get("passage_id"),
                "pages": [appearance.get("page_start"), appearance.get("page_end")],
                "action": summary,
                "combat_relevance": bool(FIGHT_WORDS.search(summary)),
            })
    actions.sort(key=lambda value: value["combat_relevance"], reverse=True)
    return actions[:10]


def compact_dossier(source: dict[str, Any], mcp_rows: list[dict[str, Any]]) -> dict[str, Any]:
    mcp = mcp_rows[0] if mcp_rows else {}
    first = mcp.get("first_mentioned") or {}
    visual = []
    for value in source.get("visual_descriptions", [])[:30]:
        quote = value.get("exact_quote")
        if quote:
            visual.append({"passage_id": value.get("passage_id"), "quote": quote})
    return {
        "source_character_id": source.get("character_id"),
        "catalog_name": source.get("canonical_name") or source.get("stable_label"),
        "normalized_name": source.get("character_name_normalized"),
        "aliases": source.get("aliases", []),
        "named": source.get("named"),
        "books_and_chapters": source.get("chapters", []),
        "first_mention": {
            key: first.get(key) for key in (
                "book_title", "chapter_label", "page_start", "page_end", "passage_id"
            ) if first.get(key) is not None
        },
        "first_mention_excerpt": str(first.get("surrounding_paragraph") or "")[:4000],
        "exact_visual_quotes": visual,
        "mcp_visual_quotes": mcp.get("visual_description_source", [])[:20],
        "appearance_progression": mcp.get("appearance_changes", [])[:20],
        "aggregate_description": str(
            mcp.get("aggregate_character_visual_description") or ""
        )[:5000],
        "scene_actions": choose_actions(source),
        "linked_item_ids": source.get("item_ids", []),
    }


def character_scoped_evidence(dossier: dict[str, Any]) -> str:
    """Evidence already tied to this specific character: their own visual
    quotes and scene actions. Deliberately excludes first_mention_excerpt,
    which is the raw multi-paragraph passage blob and can run on into other
    characters' scenes and colors within the same passage (e.g. one child's
    badge color in a scene describing several children being tested).
    """
    pieces = [value.get("quote", "") for value in dossier.get("exact_visual_quotes", [])]
    pieces.extend(dossier.get("mcp_visual_quotes", []))
    pieces.extend(value.get("action", "") for value in dossier.get("scene_actions", []))
    return re.sub(r"\s+", " ", " ".join(str(value) for value in pieces)).strip()


def supported_trait(value: Any, evidence: str, anchors: tuple[str, ...]) -> str:
    """Return `value` only if it is corroborated near an anchor word in
    character-scoped evidence; otherwise "" (unknown, not a filler sentence).
    """
    value = normalize_trait(value)
    if not value:
        return ""
    folded = evidence.casefold()
    windows = []
    for anchor in anchors:
        start = 0
        while (position := folded.find(anchor, start)) >= 0:
            windows.append(folded[max(0, position - 200):position + len(anchor) + 200])
            start = position + len(anchor)
    if not windows:
        return ""
    ignored = {
        "and", "the", "with", "not", "specified", "cited", "text", "simple",
        "suitable", "functional", "person", "individual", "medium",
    }
    value_tokens = {
        token for token in re.findall(r"[a-z]+", value.casefold())
        if len(token) > 2 and token not in ignored
    }
    if value_tokens and not any(token in " ".join(windows) for token in value_tokens):
        return ""
    return value


# Anchors widened to cover non-human subjects: a snowfox's "fur" or a
# construct's "hide" carries the same role a human's "hair" does, but the
# original anchor lists only had human vocabulary, so real cited description
# ("five-tailed", "soundless, scentless") was being discarded outright.
_HAIR_ANCHORS = ("hair", "beard", "eyebrow", "fur", "pelt", "feather", "mane")
_SKIN_ANCHORS = ("skin", "complexion", "hide", "scale", "scales", "bark")
_BUILD_ANCHORS = (
    "build", "shoulder", "muscular", "slender", "lithe", "tall", "short",
    "broad", "size", "massive", "huge", "small", "tiny", "towering", "height",
    "length", "wide", "narrow",
)
_FACE_ANCHORS = ("face", "scar", "beard", "eye", "muzzle", "snout")
_CLOTHING_ANCHORS = (
    "robe", "clothes", "clothing", "wear", "wore", "dressed", "shirt",
    "coat", "cloak", "jacket", "armor", "mantle",
)
_EMOTION_ANCHORS = (
    "expression", "emotion", "smile", "scowl", "glare", "fear", "angry",
    "calm", "unperturbed", "hope", "grief", "anxious", "resolve",
)
_POSTURE_ANCHORS = (
    "kneel", "stand", "crouch", "sit", "lean", "wait", "hover", "float",
    "perch", "poised", "stillness", "motionless",
)

_COLOR_WORDS = (
    "black", "white", "gray", "grey", "brown", "red", "orange", "yellow",
    "green", "blue", "purple", "pink", "gold", "golden", "silver", "pale",
    "colorless", "crimson", "scarlet", "violet", "emerald", "amber", "ivory",
    "cyan", "magenta", "turquoise", "indigo",
    # Deliberately NOT "copper"/"jade": both are sacred-arts advancement
    # stage names used constantly in this corpus (Copper, Iron, Jade, Gold),
    # and would false-positive as color citations almost everywhere.
)
_COLOR_PATTERN = re.compile(rf"\b({'|'.join(_COLOR_WORDS)})\b", re.IGNORECASE)
_CLAUSE_SPLIT = re.compile(r"[,;:]|—|–")


def cited_colors(character_evidence: str, limit: int = 3) -> str:
    """Short phrases binding each cited color to its surrounding context,
    scanned only over character-scoped evidence so a color from a different
    character's paragraph in the same passage can never attach here.

    Splits on clause boundaries rather than a fixed character window — a
    character window can straddle a comma and glue two unrelated clauses
    together into a grammatical mess. A long clause still gets trimmed to a
    short word window around the color so the result stays brief. Capped low
    (default 3): prolific characters accumulate quotes across the whole
    series, and a visual_descriptions quote tagged to one character can still
    describe someone else standing in the same scene, so preferring the
    first, closest-to-introduction hits is safer than exhaustive collection.
    """
    phrases: list[str] = []
    seen: set[str] = set()
    for sentence in split_sentences(character_evidence):
        for clause in _CLAUSE_SPLIT.split(sentence):
            clause = clause.strip().rstrip(".")
            match = _COLOR_PATTERN.search(clause)
            if not clause or not match:
                continue
            words = clause.split()
            if len(words) > 9:
                center = len(clause[:match.start()].split())
                clause = " ".join(words[max(0, center - 3):center + 4])
            key = re.sub(r"[^a-z0-9 ]", "", clause.casefold())
            if not clause or key in seen:
                continue
            seen.add(key)
            phrases.append(clause)
            if len(phrases) >= limit:
                break
        if len(phrases) >= limit:
            break
    # "; " rather than ", " — each phrase is a clause fragment without its own
    # terminal punctuation, so comma-joining several reads as one run-on
    # sentence. A semicolon list makes clear these are separate citations.
    return "; ".join(phrases)


def sanitize_result(result: dict[str, Any], source: dict[str, Any],
                    dossier: dict[str, Any]) -> dict[str, Any]:
    evidence = character_scoped_evidence(dossier)
    result["canonical_name"] = source.get("canonical_name") or source.get("stable_label")
    result["skin_tone"] = supported_trait(result.get("skin_tone"), evidence, _SKIN_ANCHORS)
    result["eyes"] = supported_trait(result.get("eyes"), evidence, (" eye", "eyes"))
    result["hair"] = supported_trait(result.get("hair"), evidence, _HAIR_ANCHORS)
    result["face"] = supported_trait(result.get("face"), evidence, _FACE_ANCHORS)
    result["build"] = supported_trait(result.get("build"), evidence, _BUILD_ANCHORS)
    result["clothing"] = supported_trait(result.get("clothing"), evidence, _CLOTHING_ANCHORS)
    result.pop("wardrobe", None)

    actions = dossier.get("scene_actions", [])
    result["action"] = actions[0]["action"] if actions else ""
    # posture is body configuration, not "whatever action was cited" — validate
    # it independently instead of copying action, which duplicated the same
    # text in 128/133 of the previous generation's records.
    result["posture"] = supported_trait(result.get("posture"), evidence, _POSTURE_ANCHORS)
    result["emotion"] = supported_trait(result.get("emotion"), evidence, _EMOTION_ANCHORS)

    combat = next((value["action"] for value in actions if value["combat_relevance"]), None)
    fighting_move = combat or ""
    # Don't emit a fighting move that just restates the action/posture text.
    if fighting_move and normalize_for_dedup(fighting_move) in (
        normalize_for_dedup(result["action"]), normalize_for_dedup(result["posture"])
    ):
        fighting_move = ""
    result["fighting_move"] = fighting_move

    items = [value.removeprefix("item:").replace("-", " ") for value in dossier.get("linked_item_ids", [])]
    result["accessories"] = ", ".join(items) if items else ""
    result["color_information"] = cited_colors(evidence)

    key = identity_key(source)
    recognized_nonhuman = key in SPECIFIC_NONHUMANS or key.endswith("remnant")
    model_species = normalize_trait(result.get("species_or_object_type"))
    # Trust a model-supplied nonhuman species ("snowfox", "sacred beast")
    # rather than blindly forcing "individual person" — that override used to
    # apply even when the model had already correctly classified a literal
    # animal, leaving contradictory records (species "snowfox", entity_type
    # "individual person").
    model_stated_nonhuman = bool(model_species) and model_species.casefold() not in {"human", "unspecified"}
    if not recognized_nonhuman and not model_stated_nonhuman:
        result["entity_type"] = "individual person"
        result["species_or_object_type"] = model_species or "human"

    # Salvage: real visual sentences the trait-by-trait validation above
    # couldn't attach to a specific field (wrong vocabulary, awkward phrasing)
    # are not lost — they ride along for Track C's enrichment interview and
    # for direct display via Track A's descriptive_phrases on the card.
    anchor_pid = true_first_appearance(source)
    result["unassigned_visual_facts"] = (
        descriptive_phrases(source, anchor_pid) if anchor_pid else []
    )

    result["portrait_description"] = compose_portrait(result)
    return result


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Qwen returned no JSON object")
    return json.loads(text[start:end + 1])


def generate(model: Any, processor: Any, spec: dict[str, Any], prompt: str,
             max_new_tokens: int, torch: Any) -> str:
    messages = [
        {"role": "system", "content": "You produce conservative, source-cited JSON."},
        {"role": "user", "content": prompt},
    ]
    if spec["family"] == "text":
        inputs = processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors="pt",
        ).to(model.device)
    else:
        rendered = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = processor(text=[rendered], padding=True, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    continuation = output[:, inputs.input_ids.shape[1]:]
    return processor.batch_decode(continuation, skip_special_tokens=True)[0].strip()


def load_completed(path: Path) -> tuple[set[str], set[str]]:
    source_ids, identities = set(), set()
    if not path.is_file():
        return source_ids, identities
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid existing JSONL line {number}: {exc}") from exc
            source_ids.update(row.get("source_character_ids", []))
            if row.get("identity_key"):
                identities.add(row["identity_key"])
    return source_ids, identities


def load_progress(path: Path) -> set[str]:
    completed = set()
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    completed.add(json.loads(line)["source_character_id"])
    return completed


def main() -> int:
    args = parse_args()
    progress_path = args.progress or args.output.with_suffix(".progress.jsonl")
    index = json.loads(args.index.read_text(encoding="utf-8"))
    candidates = list(index["characters"].values())
    candidates.sort(key=lambda row: (
        0 if row.get("named") else 1,
        str(row.get("canonical_name") or row.get("character_name_normalized")),
    ))
    source_ids, completed_identities = load_completed(args.output)
    source_ids.update(load_progress(progress_path))
    selected, seen = [], set(completed_identities)
    started = args.start_after is None
    for row in candidates:
        if not started:
            started = row.get("character_name_normalized") == args.start_after
            continue
        sid = row.get("character_id")
        key = identity_key(row)
        if sid in source_ids or key in seen:
            continue
        if obvious_non_character(row):
            continue
        seen.add(key)
        selected.append(row)
        if args.limit and len(selected) >= args.limit:
            break

    if not selected:
        print("No unfinished character candidates.", flush=True)
        return 0

    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required by the current qwen_media_chat model loader")
    model = processor = None
    try:
        model, processor, spec = load_model(args.model, torch, no_4bit=False)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("a", encoding="utf-8", buffering=1) as destination, \
                progress_path.open("a", encoding="utf-8", buffering=1) as progress:
            for ordinal, source in enumerate(selected, 1):
                normalized = source["character_name_normalized"]
                print(f"[{ordinal}/{len(selected)}] {normalized}: querying MCP", flush=True)
                try:
                    mcp_rows = call_character_mcp(args.mcp_url, normalized, 1)
                    dossier = compact_dossier(source, mcp_rows)
                    prompt = f"{PROMPT}\n\nLORE DOSSIER:\n{json.dumps(dossier, ensure_ascii=False)}"
                    raw = generate(
                        model, processor, spec, prompt, args.max_new_tokens, torch
                    )
                    result = extract_json(raw)
                    if not result.get("is_cast_member"):
                        print(f"[{ordinal}/{len(selected)}] {normalized}: excluded", flush=True)
                        progress.write(json.dumps({
                            "source_character_id": source["character_id"],
                            "normalized_name": normalized,
                            "status": "excluded",
                        }) + "\n")
                        continue
                    result = sanitize_result(result, source, dossier)
                    result["identity_key"] = identity_key(source)
                    result["source_character_ids"] = [source["character_id"]]
                    result["source_normalized_names"] = [normalized]
                    result["books"] = sorted({
                        chapter.get("book_id") for chapter in source.get("chapters", [])
                        if chapter.get("book_id")
                    })
                    result["qwen_model"] = args.model
                    result["lore_transport"] = "cradle-lore MCP"
                    destination.write(json.dumps(result, ensure_ascii=False) + "\n")
                    destination.flush()
                    progress.write(json.dumps({
                        "source_character_id": source["character_id"],
                        "normalized_name": normalized,
                        "status": "written",
                        "identity_key": result["identity_key"],
                    }) + "\n")
                    print(f"[{ordinal}/{len(selected)}] {normalized}: written", flush=True)
                except Exception as exc:
                    print(
                        f"[{ordinal}/{len(selected)}] {normalized}: ERROR "
                        f"{type(exc).__name__}: {exc}", flush=True,
                    )
                finally:
                    gc.collect()
                    torch.cuda.empty_cache()
    finally:
        if model is not None:
            try:
                model.to("cpu")
            except Exception:
                pass
        del model, processor
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
