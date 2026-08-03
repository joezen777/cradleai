# Cradle AI

Cradle AI turns storyboard/animatic frames into source-grounded, live-action
image prompts and renders them with Z-Image Turbo in ComfyUI. The project is
being moved away from hosted Gemini lore refinement toward a fully local stack:
Pegasus supplies clip/chapter context, the Cradle lore graph retrieves cited
book passages, Qwen interprets and refines the frame, and ComfyUI renders the
result.

The target flow is:

```text
source video
  -> scenes, clips, first/last frames, transcript
  -> Pegasus clip and chapter context
  -> local frame interpretation
  -> cited Cradle passage selection and human confirmation
  -> lore-grounded visual refinement
  -> concise Z-Image Turbo prompt
  -> ComfyUI images
  -> reconstructed video (optional)
```

This is developed on WSL2 Ubuntu 24 with an RTX 5070 (12 GB VRAM), 64 GB RAM,
and a six-core i7. Most scripts assume they are run from the repository root
with the project virtual environment at `.venv/`.

## Current state and active work

The main Phase 1 prompt pipeline now enables the local `ground_enhance` path by
default. It preserves these fields in `output/metadatagen.jsonl`:

- `grounded_enhanced_description`: the local lore-grounded frame description.
- `ground_enhancement_stages`: intermediate location, visual, character,
  scenery, prop, omission, and prompt-refinement results.
- `extracted_facts`: separate source-cited character, scenery, and prop fact
  tables produced before prose refinement; each fact is tied to a confirmed
  passage ID.
- `base_prompt_text`: the rich local-model Z-Image prompt before controlled
  variants are applied.
- `prompt_text`: the final text consumed by Phase 2/ComfyUI.

Grounding is intentionally confirmation-gated. The first call ranks likely
book passages; the selected passage IDs must be recorded in
`lore_graph/grounding_confirmations.json` before enhancement proceeds. Current
confirmed test frames are scene 066 first, scene 099 first, scene 114 last, and
scene 116 last.

Current active tasks, in priority order:

1. Diagnose repeated `ground_enhance` stage text. The present implementation
   now has a dedicated final `continuity_audit` pass and deterministic visual
   lock, but character, scenery, and prop stages still receive prose plus
   evidence rather than independent structured extraction tables. This can
   still make intermediate stages paraphrase the same answer.
2. Audit caching at both levels: frame interpretation and complete response
   caching. Cache keys include the request/corpus state, so there is no proven
   collision yet, but whole-response cache hits can conceal whether a revised
   stage prompt actually ran. Trace entries need explicit cache-hit and stage
   input fingerprints.
3. Continue the structured chained extraction workflow: the first fact-table
   pass now extracts supported character, scenery, and prop facts separately;
   remaining work is entity-to-frame matching and explicit conflict scoring
   before composition and compression.
4. Preserve immutable frame facts throughout that chain: camera angle,
   composition, posture, position, gaze, action, skin tone, and recognizable
   appearance. Lore may correct identity/material/context but must not silently
   reposition the shot.
5. Improve fantasy/material constraints so props such as an orus fruit do not
   become pumpkins and Cradle settings do not drift into modern suburbs or a
   cartoon style.
6. Re-run the four comparison frames after the extraction/cache work, compare
   every intermediate field, and only then broaden the validation set.

The existing comparison runner already isolates the heavy local text model from
ComfyUI: it asks ComfyUI to free memory, prepares lore text in a child process,
waits for that child to exit, and only then queues image jobs. This lifecycle is
important on a 12 GB GPU; do not keep Qwen/MCP inference resident while sending
Z-Image Turbo work to ComfyUI.

## Quick start

