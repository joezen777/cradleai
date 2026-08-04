#!/usr/bin/env python3
"""MCP follow-up interview ladder for book-cast enrichment.

Answering a question against the lore MCP server is a three-step loop, not a
single call: formulate a retrieval query, retrieve cited passages (via an MCP
tool or the deterministic passage-neighborhood walk), then have the local
model answer that one question from only those passages. A question with no
supporting passage may be answered from general real-world knowledge instead
(never from the model's idea of the fictional setting) — that path is always
marked "inferred" and kept separate from cited content; see the grounding
rule in tasks.md.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from bookcast_evidence import neighboring_passages
from bookcast_fields import has_value, normalize_for_dedup, normalize_trait

DEFAULT_LORE_MCP_URL = "http://127.0.0.1:8765/mcp/"


# ---------------------------------------------------------------- gating ---

def needs_enrichment(record: dict[str, Any]) -> bool:
    """Most of the cast qualifies — see tasks-c.md C1: skin_tone alone was
    empty in 128/133 records after Track B's grounding pass. That is by
    design; the interview exists to fill exactly this gap.
    """
    fields = ("face", "skin_tone", "eyes", "hair", "build", "clothing", "accessories")
    filled = sum(1 for f in fields if has_value(record.get(f)))
    portrait_words = len((record.get("portrait_description") or "").split())
    return filled < 3 or portrait_words < 15


# ------------------------------------------------------------ branching ---

_CREATURE_TYPES = {
    "sacred beast", "spirit", "remnant", "nonhuman entity", "projection", "creature",
}
_OBJECT_TYPES = {"construct", "artifact", "sentient construct", "object"}


def interview_branch(record: dict[str, Any]) -> str:
    """person | creature | object — derived from the curated entity_type
    classification (normalize_bookcast.py's NONHUMAN table and Track B's
    grounding pass), not re-guessed by a model call.
    """
    entity_type = (record.get("entity_type") or "").strip().casefold()
    if entity_type in _OBJECT_TYPES:
        return "object"
    if entity_type in _CREATURE_TYPES:
        return "creature"
    return "person"


# ------------------------------------------------------------- MCP call ---

def call_mcp_tool(url: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    """Generic Streamable HTTP MCP tool call. Mirrors call_character_mcp /
    call_lore_mcp in qwen_media_chat.py, generalized to any of the five lore
    tools since the interview needs locate_scenery_context and
    locate_prop_context too, which have no dedicated caller yet.
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def call() -> Any:
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if result.isError:
                    detail = "\n".join(
                        getattr(item, "text", str(item)) for item in result.content
                    )
                    raise RuntimeError(detail or f"{tool_name} failed")
                structured = result.structuredContent
                if structured is not None:
                    if isinstance(structured, dict) and set(structured) == {"result"}:
                        return structured["result"]
                    return structured
                for item in result.content:
                    item_text = getattr(item, "text", None)
                    if item_text:
                        return json.loads(item_text)
                raise RuntimeError(f"{tool_name} returned no result")

    return asyncio.run(call())


# ------------------------------------------------------------ Q&A core ---

_CITED_ONLY_INSTRUCTION = """
You are answering ONE question about a character, creature, or object from Will
Wight's Unsouled and Soulsmith, using ONLY the passages supplied below. Do not use
any outside knowledge and do not guess.

QUESTION: {question}

PASSAGES:
{passages}

If the passages answer the question, respond with exactly one plain factual
sentence. If they do not answer it, the answer is an empty string. Never invent
detail beyond what the passages state.

Return exactly one JSON object with no Markdown and no commentary:
{{"answer": "one sentence or empty string"}}
""".strip()

_CITED_OR_COMMON_KNOWLEDGE_INSTRUCTION = """
QUESTION: {question}

CITED PASSAGES about {subject} (a character in Will Wight's Unsouled/Soulsmith):
{passages}

If the passages answer the question, answer in one plain sentence and set
"source" to "cited".

Otherwise, "{subject_kind}" is an invented in-world name. Name the ordinary
real-world animal or object its name most resembles ("snowfox" -> fox,
"river-hawk" -> hawk), then answer the question using one plain, factual,
real-world sentence about that base type only — no invented colors, markings,
or magic. Set "source" to "inferred".

Return one JSON object, nothing else:
{{"answer": "...", "source": "cited or inferred"}}
""".strip()


_MAX_EVIDENCE_CHARS = 4000


