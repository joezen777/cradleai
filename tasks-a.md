# Track A — First-Mention Evidence on the Book Cast Card

**Request:** under the character title and first-appearance location, and below the tags,
show (a) the book sentence where the character was first mentioned, then (b) a series of
phrases found near that passage that describe the character.

**Depends on:** nothing. Code can be written in parallel with Track B; the data-rewrite
step (A4) must be serialized against Track B's rewrite (see [tasks.md](tasks.md)).

**Owns fields:** `first_mention`, `descriptive_phrases`.

---

## Where the data already lives

Both pieces exist in `lore_graph/data/service_index.json` and need no LLM call:

| Card element | Source | Notes |
| --- | --- | --- |
| First-mention sentence | `passage_context[<pid>].location.surrounding_paragraph` | Multi-paragraph blob; must be segmented and the right sentence selected |
| Descriptive phrases | `characters[<cid>].visual_descriptions[].exact_quote` | Filter to the first-appearance `passage_id` |
| Book / chapter / page | `passage_context[<pid>].location` | Already exact; better than the current regex scraping |

The anchor passage is `characters[<cid>].appearances[0].passage_id`, which each record
already carries as `evidence_notes.passage_id`, and `source_character_ids[0]` gives the
character ID.

The equivalent MCP path is `locate_character_context` → `first_mentioned` and
`visual_description_source` ([service.py:56](lore_graph/lore_api/service.py:56) filters
quotes to the first-appearance passage — exactly "phrases near that passage"). Use the
index directly so the backfill needs no running server; keep MCP as a cross-check.

---

## A1. Write the sentence extractor

New module `bookcast_evidence.py` at the repo root.

`first_mention_sentence(paragraph, names) -> str`

1. Take only the first paragraph block (split on `\n\n`) — the stored
   `surrounding_paragraph` runs on into unrelated scenes, which is how the snowfox
   record ended up citing Suriel's purple eyes.
2. Segment into sentences. Do not use a naive `.` split — the corpus contains `Mr.`,
   ellipses, and curly quotes. Split on `(?<=[.!?])["'”’]?\s+(?=[A-Z“"'\[])`.
3. Return the first sentence containing any of `names` (canonical name, aliases,
   normalized-name word stems), matched case-insensitively on word boundaries.
4. Fall back to the first sentence of the block if no name matches — unnamed characters
   ("young man", "the old woman") often are not named in their own sentence.
5. Collapse internal whitespace; preserve the book's original punctuation and curly
   quotes verbatim. **Do not paraphrase — this is quoted book text.**

**Acceptance:** for `character:snowfox` returns exactly
*"As the members of the Heaven's Glory School excavate their ancient tomb, a five-tailed
snowfox the size of a man waits nearby."* (with the book's curly apostrophe).

## A2. Write the phrase selector

In the same module: `descriptive_phrases(character, pid, limit=6) -> list[dict]`

1. Take `visual_descriptions` entries whose `passage_id == pid`.
2. Drop any whose `exact_quote` is a superset/duplicate of the first-mention sentence
   (the snowfox's first visual quote *is* the first-mention paragraph — do not print it
   twice).
