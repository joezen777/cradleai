# Track B — Blank Instead of Filler, Brief Unique Portrait Descriptions

**Request:** when a retrieved attribute is `"not specified in the cited text"`, leave it
blank. `portrait_description` should contain only unique, visually grounded statements
about the character — often very brief.

**Depends on:** nothing. Blocks Track C.

**Owns fields:** all trait fields, `portrait_description`, `record_version`.

---

## The current output, and why

```
snowfox is a snowfox. Face: not specified in the cited text. Skin tone or surface: not
specified in the cited text. Eyes: not specified in the cited text. Hair or outer
covering: not specified in the cited text. Build: not specified in the cited text.
Clothing and wardrobe: not specified in the cited text. Accessories and identifying
objects: not specified in the cited text. Posture: waits nearby. Expression or emotion:
not specified in the cited text. No distinctive fighting move is stated in the cited
passages; pose them in this supported scene action: waits nearby. Color information
grounded in the cited context: cited color words: black, white, gray, blue, purple, gold.
Any feature marked as not specified should remain visually neutral rather than being
invented.
```

131 words. Two carry information (`waits nearby`, stated twice). Meanwhile the corpus
says *"a five-tailed snowfox the size of a man"* and *"soundless, scentless"* — thrown
away. And `purple, gold` are Suriel's, from a different scene in the same blob.

Five distinct defects:

| # | Defect | Location |
| --- | --- | --- |
| B-i | Unknown returns a sentence instead of `""` | [generate_bookcast_qwen.py:221](generate_bookcast_qwen.py:221) `supported_trait()` |
| B-ii | `posture := action`, `wardrobe := clothing` | [generate_bookcast_qwen.py:277](generate_bookcast_qwen.py:277)–280 |
| B-iii | Portrait template emits every field unconditionally | [normalize_bookcast.py:71](normalize_bookcast.py:71) `portrait()` |
| B-iv | Anchor filter discards real description | [generate_bookcast_qwen.py:221](generate_bookcast_qwen.py:221) |
| B-v | Colors leak from other characters' paragraphs | [generate_bookcast_qwen.py:247](generate_bookcast_qwen.py:247) `cited_colors()` |

---

## B1. Introduce the blank convention

Replace the `UNKNOWN` sentinel with the empty string across the pipeline.

- [generate_bookcast_qwen.py:221](generate_bookcast_qwen.py:221) `supported_trait()` —
  return `""` on every rejection path (lines 223, 233, 243).
- Add a normalizer applied to every model-supplied trait *before* validation: any value
  matching `^\s*(not specified|unspecified|unknown|n/?a|none|not stated|not mentioned)`
  (case-insensitive, tolerating a trailing "in the cited text") collapses to `""`. The
  local model produces several spellings of "unknown"; catch them all in one place.
- [normalize_bookcast.py:10](normalize_bookcast.py:10) — set `UNKNOWN = ""` and delete
  the `r.get(field) or UNKNOWN` defaulting at line 120–121, which currently re-injects
  the filler.
- [generate_bookcast_zimageturbo.py:104](generate_bookcast_zimageturbo.py:104)–125 —
  `construct_optimization_instruction()` currently tests
  `"not specified" not in str(x).lower()`. Change to a shared `has_value(x)` helper that
  treats `""`, `None`, and any legacy filler as absent, so old and new records both work.

Put `has_value()` and the normalizer in one module (suggest `bookcast_fields.py`) and
import it from all three scripts. Three copies of this predicate will drift.

## B2. Stop the duplicate fields

At [generate_bookcast_qwen.py:277](generate_bookcast_qwen.py:277)–280:

- Delete `result["wardrobe"] = result["clothing"]`. Either drop `wardrobe` from the
  schema entirely, or let the model fill it and validate it independently. Dropping it
  is cleaner — nothing downstream distinguishes the two, and
  [generate_bookcast_zimageturbo.py:114](generate_bookcast_zimageturbo.py:114) already
  coalesces them.
- Delete `result["posture"] = result["action"]`. `posture` is body configuration
  ("kneeling", "shoulders hunched"); `action` is what they are doing. Validate `posture`
  against its own anchors and leave it `""` when unsupported — 128/133 records currently
  duplicate it.
- `fighting_move` must not be emitted when it merely restates `action`. Compare
  normalized text and blank it if they match.

## B3. Fix the color scoping  *(grounding bug)*

`cited_colors()` scans the whole evidence blob. Rewrite it to take only text that is
about this character:

1. Build the color-scan corpus from the character's own `visual_descriptions`
   (`exact_quote`) plus their `appearances[].action_summary` — **not** the raw
   `surrounding_paragraph`.
2. Keep colors as `(color, phrase, passage_id)` triples so the color is bound to the noun
   it modified, not floated as a bare word list. `"white fox-fur jacket"` is usable;
   `"cited color words: black, white, gray, blue, purple, gold"` is not.
3. Emit `color_information` as a short natural phrase list, or `""` when nothing is
   bound. Drop the `"cited color words: "` prefix — it leaks internals into the UI.

**Acceptance:** the snowfox record no longer claims purple or gold.

## B4. Widen the anchor filter and stop discarding real description

`supported_trait()` rejects a value unless a hardcoded anchor word appears nearby. This
is why *"five-tailed"*, *"the size of a man"*, and *"soundless, scentless"* all vanish.

1. Extend anchor sets to cover non-human subjects: `fur`, `pelt`, `scale`, `feather`,
   `tail`, `claw`, `hide`, `snout`, `muzzle`, `wing`, `horn` for `hair`/`skin_tone`;
   `size`, `length`, `massive`, `huge`, `small`, `towering` for `build`.
