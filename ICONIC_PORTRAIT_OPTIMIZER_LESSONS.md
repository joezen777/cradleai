# Iconic Portrait Optimizer: Lessons Learned

## What we tested

We built a standalone optimization loop for one iconic character image, using scene 514's first frame as the reference. The experiment intentionally does not update `metadata.jsonl`, `metadatagen.jsonl`, or any existing pipeline generation records.

The loop uses:

1. Z-Image Turbo in local ComfyUI to generate one candidate image.
2. PiDiNet plus LPIPS to measure structural similarity to the storyboard frame.
3. Qwen2.5-VL 3B, loaded locally in 4-bit, to compare the reference and candidate, evaluate character-specific details, and rewrite the prompt.
4. A fixed seed so that changes between candidates are primarily caused by prompt changes rather than random sampling.

## Results from scene 514

The original prompt described Jai Long's face covering as a dark sand-colored headscarf. The revised prompt instead specified:

- Overlapping deep crimson-red cloth strips.
- Dark handwritten script and irregular symbols across the bands.
- One narrow, irregular eye opening.
- Loose wrapping ends over the shoulders and chest.
- A layered textile construction instead of a smooth or generic mask.

With the same seed, the structural edge score increased from **51.76** to **52.93**. The corrected candidate received a combined objective score of **70.78**.

The corrected image was much more recognizable as the intended character. It successfully produced red layered wrapping, visible writing, exposed eyes, and trailing cloth. However, it weakened the storyboard composition: the spear remained at frame left, but the raised gripping hand and original body pose were lost.

## Main lessons

### Structural similarity and character accuracy are different objectives

PiDiNet and LPIPS are useful for measuring silhouette, edges, framing, and broad composition. They cannot reliably determine whether a character-specific detail is canonically correct. A sand-colored scarf and a crimson scripted wrapping can occupy similar regions and therefore receive similar structural scores.

A useful objective must combine at least:

- Structural similarity.
- Overall visual correspondence.
- Canonical character-detail accuracy.

The current experimental weighting is 35% structural edge score, 30% visual match, and 35% canonical match. These weights are a starting point rather than a proven optimum.

### Canonical facts must be supplied explicitly

The visual critic should not be expected to infer every book-specific fact from a rough grayscale storyboard. Scene 514 does not clearly communicate fabric color or written symbols by itself. Canonical requirements therefore need to be passed as authoritative constraints.

For important recurring characters, these constraints should eventually come from a curated character bible rather than being embedded in an individual experiment.

### Positive visual descriptions work better than abstract prohibitions

The most useful prompt language precisely describes the desired construction:

> overlapping deep crimson-red textile strips, individually layered, with handwritten dark script across every band and one narrow irregular eye opening

Terms such as “mask,” “phantom mask,” or “not a balaclava” can introduce the unwanted visual concept even when used negatively. Negative constraints are still useful for validation, but the generation prompt should primarily describe the correct visible result in positive, concrete language.

### Fixing identity can accidentally damage composition

The local critic concentrated on the face wrapping and simplified other details. Its rewritten prompt changed the raised spear grip into a spear held at the character's side. The result improved identity while losing pose accuracy.

Prompt rewriting should therefore treat composition as a locked section. The following elements should be copied forward unless the reference comparison explicitly calls for changing them:

- Character location in the frame.
- Camera distance and angle.
- Body orientation.
- Hand positions.
- Prop position and direction.
- Major background geometry.

The next version should separately maintain `locked_composition`, `canonical_identity`, and `adjustable_rendering` prompt sections.

### Fixed seeds are essential for prompt optimization

Using the same seed makes comparisons substantially more meaningful. If both prompt and seed change, it becomes difficult to determine whether an improvement resulted from better wording or random sampling.

Once a strong prompt is found with a fixed seed, it should be tested against several additional seeds to measure robustness. A prompt that works for only one seed is not necessarily a reliable production prompt.

### Small vision-language models need simple output tasks

Qwen2.5-VL 3B initially returned a placeholder label instead of a complete rewritten prompt when asked to score images and write a long prompt inside one JSON response.

Splitting the work into two calls was more reliable:

1. Return compact structured scores, strengths, and mismatches.
2. Produce only the replacement image prompt.

The rewritten prompt must also be validated before it can be submitted to ComfyUI. At minimum, validation should check length, required canonical terms, forbidden concepts, and preservation of locked composition details.

### Model scores are useful but not objective truth