3. Split long quotes into sentence-level phrases using A1's segmenter, and keep only
   sentences that carry visual signal: appearance, size, color, material, clothing,
   posture, or motion. Reject pure plot/interiority ("he experiences hope", "he does not
   remember the events prior to her temporal reversion").
4. Deduplicate case- and punctuation-insensitively.
5. Cap at `limit`, preserving book order.
6. Each returned item is `{text, passage_id, page_start, page_end}`.

**Acceptance:** snowfox yields phrases including *"He is soundless, scentless, his
presence masked to both sight and spirit."* and *"He is an ancient sacred beast, one of
the original inhabitants of this valley…"*, and does **not** repeat the first-mention
sentence or include the Suriel material.

## A3. Write the backfill script

New script `backfill_bookcast_evidence.py` at the repo root.

- Load `lore_graph/data/service_index.json` and `bookcast.jsonl`.
- For each record, resolve the character ID from `source_character_ids[0]`, falling back
  to matching `source_normalized_names[0]` against `character_name_normalized`.
- Resolve the anchor passage from `evidence_notes.passage_id`, falling back to
  `appearances[0].passage_id`.
- Write `first_mention` (all fields from `passage_context[pid].location` plus the
  extracted `sentence`) and `descriptive_phrases`.
- **Mutate the loaded dict and re-dump** — never rebuild from an allowlist, or Track B/C
  fields will be destroyed.
- Write atomically via a `.tmp` + `replace()`, matching
  [generate_bookcast_zimageturbo.py:54](generate_bookcast_zimageturbo.py:54).
- Support `--dry-run` printing the first 10 resolutions, and `--limit N`.
- Records whose character ID cannot be resolved get `first_mention: null` and
  `descriptive_phrases: []`, and are listed in a summary at the end. Do not guess.

## A4. Run the backfill  *(serial — coordinate with Track B)*

```bash
cp bookcast.jsonl "bookcast.jsonl.bak.$(date +%Y%m%d_%H%M%S)"
.venv/bin/python backfill_bookcast_evidence.py --dry-run
.venv/bin/python backfill_bookcast_evidence.py
```

Report how many of the 133 records resolved. Investigate any that did not before moving on.

## A5. Extend `buildBookCast()` in the server

[frontend/server.js:179](frontend/server.js:179), inside the `rawBookcast.map`:

```js
firstMentionSentence: item.first_mention?.sentence || null,
firstMentionCitation: item.first_mention
  ? `${item.first_mention.book_title} • ${item.first_mention.chapter_label} • p. ${item.first_mention.page_start}`
  : null,
descriptivePhrases: Array.isArray(item.descriptive_phrases)
  ? item.descriptive_phrases.map((p) => ({ text: p.text, page: p.page_start }))
  : [],
```

Also prefer `item.first_mention` over the regex scraping in `parseFirstAppearance()`
([frontend/server.js:60](frontend/server.js:60)) when the structured field is present —
it gives exact book/chapter/page instead of digits pulled out of a string. Keep the
regex path as the fallback for records the backfill could not resolve.

## A6. Render the new section in the card

[frontend/src/App.jsx:124](frontend/src/App.jsx:124), in `BookCastCard`. Insert **after**
the `bookcast-tags` div (closes at line 196) and **before** the Portrait Description
section (line 199):

```jsx
{member.firstMentionSentence && (
  <div className="bookcast-section bookcast-firstmention">
    <span className="bookcast-section-title">First Mention in the Text</span>
    <blockquote className="bookcast-quote">{member.firstMentionSentence}</blockquote>
    {member.firstMentionCitation && (
      <cite className="bookcast-cite">{member.firstMentionCitation}</cite>
    )}
  </div>
)}
{member.descriptivePhrases?.length > 0 && (
  <div className="bookcast-section">
    <span className="bookcast-section-title">Descriptive Phrases Nearby</span>
    <ul className="bookcast-phrase-list">
      {member.descriptivePhrases.map((p, i) => (
        <li key={i}>
          <span className="bookcast-phrase-text">{p.text}</span>
          {p.page ? <span className="bookcast-phrase-page">p. {p.page}</span> : null}
        </li>
      ))}
    </ul>
  </div>
)}
```

Both sections are conditional — a character with no resolved first mention shows neither,
rather than an empty box.

## A7. Style the new elements

`frontend/src/styles.css`, following the existing `.bookcast-section` conventions at
lines 991–1055:

- `.bookcast-quote` — book text, so make it read as a quotation: left accent border,
  serif or italic face, slightly larger line-height. Reuse the `.bookcast-evidence-box`
  (line 1038) palette so it does not look like a new design language.
- `.bookcast-cite` — small, muted, right-aligned, `font-style: normal`.
- `.bookcast-phrase-list` — unstyled `ul`, each `li` a chip or bordered row.
- `.bookcast-phrase-page` — small muted page number, right-aligned in the row.
- Long quotes must wrap, never scroll the card body horizontally.

## A8. Verify in the running app

```bash
npm --prefix frontend run dev
```

Check `snowfox`, `wei-shi-lindon`, and one unnamed character. Confirm the quote is
verbatim book text, the citation matches `first_mention`, phrases do not repeat the
quote, and the card layout still holds at narrow widths.

---

## Notes and gotchas

- `surrounding_paragraph` is **not** one paragraph. Segment before extracting or you will
  reproduce the cross-character contamination that Track B is fixing.
- Two snowfox character IDs exist (`character:snowfox` and
  `character:unsouled:chapter:2:passage:002:unnamed-snowfox`) and are separate records.
  Resolve by ID, not by name.
- The text contains typographic quotes and apostrophes. Do not normalize them — they are
  part of the quoted source.
- `descriptive_phrases` is what the card shows *and* useful input for Track C's interview.
  Keep the field shape stable once C starts consuming it.
