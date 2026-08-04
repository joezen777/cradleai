# Track C — MCP Follow-Up Interview for Visual Enrichment

**Request:** ask follow-up questions of the MCP server while building each character, so
that a thin record (e.g. "unnamed snowfox" yielding only *white snowfox*) gets filled out
with descriptive visual language before it reaches the prompt optimizer. A fixed ladder of
questions per character, branching on whether the subject is a person, an animal, or an
object.

**Depends on:** Track B. C fills the fields B leaves blank, and relies on B's blank
convention to know which fields are actually missing.

**Owns fields:** `enrichment`, `portrait_description_enriched`.

---

## The key architectural fact

**The MCP server does not answer questions — it retrieves cited passages.** The five
tools in [lore_graph/lore_api/app.py](lore_graph/lore_api/app.py) (`locate_lore_context`,
`locate_character_context`, `locate_scenery_context`, `locate_prop_context`,
`ground_enhance`) all take a name or a description and return source-linked records.

So "asking a follow-up question" is a three-step loop:

1. **Formulate** — build a retrieval query from the question template and the record.
2. **Retrieve** — call the appropriate MCP tool; get back passages with IDs and pages.
3. **Answer** — the local Qwen model answers *that one question* from *those passages
   only*, in one sentence, and reports whether the answer was supported.

Questions that no passage supports (*"what might a snowfox look like?"*) are answered by
the model from general knowledge and marked `source: "inferred"`. They never enter
`portrait_description`. See the grounding rule in [tasks.md](tasks.md).

---

## C1. Decide when to interview

Interviewing all 133 records is a long GPU run. Gate it.

`needs_enrichment(record) -> bool` — true when either:
- fewer than 3 of `face, skin_tone, eyes, hair, build, clothing, accessories` are
  non-empty after Track B, **or**
- `portrait_description` is under 15 words.

Given B's measured results (`skin_tone` empty in 128/133, `eyes` in 117/133) this will
select most of the cast. Support `--only <identity_key>` and `--limit N` so the ladder can
be validated on five characters before committing to a full run.

## C2. Classify the branch

`interview_branch(record) -> "person" | "creature" | "object"`

Derive deterministically from `entity_type` / `species_or_object_type`, which Track B's
predecessor already curated in `NONHUMAN` at
[normalize_bookcast.py:25](normalize_bookcast.py:25):

- `"individual person"` / `"human"` → **person**
- `"sacred beast"`, `"spirit"`, `"Remnant"`, `"nonhuman entity"` → **creature**
- `"construct"`, `"artifact"`, `"sentient construct"` → **object**

Do not ask a model to classify what a lookup table already knows.

## C3. The question ladder

Each question has a stable `question_id`, a tool, and a template. Answers are one
sentence. `{name}`, `{pid}`, `{species}` interpolate from the record; `{prev}`
interpolates the previous answer, which is what makes the chain work.

### Common — asked for every branch

| ID | Question | Tool | Notes |
| --- | --- | --- | --- |
| `CQ1` | *What other passages near `{pid}` describe `{name}`?* | index walk + `locate_character_context` | Passage-neighborhood expansion — see C4. Requested for people; applied to all branches because it is mechanically identical and the creature records need it most. |
| `CQ2` | *What words generally describe `{name}`'s mood near `{pid}` in the book?* | passages from CQ1 | Affect/expression vocabulary. Feeds `emotion`. Adjectives only — reject plot summary. |

`CQ1` runs first in every branch: it widens the evidence pool that every later question
draws from.

### Person branch

| ID | Question | Tool |
| --- | --- | --- |
| `P1` | *What clan, family, school, or people does `{name}` belong to?* | `locate_character_context`, plus the name prefix (`Wei`, `Jai`, `Kazan`, `Li`, `Heaven's Glory`, `Fisher`) |
| `P2` | *What do the `{prev}` look like, and how do they dress?* | `locate_character_context` on other members + `locate_prop_context` for their wardrobe |
| `P3` | *What age can be inferred from the cited text about `{name}`?* | CQ1 passages |
| `P4` | *What is `{name}`'s job or role?* | CQ1 passages + `locate_lore_context` |
| `P5` | *What tools or instruments would someone in the role of `{prev}` work with?* | `locate_prop_context` |
| `P6` | *What sacred-arts stage, Path, or Goldsign does `{name}` have?* | `locate_character_context` |

