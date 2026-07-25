import express from "express";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(here, "..");
const outputRoot = path.join(projectRoot, "output");
const metadataPath = path.join(outputRoot, "metadata.jsonl");
const requestedGenerationPath = process.env.METADATAGEN_PATH
  ? path.resolve(projectRoot, process.env.METADATAGEN_PATH)
  : null;
const generationPath = requestedGenerationPath
  || (fs.existsSync(path.join(outputRoot, "metadatagen_full.jsonl"))
    ? path.join(outputRoot, "metadatagen_full.jsonl")
    : path.join(outputRoot, "metadatagen.jsonl"));
const port = Number(process.env.PORT || 4173);
const pollMs = 30_000;

const app = express();
const clients = new Set();
let cache = null;
let signature = "";

const normalizeRelative = (value = "") => value.replaceAll("\\", "/").replace(/^\.\//, "");
const mediaUrl = (value) => {
  if (!value) return null;
  let normalized = normalizeRelative(value);
  if (normalized.startsWith("output/")) normalized = normalized.slice(7);
  return "/media/" + normalized.split("/").map(encodeURIComponent).join("/");
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

function buildState() {
  const metadataRows = parseJsonl(metadataPath);
  const scenes = metadataRows.filter((row) => Number.isFinite(row.scene_index));
  const generations = parseJsonl(generationPath);
  const generationGroups = new Map();

  for (const row of generations) {
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
        sceneIndex: scene.scene_index,
        frameType,
        label: "Scene " + String(scene.scene_index).padStart(3, "0") + " / " + frameType,
        clipUrl: mediaUrl(scene.clip_file),
        originalUrl: mediaUrl(frameFile),
        displayUrl: mediaUrl(best?.gen_filename) || mediaUrl(frameFile),
        bestSimilarity: best ? Number(best.similarity_score) : null,
        bestSequence: best ? Number(best.gen_sequence) : null,
        completedCount: completed.length,
        generations: slots
      });
    }
  }

  frames.sort((a, b) =>
    a.sceneIndex - b.sceneIndex || (a.frameType === "first" ? -1 : 1)
  );

  const completedFrames = frames.filter((frame) => frame.completedCount > 0).length;
  const completedImages = frames.reduce((sum, frame) => sum + frame.completedCount, 0);
  return {
    frames,
    stats: {
      totalFrames: frames.length,
      completedFrames,
      completedImages,
      pendingFrames: frames.length - completedFrames,
      source: path.relative(projectRoot, generationPath),
      updatedAt: new Date().toISOString()
    }
  };
}

function getSignature() {
  return [metadataPath, generationPath].map((filePath) => {
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

refresh(true);
setInterval(() => refresh(false), pollMs).unref();

app.get("/api/state", (_request, response) => {
  refresh(false);
  response.json(cache);
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

app.listen(port, "0.0.0.0", () => {
  console.log("Cradle Film Monitor: http://127.0.0.1:" + port);
  console.log("Watching: " + path.relative(projectRoot, generationPath) + " every 30 seconds");
});
