# Book Cast Rework — Master Plan

Three changes requested against the Book Cast pipeline and page:

1. **Show source evidence on the card** — the book sentence where the character was
   first mentioned, plus nearby descriptive phrases, rendered under the title/location
   and below the tags.
2. **Stop emitting filler** — `"not specified in the cited text"` becomes blank, and
   `portrait_description` becomes a short list of unique, visually grounded statements
   instead of a 130-word template full of repeats.
3. **Interview the MCP server** — a fixed ladder of follow-up questions per character to
   pull out more descriptive visual language before prompt optimization.

Work is split into three track files. Read this file first — it defines the shared
record contract and the rules that keep the tracks from clobbering each other.

| Track | File | Scope | Depends on |
| --- | --- | --- | --- |
| A | [tasks-a.md](tasks-a.md) | First-mention evidence on the card (request 1) | — |
| B | [tasks-b.md](tasks-b.md) | Blank-not-filler, brief unique descriptions (request 2) | — |
| C | [tasks-c.md](tasks-c.md) | MCP follow-up enrichment interview (request 3) | B |

---

## Why the current output is broken

Measured across all 133 records in `bookcast.jsonl`:

| Symptom | Count | Root cause |
| --- | --- | --- |
| `skin_tone` is the filler string | 128/133 | [generate_bookcast_qwen.py:221](generate_bookcast_qwen.py:221) `supported_trait()` returns the filler instead of `""` |
| `eyes` filler | 117/133 | same |
| `face` filler | 109/133 | same |
| `posture` identical to `action` | 128/133 | [generate_bookcast_qwen.py:280](generate_bookcast_qwen.py:280) literally assigns `result["posture"] = result["action"]` |
| `wardrobe` identical to `clothing` | 132/133 | [generate_bookcast_qwen.py:277](generate_bookcast_qwen.py:277) same pattern |
| Portrait averages 131 words, mostly filler | 133/133 | [normalize_bookcast.py:71](normalize_bookcast.py:71) `portrait()` emits every field unconditionally |

Two deeper grounding failures, both visible in the `snowfox` record:

- **Real description is thrown away.** `supported_trait()` keeps a value only if an
  anchor word (`"skin"`, `"hair"`, `"beard"`…) appears in the evidence. The snowfox
  quote says *"a five-tailed snowfox the size of a man"*, *"soundless, scentless"*,
  *"an ancient sacred beast"* — none of it survives, because the anchors never match.
  The information is in the corpus; the filter discards it.
- **Colors leak across characters.** `cited_colors()` at
  [generate_bookcast_qwen.py:247](generate_bookcast_qwen.py:247) regex-scans the entire
  evidence blob, which includes the whole `surrounding_paragraph`. The snowfox record
  claims *"cited color words: black, white, gray, blue, purple, gold"* — purple and gold
  come from Suriel's *"radiant emerald shine … eyes to vivid purple"* two paragraphs
  later. These are false citations and must be scoped per character.

---

## Shared record contract — `bookcast-v2`

Every track writes only its own fields. Bump `record_version` to `"bookcast-v2"` only
after B lands (it is the schema-breaking change).

```jsonc
{
  // identity — unchanged, do not touch
  "canonical_name": "", "identity_key": "", "entity_type": "",
  "species_or_object_type": "", "books": [], "confidence": "",
  "source_character_ids": [], "source_normalized_names": [], "evidence_notes": {},

  // TRACK B owns these. "" means unknown. Never write a filler sentence.
  "face": "", "skin_tone": "", "eyes": "", "hair": "", "build": "",
  "posture": "", "emotion": "", "action": "", "fighting_move": "",
  "clothing": "", "accessories": "", "color_information": "",
  "portrait_description": "",

  // TRACK A owns these. Deterministic, derived from service_index.json.
  "first_mention": {
    "passage_id": "", "book_id": "", "book_title": "", "chapter_number": 0,
    "chapter_label": "", "page_start": 0, "page_end": 0, "sentence": ""
  },
  "descriptive_phrases": [
    { "text": "", "passage_id": "", "page_start": 0, "page_end": 0 }
  ],

  // TRACK C owns these.
  "enrichment": {
    "version": "interview-v1",
    "branch": "person | creature | object",
    "answers": [{
      "question_id": "", "question": "", "answer": "",
      "source": "cited | inferred", "passage_ids": [], "mcp_tool": ""
    }],
    "grounded_additions": [], "inferred_additions": []
  },
  "portrait_description_enriched": "",

  // phase-2 render state — unchanged
  "zimageturbo_prompt": "", "prompt_optimized_at": "",
  "gen_character_image": "", "primary_image_url": "", "image_generations": [],

  "record_version": "bookcast-v2"
}
```

### Grounding rule (non-negotiable)

