from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from .cache import PersistentCache
from .image_interpreter import ImageInterpreter
from .retrieval import HybridRetriever
from .schemas import (
    CharacterContext, CharacterLookupRequest, LocateLoreRequest, LocateLoreResponse,
    LocationInBook, LoreContextResult, PropContext, PropLookupRequest,
    MacroSceneryContext, SceneryContext, SceneryLookupRequest,
    GroundEnhanceRequest, GroundEnhanceResponse,
)


class LoreService:
    def __init__(self, root: Path):
        self.root = root.resolve()
        index_path = self.root / "data" / "service_index.json"
        if not index_path.is_file():
            raise RuntimeError("service_index.json is missing; finish lore processing first")
        self.index = json.loads(index_path.read_text(encoding="utf-8"))
        cache_root = Path(
            os.environ.get(
                "CRADLE_LORE_CACHE_DIR",
                Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
                / "cradle-lore-mcp",
            )
        ).expanduser().resolve()
        cache_root.mkdir(parents=True, exist_ok=True)
        self.cache = PersistentCache(cache_root / "lore_api.sqlite3")
        self.retriever = HybridRetriever(self.root)
        project_root = Path(os.environ.get("CRADLE_PROJECT_ROOT", Path.cwd()))
        self.images = ImageInterpreter(project_root, self.cache)
        self._ground_enhancer = None

    def ground_enhance(self, request: GroundEnhanceRequest) -> GroundEnhanceResponse:
        if self._ground_enhancer is None:
            from .ground_enhancer import GroundEnhancer
            self._ground_enhancer = GroundEnhancer(self)
        return self._ground_enhancer.enhance(request)

    def _first_location(self, records: list[dict]) -> dict | None:
        if not records: return None
        ordered = sorted(records, key=lambda x: (
            1 if x.get("book_id") == "unsouled" else 2,
            int(x.get("chapter_number", 999)), x.get("passage_id", "")
        ))
        pid = ordered[0].get("passage_id")
        return self.index["passage_context"].get(pid, {}).get("location")

    def _character(self, cid: str, pid: str) -> CharacterContext:
        character = self.index["characters"][cid]
        descriptions = [
            value["exact_quote"] for value in character.get("visual_descriptions", [])
            if value.get("passage_id") == pid and value.get("exact_quote")
        ]
        appearances = [value for value in character.get("appearances", []) if value.get("passage_id") == pid]
        dialogs = self.index["passage_context"].get(pid, {}).get("dialogs", {}).get(cid, [])
        return CharacterContext(
            character_name=character.get("canonical_name") or character["stable_label"],
            character_name_normalized=character["character_name_normalized"],
            visual_description_source=descriptions,
            aggregate_character_visual_description=character.get("aggregate_character_visual_description", ""),
            appearance_changes=character.get("appearance_changes", []),
            character_interactions=[value.get("action_summary", "") for value in appearances if value.get("action_summary")],
            character_dialog=dialogs,
            first_mentioned=self._first_location(character.get("appearances", [])),
        )

    def _scenery(self, sid: str, pid: str) -> SceneryContext:
        setting = self.index["settings"][sid]
        source_desc = [
            value["exact_quote"] for value in setting.get("visual_descriptions", [])
            if value.get("passage_id") == pid and value.get("exact_quote")
        ]
        from .build_indexes import classify_scenery
        passage_text = self.index["passages"][pid]["text"]
        classified = classify_scenery(setting["name"], source_desc, passage_text)
        macro_context = [
            MacroSceneryContext.model_validate(self.index["macro_scenery"][macro_id])
            for macro_id in setting.get("macro_scenery_ids", [])
            if macro_id in self.index.get("macro_scenery", {})
        ]
        return SceneryContext(
            weather=classified["weather"], time_of_day=classified["time_of_day"],
            climate=classified["climate"], setting=classified["setting"],
            location=" ".join(source_desc) or setting["name"],
            location_name_normalized=setting["location_name_normalized"],
            backdrop=classified["backdrop"], visual_description_source=source_desc,
            first_mentioned=self._first_location(setting.get("passages", [])),
            macro_scenery_context=macro_context,
        )

    def _prop(self, iid: str, pid: str) -> PropContext:
        prop = self.index["props"][iid]
        source = [
            value["exact_quote"] for value in prop.get("visual_descriptions", [])
            if value.get("passage_id") == pid and value.get("exact_quote")
        ]
        links = [value for value in prop.get("character_links", []) if value.get("passage_id") == pid]
        character_normalized = None
        if links:
            char = self.index["characters"].get(links[0]["character_id"])
            character_normalized = char.get("character_name_normalized") if char else None
        placement = "; ".join(value.get("relationship", "") for value in links) or "mentioned in scene"
        return PropContext(
            character_name_normalized=character_normalized, placement=placement,
            source_description=source, prop_name=prop["name"],
            prop_name_normalized=prop["prop_name_normalized"],
            first_mentioned=self._first_location(prop.get("passages", [])),
        )

    def _result(self, hit: dict) -> LoreContextResult:
        pid = hit["passage_id"]; context = self.index["passage_context"][pid]
        location = {**context["location"], "confidence_rating": hit["confidence"]}
        characters = {
            self.index["characters"][cid]["character_name_normalized"]: self._character(cid, pid)
            for cid in context["character_ids"] if cid in self.index["characters"]
        }
        scenery = {
            self.index["settings"][sid]["location_name_normalized"]: self._scenery(sid, pid)
            for sid in context["setting_ids"] if sid in self.index["settings"]
        }
        props = [self._prop(iid, pid) for iid in context["prop_ids"] if iid in self.index["props"]]
        return LoreContextResult(
            location_in_book=LocationInBook(**location), characters=characters,
            scenery_source=scenery, props=props,
        )

    def _source_token_score(self, row: dict, query: str) -> float:
        tokens = {
            token for token in re.findall(r"[a-z0-9]+", query.casefold())
            if len(token) > 2 and token not in {"and", "the", "with", "from", "into", "their"}
        }
        citations = row.get("passages") or row.get("appearances") or []
        source = " ".join(
            self.index["passages"].get(citation.get("passage_id"), {}).get("text", "")
            for citation in citations
        )
        descriptions = " ".join(
            str(value.get("exact_quote") or value.get("normalized_description") or "")
            for value in row.get("visual_descriptions", [])
        )
        name = f"{row.get('name','')} {row.get('stable_label','')}".casefold()
        source_folded = source.casefold(); descriptions_folded = descriptions.casefold()
        matches = sum(token in source_folded for token in tokens)
        description_matches = sum(token in descriptions_folded for token in tokens)
        name_matches = sum(token in name for token in tokens)
        # Prefer the specific scene/entity that contains the evidence over a
        # broad location such as “Sacred Valley” linked to dozens of passages.
        specificity = max(1.0, len(citations) ** 0.5)
        return float(matches + 2 * description_matches + 3 * name_matches) / specificity

    def _passage_query_score(self, passage_id: str, query: str) -> float:
        """Favor passages containing several distinct pieces of scene evidence."""
        ignored = {
            "and", "the", "with", "from", "into", "their", "this", "that",
            "where", "while", "using", "scene", "frame", "first", "lore",
        }
        tokens = {
            token for token in re.findall(r"[a-z0-9]+", query.casefold())
            if len(token) > 2 and token not in ignored
        }
        if not tokens:
            return 0.0
        source = self.index["passages"].get(passage_id, {}).get("text", "").casefold()
        matched = {token for token in tokens if token in source}
        # Coverage matters more than repeated generic mentions. The squared
        # numerator rewards a passage joining multiple clues (Kelsa + Iron +
        # fruit + family) instead of a broad passage matching only "fruit".
        return (len(matched) ** 2) / len(tokens)

    def locate_lore(self, request: LocateLoreRequest) -> LocateLoreResponse:
        payload = {
            "corpus_fingerprint": self.index["corpus_fingerprint"],
            "request": request.model_dump(),
        }
        cached = self.cache.get("locate_lore_context", payload, version=3)
        if cached is not None:
            cached["cache_hit"] = True; return LocateLoreResponse.model_validate(cached)
        parts = []
        focus_parts = []
        if request.highlighted_summary: parts.append("HIGHLIGHTED EVENT: " + request.highlighted_summary)
        if request.highlighted_summary: focus_parts.append(request.highlighted_summary)
        if request.description:
            parts.append("DESCRIPTION: " + request.description)
            focus_parts.append(request.description)
        if request.transcript:
            parts.append("DIALOGUE/TRANSCRIPT: " + request.transcript)
            focus_parts.append(request.transcript)
        if request.frame_image:
            frame_description = self.images.describe(request.frame_image)
            parts.append("VISIBLE FRAME: " + frame_description)
            focus_parts.append(frame_description)
        if request.pegasus_chapter_summary: parts.append("CHAPTER CONTEXT: " + request.pegasus_chapter_summary)
        query = "\n".join(parts)
        focus_query = "\n".join(focus_parts) or query
        candidates = [
            hit for hit in self.retriever.search(query, max(30, request.max_locations * 10))
            if hit["passage_id"] in self.index["passage_context"]
        ]
        hits = sorted(
            candidates,
            key=lambda hit: (
                self._passage_query_score(hit["passage_id"], focus_query),
                hit.get("confidence", 0.0),
            ),
            reverse=True,
        )[:request.max_locations]
        response = LocateLoreResponse(
            matches=[self._result(hit) for hit in hits],
            query_interpretation=query, cache_hit=False,
        )
        self.cache.put("locate_lore_context", payload, response.model_dump(mode="json"), version=3)
        return response

    def locate_characters(self, request: CharacterLookupRequest) -> list[CharacterContext]:
        cache_key = {"corpus_fingerprint": self.index["corpus_fingerprint"], "request": request.model_dump()}
        cached = self.cache.get("locate_character_context", cache_key, version=2)
        if cached is not None:
            return [CharacterContext.model_validate(row) for row in cached]
        exact = request.character_name_normalized
        candidates = []
        if exact:
            candidates = [cid for cid, row in self.index["characters"].items()
                          if row["character_name_normalized"] == exact]
        else:
            hits = self.retriever.search(request.description or "", 30)
            counts = Counter(cid for hit in hits for cid in self.index["passage_context"].get(hit["passage_id"], {}).get("character_ids", []))
            query = request.description or ""
            candidates = sorted(
                self.index["characters"],
                key=lambda cid: (self._source_token_score(self.index["characters"][cid], query) * 10 + counts[cid]),
                reverse=True,
            )[:request.max_results]
        output = [self._character(cid, self.index["characters"][cid]["appearances"][0]["passage_id"])
                  for cid in candidates[:request.max_results]]
        self.cache.put("locate_character_context", cache_key, [row.model_dump(mode="json") for row in output], version=2)
        return output

    def locate_scenery(self, request: SceneryLookupRequest) -> list[SceneryContext]:
        cache_key = {"corpus_fingerprint": self.index["corpus_fingerprint"], "request": request.model_dump()}
        cached = self.cache.get("locate_scenery_context", cache_key, version=2)
        if cached is not None:
            return [SceneryContext.model_validate(row) for row in cached]
        if request.scenery_name_normalized:
            candidates = [sid for sid,row in self.index["settings"].items()
                          if row["location_name_normalized"] == request.scenery_name_normalized]
        else:
            hits=self.retriever.search(request.description or "",30)
            counts=Counter(sid for hit in hits for sid in self.index["passage_context"].get(hit["passage_id"],{}).get("setting_ids",[]))
            query = request.description or ""
            candidates = sorted(
                self.index["settings"],
                key=lambda sid: (self._source_token_score(self.index["settings"][sid], query) * 10 + counts[sid]),
                reverse=True,
            )[:request.max_results]
        output = [self._scenery(sid, self.index["settings"][sid]["passages"][0]["passage_id"])
                  for sid in candidates[:request.max_results]]
        self.cache.put("locate_scenery_context", cache_key, [row.model_dump(mode="json") for row in output], version=2)
        return output

    def locate_props(self, request: PropLookupRequest) -> list[PropContext]:
        cache_key = {"corpus_fingerprint": self.index["corpus_fingerprint"], "request": request.model_dump()}
        cached = self.cache.get("locate_prop_context", cache_key, version=2)
        if cached is not None:
            return [PropContext.model_validate(row) for row in cached]
        if request.prop_name_normalized:
            candidates=[iid for iid,row in self.index["props"].items()
                        if row["prop_name_normalized"] == request.prop_name_normalized]
        else:
            hits=self.retriever.search(request.description or "",40)
            counts=Counter(iid for hit in hits for iid in self.index["passage_context"].get(hit["passage_id"],{}).get("prop_ids",[]))
            query = request.description or ""
            candidates = sorted(
                self.index["props"],
                key=lambda iid: (self._source_token_score(self.index["props"][iid], query) * 10 + counts[iid]),
                reverse=True,
            )[:10]
        output = [self._prop(iid, self.index["props"][iid]["passages"][0]["passage_id"])
                  for iid in candidates[:min(request.max_results,10)]]
        self.cache.put("locate_prop_context", cache_key, [row.model_dump(mode="json") for row in output], version=2)
        return output
