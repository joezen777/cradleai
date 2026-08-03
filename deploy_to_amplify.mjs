import fs from "node:fs";
import path from "node:path";
import { execSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Read credentials from .credentials if not set in environment
const credsPath = path.join(here, ".credentials");
if (fs.existsSync(credsPath)) {
  const lines = fs.readFileSync(credsPath, "utf8").split("\n");
  for (const line of lines) {
    const trimmed = line.strip ? line.strip() : line.trim();
    if (trimmed && trimmed.includes("=")) {
      const [key, val] = trimmed.split("=", 2);
      if (!process.env[key]) {
        process.env[key] = val;
      }
    }
  }
}

const region = process.env.AWS_REGION || "us-east-1";
const appId = "d3px1xkakdd95h";
const branchName = "cradleai";

console.log("================================================================================");
console.log(`Deploying Cradle AI to AWS Amplify (App ID: ${appId}, Branch: ${branchName})`);
console.log("================================================================================");

// Step 1: Build static assets
console.log("\n[1/5] Building static web assets...");
execSync("npm --prefix frontend run build:static", { stdio: "inherit", cwd: here });

// Step 2: Prepare Amplify artifact (converts images to webp)
console.log("\n[2/5] Preparing Amplify artifact directory...");
execSync("node frontend/scripts/prepare-amplify-artifact.mjs frontend/amplify-artifact", { stdio: "inherit", cwd: here });

// Step 3: Zip artifact
console.log("\n[3/5] Compressing deployment zip package...");
const artifactDir = path.join(here, "frontend", "amplify-artifact");
const zipPath = path.join(here, "cradleai-deploy.zip");
if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath);
execSync(`zip -qr "${zipPath}" .`, { cwd: artifactDir, stdio: "inherit" });
const zipSizeMb = (fs.statSync(zipPath).size / 1024 / 1024).toFixed(1);
console.log(`✓ Zip package created: ${zipPath} (${zipSizeMb} MB)`);

// Helper to run AWS CLI
function awsJson(args) {
  const fullArgs = ["amplify", ...args, "--region", region, "--output", "json", "--no-cli-pager"];
  const res = spawnSync("aws", fullArgs, { encoding: "utf8", env: process.env });
  if (res.status !== 0) {
    throw new Error(`AWS CLI failed: ${res.stderr || res.stdout}`);
  }
  return JSON.parse(res.stdout);
}

// Step 4: Create deployment & upload zip
console.log("\n[4/5] Creating AWS Amplify deployment...");
const deployment = awsJson(["create-deployment", "--app-id", appId, "--branch-name", branchName]);
const jobId = deployment.jobId;
const uploadUrl = deployment.zipUploadUrl;

console.log(`✓ Deployment job created (Job ID: ${jobId})`);
console.log("Uploading package to AWS Amplify S3 storage...");
execSync(`curl --fail --silent --show-error --request PUT --header "content-type: application/zip" --upload-file "${zipPath}" "${uploadUrl}"`, { stdio: "inherit" });
console.log("✓ Upload complete.");

// Step 5: Start deployment & monitor status
console.log("\n[5/5] Starting deployment execution on AWS Amplify...");
const startJob = awsJson(["start-deployment", "--app-id", appId, "--branch-name", branchName, "--job-id", jobId]);
console.log(`Deployment started! Waiting for job ${jobId} to complete...`);

const terminalStates = new Set(["SUCCEED", "FAILED", "CANCELLED"]);
while (true) {
  const jobStatus = awsJson(["get-job", "--app-id", appId, "--branch-name", branchName, "--job-id", jobId]);
  const status = jobStatus.job.summary.status;
  console.log(`  Current deployment status: ${status}`);
  if (terminalStates.has(status)) {
    if (status === "SUCCEED") {
      console.log("\n================================================================================");
      console.log(`🎉 SUCCESS! Cradle AI has been published to AWS Amplify!`);
      console.log(`App URL: https://${branchName}.${appId}.amplifyapp.com/`);
      console.log("================================================================================");
    } else {
      throw new Error(`Amplify deployment failed with status: ${status}`);
    }
    break;
  }
  execSync("sleep 5");
}

// Cleanup
if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath);