Request 3 asks for plausible inference (*"if snowfox is an animal then describe what it
might look like"*). That conflicts with the project's source-grounding principle, so the
two are kept in separate fields and never merged silently:

- `portrait_description` — **cited only**. Every statement traceable to a passage ID.
- `portrait_description_enriched` — cited statements first, then inferred statements
  clearly marked. This is what feeds the Z-Image prompt optimizer.
- Every entry in `enrichment.answers` carries `source: "cited" | "inferred"`. An
  `inferred` answer with a non-empty `passage_ids` list is a bug.

The card shows cited and inferred content in visually distinct sections.

---

## Execution order

Development can overlap; **data rewrites cannot**. `bookcast.jsonl` is a single file and
every generator rewrites it whole via `save_bookcast()`, so two scripts running at once
will clobber each other.

```
  ┌─ A1–A3  (backfill script)     ─┐
  │                                │   code written in parallel
  └─ B1–B5  (sanitizer + rebuild) ─┘
                 │
                 ▼
        SERIAL DATA REWRITES
        1. B6  rebuild traits + portraits   (deterministic, no GPU)
        2. A4  backfill first-mention data  (deterministic, no GPU)
        3. VERIFY GATE — inspect 10 records by hand
                 │
                 ▼
  ┌─ A5–A8  (server.js + App.jsx + CSS + verify)  — no data dependency
  │
  └─ C1–C6  (interview design + implementation)
                 │
                 ▼
        4. C7   run enrichment interview      (GPU + MCP server, ~hours)
        5. C8   regenerate zimageturbo_prompt (GPU, server stopped)
        6. C9   optional: re-render images    (ComfyUI, ~133 renders)
        7. C10  surface enrichment on the card
```

A5–A8 and C10 both add sections to `BookCastCard`. Land Track A's markup first, or the
two will conflict in the same component.

## Shared modules

Two new modules are shared across tracks. Agree on their interfaces before starting, or
each track will grow its own copy and they will drift.

| Module | Owner | Contents | Used by |
| --- | --- | --- | --- |
| `bookcast_evidence.py` | A (A1–A2) | Sentence segmenter, first-mention sentence extraction, phrase selection, character/passage resolution against `service_index.json`, passage-neighborhood walk | A3, B6, C4 |
| `bookcast_fields.py` | B (B1) | `has_value()`, legacy-filler normalizer, statement dedup normalizer, the shared portrait composer | B1–B5, C6, and `generate_bookcast_zimageturbo.py` |

The passage-neighborhood walk (C4) and the phrase selector (A2) want the same logic.
Whichever track is written first should put it in `bookcast_evidence.py` and the other
should import it.

## Safety rules

1. **Back up before any rewrite.** `bookcast.jsonl` holds 133 records with completed
   prompts and rendered images:
   ```bash
   cp bookcast.jsonl "bookcast.jsonl.bak.$(date +%Y%m%d_%H%M%S)"
   ```
2. **One writer at a time.** Never run two of `normalize_bookcast.py`,
   `generate_bookcast_qwen.py`, `generate_bookcast_zimageturbo.py`, or the new backfill
   script concurrently.
3. **All scripts are additive-safe.** They `json.loads` each line, mutate, and re-dump,
   so unknown keys survive. Preserve that property in new code — do not construct fresh
   dicts from a field allowlist.
4. **VRAM.** Track C loads Qwen *and* talks to the MCP server, which lazily loads
   `bge-m3` for retrieval. That fits in 12 GB, but ComfyUI must not be rendering at the
   same time. Keep the existing phase separation in
   [generate_bookcast_zimageturbo.py:206](generate_bookcast_zimageturbo.py:206).
5. **Restart the lore server** after touching anything under `lore_graph/lore_api/` — a
   running process keeps its imported old code.

## Open decision — image regeneration

Changing `portrait_description` changes `zimageturbo_prompt`, which changes every
portrait. All 133 currently have a rendered image.

- **Option 1 (recommended):** clear `zimageturbo_prompt` on records whose portrait
  changed, leave `image_generations` intact, and let Phase 2 re-render on the next run.
  History is preserved because `image_generations` is an append list.
- **Option 2:** keep existing prompts, apply new descriptions to new characters only.
  Cheap, but the page keeps showing the bad text.

Ask before spending ~133 ComfyUI renders. C9 is written assuming Option 1.

## Verification gate

Before starting Track C, confirm on the rebuilt data:

```bash
.venv/bin/python -c "
import json
rows=[json.loads(l) for l in open('bookcast.jsonl') if l.strip()]
U='not specified'
bad=[r['identity_key'] for r in rows if U in json.dumps(r.get('portrait_description',''))]
dup=[r['identity_key'] for r in rows if r.get('posture') and r['posture']==r.get('action')]
print('records:', len(rows))
print('portraits still containing filler:', len(bad), bad[:5])
print('posture duplicating action:', len(dup), dup[:5])
print('avg portrait words:', sum(len(r.get('portrait_description','').split()) for r in rows)//len(rows))
print('missing first_mention.sentence:', sum(1 for r in rows if not r.get('first_mention',{}).get('sentence')))
print('missing descriptive_phrases:', sum(1 for r in rows if not r.get('descriptive_phrases')))
"
```

Targets: filler count `0`, posture duplication `0`, average portrait words under `60`,
missing first-mention/phrases `0` for characters that have a first appearance in the index.
