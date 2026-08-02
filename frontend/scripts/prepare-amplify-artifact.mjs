import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";

const sourceRoot = path.resolve("dist");
const targetRoot = path.resolve(process.argv[2] || "amplify-artifact");
const pngJobs = [];

function copyTree(sourceDir) {
  for (const entry of fs.readdirSync(sourceDir, { withFileTypes: true })) {
    const source = path.join(sourceDir, entry.name);
    const relative = path.relative(sourceRoot, source);
    if (relative === "state.json") continue;
    const target = path.join(targetRoot, relative);
    if (entry.isDirectory()) {
      fs.mkdirSync(target, { recursive: true });
      copyTree(source);
    } else if (entry.name.toLowerCase().endsWith(".webm")) {
      continue;
    } else if (entry.name.toLowerCase().endsWith(".png")) {
      pngJobs.push({ source, target: target.slice(0, -4) + ".webp" });
    } else {
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.copyFileSync(source, target);
    }
  }
}

function convert({ source, target }) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  return new Promise((resolve, reject) => {
    const process = spawn("ffmpeg", [
      "-v", "error", "-i", source, "-c:v", "libwebp", "-quality", "88", "-y", target
    ]);
    process.on("error", reject);
    process.on("exit", (code) => code === 0 ? resolve() : reject(new Error(`ffmpeg exited ${code}`)));
  });
}

fs.mkdirSync(targetRoot, { recursive: true });
copyTree(sourceRoot);

let nextJob = 0;
await Promise.all(Array.from({ length: 8 }, async () => {
  while (nextJob < pngJobs.length) await convert(pngJobs[nextJob++]);
}));

const state = JSON.parse(fs.readFileSync(path.join(sourceRoot, "state.json"), "utf8"));
function rewrite(value) {
  if (typeof value === "string" && value.startsWith("/media/") && value.endsWith(".webm")) {
    return null;
  }
  if (typeof value === "string" && value.startsWith("/media/") && value.endsWith(".png")) {
    return value.slice(0, -4) + ".webp";
  }
  if (Array.isArray(value)) return value.map(rewrite);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, rewrite(item)]));
  }
  return value;
}
fs.writeFileSync(path.join(targetRoot, "state.json"), JSON.stringify(rewrite(state)));
console.log(`Prepared ${pngJobs.length} WebP images in ${targetRoot}.`);