Install the project requirements already selected for this checkout and the
lore package requirements:

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r lore_graph/requirements.txt
```

Start the lore REST/MCP server:

```bash
.venv/bin/python lore_graph/serve.py --host 127.0.0.1 --port 8765
```

Its health endpoint is `http://127.0.0.1:8765/health`, REST documentation is at
`http://127.0.0.1:8765/docs`, and Streamable HTTP MCP is at
`http://127.0.0.1:8765/mcp/`.

With ComfyUI listening on `http://127.0.0.1:8188`, run both prompt generation
and rendering:

```bash
.venv/bin/python run_complete_pipeline.py \
  --batch_name zimageturbo \
  --num_copies 10 \
  --grounding-confirmations lore_graph/grounding_confirmations.json
```

The pipeline is resumable. Phase 1 updates `output/metadatagen.jsonl`; Phase 2
skips image copies already marked complete. Frames without confirmed passage
IDs stop after candidate discovery rather than inventing a location. Use
`--no-ground-enhance` only for the legacy local Qwen-only prompt path.
When grounding is enabled, resume logic treats records without
`extracted_facts` as stale and regenerates them once, migrating older prompt
rows to the structured extraction/audit format.

Run phases separately when debugging:

```bash
.venv/bin/python generate_prompts_from_metadata.py \
  --batch_name zimageturbo --num_copies 10 \
  --grounding-confirmations lore_graph/grounding_confirmations.json

.venv/bin/python generate_images_from_metadata.py \
  --num_copies 10
```

## How grounding currently works

`ground_enhance` is exposed as both the MCP tool `ground_enhance` and REST route
`POST /v1/lore/ground-enhance`.

1. The caller supplies a frame image plus Pegasus context and optional legacy
   visual/prompt text.
2. Local frame interpretation inventories visible subjects, objects, action,
   composition, and environment.
3. Hybrid BM25/vector retrieval ranks complete book passages.
4. The first response sets `requires_confirmation: true` and returns candidate
   passage IDs.
5. A second call supplies `confirmed_passage_ids`.
6. Local stages expand/correct characters, scenery, props, missing details, and
   final Z-Image guidance while retaining the visual inventory as a constraint.
7. Phase 1 stores both intermediate output and the final prompt.

The suspected weakness is between steps 5 and 6: confirmed source context is
assembled, but there is not yet a dedicated per-category fact extraction table
that forces each stage to return distinct, cited objects/characters/locations.
Consequently, repeated prose is currently more likely a pipeline-design issue
than proof of a retrieval failure. Cache behavior still needs to be instrumented
before that conclusion is final.

## Data and file locations

| Path | Contents |
| --- | --- |
| `1unsouled.pdf`, `2soulsmith.pdf` | Authorized local source books used by the lore build. |
| `output/metadata.jsonl` | Scene boundaries, clip paths, and first/last frame paths. |
| `output/clips/` | Per-scene video clips. |
| `output/frames/` | Extracted source frames and generated image batches. |
| `output/audio.wav` | Audio extracted from the source video. |
| `output/audiotranscript.jsonl` | Timestamped/diarized transcript. |
| `output/pegasus_metadata.jsonl` | Per-clip Pegasus descriptions. |
| `output/pegasus_chapters/` | Concatenated chapter-sized clip media. |
| `output/pegasus_chapter_metadata.jsonl` | Chapter/scene-range Pegasus context. |
| `output/gemini_chapter_cast.jsonl` | Chapter cast catalog (historical filename; consumed by several generators). |
| `output/metadatagen.jsonl` | Current per-frame prompts, grounding stages, and image completion state. |
| `output/metadatagen_full.jsonl` | Backup/full prompt metadata used by reset tooling. |
| `output/frames/<batch>/` | Phase 2 Z-Image outputs for a named batch. |
| `output/frames/ground_enhance_comparison/` | Watermarked four-way prompt comparison images and JSON manifests. |
| `output/iconic_portrait_optimization/` | Iterative portrait prompts, critiques, history, and chosen images. |
| `lore_graph/data/` | Passages, embeddings, extraction state, graph/service indexes, completion marker. |
| `lore_graph/output/` | Exported `cast.jsonl`, `settings.jsonl`, `props_wardrobe.jsonl`, and treatments. |
| `lore_graph/cache/lore_api.sqlite3` | In-repository persistent API response/frame cache when that cache root is selected. |
| `~/.cache/cradle-lore-mcp/` | Default mutable cache for an installed/`uvx` MCP package. |
| `lore_graph/grounding_confirmations.json` | Frame-path to confirmed passage-ID mapping. |
| `lore_graph/diagnostics/` | Reproduction and trace artifacts. |
| `lore_graph/backups/` | Point-in-time lore data/cache/output backups. |
| `zimageturbo_cinematic.json` | Default ComfyUI API workflow for Z-Image Turbo. |
| `cradleColorize*.json` | Colorization/edit ComfyUI workflows. |
| `.credentials`, `.credentials.json` | Local service credentials; never commit or print these. |

