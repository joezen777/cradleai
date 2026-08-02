from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import time
from pathlib import Path

from .graph_store import GraphStore
from .util import read_jsonl


REQUIRED_JSONL = (
    "books.jsonl", "chapters.jsonl", "passages.jsonl",
    "passage_embeddings.jsonl", "passage_extractions.jsonl",
    "chapter_treatments.jsonl", "character_aliases.jsonl",
)


def rebuild(root: Path) -> None:
    data = root / "data"
    with tempfile.TemporaryDirectory(prefix="graph-rebuild-", dir=data) as temporary:
        staged_root = Path(temporary)
        staged_data = staged_root / "data"
        staged_data.mkdir()
        for name in REQUIRED_JSONL:
            shutil.copy2(data / name, staged_data / name)

        with GraphStore(staged_root) as store:
            store.initialize()
            store.upsert_sources()
            store.set_embeddings(
                {"passage_id": row["passage_id"], "embedding": row["embedding"]}
                for row in read_jsonl(staged_data / "passage_embeddings.jsonl")
            )
            store.install_search_indexes()
            store.export_counts()

        # Keep LadybugDB focused on the stable passage search workload. The
        # richer derived relationship graph is materialized in service_index
        # and the exported JSONL catalogs; native LadybugDB derived-node writes
        # have proven unstable under WSL2 at this corpus size.
        staged_graph = staged_data / "lore.lbdb"
        if not staged_graph.is_file():
            raise RuntimeError("staged graph was not created")

        canonical = data / "lore.lbdb"
        if canonical.exists():
            backup = data / f"lore.lbdb.previous-{int(time.time())}"
            os.replace(canonical, backup)
            print(f"Preserved previous graph at {backup}", flush=True)
        canonical_wal = data / "lore.lbdb.wal"
        if canonical_wal.exists():
            os.replace(canonical_wal, data / f"lore.lbdb.wal.previous-{int(time.time())}")
        os.replace(staged_graph, canonical)
        shutil.copy2(staged_data / "graph_counts.json", data / "graph_counts.json")
        print("Atomically installed rebuilt graph", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(); rebuild(args.root.resolve()); return 0


if __name__ == "__main__":
    raise SystemExit(main())
