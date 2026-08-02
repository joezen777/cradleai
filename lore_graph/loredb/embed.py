from __future__ import annotations

import gc
from pathlib import Path

from .graph_store import GraphStore
from .util import load_config, read_jsonl, write_jsonl_atomic


def embed_passages(root: Path, batch_size: int = 8) -> list[dict]:
    import torch
    from sentence_transformers import SentenceTransformer

    config = load_config(root)
    passages = read_jsonl(root / "data" / "passages.jsonl")
    output = root / "data" / "passage_embeddings.jsonl"
    existing = {row["passage_id"]: row for row in read_jsonl(output)}
    model = SentenceTransformer(
        config["embedding_model"], device="cuda", local_files_only=True
    )
    try:
        pending = [row for row in passages if row["passage_id"] not in existing]
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            vectors = model.encode(
                [row["text"] for row in batch],
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            for row, vector in zip(batch, vectors):
                existing[row["passage_id"]] = {
                    "passage_id": row["passage_id"],
                    "sha256": row["sha256"],
                    "model": config["embedding_model"],
                    "embedding": vector.tolist(),
                }
            write_jsonl_atomic(output, (existing[key] for key in sorted(existing)))
            print(f"Embedded {min(start + len(batch), len(pending))}/{len(pending)}", flush=True)
    finally:
        try:
            model.to("cpu")
        except Exception:
            pass
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return list(existing.values())


def load_embeddings_into_graph(root: Path) -> None:
    rows = read_jsonl(root / "data" / "passage_embeddings.jsonl")
    store = GraphStore(root)
    store.set_embeddings(rows)
    store.install_search_indexes()
    store.export_counts()
    store.close()
