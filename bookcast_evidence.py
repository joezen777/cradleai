#!/usr/bin/env python3
"""Shared evidence resolution helpers for the book cast pipeline.

Sentence segmentation, first-mention extraction, nearby descriptive phrase
selection, and passage-neighborhood expansion, all operating directly on
``lore_graph/data/service_index.json`` so no model or MCP call is required.
"""

from __future__ import annotations

import re
from typing import Any

from bookcast_fields import normalize_for_dedup as _normalize_for_dedup

ROOT_INDEX_KEYS = ("characters", "passage_context")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])[\"'”’]?\s+(?=[A-Z“\"'\[])")
_PASSAGE_ID = re.compile(r"^(?P<book>[a-z0-9]+):chapter:(?P<chapter>\d+):passage:(?P<passage>\d+)$")

_PLOT_ONLY = re.compile(
    r"\b(remember|remembers|remembered|believe[sd]?|hope[sd]?|think[s]?|thought|"
    r"wonder(?:s|ed)?|realize[sd]?|decide[sd]?|plan(?:s|ned)?|feel[s]?\s+that|"
    r"understood|understand[s]?)\b",
    re.IGNORECASE,
)

_VISUAL_SIGNAL = re.compile(
    r"\b(fur|fir|hair|beard|eye|eyes|skin|face|scar|robe|cloak|coat|shirt|dress|"
    r"jacket|badge|sword|blade|dagger|tail|claw|wing|horn|scale|tall|short|"
    r"broad|slender|lithe|muscular|massive|huge|tiny|small|size|build|"
    r"colou?r|black|white|gray|grey|brown|red|orange|yellow|green|blue|"
    r"purple|pink|gold|golden|silver|pale|crimson|scarlet|hood|mask|pack|"
    r"posture|kneel|stand|crouch|sit|lean|wear|wore|wearing|dressed|"
    r"complexion|freckle|wrinkle|muscle|shoulder)\b",
    re.IGNORECASE,
)

# Some corpus passages jump mid-blob into an unrelated scene/POV (e.g. a
# "simulation report" framing device that cuts away to a different
# character's storyline). Real scene breaks in this corpus are marked by an
# ALL-CAPS lead-in ("DIVERGENCE DETECTED:") or a "***" divider — not by
# ordinary paragraph breaks, which this text uses constantly for pacing.
_SCENE_BREAK_MARKER = re.compile(r"^(\*{2,}|[A-Z][A-Z0-9 ']{3,}:)")

UNKNOWN_LEGACY = "not specified in the cited text"


_LEADING_SECTION_MARKER = re.compile(r"^\*{2,}\s*(?:Iteration\s+\d+\s*:\s*)?", re.IGNORECASE)


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences, tolerating curly quotes and abbreviations."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []
    pieces = _SENTENCE_SPLIT.split(text)
    # Some passages open with a typographic section label ("*** Iteration
    # 110: ") glued to the first sentence by paragraph-joining upstream. That
    # is a section header, not book prose — strip it, but only the marker
    # itself, never any actual sentence text.
    pieces = [_LEADING_SECTION_MARKER.sub("", p).strip() for p in pieces]
    return [p for p in pieces if p]


def first_paragraph_block(surrounding_paragraph: str) -> str:
    """The stored surrounding_paragraph can run on past an explicit scene
    break into an unrelated scene's characters and colors. Ordinary paragraph
    breaks do not indicate a scene change in this corpus (short paragraphs are
    used constantly for pacing) — only an explicit break marker does. Keep
    every paragraph up to the first such marker.

    Some passages (interlude-style "*** Iteration N: Name" chapters) open
    with what looks like a break marker as their very first line — that is
    the passage's own framing, not a jump away from it, so the first block is
    always kept regardless, and only a marker in a later block ends the run.
    """
    text = (surrounding_paragraph or "").strip()
    if not text:
        return ""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if not blocks:
        return ""
    kept = [blocks[0]]
    for block in blocks[1:]:
        if _SCENE_BREAK_MARKER.match(block):
            break
        kept.append(block)
    return "\n\n".join(kept).strip()


# Aliases in the index are extraction artifacts and include generic role
# descriptions ("unnamed Wei clan elder", "unnamed young man", "family Shi")
# rather than names. Strip the leading generic determiner and match on what's
# left: a multi-word remainder ("Wei clan elder", "young man") is specific
# enough to use as an exact phrase; a single-word remainder is only trusted
# when it is not itself a generic role word and long enough to not be a bare
# surname prefix shared across many characters ("Shi" in "Wei Shi ...").
_GENERIC_ALIAS_PREFIX = re.compile(r"^(unnamed|the|a|an|family|clan)\s+", re.IGNORECASE)
_GENERIC_LAST_WORD = {
    "elder", "elders", "man", "men", "woman", "women", "boy", "girl", "child",
    "children", "character", "disciple", "disciples", "master", "mother",
    "father", "sage", "clan", "family", "school", "person", "guy", "lady",
    "sir", "madam", "school's", "unnamed",
}