Model weights live in the host Hugging Face cache. The lore service uses
`BAAI/bge-m3` for embeddings; image interpretation/refinement uses
`Qwen/Qwen2.5-VL-3B-Instruct` when required. Set `CRADLE_LORE_CACHE_DIR` to
explicitly isolate a diagnostic cache, for example:

```bash
CRADLE_LORE_CACHE_DIR=/tmp/cradle-ground-cache \
  .venv/bin/python lore_graph/serve.py --host 127.0.0.1 --port 8765
```

## Main pipeline and media commands

All commands below are run from the repository root. Add the listed options as
needed; run a script with `--help` for option defaults.

| Program | Example command | Purpose |
| --- | --- | --- |
| `video_scene_analyzer.py` | `.venv/bin/python video_scene_analyzer.py` | Interactively choose/analyze the source video; write clips, first/last frames, audio, and `metadata.jsonl`. |
| `transcribe_audio_elevenlabs.py` | `.venv/bin/python transcribe_audio_elevenlabs.py --audio output/audio.wav --output output/audiotranscript.jsonl` | Transcribe/diarize extracted audio with ElevenLabs. |
| `convert_videos_h264.py` | `.venv/bin/python convert_videos_h264.py` | Convert project video assets to H.264; `--skip-metadata` avoids metadata updates. |
| `build_pegasus_metadata.py` | `.venv/bin/python build_pegasus_metadata.py --max-scenes 10` | Generate resumable per-clip Pegasus descriptions. Supports scene ranges, retries, import, and initialize-only modes. |
| `build_pegasus_chapters.py` | `.venv/bin/python build_pegasus_chapters.py --maximum-seconds 300` | Assemble clips into chapter-sized media and generate resumable Pegasus chapter context. |
| `supervise_pegasus_pipeline.py` | `.venv/bin/python supervise_pegasus_pipeline.py --wait-pid PID` | Wait for a process, cool down, then supervise/resume Pegasus jobs. |
| `describe_clips_twelvelabs.py` | `.venv/bin/python describe_clips_twelvelabs.py --scenes 66 99` | Produce an alternative TwelveLabs clip-description dataset. |
| `retrieve_clip_lore_context.py` | `.venv/bin/python retrieve_clip_lore_context.py --scene 66 --write` | Retrieve hosted/Gemini-era lore context for one clip and optionally store it; retained for comparison. |
| `generate_prompts_from_metadata.py` | `.venv/bin/python generate_prompts_from_metadata.py --scenes 66 --frames first` | Phase 1: create/resume per-frame prompts, locally ground by default, and update `metadatagen.jsonl`. |
| `generate_images_from_metadata.py` | `.venv/bin/python generate_images_from_metadata.py --batch_name zimageturbo --num_copies 10` | Phase 2: send outstanding `prompt_text` entries to ComfyUI and record results. |
| `run_complete_pipeline.py` | `.venv/bin/python run_complete_pipeline.py --batch_name zimageturbo --num_copies 10` | Run Phase 1 then Phase 2; supports `--skip_phase1`, `--skip_phase2`, and grounding switches. |
| `zimageturbo_batch_generator.py` | `.venv/bin/python zimageturbo_batch_generator.py "prompt text" -n 4 -b test` | Directly render one prompt as a ComfyUI batch, optionally tied to a clip/frame and metadata file. |
| `integrated_workflow.py` | `.venv/bin/python integrated_workflow.py single --frame output/frames/scene_066_first_frame.png -n 1` | Older integrated single/batch workflow wrapper. The positional mode selects its operation. |
| `reconstruct_video.py` | `.venv/bin/python reconstruct_video.py` | Reassemble generated scene imagery/media into a video using the script's configured paths. |