`P6` is Cradle-specific and high value: advancement stage (Foundation / Copper / Iron /
Jade / Gold) and Goldsigns are *visible* markers — Yerin's silver blade-like Goldsign,
badge colors by rank. This is exactly the kind of detail the current pipeline misses.

### Creature branch

| ID | Question | Tool |
| --- | --- | --- |
| `A1` | *Is `{name}` an animal, a spirit or Remnant, or a constructed thing?* | record fields; no call |
| `A2` | *If `{name}` is an animal, describe in one sentence what it looks like. If it is a person, answer nothing.* | CQ1 passages, then inference | The user's literal example. Cited first; falls back to `inferred`. |
| `A3` | *Where does `{name}` live?* | `locate_scenery_context` |
| `A4` | *Describe the landscape and natural climate of `{prev}`.* | `locate_scenery_context` | `SceneryContext` already returns `weather`, `climate`, `backdrop`, `time_of_day` — read the fields, do not ask the model to invent them. |
| `A5` | *What size, coloring, and distinguishing markings are stated for `{name}`?* | CQ1 passages |

### Object branch

| ID | Question | Tool |
| --- | --- | --- |
| `O1` | *What material is `{name}` made of?* | `locate_prop_context` |
| `O2` | *Who made or carries `{name}`?* | `locate_prop_context` → `locate_character_context` |
| `O3` | *What is its size, and how is it carried or mounted?* | `locate_prop_context` |

## C4. Implement the passage-neighborhood walk (`CQ1`)

Passage IDs are structured — `unsouled:chapter:20:passage:010` — so "near this passage"
is a deterministic string operation, not a search:

1. Parse `book:chapter:N:passage:MMM` from the anchor `pid`.
2. Generate neighbors at `MMM ± 1..k` (start `k=2`), zero-padded to the same width, and
   keep those present in `index["passage_context"]`.
3. Keep neighbors whose `character_ids` include this character — that is what makes them
   *describe* the character rather than merely being adjacent.
4. Union with the character's other `visual_descriptions` passages in the same chapter.
5. Return `[{passage_id, page_start, page_end, text}]`, capped (start at 6) and ordered.

This is cheap, exact, needs no model, and is reusable — Track A's `descriptive_phrases`
selector wants the same neighborhood logic. **Put it in the shared module from A3/B6.**

For `CQ2`, feed only these passages to the model and ask for mood adjectives describing
`{name}`. Constrain hard: adjectives and short phrases only, drop anything naming another
character, and blank the answer when the passages carry no affect. Mood must come from
text about *this* character — the same contamination that produced snowfox's fake purple
and gold applies here.

## C5. Build the interview runner

New script `enrich_bookcast_mcp.py` at the repo root, modeled on
[generate_bookcast_qwen.py:371](generate_bookcast_qwen.py:371) (which already has the
resumable JSONL + progress-file + VRAM-teardown pattern worth copying).

Structure:

- Load `bookcast.jsonl` and `service_index.json`.
- Select records via `needs_enrichment()`, honoring `--only` / `--limit` / `--start-after`.
- Load Qwen **once** for the whole run (`load_model` from `qwen_media_chat`); do not
  reload per character.
- For each record: classify branch → run `CQ1`, `CQ2`, then the branch ladder in order,
  threading `{prev}` through.
- Append each answer to `enrichment.answers` with `question_id`, `question`, `answer`,
  `source`, `passage_ids`, `mcp_tool`.
- **Persist after every character** and append to a `.progress.jsonl`, so a crash three
  hours in loses one record. Mirror
  [generate_bookcast_qwen.py:411](generate_bookcast_qwen.py:411).
- A failed question logs and continues — never abort a character for one bad answer.
- `--dry-run` prints the full question/answer transcript for one character without
  writing. Build this first; it is how the ladder gets tuned.

## C6. Compose the enriched description

`portrait_description_enriched` = Track B's cited portrait, then a clearly separated
inferred section:

```
<portrait_description>

Plausible reconstruction (not stated in the source): <inferred sentences>
```

