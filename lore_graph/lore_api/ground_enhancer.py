from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from loredb.local_model import LocalLoreModel
from loredb.util import load_config

from .schemas import (
    GroundEnhanceRequest,
    GroundEnhanceResponse,
    GroundEnhancementStage,
    GroundingLocationCandidate,
    FrameVisualInventory,
    LocateLoreRequest,
)


ZIMAGE_TURBO_GUIDANCE = """
Rewrite the grounded description as one dense 120-180 word positive prompt for
ComfyUI Z-Image Turbo that produces a polished cinematic live-action still,
never a cartoon, drawing, illustration, anime frame, or storyboard. Return only
the prompt paragraph. Begin with orientation,
shot size, and camera angle. Preserve exact visible subject count, screen
positions, framing, pose, gaze, expression, prop placement, and background
geometry from the visual lock without reinterpretation. Preserve visible skin
tone, facial structure, hair, clothing, and action. Bind every color and
material directly to its noun. Translate line art into plausible Cradle-fantasy
physical materials using cited lore, never modern suburban or contemporary
design unless the frame visibly requires it, and never add off-frame people or
objects. Include the complete visible support chain (for example fruit on plate
on table). Specify coherent key-light direction, restrained
bounce/edge light, a plausible photographic lens and aperture, focal plane,
depth behavior, and subtle film grain. Use positive concrete language. Omit
generic quality buzzwords, Markdown, explanations, and negative prompting.
Never replace a visible face with a generic face, neutralize an expression,
redirect eyes, change a gesture, or turn an action into a static pose. The
visual lock is an instruction, not optional context: repeat its important
camera, position, gaze, expression, action, and contact facts in the prompt.
""".strip()


