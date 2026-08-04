# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

Cradle AI turns storyboard/animatic frames into source-grounded, live-action image
prompts and renders them with Z-Image Turbo in ComfyUI. The stack is being moved
off hosted Gemini onto a fully local one:

```text
source video -> scenes/clips/frames/transcript -> Pegasus clip & chapter context
  -> local frame interpretation -> cited Cradle passage selection (human-confirmed)
  -> lore-grounded refinement -> Z-Image Turbo prompt -> ComfyUI images -> video
```

Read [README.md](README.md) for the full command inventory and
[lore_graph/README.md](lore_graph/README.md) for the lore system design.
[AGENT.md](AGENT.md) documents the `output/metadata.jsonl` scene-database schema.

## Environment — non-negotiable

- **All commands run in WSL2 bash. Never use PowerShell or Windows paths.**
- Host: WSL2 Ubuntu 24, RTX 5070 (12 GB VRAM), 64 GB RAM, 6-core i7.
- **Always invoke Python as `.venv/bin/python`**, from the repository root. Do not
  activate the venv or use bare `python`.
- Lore modules need `PYTHONPATH=lore_graph` (e.g.
  `PYTHONPATH=lore_graph .venv/bin/python -m loredb.query search "wooden badge"`).
- Services: lore REST/MCP on `http://127.0.0.1:8765`, ComfyUI on
  `http://127.0.0.1:8188`.

## VRAM discipline

12 GB is the binding constraint. Qwen/lore inference and ComfyUI rendering must not
be resident at the same time. The comparison runner already handles this: it asks
ComfyUI to free memory, prepares lore text in a **child process**, waits for that
child to exit, then queues image jobs. Preserve that lifecycle in any new code, and
for manual runs stop the Qwen chat/server process and verify GPU memory is released
before rendering.

## Grounding is confirmation-gated — do not bypass it

`ground_enhance` (MCP tool / `POST /v1/lore/ground-enhance`) never invents a
location. The first call returns `requires_confirmation: true` plus candidate
passage IDs; a second call must supply `confirmed_passage_ids`. Those IDs live in
[lore_graph/grounding_confirmations.json](lore_graph/grounding_confirmations.json),
keyed by frame path. Frames without confirmed IDs correctly stop after candidate
discovery — that is not a bug to "fix."

Confirmed test frames: scene 066 first, 099 first, 114 last, 116 last.

Immutable frame facts that lore must never overwrite: camera angle, composition,
posture, position, gaze, action, skin tone, recognizable appearance. Lore may
correct identity, material, and context only.

## Active work (priority order)

1. Diagnose repeated `ground_enhance` stage text — character/scenery/prop stages
   still get prose plus evidence rather than independent structured extraction
   tables, so they paraphrase each other.
2. Instrument caching at both levels (frame interpretation, whole-response). Add
   explicit cache-hit flags and stage input fingerprints to trace entries.
3. Finish the chained extraction workflow: entity-to-frame matching and explicit
   conflict scoring before composition/compression.
4. Preserve the immutable frame facts above through that chain.
5. Tighten fantasy/material constraints (an orus fruit must not become a pumpkin;
   Cradle settings must not drift modern or cartoon).
6. Re-run the four confirmed comparison frames, diff every intermediate field, and
   only then broaden the validation set.

A repeated response is **not** by itself proof of a cache-key collision. Check the
trace for a cache hit, compare request/corpus fingerprints, then compare exact
stage inputs — identical source bundles legitimately produce near-identical text.

## Working rules

- **Everything is resumable.** Prompt/image metadata and lore extraction files are
  designed to resume. Do not delete them to retry one frame; use the scene/frame
  selectors instead. Back up before touching `reset_metadatagen_full.py`.
- **Restart the lore server after changing server or refinement code** — a running
  process keeps its imported old code. Stop it before rebuilding LadybugDB/index
  artifacts, then restart so the new corpus fingerprint loads.
- **For cache experiments, set a fresh `CRADLE_LORE_CACHE_DIR`** rather than
  deleting the normal cache.
- **Never commit or print `.credentials` / `.credentials.json`.** Source PDFs,
  `output/`, `models/`, and media are gitignored — keep them that way.
- **Hosted paths cost money**: Gemini, OpenAI, ElevenLabs, TwelveLabs, GCP scripts.
  The lore build, `ground_enhance`, Qwen chat, and ComfyUI paths are local and free.
  Prefer local paths and flag hosted ones before running them.

## Common commands

```bash
.venv/bin/python lore_graph/serve.py --host 127.0.0.1 --port 8765
```

```bash
.venv/bin/python run_complete_pipeline.py --batch_name zimageturbo --num_copies 10 --grounding-confirmations lore_graph/grounding_confirmations.json
```

Phases separately when debugging:

```bash
.venv/bin/python generate_prompts_from_metadata.py --scenes 66 --frames first --grounding-confirmations lore_graph/grounding_confirmations.json
```

```bash
.venv/bin/python generate_images_from_metadata.py --batch_name zimageturbo --num_copies 10
```

Four-way prompt comparison for a confirmed frame (renders `old_prompt_text`,
`grounded_enhanced_description`, `base_prompt_text`, `new_prompt_text` at one seed,
watermarked, with a JSON manifest):

```bash
.venv/bin/python test_scene066_ground_enhance_comfy.py --scene 66 --frame first
```

Validate the lore corpus:

```bash
PYTHONPATH=lore_graph .venv/bin/python -m loredb.validate
```

Tests:

```bash
PYTHONPATH=lore_graph .venv/bin/python -m unittest lore_graph.tests.test_lore_api
```

```bash
PYTHONPATH=lore_graph .venv/bin/python lore_graph/tests/acceptance_queries.py
```

## Layout

- Root `*.py` — pipeline stages, generators, and experiments (see README tables).
- `lore_graph/loredb/` — corpus build: ingest, embed, extract, treatments, graph,
  export, validate.
- `lore_graph/lore_api/` — service: transport, cache, `ground_enhancer`,
  `image_interpreter`, retrieval, schemas, orchestration. Libraries, not CLIs.
- `output/` — scene metadata, clips, frames, transcripts, generated batches.
  `output/metadatagen.jsonl` is the live per-frame prompt/grounding/state record.
- `frontend/` — Vite + React 19 + MUI monitor UI, Express `server.js` for local
  serving, static build packaged for AWS Amplify via `amplify.yml`.

Key `metadatagen.jsonl` fields: `grounded_enhanced_description`,
`ground_enhancement_stages`, `extracted_facts` (per-category, each tied to a
confirmed passage ID), `base_prompt_text`, and `prompt_text` (what Phase 2 renders).

## Frontend

```bash
npm --prefix frontend run dev
```

```bash
npm --prefix frontend run build:static
```

Amplify build runs `build:static` then `scripts/prepare-amplify-artifact.mjs`,
publishing `frontend/amplify-artifact`.