Important Phase 1 selectors are `--scenes 66 99`, `--frames
scene_066_first_frame.png scene_066_last_frame.png` (exact paths or basenames),
`--max_frames N`, `--no_resume`, `--ground-enhance` (default),
`--no-ground-enhance`, and `--grounding-confirmations PATH`. Phase 2 selectors
include `--max_clips`, `--num_copies`, `--save_interval`, workflow, endpoint,
batch name, and log file.

## Ground-enhance comparison test

The standalone comparison test does not modify the production pipeline. For a
confirmed frame it renders the same seed with four inputs:

1. `old_prompt_text`
2. `grounded_enhanced_description`
3. `base_prompt_text`
4. `new_prompt_text`

Each image is watermarked with its variable name plus scene/frame, and filenames
include the shared job start timestamp. A JSON manifest records all text and
outputs.

```bash
.venv/bin/python test_scene066_ground_enhance_comfy.py --scene 66 --frame first
.venv/bin/python test_scene066_ground_enhance_comfy.py --scene 99 --frame first
.venv/bin/python test_scene066_ground_enhance_comfy.py --scene 114 --frame last
.venv/bin/python test_scene066_ground_enhance_comfy.py --scene 116 --frame last
```

Discover candidates without rendering:

```bash
.venv/bin/python test_scene066_ground_enhance_comfy.py \
  --scene 66 --frame first --discover-only
```

Useful overrides are `--metadata`, `--legacy-metadatagen`,
`--grounding-confirmations`, `--endpoint`, `--workflow`, `--output-dir`,
`--seed`, and `--variation-sequence`. `--prepare-output` is an internal child
process option and should not normally be supplied manually.

## Local chat, visual prompting, and experiments

| Program | Example command | Purpose |
| --- | --- | --- |
| `qwen_media_chat.py` | `.venv/bin/python qwen_media_chat.py --model qwen2.5-vl-3b --response-mode clip-lore` | Interactive local image/video chat with optional lore MCP retrieval. Supports media root, history/token limits, lore URL/context limits, and `--no-lore`. |
| `gcp_vision_prompt.py` | `.venv/bin/python gcp_vision_prompt.py IMAGE --output prompt.txt` | Ask the configured Google vision model for a prompt; legacy/hosted comparison path. |
| `experiment_cast_guided_frame_prompts.py` | `.venv/bin/python experiment_cast_guided_frame_prompts.py --scenes 12 14 15` | Compare frame prompting supplied with chapter cast/transcript context. |
| `experiment_cast_prompt_variants.py` | `.venv/bin/python experiment_cast_prompt_variants.py` | Run the fixed cast prompt-variant experiment. |
| `experiment_scene14_lore_frames.py` | `.venv/bin/python experiment_scene14_lore_frames.py` | Run the fixed scene 14 lore/frame experiment. |
| `generate_cast_guided_experiment_images.py` | `.venv/bin/python generate_cast_guided_experiment_images.py --num-generations 1` | Render prompts from the cast-guided experiment with ComfyUI. |
| `quality_check_prompt_variants.py` | `.venv/bin/python quality_check_prompt_variants.py --scenes 12 14 15` | Inspect/score generated prompt variants. |
| `iconic_portrait_critic.py` | `.venv/bin/python iconic_portrait_critic.py --reference REF.png --candidate CANDIDATE.png --prompt-file prompt.txt` | Critique a candidate portrait against its reference and requirements. |
| `optimize_iconic_portrait.py` | `.venv/bin/python optimize_iconic_portrait.py --scene 514 --frame first --iterations 5` | Iterate render/critique/revise for one iconic portrait and save its history/best prompt. |