class GroundEnhancer:
    """Two-step, source-cited frame grounding and production enhancement."""

    def __init__(self, service: Any):
        self.service = service
        self.root: Path = service.root
        self.config = load_config(self.root)
        self.lock = threading.RLock()

    def _candidate(self, match: Any) -> GroundingLocationCandidate:
        location = match.location_in_book
        excerpt = re.sub(r"\s+", " ", location.surrounding_paragraph).strip()
        return GroundingLocationCandidate(
            passage_id=location.passage_id,
            book_title=location.book_title,
            chapter_label=location.chapter_label,
            page_start=location.page_start,
            page_end=location.page_end,
            confidence_rating=location.confidence_rating,
            event_excerpt=excerpt[:900] + ("…" if len(excerpt) > 900 else ""),
        )

    def _confirmed_evidence(self, passage_ids: list[str]) -> dict[str, Any]:
        missing = [pid for pid in passage_ids if pid not in self.service.index["passages"]]
        if missing:
            raise ValueError(f"Unknown confirmed passage IDs: {', '.join(missing)}")

        evidence: dict[str, Any] = {
            "passages": [], "characters": [], "scenery": [], "props": [],
        }
        character_seen: set[tuple[str, str]] = set()
        scenery_seen: set[tuple[str, str]] = set()
        prop_seen: set[tuple[str, str]] = set()
        for passage_id in passage_ids:
            passage = self.service.index["passages"][passage_id]
            context = self.service.index["passage_context"].get(passage_id, {})
            location = context.get("location", {})
            evidence["passages"].append({
                "passage_id": passage_id,
                "book_title": location.get("book_title"),
                "chapter_label": location.get("chapter_label"),
                "pages": [location.get("page_start"), location.get("page_end")],
                "source_text": passage.get("text", "")[:9000],
            })
            for character_id in context.get("character_ids", []):
                character = self.service.index["characters"].get(character_id)
                if not character:
                    continue
                key = (character_id, passage_id)
                if key in character_seen:
                    continue
                character_seen.add(key)
                quotes = [
                    row.get("exact_quote") for row in character.get("visual_descriptions", [])
                    if row.get("passage_id") == passage_id and row.get("exact_quote")
                ]
                actions = [
                    row.get("action_summary") for row in character.get("appearances", [])
                    if row.get("passage_id") == passage_id and row.get("action_summary")
                ]
                evidence["characters"].append({
                    "passage_id": passage_id,
                    "name": character.get("canonical_name") or character.get("stable_label"),
                    "source_descriptions": quotes[:8],
                    "scene_actions": actions[:6],
                })
            for setting_id in context.get("setting_ids", []):
                setting = self.service.index["settings"].get(setting_id)
                if not setting:
                    continue
                key = (setting_id, passage_id)
                if key in scenery_seen:
                    continue
                scenery_seen.add(key)
                quotes = [
                    row.get("exact_quote") for row in setting.get("visual_descriptions", [])
                    if row.get("passage_id") == passage_id and row.get("exact_quote")
                ]
                evidence["scenery"].append({
                    "passage_id": passage_id,
                    "name": setting.get("name"),
                    "source_descriptions": quotes[:8],
                })
            for prop_id in context.get("prop_ids", []):
                prop = self.service.index["props"].get(prop_id)
                if not prop:
                    continue
                key = (prop_id, passage_id)
                if key in prop_seen:
                    continue
                prop_seen.add(key)
                quotes = [
                    row.get("exact_quote") for row in prop.get("visual_descriptions", [])
                    if row.get("passage_id") == passage_id and row.get("exact_quote")
                ]
                evidence["props"].append({
                    "passage_id": passage_id,
                    "name": prop.get("name"),
                    "source_descriptions": quotes[:8],
                })
        return evidence

    def _stage(
        self,
        model: LocalLoreModel,
        stage: str,
        current: str,
        instruction: str,
        evidence: Any,
        passage_ids: list[str],
        inventory: FrameVisualInventory,
    ) -> GroundEnhancementStage:
        prompt = f"""
You are revising a production-reference description of one Cradle storyboard
frame. Preserve every supported detail from CURRENT DESCRIPTION. Apply only the
requested stage. The frame observation is primary; cited book evidence may
correct identity, wardrobe, color, material, location, or contextual meaning,
but cannot add an off-frame person, object, action, or background element.
VISUAL INVENTORY is immutable. DESCRIPTION must describe visible pixels only.
Put off-screen event meaning in context_notes; never turn it into visible
people, scenery, props, actions, or colors. Every lore-derived statement must
include its passage_id. Return JSON with exactly:
{{"description":"...", "context_notes":"...", "corrections":["..."]}}.

STAGE: {stage}
TASK: {instruction}
CURRENT DESCRIPTION:
{current}
IMMUTABLE VISUAL INVENTORY:
{inventory.model_dump_json()}
STAGE EVIDENCE:
{json.dumps(evidence, ensure_ascii=False)}
""".strip()
        result = model.generate_json(prompt, max_new_tokens=1200)
        description = str(result.get("description") or "").strip()
        if not description:
            raise RuntimeError(f"Local model returned an empty {stage} description")
        corrections = [str(value) for value in result.get("corrections", []) if value]
        return GroundEnhancementStage(
            stage=stage,
            description=description,
            context_notes=str(result.get("context_notes") or "").strip(),
            evidence_passage_ids=passage_ids,
            corrections=corrections,
        )

    def _extract_facts(
        self,
        model: LocalLoreModel,
        inventory: FrameVisualInventory,
        evidence: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        """Extract category-specific, cited facts once before prose rewriting."""
        prompt = f"""
Extract source-grounded facts for one visible Cradle storyboard frame. This is
an extraction step, not a description-writing step. The image inventory is the
authority for what is visible; confirmed passages are the authority for names,
colors, materials, identity, and setting continuity. Do not merge categories,
repeat the whole passage, or invent facts. Every fact must carry one of the
provided passage IDs. If a fact is not supported, omit it. Return JSON only with
exactly these arrays:
{{
  "characters": [{{"visible_figure":"...", "canonical_name":"...", "facts":["..."], "passage_id":"..."}}],
  "scenery": [{{"visible_region":"...", "canonical_location":"...", "facts":["..."], "passage_id":"..."}}],
  "props": [{{"visible_object":"...", "canonical_name":"...", "facts":["..."], "passage_id":"..."}}]
}}
Only include a character, setting region, or prop when the corresponding
visible inventory entry exists. Do not change camera angle, placement, posture,
gaze, expression, action, or object contact; those are frame locks and must not
be returned as lore facts.

IMMUTABLE FRAME INVENTORY:
{inventory.model_dump_json()}

CONFIRMED SOURCE EVIDENCE:
{json.dumps(evidence, ensure_ascii=False)}
""".strip()
        result = model.generate_json(prompt, max_new_tokens=1500)
        facts: dict[str, list[dict[str, Any]]] = {}
        for category in ("characters", "scenery", "props"):
            rows = result.get(category, [])
            if not isinstance(rows, list):
                rows = [rows]
            valid: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                values = row.get("facts", [])
                if isinstance(values, str):
                    values = [values]
                if not isinstance(values, list):
                    values = []
                clean = {
                    key: value for key, value in row.items()
                    if key in {"visible_figure", "visible_region", "visible_object",
                               "canonical_name", "canonical_location", "facts", "passage_id"}
                }
                clean["facts"] = [str(value).strip() for value in values if str(value).strip()]
                if clean.get("passage_id") in {p["passage_id"] for p in evidence["passages"]} and clean["facts"]:
                    valid.append(clean)
            facts[category] = valid
        return facts

    def _model_path(self) -> Path:
        configured = str(self.config["local_lore_model"])
        path = Path(configured)
        return path if path.is_absolute() else (self.root / path).resolve()

    @staticmethod
    def _object_identity_mentions(passages: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Put late, explicit scene-object names before nearby setup/decoy nouns."""
        terms = re.compile(
            r"\b(fruit|spirit-fruit|orus|elixir|weapon|sword|blade|badge|"
            r"construct|drudge|tool|artifact|treasure)\b", re.I
        )
        mentions: list[dict[str, str]] = []
        for passage in reversed(passages):
            sentences = re.split(r"(?<=[.!?])\s+", passage.get("source_text", ""))
            for sentence in reversed(sentences):
                sentence = re.sub(r"\s+", " ", sentence).strip()
                if terms.search(sentence):
                    mentions.append({
                        "passage_id": passage["passage_id"],
                        "source_sentence": sentence[:800],
                    })
        def specificity(row: dict[str, str]) -> int:
            text = row["source_sentence"].lower()
            return (4 if "orus" in text else 0) + (2 if "spirit-fruit" in text else 0) + (
                1 if "held up" in text or "sat on" in text or "center" in text else 0
            )
        return sorted(mentions, key=specificity, reverse=True)[:24]

    @staticmethod
    def _canonical_object_lock(mentions: list[dict[str, str]]) -> tuple[str, str] | None:
        for row in mentions:
            match = re.search(
                r"\bthe\s+([a-z][a-z -]{1,50}?),\s+the\s+(spirit-fruit|elixir|"
                r"weapon|sword|blade|badge|construct|drudge|artifact|treasure)\b",
                row["source_sentence"], re.I,
            )
            if match:
                return f"{match.group(1).strip()} {match.group(2).lower()}", row["passage_id"]
        return None

    @staticmethod
    def _support_surface_lock(passages: list[dict[str, Any]]) -> tuple[str, str] | None:
        for passage in passages:
            for sentence in re.split(r"(?<=[.!?])\s+", passage.get("source_text", "")):
                match = re.search(
                    r"\b(?:sat|rested|lay|stood)\s+(?:on|at)\s+(?:the\s+)?"
                    r"(?:center\s+of\s+)?([^.!?]{0,80}\btable)\b",
                    sentence, re.I,
                )
                if match:
                    return match.group(1).strip(), passage["passage_id"]
        return None

    @staticmethod
    def _appearance_locks(passages: list[dict[str, Any]]) -> list[tuple[str, str]]:
        locks: list[tuple[str, str]] = []
        visual_terms = re.compile(
            r"\b(shone|shine|bright color|wrinkle|imperfection|pale|smooth|"
            r"fur|hair|skin|scar|limp|tail|scale|wood|stone|metal)\b", re.I
        )
        for passage in passages:
            for sentence in re.split(r"(?<=[.!?])\s+", passage.get("source_text", "")):
                sentence = re.sub(r"\s+", " ", sentence).strip()
                if visual_terms.search(sentence):
                    locks.append((sentence[:500], passage["passage_id"]))
        return locks[:12]

    @staticmethod
    def _enforce_object_correction(value: str, canonical_lock: tuple[str, str] | None) -> str:
        if not canonical_lock:
            return value
        name = canonical_lock[0]
        value = re.sub(r"\b(?:pumpkin|melon)\b", name, value, flags=re.I)
        if "white" in name.lower():
            value = re.sub(r"\borange\b", "white", value, flags=re.I)
        return re.sub(
            rf"\b{name}\s+{re.escape(name)}\b", name, value, flags=re.I
        )

    @staticmethod
    def _enforce_support_material(
        value: str, support_lock: tuple[str, str] | None
    ) -> str:
        if not support_lock or "table" not in support_lock[0].lower():
            return value
        return re.sub(
            r"\b(?:smoothly rendered[, ]*)?(?:dark gray\s+)?(?:matte\s+)?"
            r"(?:concrete surface|countertop)\b",
            "dark-stained wooden surface of Lindon’s table",
            value,
            flags=re.I,
        )

    @staticmethod
    def _enforce_cradle_materials(value: str) -> str:
        """Translate modern guessed materials while preserving visible geometry."""
        replacements = (
            (r"\bmid-20th-century American (?:residential area|homes?)\b", "Wei clan compound"),
            (r"\b(?:modern )?suburban (?:setting|neighborhood|background)\b", "Wei clan compound"),
            (r"\bresidential area\b", "Wei clan compound"),
            (r"\blight gr[ae]y cotton t-shirt\b", "light-gray handwoven training tunic"),
            (r"\bcotton t-shirt\b", "handwoven training tunic"),
            (r"\bweathered white wooden picket fence\b", "weathered pale orus-wood boundary fence"),
            (r"\b(?:white wooden )?picket fence\b", "pale orus-wood boundary fence"),
            (r"\bdark brown shingle roof\b", "purple glazed-tile roof"),
            (r"\brustic(?:, sun-drenched)? wooden house\b", "pale smooth orus-wood Wei clan house"),
        )
        for pattern, replacement in replacements:
            value = re.sub(pattern, replacement, value, flags=re.I)
        return value

    @staticmethod
    def _clean_zimage_prompt(value: str) -> str:
        value = re.sub(r"^\s*\*{0,2}prompt\*{0,2}\s*:\s*", "", value, flags=re.I)
        value = value.replace("**", "").replace("```", "")
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _visual_lock_text(inventory: FrameVisualInventory) -> str:
        """Serialize frame-owned facts for every downstream prompt stage."""
        parts = [
            f"Visible human count: {inventory.visible_human_count}",
            f"Composition: {inventory.composition}",
            f"Camera/framing: {inventory.camera_and_framing}",
        ]
        for label, values in (
            ("Subject positions", inventory.subject_positions),
            ("Posture, gaze, expression, action", inventory.posture_gaze_and_action),
            ("Visible appearance", inventory.visible_appearance),
            ("Visible props", inventory.visible_objects),
            ("Prop contact/support", inventory.support_and_contact),
            ("Background geometry", inventory.background_geometry),
        ):
            if values:
                parts.append(f"{label}: " + "; ".join(values))
        return " ".join(part for part in parts if part.split(":", 1)[-1].strip())

    @classmethod
    def _append_visual_lock(
        cls, value: str, inventory: FrameVisualInventory
    ) -> str:
        lock = cls._visual_lock_text(inventory)
        if not lock:
            return value
        return f"{value.rstrip()} Frame continuity lock: {lock}"

    def enhance(self, request: GroundEnhanceRequest) -> GroundEnhanceResponse:
        payload = {
            "corpus_fingerprint": self.service.index["corpus_fingerprint"],
            "request": request.model_dump(),
        }
        # Version 14 invalidates responses produced before structured fact extraction.
        cached = self.service.cache.get("ground_enhance", payload, version=14)
        if cached is not None:
            cached["cache_hit"] = True
            return GroundEnhanceResponse.model_validate(cached)

        with self.lock:
            inventory = FrameVisualInventory.model_validate(
                self.service.images.inspect(
                    request.frame_image, request.visual_reference_description
                )
            )
            frame_description = self.service.images.describe(request.frame_image)
            visual_anchor = (
                request.visual_reference_description or frame_description
            ).strip()
            located = self.service.locate_lore(LocateLoreRequest(
                frame_image=request.frame_image,
                transcript=request.transcript,
                pegasus_chapter_summary=request.pegasus_chapter_context,
                highlighted_summary=request.highlighted_summary,
                max_locations=request.max_locations,
            ))
            candidates = [self._candidate(match) for match in located.matches]

            if not request.confirmed_passage_ids:
                response = GroundEnhanceResponse(
                    status="location_candidates",
                    requires_confirmation=True,
                    frame_description=frame_description,
                    visual_inventory=inventory,
                    location_candidates=candidates,
                )
                self.service.cache.put(
                    "ground_enhance", payload, response.model_dump(mode="json"), version=14
                )
                self.service.images.close()
                self.service.retriever.release_model()
                return response

            confirmed = list(dict.fromkeys(request.confirmed_passage_ids))
            evidence = self._confirmed_evidence(confirmed)

            # The visual and embedding models are no longer needed. Releasing
            # them keeps the text synthesis model within a 12 GB GPU budget.
            self.service.images.close()
            self.service.retriever.release_model()
            model = LocalLoreModel(self._model_path())
            try:
                extracted_facts = self._extract_facts(model, inventory, evidence)
                stages: list[GroundEnhancementStage] = []
                pegasus_stage = self._stage(
                    model, "pegasus_context", visual_anchor,
                    "Add only omitted visible details from Pegasus. Copy camera angle, framing, subject positions, posture, head direction, gaze, expression, action, skin tone, and background geometry from CURRENT DESCRIPTION without revising them. Treat words such as 'resembles' as visual analogy, never identity. Put later-shot or event details in context_notes. Correct no book identities yet.",
                    {
                        "chapter_context": request.pegasus_chapter_context,
                        "highlighted_summary": request.highlighted_summary,
                        "transcript": request.transcript,
                    }, [], inventory,
                )
                # Pegasus is visual/context input, not a citable book source.
                # Do not retain identities or citations invented by synthesis.
                pegasus_stage.context_notes = (
                    "Pegasus context refined visible composition and motion only; "
                    "canonical identity remains unresolved until confirmed book evidence."
                )
                pegasus_stage.corrections = []
                stages.append(pegasus_stage)
                if inventory.visible_human_count == 0:
                    character_stage = GroundEnhancementStage(
                        stage="characters", description=pegasus_stage.description,
                        context_notes="Book characters belong to the event context but no figure is visible in this frame.",
                        corrections=["Kept visible character count at zero; did not render off-screen participants."],
                        evidence_passage_ids=confirmed,
                    )
                else:
                    character_stage = self._stage(
                        model, "characters", pegasus_stage.description,
                        "Correct identity, lore appearance, wardrobe, and accessories only for visibly present figures. Do not revise, paraphrase, or infer posture, screen position, head direction, eye direction, expression, or action; preserve those visual locks exactly. Preserve image-visible skin tone and facial structure unless a citation explicitly corrects them.",
                        {"source_records": evidence["characters"], "extracted_facts": extracted_facts["characters"]}, confirmed, inventory,
                    )
                stages.append(character_stage)
                if not inventory.setting_visible:
                    scenery_stage = GroundEnhancementStage(
                        stage="scenery", description=character_stage.description,
                        context_notes="The confirmed event has a book location, but the frame does not reveal scenery sufficient to render it.",
                        corrections=["Did not add architecture, terrain, or other off-frame location details."],
                        evidence_passage_ids=confirmed,
                    )
                else:
                    scenery_stage = self._stage(
                        model, "scenery", character_stage.description,
                        "Correct the visible location and enrich its architecture, terrain, materials, and atmosphere as Cradle fantasy. Preserve the background's exact object count, positions, silhouettes, and spatial geometry. Replace unsupported modern suburban/contemporary styling with cited in-world materials without moving or adding structures.",
                        {"source_records": evidence["scenery"], "extracted_facts": extracted_facts["scenery"]}, confirmed, inventory,
                    )
                stages.append(scenery_stage)
                identity_mentions = self._object_identity_mentions(evidence["passages"])
                canonical_lock = self._canonical_object_lock(identity_mentions)
                support_lock = self._support_surface_lock(evidence["passages"])
                appearance_locks = self._appearance_locks(evidence["passages"])
                prop_stage = self._stage(
                    model, "props", scenery_stage.description,
                    "Resolve each visible item's canonical identity from the most specific explicit mention in the confirmed passages. Follow the scene chronologically and do not confuse an earlier adjacent, carried, or decoy object. Preserve every image-visible prop position and contact point. Add missing cited support relationships (object on plate, plate on table) even when tightly cropped. Replace visual analogies such as pumpkin with the canonical book name; then add cited shape, color, material, placement, use, and magical significance only for visible items.",
                    {
                        "canonical_visible_object_name": canonical_lock,
                        "canonical_support_surface": support_lock,
                        "cited_visual_appearance_locks": appearance_locks,
                        "identity_mentions_prioritized": identity_mentions,
                        "props": evidence["props"],
                        "extracted_facts": extracted_facts["props"],
                        "source_passages": evidence["passages"],
                    },
                    confirmed, inventory,
                )
                if canonical_lock and canonical_lock[0].lower() not in prop_stage.description.lower():
                    name, passage_id = canonical_lock
                    prop_stage.description += (
                        f" Canonical visible-object identity: {name} ({passage_id})."
                    )
                    prop_stage.corrections.append(
                        f"Locked the explicit canonical name '{name}' from {passage_id}."
                    )
                stages.append(prop_stage)
                missing_stage = self._stage(
                    model, "missing_details", prop_stage.description,
                    "Audit CURRENT DESCRIPTION against the immutable inventory, VISUAL REFERENCE LOCK, and confirmed lore. Restore every omitted camera/framing fact, screen position, posture, gaze, expression, action, skin tone, face/hair/clothing detail, prop contact/support relationship, and background geometry. Geometry and human appearance are immutable, but confirmed lore overrides guessed object identity, object color/material, setting material, and support-surface identity. Never restore a contradicted visual analogy such as pumpkin, orange pumpkin, lighthouse, modern suburb, concrete, or contemporary clothing after lore corrects it. Correct unsupported modern/suburban styling to Cradle fantasy without changing layout. State a physically plausible live-action material treatment; do not call the result a sketch, drawing, cartoon, anime, or illustration. Add no person or object absent from the frame except a cited support surface directly required by a visible object. Return the complete corrected visible description.",
                    {
                        "visual_reference_lock": visual_anchor,
                        "canonical_visible_object_name": canonical_lock,
                        "canonical_support_surface": support_lock,
                        "cited_visual_appearance_locks": appearance_locks,
                        "confirmed_passages": evidence["passages"],
                        "characters": evidence["characters"],
                        "scenery": evidence["scenery"],
                        "props": evidence["props"],
                        "extracted_facts": extracted_facts,
                    },
                    confirmed, inventory,
                )
                stages.append(missing_stage)
                continuity_stage = self._stage(
                    model, "continuity_audit", missing_stage.description,
                    "Perform a final frame-continuity audit. Treat the immutable visual inventory as a checklist, not inspiration. Preserve the exact visible human count, each figure's screen position, body posture, head direction, eye direction, facial expression, hand/arm gesture, and action. Preserve visible skin tone, face shape, hair, clothing silhouette, every visible prop, its contact point, and the background geometry. Keep lore corrections for canonical names, colors, materials, setting identity, and support relationships. Remove any newly invented person, prop, architecture, or action. Return a complete description that still names the grounded colors/materials, but never changes the shot's staging.",
                    {
                        "visual_lock": self._visual_lock_text(inventory),
                        "current_description": missing_stage.description,
                        "confirmed_passages": evidence["passages"],
                    },
                    confirmed, inventory,
                )
                continuity_stage.corrections.append(
                    "Final audit rechecked frame-owned count, composition, gaze, expression, action, appearance, props, and geometry."
                )
                stages.append(continuity_stage)
                grounded = self._enforce_object_correction(
                    continuity_stage.description, canonical_lock
                )
                grounded = self._enforce_support_material(grounded, support_lock)
                grounded = self._enforce_cradle_materials(grounded)
                grounded = self._append_visual_lock(grounded, inventory)
                if canonical_lock and canonical_lock[0].lower() not in grounded.lower():
                    name, passage_id = canonical_lock
                    grounded += f" Canonical visible-object identity: {name} ({passage_id})."
                if support_lock and support_lock[0].lower() not in grounded.lower():
                    support, passage_id = support_lock
                    grounded += (
                        f" The visible object and its immediate support rest on "
                        f"{support} ({passage_id})."
                    )
                for appearance, passage_id in appearance_locks:
                    if "wrinkle" in appearance.lower() or "shone" in appearance.lower():
                        if appearance.lower() not in grounded.lower():
                            grounded += f" Cited appearance ({passage_id}): {appearance}"
                z_prompt = self._clean_zimage_prompt(model.generate_text(
                    f"{ZIMAGE_TURBO_GUIDANCE}\n\nIMMUTABLE VISUAL INVENTORY:\n"
                    f"{inventory.model_dump_json()}\n\nVISUAL REFERENCE LOCK:\n"
                    f"{visual_anchor}\n\nCANONICAL VISIBLE OBJECT NAME:\n"
                    f"{canonical_lock}\n\nGROUNDED DESCRIPTION:\n{grounded}",
                    max_new_tokens=500,
                ))
                if canonical_lock and canonical_lock[0].lower() not in z_prompt.lower():
                    name = canonical_lock[0]
                    z_prompt = re.sub(
                        r"\b(?:spirit-fruit|fruit|object)\b", name, z_prompt,
                        count=1, flags=re.I,
                    )
                z_prompt = self._enforce_object_correction(z_prompt, canonical_lock)
                z_prompt = self._enforce_support_material(z_prompt, support_lock)
                z_prompt = self._enforce_cradle_materials(z_prompt)
                z_prompt = self._append_visual_lock(z_prompt, inventory)
                if support_lock and support_lock[0].lower() not in z_prompt.lower():
                    z_prompt += f" The visible object and plate rest on {support_lock[0]}."
            finally:
                model.close()

            response = GroundEnhanceResponse(
                status="enhanced",
                requires_confirmation=False,
                frame_description=frame_description,
                visual_inventory=inventory,
                location_candidates=candidates,
                confirmed_passage_ids=confirmed,
                extracted_facts=extracted_facts,
                stages=stages,
                grounded_enhanced_description=grounded,
                zimageturbo_prompt=z_prompt,
            )
            self.service.cache.put(
                "ground_enhance", payload, response.model_dump(mode="json"), version=14
            )
            return response
