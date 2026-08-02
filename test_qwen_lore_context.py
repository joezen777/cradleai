import json
import unittest

from qwen_media_chat import (
    compact_lore_context, format_lore_context, normalize_clip_lore_answer,
)


class LoreContextCompactionTests(unittest.TestCase):
    def test_drops_recursive_aggregate_fields_and_keeps_citation(self):
        result = {
            "query_interpretation": "orus fruit on table with Kelsa",
            "matches": [{
                "location_in_book": {
                    "book_title": "Unsouled",
                    "chapter_label": "Chapter 2",
                    "page_start": 19,
                    "page_end": 20,
                    "passage_id": "unsouled:chapter:2:passage:009",
                    "surrounding_paragraph": "The fruit sat on Lindon's table.",
                },
                "characters": {
                    "kelsa": {
                        "character_name": "Kelsa",
                        "character_name_normalized": "kelsa",
                        "visual_description_source": ["Kelsa rolled the white fruit."],
                        "character_interactions": ["Prepared to divide the fruit."],
                        "aggregate_character_visual_description": "x" * 400_000,
                        "first_mentioned": {"surrounding_paragraph": "y" * 400_000},
                    }
                },
                "scenery_source": {},
                "props": [],
            }],
        }

        compact = compact_lore_context(result)
        encoded = json.dumps(compact)

        self.assertLess(len(encoded), 24_000)
        self.assertIn("unsouled:chapter:2:passage:009", encoded)
        self.assertIn("Kelsa rolled the white fruit", encoded)
        self.assertNotIn("aggregate_character_visual_description", encoded)
        self.assertNotIn("first_mentioned", encoded)

    def test_formatted_context_obeys_small_budget_approximately(self):
        result = {
            "query_interpretation": "fruit",
            "matches": [{
                "location_in_book": {
                    "passage_id": "p1",
                    "surrounding_paragraph": "fruit " * 5000,
                },
                "characters": {},
                "scenery_source": {},
                "props": [],
            }],
        }
        formatted = format_lore_context(result, max_chars=4000)
        self.assertLess(len(formatted), 5500)
        self.assertIn('"passage_id": "p1"', formatted)

    def test_normalizes_fenced_clip_lore_json(self):
        answer, valid = normalize_clip_lore_answer(
            '```json\n{"video_description":"fruit", "dialog": []}\n```'
        )
        parsed = json.loads(answer)
        self.assertTrue(valid)
        self.assertEqual(parsed["video_description"], "fruit")
        self.assertEqual(parsed["characters_lore"], [])
        self.assertEqual(set(parsed), {
            "video_description", "dialog", "characters_lore",
            "scenery_lore", "magic_lore",
        })


if __name__ == "__main__":
    unittest.main()
