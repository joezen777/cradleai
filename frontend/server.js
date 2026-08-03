import express from "express";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(here, "..");
const outputRoot = path.join(projectRoot, "output");
const metadataPath = path.join(outputRoot, "metadata.jsonl");
const generationPath = path.join(outputRoot, "metadatagen.jsonl");
const pegasusMetadataPath = path.join(outputRoot, "pegasus_metadata.jsonl");
const chapterMetadataPath = path.join(outputRoot, "pegasus_chapter_metadata.jsonl");
const chapterCastPath = path.join(outputRoot, "gemini_chapter_cast.jsonl");
const batchRegistryPath = path.join(here, "batches.jsonl");
const enrichedChapterCastPath = path.join(
  outputRoot,
  "gemini_chapter_cast.before_pegasus_rerun.jsonl"
);
const bookcastPath = path.join(projectRoot, "bookcast.jsonl");
const port = Number(process.env.PORT || 4173);
const host = process.env.HOST || "0.0.0.0";
const pollMs = 30_000;

const app = express();
const clients = new Set();
let cache = null;
let signature = "";

const normalizeRelative = (value = "") => value.replaceAll("\\", "/").replace(/^\.\//, "");
const mediaUrl = (value) => {
  if (!value) return null;
  let normalized = normalizeRelative(value);
  const idx = normalized.indexOf("output/");
  if (idx !== -1) {
    normalized = normalized.slice(idx + 7);
  }
  return "/media/" + normalized.split("/").filter(Boolean).map(encodeURIComponent).join("/");
};

function parseJsonl(filePath) {
  if (!fs.existsSync(filePath)) return [];
  return fs.readFileSync(filePath, "utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .flatMap((line) => {
      try { return [JSON.parse(line)]; }
      catch { return []; }
    });
}

