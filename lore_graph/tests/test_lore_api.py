from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from lore_api.build_indexes import normalize_identifier
from lore_api.cache import PersistentCache
from lore_api.schemas import LocateLoreRequest


class LoreApiUnitTests(unittest.TestCase):
    def test_lore_request_requires_evidence(self):
        with self.assertRaises(ValidationError):
            LocateLoreRequest()

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