## Cast and chapter generation

| Program | Example command | Purpose |
| --- | --- | --- |
| `generate_chapter_cast.py` | `.venv/bin/python generate_chapter_cast.py --chapter 1 --max-characters 10` | Generate/resume chapter cast metadata with the configured hosted text model. |
| `generate_chapter_lore_mistral.py` | `.venv/bin/python generate_chapter_lore_mistral.py --max-chapters 2` | Generate chapter lore summaries with a local Mistral model. |
| `generate_chapter_thumbnails.py` | `.venv/bin/python generate_chapter_thumbnails.py --metadata output/pegasus_chapter_metadata.jsonl` | Create thumbnails for assembled Pegasus chapters. |
| `generate_cast_images_zimageturbo.py` | `.venv/bin/python generate_cast_images_zimageturbo.py --chapter 1 --max-images 10` | Render cast portraits locally with Z-Image Turbo/ComfyUI. |
| `generate_cast_images_zcelebrity.py` | `.venv/bin/python generate_cast_images_zcelebrity.py --chapter 1 --max-images 10` | Refine cast text with its configured LLM and render through ComfyUI. |
| `generate_cast_images_gemini.py` | `.venv/bin/python generate_cast_images_gemini.py --chapter 1 --max-images 10` | Generate cast images with Gemini image generation; hosted and billable. |
| `generate_cast_images_openai.py` | `.venv/bin/python generate_cast_images_openai.py --chapter 1 --max-images 10` | Generate cast images with the configured OpenAI image model; hosted and billable. |
| `supervise_cast_images.py` | `.venv/bin/python supervise_cast_images.py` | Run/supervise the script's configured cast-image queue. |

## Metadata, colorization, and diagnostics

| Program | Command | Purpose |
| --- | --- | --- |
| `add_colorized_properties.py` | `.venv/bin/python add_colorized_properties.py` | Add colorized-frame properties to `metadata.jsonl`. |
| `verify_colorized_properties.py` | `.venv/bin/python verify_colorized_properties.py` | Verify those colorized metadata fields and referenced files. |
| `reset_metadatagen_full.py` | `.venv/bin/python reset_metadatagen_full.py --metadata output/metadatagen_full.jsonl` | Atomically clear generated/result fields in the selected JSONL (the full file by default) before a complete rerun. Back up files before using reset utilities. |
| `show_metadata_structure.py` | `.venv/bin/python show_metadata_structure.py` | Print metadata structure/file statistics. |
| `show_results.py` | `.venv/bin/python show_results.py` | Summarize the currently configured generation results. |
| `check_cuda.py` | `.venv/bin/python check_cuda.py` | Report PyTorch/CUDA visibility and device information. |
| `install_cuda_opencv.py` | `.venv/bin/python install_cuda_opencv.py` | Build/install CUDA-enabled OpenCV using the script's host assumptions; this mutates the environment. |
| `test_imports.py` | `.venv/bin/python test_imports.py` | Smoke-test project imports and selected metadata access. |
| `test_gcp_vision.py` | `.venv/bin/python test_gcp_vision.py` | Exercise the configured GCP vision prompt path. |
| `test_qwen_lore_context.py` | `.venv/bin/python test_qwen_lore_context.py` | Exercise Qwen plus lore-context integration. |
| `test_zimageturbo_batch.py` | `.venv/bin/python test_zimageturbo_batch.py` | Smoke-test the Z-Image Turbo batch generator. |
| `test_comfyui_workflow.py` | `.venv/bin/python test_comfyui_workflow.py` | Exercise/inspect the configured colorization ComfyUI workflow. |