def _name_pattern(names: list[str]) -> re.Pattern | None:
    tokens = set()
    for name in names:
        core = _GENERIC_ALIAS_PREFIX.sub("", (name or "").strip()).strip()
        if not core:
            continue
        words = [w for w in re.findall(r"[A-Za-z']+", core) if len(w) > 2]
        if not words:
            continue
        if len(words) > 1:
            tokens.add(core)
        last = words[-1]
        if len(last) >= 4 and last.lower() not in _GENERIC_LAST_WORD:
            tokens.add(last)
    tokens = {t for t in tokens if t}
    if not tokens:
        return None
    alternation = "|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)


def first_mention_sentence(surrounding_paragraph: str, names: list[str]) -> str:
    """Return the book sentence that first mentions this character.

    Falls back to the block's first sentence for characters the prose refers
    to only by description ("a young man", "the old woman").
    """
    block = first_paragraph_block(surrounding_paragraph)
    sentences = split_sentences(block)
    if not sentences:
        return ""
    pattern = _name_pattern(names)
    if pattern:
        for sentence in sentences:
            if pattern.search(sentence):
                return sentence
    return sentences[0]


def descriptive_phrases(
    character: dict[str, Any], passage_id: str, limit: int = 6
) -> list[dict[str, Any]]:
    """Visually useful sentences near the anchor passage, excluding the
    first-mention sentence and plot-only interiority.
    """
    names = [character.get("canonical_name") or character.get("stable_label") or ""]
    names.extend(character.get("aliases") or [])

    anchor_quotes = [
        v for v in character.get("visual_descriptions", [])
        if v.get("passage_id") == passage_id and v.get("exact_quote")
    ]
    if not anchor_quotes:
        return []

    # The first anchor quote is frequently the same paragraph used for the
    # first-mention sentence; do not print it twice on the card.
    fm_sentence = first_mention_sentence(anchor_quotes[0]["exact_quote"], names)
    fm_normalized = _normalize_for_dedup(fm_sentence)

    seen: set[str] = {fm_normalized} if fm_normalized else set()
    candidates: list[dict[str, Any]] = []
    for quote in anchor_quotes:
        for sentence in split_sentences(quote["exact_quote"]):
            key = _normalize_for_dedup(sentence)
            if not key or key in seen:
                continue
            # Interiority (belief, memory, hope, plans) is plot, not description,
            # unless the same sentence also carries concrete visual/physical detail.
            if _PLOT_ONLY.search(sentence) and not _VISUAL_SIGNAL.search(sentence):
                continue
            seen.add(key)
            candidates.append({
                "text": sentence,
                "passage_id": quote.get("passage_id"),
                "page_start": quote.get("page_start"),
                "page_end": quote.get("page_end"),
                "_visual": bool(_VISUAL_SIGNAL.search(sentence)),
            })

    # Prefer sentences with concrete visual/physical detail, but keep book order
    # within each group so the result still reads as a passage, not a shuffle.
    ordered = sorted(candidates, key=lambda c: not c["_visual"])
    for item in ordered:
        item.pop("_visual", None)
    return ordered[:limit]


def parse_passage_id(passage_id: str) -> dict[str, Any] | None:
    match = _PASSAGE_ID.match(passage_id or "")
    if not match:
        return None
    return {
        "book": match.group("book"),
        "chapter": int(match.group("chapter")),
        "passage": int(match.group("passage")),
        "width": len(match.group("passage")),
    }


