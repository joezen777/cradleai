from __future__ import annotations

import argparse
from pathlib import Path

from .graph_store import GraphStore
from .util import load_config


def rows(cursor) -> list[dict]:
    names = cursor.get_column_names()
    output = []
    while cursor.has_next():
        output.append(dict(zip(names, cursor.get_next())))
    return output


def hybrid_search(root: Path, query: str, limit: int = 8, book_id: str | None = None) -> list[dict]:
    from sentence_transformers import SentenceTransformer

    store = GraphStore(root)
    store.conn.execute("LOAD fts; LOAD vector")
    config = load_config(root)
    model = SentenceTransformer(
        config["embedding_model"], device="cuda", local_files_only=True
    )
    vector = model.encode(query, normalize_embeddings=True).tolist()
    lexical = rows(store.conn.execute(
        """CALL QUERY_FTS_INDEX('Passage', 'passage_text_fts', $query, top := $top)
        RETURN node.passage_id AS passage_id, node.book_id AS book_id,
        node.chapter_id AS chapter_id, node.page_start AS page_start,
        node.page_end AS page_end, node.text AS text, score""",
        {"query": query, "top": limit * 4},
    ))
    semantic = rows(store.conn.execute(
        """CALL QUERY_VECTOR_INDEX('Passage', 'passage_embedding_hnsw', $vector, $top)
        RETURN node.passage_id AS passage_id, node.book_id AS book_id,
        node.chapter_id AS chapter_id, node.page_start AS page_start,
        node.page_end AS page_end, node.text AS text, distance""",
        {"vector": vector, "top": limit * 4},
    ))
    if book_id:
        lexical = [row for row in lexical if row["book_id"] == book_id]
        semantic = [row for row in semantic if row["book_id"] == book_id]
    scores: dict[str, float] = {}
    records = {}
    for result_set in (lexical, semantic):
        for rank, row in enumerate(result_set, 1):
            pid = row["passage_id"]
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (60 + rank)
            records[pid] = row
    ordered = sorted(scores, key=scores.get, reverse=True)[:limit]
    return [{**records[pid], "rrf_score": scores[pid]} for pid in ordered]


def character_dossier(root: Path, name: str) -> list[dict]:
    store = GraphStore(root)
    return rows(store.conn.execute(
        """MATCH (c:Character)-[:MentionedIn]->(h:Chapter)
        WHERE lower(c.canonical_name) CONTAINS lower($name)
           OR lower(c.stable_label) CONTAINS lower($name)
        OPTIONAL MATCH (d:Description)-[:DescribesCharacter]->(c)
        OPTIONAL MATCH (d)-[:DescriptionSource]->(p:Passage)
        RETURN c.character_id AS character_id, c.canonical_name AS canonical_name,
        c.stable_label AS stable_label, collect(DISTINCT h.chapter_id) AS chapters,
        collect(DISTINCT {quote:d.exact_quote, normalized:d.normalized_description,
        passage_id:p.passage_id, pages:[p.page_start,p.page_end]}) AS descriptions""",
        {"name": name},
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("search", "character"))
    parser.add_argument("query")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--book", choices=("unsouled", "soulsmith"))
    args = parser.parse_args()
    if args.mode == "search":
        result = hybrid_search(args.root.resolve(), args.query, args.limit, args.book)
    else:
        result = character_dossier(args.root.resolve(), args.query)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