`comfyui_integration.py`, `local_frame_prompt.py`, `prompt_variations.py`, and
`cast_metadata_store.py` are primarily importable libraries. Running
`comfyui_integration.py` directly executes its small built-in connectivity/demo
path, but production callers should import its client classes.

## Lore graph build and query commands

The complete lore-system design, MCP configuration, and quality rules are in
[`lore_graph/README.md`](lore_graph/README.md). The normal resumable build is:

```bash
PYTHONPATH=lore_graph .venv/bin/python -m loredb.cli ingest
PYTHONPATH=lore_graph .venv/bin/python -m loredb.embed
PYTHONPATH=lore_graph .venv/bin/python -m loredb.cli index
PYTHONPATH=lore_graph .venv/bin/python -m loredb.extract
PYTHONPATH=lore_graph .venv/bin/python -m loredb.treatments
PYTHONPATH=lore_graph .venv/bin/python -m loredb.resolve_aliases
PYTHONPATH=lore_graph .venv/bin/python -m loredb.rebuild_graph
PYTHONPATH=lore_graph .venv/bin/python -m loredb.export_catalog
PYTHONPATH=lore_graph .venv/bin/python -m lore_api.build_indexes
PYTHONPATH=lore_graph .venv/bin/python -m loredb.validate
```

Resume the entire sequence after an interruption:

```bash
.venv/bin/python lore_graph/resume_processing.py
```

Wait for another process and finish the build afterward:

```bash
.venv/bin/python lore_graph/finish_processing.py --wait-pid PID
```

Individual programs and their roles:

| Program/module | Example command | Purpose |
| --- | --- | --- |
| `loredb.cli` | `PYTHONPATH=lore_graph .venv/bin/python -m loredb.cli ingest --root lore_graph` | Top-level lore build command dispatcher (`ingest`, `index`, and supported maintenance commands). |
| `loredb.embed` | `PYTHONPATH=lore_graph .venv/bin/python -m loredb.embed` | Generate local passage embeddings. |
| `loredb.extract` | `PYTHONPATH=lore_graph .venv/bin/python -m loredb.extract --batch-size 1` | Extract source-grounded entities/descriptions from passages with the local model. |
| `loredb.treatments` | `PYTHONPATH=lore_graph .venv/bin/python -m loredb.treatments --max-chapters 1` | Generate local chapter treatments. |
| `loredb.resolve_aliases` | `PYTHONPATH=lore_graph .venv/bin/python -m loredb.resolve_aliases` | Resolve entity aliases after extraction. |
| `loredb.rebuild_graph` | `PYTHONPATH=lore_graph .venv/bin/python -m loredb.rebuild_graph` | Rebuild the derived relationship graph. Stop the API first because this needs the writer lock. |
| `loredb.export_catalog` | `PYTHONPATH=lore_graph .venv/bin/python -m loredb.export_catalog` | Export cast, setting, prop/wardrobe, and treatment catalogs. |
| `lore_api.build_indexes` | `PYTHONPATH=lore_graph .venv/bin/python -m lore_api.build_indexes` | Build the API service index from passages and catalogs. |
| `loredb.validate` | `PYTHONPATH=lore_graph .venv/bin/python -m loredb.validate` | Strictly validate source citations, artifacts, and completion state. |
| `loredb.repair_extractions` | `PYTHONPATH=lore_graph .venv/bin/python -m loredb.repair_extractions` | Repair/retry invalid or incomplete extraction records. |
| `loredb.query` | `PYTHONPATH=lore_graph .venv/bin/python -m loredb.query search "wooden badge" --limit 5` | Hybrid passage search; use mode `character` for a character dossier. |
| `lore_api.cli` | `PYTHONPATH=lore_graph .venv/bin/python -m lore_api.cli` | Start the stdio MCP server used by local MCP clients. |
| `lore_graph/serve.py` | `.venv/bin/python lore_graph/serve.py --host 127.0.0.1 --port 8765` | Start combined FastAPI REST and Streamable HTTP MCP. |
| `acceptance_queries.py` | `PYTHONPATH=lore_graph .venv/bin/python lore_graph/tests/acceptance_queries.py` | Run semantic/source-grounding acceptance checks. |
| `test_lore_api.py` | `PYTHONPATH=lore_graph .venv/bin/python -m unittest lore_graph.tests.test_lore_api` | Run lore API unit/integration tests. |