def _passages_block(passages: list[dict[str, Any]]) -> str:
    """Second line of defense on top of neighboring_passages()'s per-passage
    cap: MCP-sourced quote pools (aggregate_character_visual_description,
    prop source_description) aren't capped at the source, so bound the total
    joined block too rather than trusting every caller to have limited its
    own inputs.
    """
    block = "\n\n".join(f"[{p['passage_id']}] {p['text']}" for p in passages if p.get("text"))
    if len(block) > _MAX_EVIDENCE_CHARS:
        block = block[:_MAX_EVIDENCE_CHARS].rsplit(" ", 1)[0] + "…"
    return block


def ask_cited(model: Any, question: str, passages: list[dict[str, Any]]) -> dict[str, Any]:
    """Cited-only question: no inference fallback (used for CQ2 and any
    branch question where a fabricated answer would be worse than none).
    """
    if not passages:
        return {"answer": "", "source": "cited"}
    instruction = _CITED_ONLY_INSTRUCTION.format(
        question=question, passages=_passages_block(passages)
    )
    result = model.generate_json(instruction, max_new_tokens=200)
    answer = str(result.get("answer") or "").strip()
    return {"answer": answer, "source": "cited"}


def ask_with_fallback(
    model: Any, question: str, passages: list[dict[str, Any]], subject: str, subject_kind: str
) -> dict[str, Any]:
    """Cited if the passages support it, otherwise a tightly-constrained
    common-knowledge answer — never fictional embellishment. This is the
    "if snowfox is an animal, describe what it might look like" path from the
    request: real-world knowledge only, explicitly barred from inventing
    color, markings, or material.
    """
    instruction = _CITED_OR_COMMON_KNOWLEDGE_INSTRUCTION.format(
        question=question,
        passages=_passages_block(passages) or "(none)",
        subject=subject,
        subject_kind=subject_kind,
    )
    result = model.generate_json(instruction, max_new_tokens=200)
    answer = str(result.get("answer") or "").strip()
    source = str(result.get("source") or "cited").strip().casefold()
    if source not in {"cited", "inferred"}:
        source = "cited" if passages else "inferred"
    if source == "inferred" and not answer:
        source = "cited"
    return {"answer": answer, "source": source}


def make_answer_record(
    question_id: str, question: str, result: dict[str, Any],
    passages: list[dict[str, Any]], mcp_tool: str,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question": question,
        "answer": result["answer"],
        "source": result["source"],
        "passage_ids": [p["passage_id"] for p in passages] if result["source"] == "cited" else [],
        "mcp_tool": mcp_tool,
    }


# --------------------------------------------------------------- ladder ---