The visual critic gave relatively generous scores and sometimes described details inconsistently. Its scores are best treated as one noisy signal, not as a definitive judge.

For stronger optimization, the loop should use several independent signals:

- Edge or layout similarity.
- A semantic image-embedding score.
- A canonical-detail checklist evaluated by a visual model.
- Hard prompt validation.
- Periodic human selection for calibration.

### GPU models need explicit lifecycle boundaries

ComfyUI, PiDiNet/LPIPS, and Qwen cannot all safely occupy a 12 GB GPU at once. The successful sequence is:

1. Generate in ComfyUI.
2. Ask ComfyUI to unload its models and release cached VRAM.
3. Load PiDiNet/LPIPS, score the candidate, and release them.
4. Run Qwen in a separate subprocess.
5. Let the subprocess exit so all Qwen VRAM is released.
6. Begin the next ComfyUI generation.

Qwen2.5-VL 3B in 4-bit fits on the RTX 5070 12 GB. The first run downloads roughly 7 GB of model files, but subsequent loads use the local Hugging Face cache.

### Environment compatibility needs defensive handling

The installed PyTorch build attempted to compile an optional Triton-native kernel and failed because system Python development headers were absent. Setting `TORCH_DISABLE_NATIVE_JIT=1` allowed PyTorch to use a compatible fallback without requiring system-level package installation.

The parent optimizer originally hid critic subprocess errors because it captured stderr without displaying it. It now includes the critic's stderr in failures, which makes model-loading and inference problems diagnosable.

### Isolation is straightforward and worth preserving

All experimental prompts, images, scores, and history are stored under:

`output/iconic_portrait_optimization/scene_514_first/`

The optimizer only reads the reference frame and calls ComfyUI. It does not write to pipeline metadata. This prevents experimental candidates from being mistaken for approved production generations.

## Recommended next improvements

1. Add hard validation that every revised prompt preserves the reference pose, raised hand, upright spear, framing, and character placement.
2. Add a semantic embedding score, such as DINOv2, alongside edge-based LPIPS.
3. Score defined image regions separately: face covering, eyes, hands and spear, body silhouette, and background.
4. Save explicit baseline records when resuming an interrupted experiment.
5. Prevent prompt and iteration filenames from being overwritten across resumed runs.
6. Generate two or three prompt proposals per round, then test each with the same seed instead of trusting one rewrite.
7. Re-score the strongest prompt over multiple seeds to measure stability.
8. Add convergence and stopping rules, such as no objective improvement for three rounds or a maximum generation budget.
9. Calibrate visual-model scores against a small set of human rankings before relying on them for large automated runs.
10. Move reusable canonical character constraints into a versioned character-bible file.

## Cross-sample experiment

We subsequently ran the same fixed-seed baseline-versus-one-rewrite comparison on the six other proposed frames. Every comparison used the source prompt from `output/metadatagen.jsonl`, a scene-specific set of authoritative constraints, one fixed seed per scene, and the same scoring formula.

| Scene | Frame | Content type | Baseline edge score | Rewritten edge score | Change |
|---:|:---:|---|---:|---:|---:|
| 030 | first | Seated person in a tree | 50.39 | 46.88 | -3.51 |
| 108 | last | Face close-up with foreground arm | 44.14 | 50.00 | +5.86 |
| 152 | last | Person lying diagonally, badge visible | 49.22 | 46.88 | -2.34 |
| 194 | last | Two people, flag, ship deck | 48.05 | 48.44 | +0.39 |
| 576 | first | Single person walking in an alley | 41.80 | 45.31 | +3.51 |
| 767 | last | Dynamic attack with scythe and energy | 56.64 | 51.76 | -4.88 |

Three rewrites improved structural similarity and three made it worse. The mean change across these six scenes was approximately **-0.16 points**, which is effectively no net structural improvement. Including scene 514's earlier +1.17 result leaves the seven-sample mean close to zero.

These results do not mean prompt optimization is ineffective. They show that the current one-proposal critic and current selection objective are not yet reliable enough for unattended optimization.

## New lessons from the expanded test

### Image complexity predicts rewrite risk

The largest improvement occurred on scene 108, a tight face close-up. Scene 576, with one centered walking figure and a symmetrical alley, also improved. The largest regression occurred on scene 767, which combines a dynamic body silhouette, an overhead long weapon, flowing clothing, directional energy, and a rune platform.

