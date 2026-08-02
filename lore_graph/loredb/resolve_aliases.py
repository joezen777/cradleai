from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

from .util import read_jsonl, write_jsonl_atomic


CANONICAL_NAME_OVERRIDES = {
    "elder whisper": "Elder Whisper",
    "whisper": "Elder Whisper",
    "forger on the path of the white fox": "Elder Whisper",
    "first elder": "First Elder",
    "the first elder": "First Elder",
}


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, value: str) -> str:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def build(root: Path) -> list[dict]:
    uf = UnionFind()
    spellings: dict[str, Counter] = defaultdict(Counter)
    sources: dict[str, set[str]] = defaultdict(set)
    for row in read_jsonl(root / "data" / "passage_extractions.jsonl"):
        if not str(row.get("status") or "").startswith("success"):
            continue
        for character in row.get("characters", []):
            if not character.get("named"):
                continue
            primary = str(character.get("name_or_label") or "").strip()
            names = [primary, *(str(x).strip() for x in character.get("aliases_seen", []))]
            names = [name for name in names if normalized(name)]
            if not names:
                continue
            keys = [normalized(name) for name in names]
            primary_canonical = CANONICAL_NAME_OVERRIDES.get(keys[0])
            if primary_canonical:
                filtered = [
                    (name, key) for name, key in zip(names, keys)
                    if CANONICAL_NAME_OVERRIDES.get(key, primary_canonical) == primary_canonical
                ]
                names = [name for name, _ in filtered]
                keys = [key for _, key in filtered]
            for name, key in zip(names, keys):
                spellings[key][name] += 1
                sources[key].add(row["passage_id"])
            for key in keys[1:]:
                uf.union(keys[0], key)
    groups: dict[str, set[str]] = defaultdict(set)
    for key in spellings:
        groups[uf.find(key)].add(key)
    rows = []
    for keys in groups.values():
        candidates = Counter()
        passages = set()
        for key in keys:
            candidates.update(spellings[key])
            passages.update(sources[key])
        forced = {CANONICAL_NAME_OVERRIDES[key] for key in keys if key in CANONICAL_NAME_OVERRIDES}
        canonical = next(iter(forced)) if len(forced) == 1 else max(
            candidates, key=lambda name: (candidates[name], len(name), name)
        )
        rows.append({
            "canonical_name": canonical,
            "normalized_aliases": sorted(keys),
            "aliases": sorted(candidates),
            "supporting_passage_ids": sorted(passages),
            "resolution_method": "explicit-source-alias-union",
        })
    rows.sort(key=lambda row: row["canonical_name"].casefold())
    write_jsonl_atomic(root / "data" / "character_aliases.jsonl", rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    rows = build(args.root.resolve())
    print(f"Resolved {sum(len(row['normalized_aliases']) for row in rows)} names into {len(rows)} source-supported characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
