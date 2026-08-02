import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildState } from "../server.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(here, "..");
const outputRoot = path.resolve(frontendRoot, "../output");
const distRoot = path.join(frontendRoot, "dist");
const state = buildState();
const mediaUrls = new Set();

function collect(value) {
  if (typeof value === "string" && value.startsWith("/media/")) mediaUrls.add(value);
  else if (Array.isArray(value)) value.forEach(collect);
  else if (value && typeof value === "object") Object.values(value).forEach(collect);
}

collect(state);
fs.writeFileSync(path.join(distRoot, "state.json"), JSON.stringify(state));

let bytes = 0;
for (const mediaUrl of [...mediaUrls].sort()) {
  const relative = decodeURIComponent(mediaUrl.slice("/media/".length));
  const source = path.resolve(outputRoot, relative);
  if (source !== outputRoot && !source.startsWith(outputRoot + path.sep)) {
    throw new Error(`Unsafe media path: ${relative}`);
  }
  if (!fs.existsSync(source)) throw new Error(`Missing referenced media: ${relative}`);
  const target = path.join(distRoot, "media", relative);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
  bytes += fs.statSync(source).size;
}

console.log(`Packaged ${mediaUrls.size} referenced media files (${(bytes / 1024 / 1024).toFixed(1)} MiB).`);
