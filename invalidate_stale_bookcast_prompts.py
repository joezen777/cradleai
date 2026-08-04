#!/usr/bin/env python3
"""Clear zimageturbo_prompt on records whose portrait_description changed
since a given backup, so generate_bookcast_zimageturbo.py's Phase 1 resumes
and regenerates only the prompts that are actually stale. image_generations
and the rendered image are left untouched — only the prompt is cleared.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", type=Path, default=Path("bookcast.jsonl"))
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    backup_by_key = {r["identity_key"]: r for r in load_jsonl(args.backup)}
    current = load_jsonl(args.current)

    changed = 0
    for record in current:
        old = backup_by_key.get(record["identity_key"])
        old_portrait = (old or {}).get("portrait_description", "")
        if record.get("portrait_description", "") != old_portrait and record.get("zimageturbo_prompt"):
            changed += 1
            if not args.dry_run:
                record.pop("zimageturbo_prompt", None)
                record.pop("prompt_optimized_at", None)

    print(f"{changed}/{len(current)} records have a changed portrait_description "
          f"{'(dry run, nothing written)' if args.dry_run else 'and had their stale prompt cleared'}")

    if not args.dry_run and changed:
        tmp = args.current.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in current))
        tmp.replace(args.current)
        print(f"Wrote {args.current}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