Most lore commands accept `--root lore_graph`; extraction also accepts
`--max-passages` and `--batch-size`, treatments accepts `--max-chapters`, and
query accepts `--book` and `--limit`.

The internal modules `loredb.graph_store`, `loredb.local_model`,
`loredb.materialize`, `loredb.pdf_ingest`, and `loredb.util` implement storage,
local inference, derived records, PDF parsing, and common helpers. The internal
modules `lore_api.app`, `cache`, `ground_enhancer`, `image_interpreter`,
`retrieval`, `schemas`, and `service` implement transport, persistent caching,
staged grounding, local vision, retrieval, request/response models, and service
orchestration. They are libraries rather than user-facing commands.

## Lore service operations

| MCP tool | REST route | Purpose |
| --- | --- | --- |
| `locate_lore_context` | `POST /v1/lore/locate` | Rank complete cited scene contexts from text, transcript, Pegasus context, or a frame. |
| `locate_character_context` | `POST /v1/characters/locate` | Resolve a character and return source-linked appearance context. |
| `locate_scenery_context` | `POST /v1/scenery/locate` | Resolve a location/setting and return source-linked context. |
| `locate_prop_context` | `POST /v1/props/locate` | Resolve source-linked props or wardrobe. |
| `ground_enhance` | `POST /v1/lore/ground-enhance` | Confirmation-gated frame grounding and local Z-Image prompt refinement. |

Example text lookup:

```bash
curl -sS -X POST http://127.0.0.1:8765/v1/lore/locate \
  -H 'content-type: application/json' \
  -d '{"description":"Lindon examines his wooden badge","max_locations":3}'
```

## Resuming safely and diagnosing stale results

- Prompt/image metadata and lore extraction files are designed to resume; do
  not delete them merely to retry one frame.
- Use a fresh `CRADLE_LORE_CACHE_DIR` for controlled cache experiments. That is
  safer and more informative than deleting the normal cache.
- Restart the lore process after changing server/refinement code. An already
  running process will continue using its imported old code.
- Stop the lore server before rebuilding LadybugDB/index artifacts, then restart
  it so the new corpus fingerprint is loaded.
- Before ComfyUI rendering on limited VRAM, allow the comparison runner to end
  its lore child process. For manual runs, explicitly stop the Qwen chat/server
  process and verify GPU memory is released.
- A repeated response is not by itself evidence of a cache-key collision. Check
  whether the trace says cache hit, compare request and corpus fingerprints,
  then compare the exact stage inputs. Identical source bundles and rewrite
  instructions can legitimately produce near-identical text.
- Hosted Gemini, OpenAI, ElevenLabs, TwelveLabs, and GCP scripts may incur cost.
  The core lore build, `ground_enhance`, Qwen chat, and ComfyUI paths are local.

## Historical goal

The project began as an experiment in finding the “best thousand words” that
could carry a storyboard frame through image-to-text and back into a plausible
live-action image. The central challenge is not simply prompt richness: it is
preserving visible truth from the frame while adding only source-supported
Cradle details. The local lore graph and staged grounding work exist to make
that boundary inspectable, reproducible, and eventually better than the older
single hosted-model pass.
