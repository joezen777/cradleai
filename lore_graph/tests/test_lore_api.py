from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from lore_api.build_indexes import normalize_identifier
from lore_api.cache import PersistentCache
from lore_api.schemas import (
    FrameVisualInventory,
    GroundEnhanceRequest,
    GroundEnhanceResponse,
    LocateLoreRequest,
)


class LoreApiUnitTests(unittest.TestCase):
    def test_lore_request_requires_evidence(self):
        with self.assertRaises(ValidationError):
            LocateLoreRequest()

    def test_ground_enhance_requires_frame_and_pegasus_context(self):
        with self.assertRaises(ValidationError):
            GroundEnhanceRequest(frame_image="frame.png", pegasus_chapter_context="")

    def test_location_candidate_response_carries_immutable_inventory(self):
        response = GroundEnhanceResponse(
            status="location_candidates",
            requires_confirmation=True,
            frame_description="A segmented object sits on a plate.",
            visual_inventory=FrameVisualInventory(
                composition="Centered close-up",
                visible_human_count=0,
                visible_objects=["one segmented object", "one plate"],
                visible_background=["flat gray field"],
                setting_visible=False,
            ),
            location_candidates=[],
        )
        self.assertEqual(response.visual_inventory.visible_human_count, 0)
        self.assertFalse(response.visual_inventory.setting_visible)

    def test_explicit_prop_name_can_be_locked_from_cited_sentence(self):
        from lore_api.ground_enhancer import GroundEnhancer

        lock = GroundEnhancer._canonical_object_lock([{
            "passage_id": "unsouled:chapter:3:passage:001",
            "source_sentence": (
                "Kelsa held up the white orus, the spirit-fruit Lindon had hunted for."
            ),
        }])
        self.assertEqual(lock, ("white orus spirit-fruit", "unsouled:chapter:3:passage:001"))

    def test_zimage_prompt_cleanup_removes_markdown_label(self):
        from lore_api.ground_enhancer import GroundEnhancer

        self.assertEqual(
            GroundEnhancer._clean_zimage_prompt("**Prompt:**\n\nA white orus."),
            "A white orus.",
        )

    def test_visual_lock_preserves_expression_gaze_action_and_support(self):
        from lore_api.ground_enhancer import GroundEnhancer

        inventory = FrameVisualInventory(
            composition="tight three-quarter close-up",
            visible_human_count=1,
            camera_and_framing="slightly elevated angle",
            subject_positions=["young man at left-center"],
            posture_gaze_and_action=[
                "right hand extended toward the fruit",
                "eyes looking down at the fruit",
                "focused, wary expression",
            ],
            visible_appearance=["warm brown skin and black hair"],
            visible_objects=["white segmented orus fruit", "ceramic plate"],
            support_and_contact=["fruit rests on plate; plate rests on table"],
            background_geometry=["wooden table fills lower foreground"],
        )
        lock = GroundEnhancer._visual_lock_text(inventory)
        self.assertIn("eyes looking down at the fruit", lock)
        self.assertIn("focused, wary expression", lock)
        self.assertIn("right hand extended", lock)
        self.assertIn("plate rests on table", lock)
        prompt = GroundEnhancer._append_visual_lock("A live-action still.", inventory)
        self.assertIn("Frame continuity lock:", prompt)

    def test_fact_extraction_keeps_categories_and_rejects_unknown_passages(self):
        from lore_api.ground_enhancer import GroundEnhancer

        class FakeModel:
            def generate_json(self, prompt, max_new_tokens=1500):
                return {
                    "characters": [{
                        "visible_figure": "figure at left",
                        "canonical_name": "Lindon",
                        "facts": ["dark hair"],
                        "passage_id": "p1",
                    }],
                    "props": [{
                        "visible_object": "round fruit",
                        "canonical_name": "white orus spirit-fruit",
                        "facts": ["segmented white shell"],
                        "passage_id": "unknown",
                    }],
                }

        inventory = FrameVisualInventory(composition="close-up", visible_human_count=1)
        evidence = {"passages": [{"passage_id": "p1"}], "characters": [], "scenery": [], "props": []}
        enhancer = GroundEnhancer.__new__(GroundEnhancer)
        facts = enhancer._extract_facts(FakeModel(), inventory, evidence)
        self.assertEqual(facts["characters"][0]["canonical_name"], "Lindon")
        self.assertEqual(facts["props"], [])

    def test_phase1_resume_requires_fact_trace_for_grounded_records(self):
        from generate_prompts_from_metadata import PromptGenerationPhase1

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadatagen.jsonl"
            path.write_text(
                json.dumps({"frame_file": "old.png", "prompt_text": "old", "gcp_success": True})
                + "\n"
                + json.dumps({"frame_file": "new.png", "prompt_text": "new", "gcp_success": True, "extracted_facts": {}})
                + "\n",
                encoding="utf-8",
            )
            phase = PromptGenerationPhase1.__new__(PromptGenerationPhase1)
            phase.metadatagen_file = str(path)
            phase.ground_enhance = True
            self.assertEqual(phase._get_processed_frames(), {"new.png"})

    def test_unnamed_ids_are_deterministic_and_passage_scoped(self):
        left = normalize_identifier(
            "unnamed Wei clan elder", "character:unsouled:chapter:1:passage:001:unnamed"
        )
        repeated = normalize_identifier(
            "unnamed Wei clan elder", "character:unsouled:chapter:1:passage:001:unnamed"
        )
        right = normalize_identifier(
            "unnamed Wei clan elder", "character:unsouled:chapter:2:passage:001:unnamed"
        )
        self.assertEqual(left, repeated)
        self.assertNotEqual(left, right)

    def test_persistent_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = PersistentCache(Path(directory) / "cache.sqlite3")
            cache.put("test", {"b": 2, "a": 1}, {"ok": True})
            self.assertEqual(cache.get("test", {"a": 1, "b": 2}), {"ok": True})


class LoreApiIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        (Path(__file__).resolve().parents[1] / "data" / "service_index.json").is_file(),
        "service index has not been built",
    )
    def test_health_and_exact_character_lookup(self):
        from lore_api.app import app

        root = Path(__file__).resolve().parents[1]
        index = json.loads((root / "data" / "service_index.json").read_text())
        normalized = next(iter(index["characters"].values()))["character_name_normalized"]
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            response = client.post(
                "/v1/characters/locate",
                json={"character_name_normalized": normalized},
            )
            self.assertEqual(response.status_code, 200)
            self.assertGreaterEqual(len(response.json()), 1)


if __name__ == "__main__":
    unittest.main()
