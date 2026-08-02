from __future__ import annotations

import threading
from pathlib import Path

from loredb.graph_store import GraphStore
from loredb.util import load_config


def cursor_rows(cursor) -> list[dict]:
    names = cursor.get_column_names(); output = []
    while cursor.has_next(): output.append(dict(zip(names, cursor.get_next())))
    return output


class HybridRetriever:
    def __init__(self, root: Path):
        self.root = root
        self.config = load_config(root)
        self.store = GraphStore(root, read_only=True)
        self.store.conn.execute("LOAD fts; LOAD vector")
        self.model = None
        self.lock = threading.RLock()

    def _model(self):
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(
                self.config["embedding_model"], device="cuda", local_files_only=True
            )
        return self.model

    def search(self, query: str, limit: int = 10) -> list[dict]:
        with self.lock:
            # Model loading, CUDA inference, and the embedded graph connection
            # are intentionally serialized inside one process.
            vector = self._model().encode(query, normalize_embeddings=True).tolist()
            lexical = cursor_rows(self.store.conn.execute(
                """CALL QUERY_FTS_INDEX('Passage','passage_text_fts',$query,top := $top)
                RETURN node.passage_id AS passage_id, score""",
                {"query": query, "top": max(limit * 4, 20)},
            ))
            semantic = cursor_rows(self.store.conn.execute(
                """CALL QUERY_VECTOR_INDEX('Passage','passage_embedding_hnsw',$vector,$top)
                RETURN node.passage_id AS passage_id, distance""",
                {"vector": vector, "top": max(limit * 4, 20)},
            ))
        scores = {}; modes = {}; semantic_similarity = {}; lexical_rank = {}
        for mode, result_set in (("lexical", lexical), ("semantic", semantic)):
            for rank, row in enumerate(result_set, 1):
                pid = row["passage_id"]
                scores[pid] = scores.get(pid, 0.0) + 1.0 / (60 + rank)
                modes.setdefault(pid, []).append(mode)
                if mode == "semantic":
                    semantic_similarity[pid] = max(
                        0.0, min(1.0, 1.0 - float(row["distance"]))
                    )
                else:
                    lexical_rank[pid] = rank
        ordered = sorted(scores, key=scores.get, reverse=True)[:limit]
        return [
            {
                "passage_id": pid,
                "rrf_score": scores[pid],
                "retrieval_modes": modes[pid],
                # Calibrate against absolute cosine similarity rather than
                # declaring the best member of every query 98% correct.
                "confidence": min(
                    0.98,
                    max(
                        0.05,
                        0.72 * semantic_similarity.get(pid, 0.0)
                        + (0.14 if len(modes[pid]) == 2 else 0.0)
                        + (0.10 / lexical_rank[pid] if pid in lexical_rank else 0.0),
                    ),
                ),
            }
            for pid in ordered
        ]