The optimizer should classify a reference before choosing its strategy:

- Simple portrait or centered single-person shot: a full rewrite may be acceptable.
- Unusual rotation, multiple people, action pose, long prop, or layered effects: preserve most of the original prompt and make narrow edits only.

### Full rewrites are too destructive

The rewritten prompts were much shorter than their sources. Across these samples, original prompts were roughly 154-210 words, while rewrites were roughly 55-101 words. The shorter prompts frequently discarded visually important information.

Examples observed during visual review:

- Scene 030 changed clothing and seated posture even though the character remained in a tree.
- Scene 108 improved the foreground-arm composition but discarded the blue martial-arts clothing and made the character look significantly older.
- Scene 152 correctly placed a rectangular badge on a neck cord, but also introduced an unrelated modern belt and changed the outfit.
- Scene 194 corrected the badge location but replaced Lindon's green gi with a white modern suit and changed the second character and ship staging.
- Scene 767 preserved an overhead scythe pose but replaced the costume, platform, environment, and energy treatment.

The safer operation is a constrained patch to the existing prompt: identify the exact erroneous phrase, replace it, and leave every unrelated clause unchanged.

### Prompt length is not a useful validity rule by itself

The first two expanded trials produced coherent rewrites that were rejected only because they contained fewer than 90 words. Lowering the minimum allowed the experiment to continue, but the visual results showed that a short prompt can be either effective or destructive.

Validation should measure retained facts, not raw word count. A rewrite should be compared against a structured inventory extracted from the source prompt, including people, wardrobe, pose, props, environment, lighting, and camera. Dropping a required fact should invalidate the rewrite regardless of length.

### The current visual-model scores are poorly calibrated

Qwen repeatedly assigned baseline scores around 75 for visual match and 85 for canonical match, then often raised rewritten candidates to 85 and 95. These repeated values did not track the magnitude of visible changes. In scene 194, for example, the rewrite made large unwanted wardrobe and staging changes without receiving a corresponding penalty.

Because semantic and canonical scores carry 65% of the current objective, these generous scores caused the composite objective to select five of six rewrites, including several visually questionable results. The composite score must not be treated as a trustworthy automatic winner selector in its current form.

A stronger evaluator should compare the baseline and candidate side by side in the same request and make a direct pairwise choice for each criterion. Pairwise judgments are likely to be more stable than independent absolute scores.

### Correct canonical text does not prove correct visual execution

The critic can reward a prompt for containing the right concept even if the generated image expresses it incorrectly or damages everything around it. Scene 152 rendered the word “Unsouled” on a modern-looking wooden tag and added a belt. This met part of the literal badge requirement while remaining aesthetically and historically inconsistent.

Canonical evaluation must inspect the rendered pixels and answer narrow visual questions, such as:

- Is the badge visibly suspended from the neck?
- Is there any belt attachment?
- Is the badge shape and material appropriate?
- Did unrelated modern clothing appear?

### Edge similarity can improve for the wrong reason

Scene 108's edge score improved substantially, and the foreground arm became more prominent, but the rewritten image changed age, clothing, and character presentation. Edge similarity is therefore a useful layout signal, not a sufficient quality signal.

Likewise, scene 194's edge score changed by only +0.39 despite major semantic changes. Small edge improvements should never override visible identity or continuity failures.

### Optimization should be edit-based and hierarchical

The next loop should use the following sequence:

1. Extract a structured inventory from the original prompt.
2. Divide it into locked composition, locked continuity, target correction, and optional rendering style.
3. Ask the model for a minimal phrase-level patch rather than a replacement prompt.
4. Apply the patch programmatically while preserving all locked clauses.
5. Generate a candidate with the fixed seed.
6. Compare baseline and candidate together, criterion by criterion.
7. Reject immediately if any locked criterion regresses materially.
8. Accept only when the target correction improves and the locked content remains stable.

For complicated scenes, optimization may need separate passes for composition, character identity, props, and rendering rather than one global score.

## Revised practical conclusion

The local generate-and-critique architecture is technically viable on a 12 GB GPU, and targeted canonical corrections can succeed. However, the expanded test changes the operational conclusion: full-prompt rewriting plus independently assigned absolute scores is not a safe optimizer.

The next version should preserve the original prompt, perform minimal edits, compare candidates pairwise, and enforce hard regression gates for composition and continuity. Until those changes are implemented, results should be treated as experiments for human review rather than automatically approved improvements.