Rules:
- Cited content always first, never reworded.
- An answer promotes into `grounded_additions` only if it has at least one `passage_id`.
- Deduplicate against `portrait_description` — B's dedup normalizer applies here too.
- Where a `CQ2` mood answer is cited, use it to fill B's empty `emotion` field.
- Where `P6` yields a stage/Goldsign, that is a *visible* attribute — route it into
  `accessories`, not into prose.

`portrait_description` itself stays cited-only and untouched.

## C7. Run the interview  *(GPU + MCP server; hours)*

Start the lore server first — it must be running for every MCP call:

```bash
.venv/bin/python lore_graph/serve.py --host 127.0.0.1 --port 8765
```

Validate the ladder on a handful before the full run:

```bash
.venv/bin/python enrich_bookcast_mcp.py --dry-run --only snowfox
.venv/bin/python enrich_bookcast_mcp.py --limit 5
```

Read those five transcripts end to end. Check that cited answers really are supported by
the passages they cite, and that inferred answers are marked. Then:

```bash
cp bookcast.jsonl "bookcast.jsonl.bak.$(date +%Y%m%d_%H%M%S)"
.venv/bin/python enrich_bookcast_mcp.py
```

## C8. Regenerate the Z-Image prompts

Point the optimizer at the enriched text. In
[generate_bookcast_zimageturbo.py:135](generate_bookcast_zimageturbo.py:135), prefer
`portrait_description_enriched` and fall back to `portrait_description`.

Also revisit `ZIMAGE_TURBO_GUIDANCE` at
[generate_bookcast_zimageturbo.py:31](generate_bookcast_zimageturbo.py:31): it currently
says *"Translate any missing or vague features into plausible Cradle-fantasy physical
materials and details"*, which invites exactly the free invention that Tracks B and C
work to constrain. With enrichment supplying real material, tighten it to prefer supplied
detail and invent only what remains unspecified.

The lore server must be **stopped** before this step so ComfyUI has the VRAM.

```bash
.venv/bin/python generate_bookcast_zimageturbo.py --phase prompt
```

## C9. Re-render images *(optional — needs a decision)*

~133 ComfyUI renders. See the open decision in [tasks.md](tasks.md); confirm before
starting.

```bash
.venv/bin/python generate_bookcast_zimageturbo.py --phase image
```

## C10. Surface enrichment on the card

Extend `buildBookCast()` ([frontend/server.js:179](frontend/server.js:179)) with
`enrichedDescription` and an `enrichmentAnswers` list, and add a collapsed
"Reconstructed Detail" section to `BookCastCard`. Style it distinctly from the cited
sections — a reader must be able to tell at a glance which claims come from the books.
Coordinate with Track A so both add sections to the same component without conflicting.

---

## Notes and gotchas

- **VRAM.** This run holds Qwen in the generator process while the lore server holds
  `bge-m3` for retrieval (~2 GB) and possibly `Qwen2.5-VL` for image interpretation. It
  fits in 12 GB, but ComfyUI must be idle. Never overlap C7 with C9.
- **Caching hides prompt changes.** `locate_character_context` and friends cache on
  `corpus_fingerprint` + request, versioned per method
  ([service.py:224](lore_graph/lore_api/service.py:224)). Identical retrieval queries
  return identical evidence — expected, not a bug. But if you change what a tool
  *returns*, bump its cache version or you will validate against stale rows. For clean
  experiments set a scratch cache:
  ```bash
  CRADLE_LORE_CACHE_DIR=/tmp/cradle-enrich-cache .venv/bin/python lore_graph/serve.py --host 127.0.0.1 --port 8765
  ```
- **Restart the server** after editing anything in `lore_graph/lore_api/`.
- The interview is a chain: a wrong `P1` poisons `P2`. Log `{prev}` with each answer so
  bad chains are diagnosable, and blank the downstream question when its input is empty
  rather than asking about `""`.
- Question wording is a tuning surface. Keep templates in one dict at the top of the
  script with stable IDs so `enrichment.version` can be bumped and records selectively
  re-interviewed.
- `locate_scenery_context` returns structured `weather` / `climate` / `backdrop` fields
  — for `A4`, read them rather than asking the model to describe a climate. Cheaper and
  actually cited.
