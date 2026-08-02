from __future__ import annotations

import argparse
from pathlib import Path

from .embed import embed_passages, load_embeddings_into_graph
from .graph_store import GraphStore
from .pdf_ingest import ingest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and query the local Cradle lore graph")
    parser.add_argument("command", choices=("ingest", "embed", "index", "counts"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "ingest":
        books, chapters, passages = ingest(root)
        store = GraphStore(root)
        store.initialize()
        store.upsert_sources()
        store.export_counts()
        store.close()
        print(f"Ingested {len(books)} books, {len(chapters)} chapters, {len(passages)} passages")
    elif args.command == "embed":
        embed_passages(root)
    elif args.command == "index":
        load_embeddings_into_graph(root)
    else:
        with GraphStore(root) as store:
            print(store.counts())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