function normName(str) {
  return String(str || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function parseFirstAppearance(row) {
  const ev = row.evidence_notes;
  const books = Array.isArray(row.books) ? row.books : [];
  let bookName = "";
  let chapterName = "";

  if (ev && typeof ev === "object") {
    bookName = ev.book || ev.cited_book || ev.book_id || "";
    chapterName = ev.chapter || ev.cited_chapter || ev.chapter_id || "";
    if (!chapterName && ev.passage_id) {
      const parts = String(ev.passage_id).split(":");
      if (parts.length >= 3 && parts[1] === "chapter") {
        chapterName = "Chapter " + parts[2];
      }
    }
  } else if (typeof ev === "string") {
    const passMatch = ev.match(/([a-z]+):chapter:(\d+)/i);
    if (passMatch) {
      bookName = passMatch[1];
      chapterName = "Chapter " + passMatch[2];
    } else {
      const chMatch = ev.match(/chapter\s*(\d+)/i);
      if (chMatch) chapterName = "Chapter " + chMatch[1];
      if (/unsouled/i.test(ev)) bookName = "Unsouled";
      else if (/soulsmith/i.test(ev)) bookName = "Soulsmith";
    }
  }

  if (!bookName && books.length) {
    bookName = books[0];
  }
  if (!bookName) bookName = "Unsouled";

  bookName = bookName.trim().charAt(0).toUpperCase() + bookName.trim().slice(1);
  if (/unsouled/i.test(bookName)) bookName = "Unsouled";
  if (/soulsmith/i.test(bookName)) bookName = "Soulsmith";

  chapterName = (chapterName || "Chapter 1").trim();
  if (/^\d+$/.test(chapterName)) chapterName = "Chapter " + chapterName;
  if (/^chapter:\s*\d+$/i.test(chapterName)) {
    chapterName = "Chapter " + chapterName.replace(/^chapter:\s*/i, "");
  }
  if (/^[a-z]+:chapter:\d+$/i.test(chapterName)) {
    chapterName = "Chapter " + chapterName.split(":").pop();
  }

  return { book: bookName, chapter: chapterName, subtitle: `${bookName} • ${chapterName}` };
}

function buildBookCast() {
  const rawBookcast = parseJsonl(bookcastPath);
  if (!rawBookcast.length) return [];

  const imagesByName = new Map();
  for (const castFile of [enrichedChapterCastPath, chapterCastPath]) {
    for (const record of parseJsonl(castFile)) {
      for (const c of record.cast || []) {
        if (!c.character_name) continue;
        const key = normName(c.character_name);
        for (const img of c.image_generations || []) {
          if (img.gen_character_image) {
            if (!imagesByName.has(key)) imagesByName.set(key, []);
            imagesByName.get(key).push({
              genaimodel: img.genaimodel,
              celebrityName: img.celebrity_name || null,
              imageUrl: mediaUrl(img.gen_character_image)
            });
          }
        }
      }
    }
  }

  return rawBookcast.map((item, index) => {
    const canonicalName = item.canonical_name || "Unknown Character";
    const identityKey = item.identity_key || "";
    const k1 = normName(canonicalName);
    const k2 = normName(identityKey);

    let matched = imagesByName.get(k1) || imagesByName.get(k2) || null;
    if (!matched) {
      for (const [key, imgs] of imagesByName.entries()) {
        if (key.length >= 4 && (k1.includes(key) || key.includes(k1))) {
          matched = imgs;
          break;
        }
      }
    }

    let directImgUrl = mediaUrl(item.gen_character_image || item.primary_image_url);
    if (!directImgUrl && Array.isArray(item.image_generations) && item.image_generations.length) {
      directImgUrl = mediaUrl(item.image_generations[0].gen_character_image);
    }
    const { book, chapter, subtitle } = parseFirstAppearance(item);
    const finalImageUrl = directImgUrl || matched?.[0]?.imageUrl || null;

    return {
      id: "bookcast-" + index + "-" + (identityKey || normName(canonicalName)),
      canonicalName,
      identityKey,
      entityType: item.entity_type || "individual person",
      speciesOrObjectType: item.species_or_object_type || "human",
      portraitDescription: item.portrait_description || "",
      zimageturboPrompt: item.zimageturbo_prompt || null,
      firstAppearanceBook: book,
      firstAppearanceChapter: chapter,
      firstAppearanceSubtitle: subtitle,
      face: item.face || null,
      skinTone: item.skin_tone || null,
      eyes: item.eyes || null,
      hair: item.hair || null,
      build: item.build || null,
      posture: item.posture || null,
      emotion: item.emotion || null,
      action: item.action || null,
      fightingMove: item.fighting_move || null,
      clothing: item.clothing || null,
      wardrobe: item.wardrobe || null,
      accessories: item.accessories || null,
      colorInformation: item.color_information || null,
      evidenceNotes: typeof item.evidence_notes === "object" ? JSON.stringify(item.evidence_notes) : (item.evidence_notes || null),
      confidence: item.confidence || "high",
      qwenModel: item.qwen_model || null,
      imageGenerations: matched || [],
      primaryImageUrl: finalImageUrl
    };
  });
}

export function buildState(requestedBatch = null) {
  const metadataRows = parseJsonl(metadataPath);
  const scenes = metadataRows.filter((row) => Number.isFinite(row.scene_index));
  const generations = parseJsonl(generationPath);
  const configuredBatches = parseJsonl(batchRegistryPath)
    .filter((row) => String(row.batchName || "").trim())
    .map((row) => ({
      batchName: String(row.batchName).trim(),
      batchTip: String(row.batchTip || "").trim(),
      default: String(row.default).toLowerCase() === "yes"
    }));
  const batches = configuredBatches.length
    ? configuredBatches
    : [{ batchName: "zimageturbo", batchTip: "", default: true }];
  const defaultBatch = batches.find((batch) => batch.default)?.batchName || batches[0].batchName;
  const selectedBatch = batches.some((batch) => batch.batchName === requestedBatch)
    ? requestedBatch
    : defaultBatch;
  const clipDescriptions = new Map(
    parseJsonl(pegasusMetadataPath).map((row) => [
      Number(row.scene_index),
      row.description || null
    ])
  );
  function buildFrames(batchName) {
    const generationGroups = new Map();
    for (const row of generations) {
      if (String(row.batch_name || "zimageturbo") !== batchName) continue;
      const key = normalizeRelative(row.frame_file);
      if (!key) continue;
      if (!generationGroups.has(key)) generationGroups.set(key, []);
      generationGroups.get(key).push(row);
    }

    const frames = [];
    for (const scene of scenes) {
      const frameFields = [
        ["first_frame_file", "first"],
        ["last_frame_file", "last"]
      ];
      for (const [field, frameType] of frameFields) {
        const rawFrame = scene[field];
        if (!rawFrame) continue;
        const frameFile = normalizeRelative(rawFrame);
        const rows = generationGroups.get(frameFile) || [];
      const promptText = rows.find((row) =>
        String(row.prompt_text || "").trim()
      )?.prompt_text || null;
      const completed = rows.filter((row) =>
        row.gen_filename && Number.isFinite(Number(row.similarity_score))
      );
      const best = completed.reduce((winner, row) =>
        !winner || Number(row.similarity_score) > Number(winner.similarity_score)
          ? row : winner
      , null);
      const slots = Array.from({ length: 10 }, (_, index) => {
        const sequence = index + 1;
        const candidates = rows.filter((row) => Number(row.gen_sequence) === sequence);
        const row = candidates.find((item) => item.gen_filename) || candidates[0];
        return {
          sequence,
          url: mediaUrl(row?.gen_filename),
          similarity: Number.isFinite(Number(row?.similarity_score))
            ? Number(row.similarity_score)
            : null,
          success: row?.generation_success ?? null,
          seed: row?.seed ?? null
        };
      });

      frames.push({
        id: String(scene.scene_index) + "-" + frameType,
        batchName,
        sceneIndex: scene.scene_index,
        frameType,
        label: "Scene " + String(scene.scene_index).padStart(3, "0") + " / " + frameType,
        clipUrl: mediaUrl(scene.clip_file),
        clipDescription: clipDescriptions.get(Number(scene.scene_index)) || null,
        originalUrl: mediaUrl(frameFile),
        displayUrl: mediaUrl(best?.gen_filename) || mediaUrl(frameFile),
        bestSimilarity: best ? Number(best.similarity_score) : null,
        bestSequence: best ? Number(best.gen_sequence) : null,
        completedCount: completed.length,
        promptText,
        generations: slots
      });
      }
    }
    frames.sort((a, b) =>
      a.sceneIndex - b.sceneIndex || (a.frameType === "first" ? -1 : 1)
    );
    return frames;
  }

  const framesByBatch = Object.fromEntries(
    batches.map((batch) => [batch.batchName, buildFrames(batch.batchName)])
  );
  const frames = framesByBatch[selectedBatch] || [];

  const completedFrames = frames.filter((frame) => frame.completedCount > 0).length;
  const completedImages = frames.reduce((sum, frame) => sum + frame.completedCount, 0);
  const statsByBatch = Object.fromEntries(
    Object.entries(framesByBatch).map(([batchName, batchFrames]) => [batchName, {
      totalFrames: batchFrames.length,
      completedFrames: batchFrames.filter((frame) => frame.completedCount > 0).length,
      completedImages: batchFrames.reduce((sum, frame) => sum + frame.completedCount, 0),
      pendingFrames: batchFrames.filter((frame) => frame.completedCount === 0).length
    }])
  );
  const chapterRows = parseJsonl(chapterMetadataPath);
  const currentCastRows = new Map(
    parseJsonl(chapterCastPath).map((row) => [Number(row.chapter_number), row])
  );
  const enrichedCastRows = new Map(
    parseJsonl(enrichedChapterCastPath).map((row) => [Number(row.chapter_number), row])
  );
  const chapters = chapterRows
    .filter((row) => Number.isFinite(Number(row.chapter_index)))
    .map((chapter) => {
      const chapterNumber = Number(chapter.chapter_index);
      const names = new Map(
        (chapter.speaker_name_guesses || []).map((guess) => [
          String(guess.speaker_id),
          String(guess.character_name_guess || guess.speaker_id)
        ])
      );
      const transcript = (chapter.transcript_turns || [])
        .filter((turn) => String(turn.text || "").trim())
        .map((turn) => ({
          speaker: turn.speaker_id === "audio_event"
            ? "Sound"
            : names.get(String(turn.speaker_id)) || String(turn.speaker_id || "Unknown"),
          text: String(turn.text).replace(/\s+/g, " ").trim()
        }));
      const currentCastRecord = currentCastRows.get(chapterNumber);
      const enrichedCastRecord = enrichedCastRows.get(chapterNumber);
      const castRecord = enrichedCastRecord?.cast?.some((member) =>
        member.image_generations?.some((generation) => generation.gen_character_image)
      ) ? enrichedCastRecord : currentCastRecord;
      const chapterStem = "chapter_" + String(chapterNumber).padStart(3, "0");
      const mp4Path = path.join(outputRoot, "pegasus_chapters", chapterStem + ".mp4");
      const thumbnailPath = path.join(
        outputRoot,
        "pegasus_chapter_thumbnails",
        chapterStem + ".jpg"
      );
      return {
        id: "chapter-" + chapterNumber,
        chapterNumber,
        sceneIndex: chapterNumber,
        frameType: "chapter",
        label: "Chapter " + String(chapterNumber).padStart(2, "0"),
        clipUrl: mediaUrl(
          fs.existsSync(mp4Path)
            ? path.relative(outputRoot, mp4Path)
            : chapter.aggregate_clip_file
        ),
        thumbnailUrl: mediaUrl(
          chapter.thumbnail || (fs.existsSync(thumbnailPath)
            ? path.relative(outputRoot, thumbnailPath)
            : null)
        ),
        displayUrl: mediaUrl(
          chapter.thumbnail || (fs.existsSync(thumbnailPath)
            ? path.relative(outputRoot, thumbnailPath)
            : null)
        ),
        movieStartTimecode: chapter.movie_start_timecode,
        movieEndTimecode: chapter.movie_end_timecode,
        durationSeconds: chapter.duration_seconds,
        chapterSummary: chapter.chapter_summary || "",
        transcript,
        cast: (castRecord?.cast || []).map((member, index) => ({
          id: chapterNumber + "-cast-" + index,
          characterName: member.character_name,
          characterDescription: member.character_description,
          characterDetails: member.character_details,
          characterGenprompt: member.character_genprompt,
          imageGenerations: (member.image_generations || []).map((generation) => ({
            genaimodel: generation.genaimodel,
            celebrityName: generation.celebrity_name || null,
            imageUrl: mediaUrl(generation.gen_character_image)
          }))
        }))
      };
    })
    .sort((a, b) => a.chapterNumber - b.chapterNumber);

  const bookCast = buildBookCast();

  return {
    frames,
    framesByBatch,
    batches,
    selectedBatch,
    statsByBatch,
    chapters,
    bookCast,
    stats: {
      totalFrames: frames.length,
      completedFrames,
      completedImages,
      pendingFrames: frames.length - completedFrames,
      totalChapters: chapters.length,
      chaptersWithCast: chapters.filter((chapter) => chapter.cast.length).length,
      totalBookCast: bookCast.length,
      bookCastWithImages: bookCast.filter((c) => c.primaryImageUrl).length,
      castImages: chapters.reduce(
        (total, chapter) =>
          total + chapter.cast.reduce(
            (chapterTotal, member) =>
              chapterTotal + member.imageGenerations.filter(
                (generation) => generation.imageUrl
              ).length,
            0
          ),
        0
      ),
      source: path.relative(projectRoot, generationPath),
      updatedAt: new Date().toISOString()
    }
  };
}

function getSignature() {
  return [
    metadataPath,
    generationPath,
    pegasusMetadataPath,
    chapterMetadataPath,
    chapterCastPath,
    enrichedChapterCastPath,
    batchRegistryPath,
    bookcastPath
  ].map((filePath) => {
    try {
      const stat = fs.statSync(filePath);
      return filePath + ":" + stat.size + ":" + stat.mtimeMs;
    } catch {
      return filePath + ":missing";
    }
  }).join("|");
}

function refresh(force = false) {
  const nextSignature = getSignature();
  if (!force && nextSignature === signature) return;
  signature = nextSignature;
  cache = buildState();
  const payload = "event: update\ndata: " + JSON.stringify(cache.stats) + "\n\n";
  for (const response of clients) response.write(payload);
}

app.get("/api/state", (request, response) => {
  refresh(false);
  const requestedBatch = String(request.query.batch || "").trim();
  response.json(requestedBatch ? buildState(requestedBatch) : cache);
});

app.get("/api/events", (request, response) => {
  response.set({
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive"
  });
  response.flushHeaders();
  clients.add(response);
  response.write("event: connected\ndata: {}\n\n");
  request.on("close", () => clients.delete(response));
});

app.get("/api/health", (_request, response) => {
  response.json({
    ok: true,
    source: path.relative(projectRoot, generationPath),
    pollSeconds: pollMs / 1000,
    clients: clients.size
  });
});

app.use("/media", express.static(outputRoot, {
  fallthrough: false,
  maxAge: "1h",
  immutable: false
}));
app.use(express.static(path.join(here, "dist")));
app.use((_request, response) => {
  response.sendFile(path.join(here, "dist", "index.html"));
});

export function startServer() {
  refresh(true);
  setInterval(() => refresh(false), pollMs).unref();
  return app.listen(port, host, () => {
    console.log("Cradle Film Monitor:");
    console.log("  Local:   http://127.0.0.1:" + port);
    const addresses = Object.values(os.networkInterfaces())
      .flat()
      .filter((address) =>
        address
        && address.family === "IPv4"
        && !address.internal
      )
      .map((address) => address.address);
    for (const address of [...new Set(addresses)]) {
      console.log("  Network: http://" + address + ":" + port);
    }
    if (host !== "0.0.0.0") console.log("  Bound to HOST=" + host);
    console.log("Watching: " + path.relative(projectRoot, generationPath) + " every 30 seconds");
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  startServer();
}