2. Keep the "value tokens must appear in the evidence window" check — that is the part
   actually preventing hallucination. Widen the window from ±100 to ±200 characters so a
   description split across a sentence boundary is not lost.
3. Add a **salvage path**: when a trait validates to `""` but the character's own visual
   quotes contain unused visual sentences, record them in a new
   `unassigned_visual_facts: [{text, passage_id}]` list rather than dropping them. Track C
   consumes this; Track A already surfaces the same material as `descriptive_phrases`.

Do not weaken the token check to make more traits pass. An empty field that Track C fills
from a cited follow-up is better than a fabricated one.

## B5. Rewrite the portrait composer

Replace `portrait()` at [normalize_bookcast.py:71](normalize_bookcast.py:71) with a
composer that emits only what exists.

Rules:

1. **Skip empty fields entirely.** No label, no sentence, no placeholder.
2. **No tautologies.** `"snowfox is a snowfox"` — suppress the identity clause when
   `canonical_name` and `species_or_object_type` normalize to the same string, or when
   the species adds nothing (`"individual person"` / `"human"` for a named human).
3. **Deduplicate before composing.** Normalize each candidate statement (lowercase, strip
   punctuation, collapse whitespace) and drop exact and near-duplicate repeats — this is
   what currently prints `waits nearby` twice.
4. **One clause per fact**, comma-joined into at most 2–3 sentences. Group naturally:
   *physical* (face, skin, eyes, hair, build) → *wardrobe* (clothing, accessories) →
   *pose* (posture, action or fighting move, emotion) → *color*.
5. **Drop the boilerplate tail.** `"Any feature marked as not specified should remain
   visually neutral rather than being invented."` is an instruction to the prompt
   optimizer, not a description of the character. Move it into
   `ZIMAGE_TURBO_GUIDANCE` at
   [generate_bookcast_zimageturbo.py:31](generate_bookcast_zimageturbo.py:31), where it
   belongs, and delete it from the record.
6. **Allow a very short result.** If only one fact is grounded, the portrait is one
   clause. If nothing is grounded, `portrait_description` is `""` — that is a correct
   answer and Track C's signal to interview this character.

Target: under 60 words average, versus the current 131.

Expected snowfox result, roughly:

> A five-tailed snowfox the size of a man, soundless and scentless, its presence masked
> to both sight and spirit; waits nearby.

Apply the same skip-empty composition to the parallel `details` builder in
[generate_bookcast_qwen.py:295](generate_bookcast_qwen.py:295)–307, which duplicates this
logic for freshly generated records. Better: have both call one shared composer.

## B6. Rebuild the existing 133 records  *(serial — coordinate with Track A)*

`normalize_bookcast.py` is pure Python with no model dependency, so the rebuild is fast
and repeatable. It rewrites traits and portraits from fields already on disk.

```bash
cp bookcast.jsonl "bookcast.jsonl.bak.$(date +%Y%m%d_%H%M%S)"
.venv/bin/python normalize_bookcast.py
```

Caveat: B4's salvage path needs `visual_descriptions`, which are **not** stored in
`bookcast.jsonl` — they live in `service_index.json`. Either have `normalize_bookcast.py`
load the index (same resolution logic as `backfill_bookcast_evidence.py` in A3 — share
it), or run A4 first and read `descriptive_phrases` off the record. **Sharing the
resolver with Track A is the cleaner option; agree on it before either track starts.**

Then set `record_version = "bookcast-v2"`.

## B7. Invalidate stale prompts

Every record has a `zimageturbo_prompt` derived from the old filler text. Once portraits
change, those prompts are stale.

Per the decision in [tasks.md](tasks.md), clear `zimageturbo_prompt` and
`prompt_optimized_at` on records whose `portrait_description` changed, leaving
`image_generations` untouched. Phase 1 of
[generate_bookcast_zimageturbo.py:149](generate_bookcast_zimageturbo.py:149) already
selects on `not r.get("zimageturbo_prompt")`, so regeneration resumes naturally.

**Do not run the regeneration until Track C lands** — C adds the enrichment that makes
the new prompts worth generating. One GPU pass, not two.

## B8. Verify

Run the verification block in [tasks.md](tasks.md). Then read ten portraits by hand,
including `snowfox`, `wei-shi-lindon`, `yerin`, `eithan-arelius`, and two unnamed
characters. Every sentence must be traceable to a cited quote, and nothing may repeat.

---

## Notes and gotchas

- `normalize_bookcast.py` is **not idempotent against the old data** once `UNKNOWN`
  becomes `""` — legacy records still hold the literal filler string. The B1 normalizer
  must run on read, converting legacy fillers to `""`, so a rebuild is safe on both old
  and new records.
- The hand-written override tables at
  [normalize_bookcast.py:41](normalize_bookcast.py:41)–54 (`ACCESSORY_OVERRIDES`,
  `FIGHT_OVERRIDES`) are real curated knowledge for the main cast. Keep them; they should
  win over generated values.
- `evidence_notes` is sometimes a dict and sometimes a string
  ([frontend/server.js:97](frontend/server.js:97) handles both). Do not change its shape
  in this track.
- Blanking fields will make the card show fewer attribute rows. That is intended, but
  check `CharacterDetails` / the `bookcast-details-grid` at
  [frontend/src/App.jsx:216](frontend/src/App.jsx:216) filters out empty values so the
  grid does not render empty cells.
