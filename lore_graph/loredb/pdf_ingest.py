from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .util import load_config, write_jsonl_atomic

CHAPTER_HEADING = re.compile(r"^(PROLOGUE|CHAPTER[\t ]+(\d+))\s*$", re.I | re.M)


@dataclass
class PageText:
    page: int
    text: str


def normalize_page(text: str) -> str:
    text = text.replace("\x00", "").replace("\t", " ")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"[ \u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def paragraphize(text: str) -> list[str]:
    # Ebook PDFs often encode paragraphs as wrapped lines with no blank line.
    lines = [line.strip() for line in text.splitlines()]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if CHAPTER_HEADING.fullmatch(line):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            paragraphs.append(line)
            continue
        current.append(line)
        if re.search(r"[.!?…][\"'’”)]?$", line):
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return [re.sub(r"\s+", " ", value).strip() for value in paragraphs if value.strip()]


def extract_chapters(pdf: Path, book: dict) -> list[dict]:
    pages = [
        PageText(index + 1, normalize_page(page.extract_text() or ""))
        for index, page in enumerate(PdfReader(pdf).pages)
    ]
    start_index = next(
        (
            index
            for index, page in enumerate(pages)
            if len(CHAPTER_HEADING.findall(page.text)) == 1
            and CHAPTER_HEADING.search(page.text)
            and len(page.text[CHAPTER_HEADING.search(page.text).end():].split()) >= 30
        ),
        None,
    )
    if start_index is None:
        raise ValueError(f"Could not locate first body chapter in {pdf}")
    pages = pages[start_index:]
    chapters: list[dict] = []
    current: dict | None = None
    for page in pages:
        matches = list(CHAPTER_HEADING.finditer(page.text))
        if not matches:
            if current is not None and page.text:
                current["pages"].append(page)
            continue
        cursor = 0
        for match in matches:
            before = page.text[cursor:match.start()].strip()
            if before and current is not None:
                current["pages"].append(PageText(page.page, before))
            if current is not None:
                chapters.append(current)
            label = match.group(1).upper().replace("\t", " ")
            number = 0 if label == "PROLOGUE" else int(match.group(2))
            current = {
                "book_id": book["book_id"],
                "chapter_id": f"{book['book_id']}:chapter:{number}",
                "chapter_number": number,
                "label": "Prologue" if number == 0 else f"Chapter {number}",
                "pages": [],
            }
            cursor = match.end()
        remainder = page.text[cursor:].strip()
        if remainder and current is not None:
            current["pages"].append(PageText(page.page, remainder))
    if current is not None:
        chapters.append(current)
    return chapters


def chunk_chapter(chapter: dict, target: int, maximum: int, overlap: int) -> list[dict]:
    units: list[tuple[int, str]] = []
    for page in chapter["pages"]:
        units.extend((page.page, paragraph) for paragraph in paragraphize(page.text))
    chunks: list[dict] = []
    start = 0
    sequence = 1
    while start < len(units):
        end = start
        words = 0
        while end < len(units):
            next_words = len(units[end][1].split())
            if end > start and words >= target:
                break
            if end > start and words + next_words > maximum:
                break
            words += next_words
            end += 1
        if end == start:
            end += 1
        selected = units[start:end]
        text = "\n\n".join(value for _, value in selected)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        passage_id = f"{chapter['chapter_id']}:passage:{sequence:03d}"
        chunks.append({
            "passage_id": passage_id,
            "book_id": chapter["book_id"],
            "chapter_id": chapter["chapter_id"],
            "chapter_number": chapter["chapter_number"],
            "chapter_label": chapter["label"],
            "sequence": sequence,
            "page_start": selected[0][0],
            "page_end": selected[-1][0],
            "word_count": len(text.split()),
            "sha256": digest,
            "text": text,
        })
        if end >= len(units):
            break
        start = max(start + 1, end - overlap)
        sequence += 1
    return chunks


def ingest(root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    config = load_config(root)
    books: list[dict] = []
    chapter_rows: list[dict] = []
    passages: list[dict] = []
    for spec in config["books"]:
        pdf = (root / spec["pdf"]).resolve()
        if not pdf.is_file():
            raise FileNotFoundError(pdf)
        book = {**spec, "pdf": str(pdf), "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()}
        books.append(book)
        chapters = extract_chapters(pdf, book)
        for chapter in chapters:
            chapter_rows.append({key: value for key, value in chapter.items() if key != "pages"})
            passages.extend(chunk_chapter(
                chapter,
                int(config["chunking"]["target_words"]),
                int(config["chunking"]["maximum_words"]),
                int(config["chunking"]["overlap_paragraphs"]),
            ))
    data = root / "data"
    write_jsonl_atomic(data / "books.jsonl", books)
    write_jsonl_atomic(data / "chapters.jsonl", chapter_rows)
    write_jsonl_atomic(data / "passages.jsonl", passages)
    return books, chapter_rows, passages