def neighboring_passages(
    index: dict[str, Any], character_id: str, passage_id: str, radius: int = 2, limit: int = 6,
    max_chars: int = 700,
) -> list[dict[str, Any]]:
    """Passages within `radius` of the anchor, in the same chapter, that this
    character is actually linked to (mentioned or visually present) — plus any
    other passage in the corpus already tied to this character's
    visual_descriptions. Purely a lookup; no model call.

    Each passage's text is truncated to max_chars. Some passages (dense
    "Iteration ..." interlude-style chapters — see the scene-break marker in
    first_paragraph_block) run thousands of characters; a character with many
    visual_descriptions entries (Suriel: 114) can otherwise pull several such
    passages into one evidence pool and balloon a downstream prompt to tens
    of thousands of characters, which is slow-to-unusable for local
    generation. These are meant to be short context snippets, not full scenes.
    """
    parsed = parse_passage_id(passage_id)
    passage_context = index.get("passage_context", {})
    character = index.get("characters", {}).get(character_id, {})

    candidate_ids: list[str] = []
    if parsed:
        for offset in range(-radius, radius + 1):
            if offset == 0:
                continue
            candidate = f"{parsed['book']}:chapter:{parsed['chapter']}:passage:{parsed['passage'] + offset:0{parsed['width']}d}"
            if candidate in passage_context:
                candidate_ids.append(candidate)

    linked_ids = {
        v.get("passage_id") for v in character.get("visual_descriptions", [])
        if v.get("passage_id") and v.get("passage_id") != passage_id
    }
    candidate_ids.extend(pid for pid in linked_ids if pid not in candidate_ids)

    results: list[dict[str, Any]] = []
    for pid in candidate_ids:
        ctx = passage_context.get(pid)
        if not ctx:
            continue
        if character_id not in ctx.get("character_ids", []):
            continue
        location = ctx.get("location", {})
        text = first_paragraph_block(location.get("surrounding_paragraph", ""))
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + "…"
        results.append({
            "passage_id": pid,
            "page_start": location.get("page_start"),
            "page_end": location.get("page_end"),
            "text": text,
        })
        if len(results) >= limit:
            break
    return results


def _richness(row: dict[str, Any]) -> int:
    return len(row.get("appearances", [])) + len(row.get("visual_descriptions", []))


def resolve_character(
    index: dict[str, Any], record: dict[str, Any]
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve a bookcast.jsonl record back to its service_index character row.

    Entity extraction sometimes splits one real character into multiple thin
    nodes (e.g. a bare-title stub "Sage" alongside the fuller "Sword Sage"
    node with actual visual_descriptions), and source_character_ids can point
    at the thinner one. When another node shares this record's canonical name
    and carries more source material, prefer it — the card should quote the
    richer node, not whichever one extraction happened to link first.
    """
    characters = index.get("characters", {})
    primary_cid = primary = None
    for cid in record.get("source_character_ids", []) or []:
        if cid in characters:
            primary_cid, primary = cid, characters[cid]
            break
    if primary is None:
        for name in record.get("source_normalized_names", []) or []:
            for cid, row in characters.items():
                if row.get("character_name_normalized") == name:
                    primary_cid, primary = cid, row
                    break
            if primary is not None:
                break
    if primary is None:
        return None, None

    canonical = (record.get("canonical_name") or "").strip().casefold()
    best_cid, best, best_score = primary_cid, primary, _richness(primary)
    if canonical:
        for cid, row in characters.items():
            label = (row.get("canonical_name") or row.get("stable_label") or "").strip().casefold()
            if label != canonical:
                continue
            score = _richness(row)
            if score > best_score:
                best_cid, best, best_score = cid, row, score
    return best_cid, best


def true_first_appearance(character: dict[str, Any]) -> str | None:
    """The character's earliest appearance by book/chapter/passage order.

    Mirrors LoreService._first_location's sort key
    (lore_graph/lore_api/service.py). character["appearances"] is not stored
    in chronological order — for characters spanning both books, Soulsmith
    entries can precede Unsouled ones — so this must sort, never take [0].
    """
    appearances = character.get("appearances") or []
    if not appearances:
        return None
    ordered = sorted(appearances, key=lambda a: (
        0 if a.get("book_id") == "unsouled" else 1,
        int(a.get("chapter_number", 999)),
        a.get("passage_id", ""),
    ))
    return ordered[0].get("passage_id")


def resolve_anchor_passage(record: dict[str, Any], character: dict[str, Any]) -> str | None:
    """The card shows "where they were found" — always the true first
    appearance, never a citation the generation model happened to pick.
    evidence_notes.passage_id is untrusted for this purpose: it reflects
    whatever passage the Qwen generation step cited as supporting evidence,
    which is not guaranteed to be the character's earliest appearance.
    """
    return true_first_appearance(character)


def build_first_mention(index: dict[str, Any], passage_id: str, sentence: str) -> dict[str, Any]:
    location = index.get("passage_context", {}).get(passage_id, {}).get("location", {})
    return {
        "passage_id": passage_id,
        "book_id": location.get("book_id"),
        "book_title": location.get("book_title"),
        "chapter_number": location.get("chapter_number"),
        "chapter_label": location.get("chapter_label"),
        "page_start": location.get("page_start"),
        "page_end": location.get("page_end"),
        "sentence": sentence,
    }
