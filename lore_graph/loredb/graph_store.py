from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import real_ladybug as lb

from .util import read_jsonl


class GraphStore:
    def __init__(self, root: Path, *, read_only: bool = False):
        self.root = root
        self.path = root / "data" / "lore.lbdb"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = lb.Database(str(self.path), read_only=read_only)
        self.conn = lb.Connection(self.db)
        self.closed = False

    def close(self) -> None:
        if self.closed:
            return
        self.conn.close()
        self.db.close()
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def execute_script(self, path: Path) -> None:
        statements = [part.strip() for part in path.read_text(encoding="utf-8").split(";")]
        for statement in statements:
            if statement:
                self.conn.execute(statement)

    def initialize(self) -> None:
        self.execute_script(Path(__file__).with_name("schema.cypher"))

    def upsert_sources(self) -> None:
        books = read_jsonl(self.root / "data" / "books.jsonl")
        chapters = read_jsonl(self.root / "data" / "chapters.jsonl")
        passages = read_jsonl(self.root / "data" / "passages.jsonl")
        for book in books:
            self.conn.execute(
                """MERGE (n:Book {book_id: $book_id}) SET n.title=$title,
                n.author=$author, n.series_number=$series_number, n.pdf=$pdf,
                n.pdf_sha256=$pdf_sha256""",
                book,
            )
        for chapter in chapters:
            values = {**chapter, "treatment": "", "treatment_status": "pending"}
            self.conn.execute(
                """MERGE (n:Chapter {chapter_id: $chapter_id}) SET
                n.book_id=$book_id, n.chapter_number=$chapter_number,
                n.label=$label, n.treatment=$treatment,
                n.treatment_status=$treatment_status""",
                values,
            )
            self.conn.execute(
                """MATCH (b:Book {book_id:$book_id}),
                (c:Chapter {chapter_id:$chapter_id})
                MERGE (b)-[:ContainsChapter]->(c)""",
                values,
            )
        empty_embedding = [0.0] * 1024
        for passage in passages:
            values = {**passage, "embedding": empty_embedding}
            self.conn.execute(
                """MERGE (n:Passage {passage_id:$passage_id}) SET
                n.chapter_id=$chapter_id, n.book_id=$book_id,
                n.sequence=$sequence, n.page_start=$page_start,
                n.page_end=$page_end, n.word_count=$word_count,
                n.sha256=$sha256, n.text=$text, n.embedding=$embedding""",
                values,
            )
            self.conn.execute(
                """MATCH (c:Chapter {chapter_id:$chapter_id}),
                (p:Passage {passage_id:$passage_id})
                MERGE (c)-[:ContainsPassage]->(p)""",
                values,
            )

    def set_embeddings(self, rows: Iterable[dict]) -> None:
        for row in rows:
            self.conn.execute(
                "MATCH (p:Passage {passage_id:$passage_id}) SET p.embedding=$embedding",
                row,
            )

    def install_search_indexes(self) -> None:
        # Extensions download once from Ladybug's official extension repository.
        self.conn.execute("INSTALL fts; LOAD fts")
        self.conn.execute("INSTALL vector; LOAD vector")
        try:
            self.conn.execute("CALL DROP_FTS_INDEX('Passage', 'passage_text_fts')")
        except Exception:
            pass
        try:
            self.conn.execute("CALL DROP_VECTOR_INDEX('Passage', 'passage_embedding_hnsw')")
        except Exception:
            pass
        self.conn.execute(
            "CALL CREATE_FTS_INDEX('Passage', 'passage_text_fts', ['text'])"
        )
        self.conn.execute(
            """CALL CREATE_VECTOR_INDEX('Passage', 'passage_embedding_hnsw',
            'embedding', metric := 'cosine')"""
        )

    def counts(self) -> dict[str, int]:
        result = {}
        for label in ("Book", "Chapter", "Passage", "Character", "Setting", "Item", "Description"):
            cursor = self.conn.execute(f"MATCH (n:{label}) RETURN count(n)")
            result[label] = int(cursor.get_next()[0])
        return result

    def export_counts(self) -> None:
        path = self.root / "data" / "graph_counts.json"
        path.write_text(json.dumps(self.counts(), indent=2) + "\n", encoding="utf-8")