def run_common_ladder(
    model: Any, index: dict[str, Any], character_id: str, character: dict[str, Any],
    anchor_pid: str, name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """CQ1 (passage-neighborhood widening) then CQ2 (mood words). Returns the
    answers plus the neighbor pool so branch ladders can reuse it instead of
    re-walking the index.
    """
    answers: list[dict[str, Any]] = []
    neighbors = neighboring_passages(index, character_id, anchor_pid, radius=3, limit=8)

    cq1_question = f"What other passages near {anchor_pid} describe {name}?"
    cq1_answer = "; ".join(p["passage_id"] for p in neighbors)
    answers.append({
        "question_id": "CQ1", "question": cq1_question, "answer": cq1_answer,
        "source": "cited", "passage_ids": [p["passage_id"] for p in neighbors],
        "mcp_tool": "passage-neighborhood-walk",
    })

    cq2_question = f"What words generally describe {name}'s mood near this passage in the book?"
    cq2_result = ask_cited(model, cq2_question, neighbors)
    answers.append(make_answer_record("CQ2", cq2_question, cq2_result, neighbors, "passage-neighborhood-walk"))

    return answers, neighbors


_LEADING_COPULA = re.compile(
    r"^(belongs to|is (?:part|a member) of|is the|is an?|works as|serves as|has the)\s+",
    re.IGNORECASE,
)


def _short_phrase(sentence: str, name: str) -> str:
    """Reduce a full-sentence answer ("Wei Shi Jaran belongs to the Wei
    clan.") to a short noun phrase ("the Wei clan") suitable for interpolating
    into the next question — the raw sentence produces a grammatically broken
    follow-up ("What do members of Wei Shi Jaran belongs to the Wei clan.
    generally look like...") and is a worse MCP search query besides.
    """
    text = sentence.strip().rstrip(".")
    if name:
        text = re.sub(re.escape(name), "", text, count=1, flags=re.IGNORECASE).strip()
    text = _LEADING_COPULA.sub("", text).strip()
    text = re.split(r"[,;]", text)[0].strip()
    return text or sentence.strip().rstrip(".")


def run_person_ladder(
    model: Any, mcp_url: str, name: str, neighbors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []

    p1_q = f"What clan, family, school, or people does {name} belong to?"
    p1 = ask_cited(model, p1_q, neighbors)
    answers.append(make_answer_record("P1", p1_q, p1, neighbors, "passage-neighborhood-walk"))

    if p1["answer"]:
        group_name = _short_phrase(p1["answer"], name)
        try:
            group_hits = call_mcp_tool(
                mcp_url, "locate_character_context",
                {"description": group_name, "max_results": 5},
            ) or []
        except Exception:
            group_hits = []
        group_quotes = [
            {"passage_id": q, "text": row.get("aggregate_character_visual_description", "")}
            for row in group_hits if isinstance(row, dict)
            for q in [row.get("character_name_normalized", "")]
            if row.get("aggregate_character_visual_description")
        ]
        p2_q = f"What do members of {group_name} generally look like, and how do they dress?"
        p2 = ask_cited(model, p2_q, group_quotes)
        answers.append(make_answer_record("P2", p2_q, p2, group_quotes, "locate_character_context"))

    p3_q = f"What age can be inferred from the cited text about {name}?"
    p3 = ask_cited(model, p3_q, neighbors)
    answers.append(make_answer_record("P3", p3_q, p3, neighbors, "passage-neighborhood-walk"))

    p4_q = f"What is {name}'s job or role?"
    p4 = ask_cited(model, p4_q, neighbors)
    answers.append(make_answer_record("P4", p4_q, p4, neighbors, "passage-neighborhood-walk"))

    if p4["answer"]:
        role_name = _short_phrase(p4["answer"], name)
        p5_q = f"What tools or instruments would someone in the role of {role_name} work with?"
        try:
            prop_hits = call_mcp_tool(
                mcp_url, "locate_prop_context",
                {"description": role_name, "max_results": 5},
            ) or []
        except Exception:
            prop_hits = []
        prop_quotes = [
            {"passage_id": row.get("prop_name_normalized", ""), "text": " ".join(row.get("source_description", []))}
            for row in prop_hits if isinstance(row, dict) and row.get("source_description")
        ]
        p5 = ask_cited(model, p5_q, prop_quotes)
        answers.append(make_answer_record("P5", p5_q, p5, prop_quotes, "locate_prop_context"))

    p6_q = f"What sacred-arts stage, Path, or Goldsign does {name} have?"
    p6 = ask_cited(model, p6_q, neighbors)
    answers.append(make_answer_record("P6", p6_q, p6, neighbors, "passage-neighborhood-walk"))

    return answers


# The common-knowledge fallback only makes sense for something with a
# plausible real-world analogue. Asked about a spirit, Remnant, or projection
# ("the Razor", "Presence") the model still complies rather than admitting no
# analogue exists, producing nonsense ("The Razor is a fox."). Restrict the
# fallback to entity types that are physical creatures; everything else stays
# cited-only, so "not an animal" correctly yields silence per the request.
_ANIMAL_LIKE_ENTITY_TYPES = {"sacred beast", "nonhuman entity", "creature"}


def run_creature_ladder(
    model: Any, mcp_url: str, name: str, species: str, entity_type: str,
    neighbors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    subject_kind = species or "animal"
    is_animal_like = (entity_type or "").strip().casefold() in _ANIMAL_LIKE_ENTITY_TYPES

    # The animal/not-animal decision is made in code via is_animal_like, not
    # left to the model — asking the model to also judge it in the question
    # text produced a confused literal answer ("snowfox is not an animal")
    # instead of the description itself.
    a2_q = f"Describe in one sentence what {name} looks like."
    if is_animal_like:
        a2 = ask_with_fallback(model, a2_q, neighbors, subject=name, subject_kind=subject_kind)
    else:
        a2 = ask_cited(model, a2_q, neighbors)
    answers.append(make_answer_record("A2", a2_q, a2, neighbors, "passage-neighborhood-walk"))

    a3_q = f"Where does {name} live?"
    a3 = ask_cited(model, a3_q, neighbors)
    answers.append(make_answer_record("A3", a3_q, a3, neighbors, "passage-neighborhood-walk"))

    if a3["answer"]:
        a4_q = f"Describe the landscape and natural climate of {a3['answer']}."
        try:
            scenery_hits = call_mcp_tool(
                mcp_url, "locate_scenery_context",
                {"description": a3["answer"], "max_results": 1},
            ) or []
        except Exception:
            scenery_hits = []
        if scenery_hits and isinstance(scenery_hits[0], dict):
            s = scenery_hits[0]
            # SceneryContext already returns structured weather/climate/backdrop
            # fields — read them directly rather than asking the model to
            # invent a climate description.
            parts = [s.get("climate"), s.get("weather"), s.get("backdrop")]
            a4_answer = ". ".join(p for p in parts if p)
            a4 = {"answer": a4_answer, "source": "cited" if a4_answer else "cited"}
            pid = s.get("first_mentioned", {}).get("passage_id") if isinstance(s.get("first_mentioned"), dict) else None
            answers.append({
                "question_id": "A4", "question": a4_q, "answer": a4_answer,
                "source": "cited", "passage_ids": [pid] if pid else [],
                "mcp_tool": "locate_scenery_context",
            })

    a5_q = f"What size, coloring, and distinguishing markings are stated for {name}?"
    a5 = ask_cited(model, a5_q, neighbors)
    answers.append(make_answer_record("A5", a5_q, a5, neighbors, "passage-neighborhood-walk"))

    return answers


def run_object_ladder(
    model: Any, mcp_url: str, name: str, neighbors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    try:
        prop_hits = call_mcp_tool(
            mcp_url, "locate_prop_context", {"description": name, "max_results": 3},
        ) or []
    except Exception:
        prop_hits = []
    prop_quotes = [
        {"passage_id": row.get("prop_name_normalized", ""), "text": " ".join(row.get("source_description", []))}
        for row in prop_hits if isinstance(row, dict) and row.get("source_description")
    ]
    pool = prop_quotes or neighbors
    tool = "locate_prop_context" if prop_quotes else "passage-neighborhood-walk"

    o1_q = f"What material is {name} made of?"
    o1 = ask_cited(model, o1_q, pool)
    answers.append(make_answer_record("O1", o1_q, o1, pool, tool))

    o2_q = f"Who made or carries {name}?"
    o2 = ask_cited(model, o2_q, pool)
    answers.append(make_answer_record("O2", o2_q, o2, pool, tool))

    o3_q = f"What is {name}'s size, and how is it carried or mounted?"
    o3 = ask_cited(model, o3_q, pool)
    answers.append(make_answer_record("O3", o3_q, o3, pool, tool))

    return answers


def run_interview(
    model: Any, mcp_url: str, index: dict[str, Any],
    character_id: str, character: dict[str, Any], anchor_pid: str, record: dict[str, Any],
) -> list[dict[str, Any]]:
    name = record.get("canonical_name") or character.get("canonical_name") or character.get("stable_label") or "this character"
    branch = interview_branch(record)
    answers, neighbors = run_common_ladder(model, index, character_id, character, anchor_pid, name)
    if branch == "person":
        answers += run_person_ladder(model, mcp_url, name, neighbors)
    elif branch == "creature":
        species = record.get("species_or_object_type") or ""
        entity_type = record.get("entity_type") or ""
        answers += run_creature_ladder(model, mcp_url, name, species, entity_type, neighbors)
    else:
        answers += run_object_ladder(model, mcp_url, name, neighbors)
    return answers


# ----------------------------------------------------------- composing ---

def compose_enriched(record: dict[str, Any], answers: list[dict[str, Any]]) -> str:
    """portrait_description stays cited-only and untouched — this builds the
    separate enriched field: cited additions first (deduplicated against the
    existing portrait), then a clearly labeled inferred section.
    """
    base = (record.get("portrait_description") or "").strip()
    base_keys = {normalize_for_dedup(s) for s in base.split(". ") if s.strip()}

    cited_additions: list[str] = []
    inferred_additions: list[str] = []
    seen: set[str] = set(base_keys)

    for a in answers:
        if a.get("question_id") == "CQ1":
            continue  # a passage-ID list, not prose — evidence metadata only
        answer = normalize_trait(a.get("answer"))
        if not answer:
            continue
        key = normalize_for_dedup(answer)
        if not key or key in seen:
            continue
        seen.add(key)
        if a.get("source") == "cited":
            cited_additions.append(answer.rstrip("."))
        else:
            inferred_additions.append(answer.rstrip("."))

    record["enrichment_grounded_additions"] = cited_additions
    record["enrichment_inferred_additions"] = inferred_additions

    pieces = [base] if base else []
    if cited_additions:
        pieces.append(". ".join(cited_additions) + ".")
    text = " ".join(pieces)
    if inferred_additions:
        text += "\n\nPlausible reconstruction (not stated in the source): " + ". ".join(inferred_additions) + "."
    return text.strip()
