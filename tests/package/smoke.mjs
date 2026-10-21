// Package smoke test: pack the repo, install the tarball into a fresh project,
// and run the installed CLI. Plain JavaScript, Node 20+, no dependencies.

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const pkg = JSON.parse(fs.readFileSync(path.join(repoRoot, "package.json"), "utf-8"));
const isWindows = process.platform === "win32";

class Abort extends Error {}

let passed = 0;
let failed = 0;

function check(name, ok, detail = "") {
  if (ok) {
    passed++;
    console.log(`PASS  ${name}`);
  } else {
    failed++;
    console.log(`FAIL  ${name}`);
    if (detail) console.log(`      ${detail.trim().split("\n").join("\n      ")}`);
  }
  return ok;
}

// Fail the check and stop: later steps depend on this one.
function abort(name, detail) {
  check(name, false, detail);
  throw new Abort(name);
}

function quoteArg(arg) {
  return /[\s"&|<>^]/.test(arg) ? `"${arg.replace(/"/g, '\\"')}"` : arg;
}

// npm is npm.cmd on Windows, which Node only runs through a shell.
function npm(args, cwd) {
  const options = { cwd, encoding: "utf-8", timeout: 300000 };
  if (isWindows) {
    return spawnSync(`npm.cmd ${args.map(quoteArg).join(" ")}`, { ...options, shell: true });
  }
  return spawnSync("npm", args, options);
}

function runCli(cliPath, args, cwd) {
  return spawnSync(process.execPath, [cliPath, ...args], { cwd, encoding: "utf-8", timeout: 120000 });
}

function describe(res) {
  const out = `${res.stdout || ""}${res.stderr || ""}`.trim();
  return `exit=${res.status} ${res.error ? `error=${res.error.message} ` : ""}${out.slice(0, 800)}`;
}

function removeDir(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true, maxRetries: 3 });
    return true;
  } catch (err) {
    console.log(`WARN  could not remove ${dir}: ${err.message}`);
    return false;
  }
}

function main() {
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "terraproof-smoke-"));
  const packDir = path.join(workDir, "pack");
  const projectDir = path.join(workDir, "project");
  console.log(`Package smoke test for ${pkg.name}@${pkg.version}`);
  console.log(`Temp dir: ${workDir}`);

  try {
    fs.mkdirSync(packDir);
    fs.mkdirSync(projectDir);

    // 1. Pack. The prepack script builds dist/ first.
    const pack = npm(["pack", "--pack-destination", packDir], repoRoot);
    if (pack.status !== 0) abort("npm pack succeeds", describe(pack));
    const tarball = fs.readdirSync(packDir).find((f) => f.endsWith(".tgz"));
    if (!check("npm pack produces a tarball", Boolean(tarball), describe(pack))) throw new Abort("pack");
    const tarballPath = path.join(packDir, tarball);

    // 2. Fresh project and install of the tarball
    const init = npm(["init", "-y"], projectDir);
    if (init.status !== 0) abort("npm init -y in a fresh project", describe(init));
    check("npm init -y in a fresh project", true);
    const install = npm(["install", tarballPath, "--no-audit", "--no-fund"], projectDir);
    if (install.status !== 0) abort("npm install <tarball> into a fresh project", describe(install));
    check("npm install <tarball> into a fresh project", true);

    const installedRoot = path.join(projectDir, "node_modules", pkg.name);
    const cliPath = path.join(installedRoot, "bin", "terraproof.js");
    check(
      "installed package ships compiled dist/router and no router/ sources",
      fs.existsSync(path.join(installedRoot, "dist", "router", "index.js")) &&
        !fs.existsSync(path.join(installedRoot, "router"))
    );

    // 3. Installed CLI behaviour
    const version = runCli(cliPath, ["--version"], projectDir);
    check(
      `--version prints "${pkg.name} v${pkg.version}"`,
      version.status === 0 && version.stdout.trim() === `${pkg.name} v${pkg.version}`,
      describe(version)
    );

    const route = runCli(
      cliPath,
      ["route", "Reproject a GeoTIFF to EPSG:3857 and build a COG with GDAL", "--format", "json"],
      projectDir
    );
    let skillNames = [];
    let jsonOk = false;
    if (route.status === 0) {
      try {
        skillNames = JSON.parse(route.stdout).skills.map((s) => s.name);
        jsonOk = true;
      } catch {
        jsonOk = false;
      }
    }
    check(
      "route ... --format json exits 0 and selects gdal",
      route.status === 0 && jsonOk && skillNames.includes("gdal"),
      describe(route)
    );

    const validate = runCli(cliPath, ["validate"], projectDir);
    check("validate exits 0", validate.status === 0, describe(validate));

    const badCollection = runCli(cliPath, ["route", "x", "--collection", "doesnotexist"], projectDir);
    check(
      "route with unknown --collection exits non-zero and names it",
      badCollection.status !== 0 && badCollection.stderr.includes("doesnotexist"),
      describe(badCollection)
    );
  } catch (err) {
    if (!(err instanceof Abort)) {
      check("unexpected error", false, err && err.stack ? err.stack : String(err));
    }
  } finally {
    const cleaned = removeDir(workDir);
    if (cleaned) console.log("Cleaned up temp dir.");
  }

  console.log("");
  const total = passed + failed;
  if (failed === 0) {
    console.log(`PASS: package smoke test passed (${passed}/${total} checks).`);
    process.exit(0);
  } else {
    console.log(`FAIL: package smoke test failed (${failed} of ${total} checks failed).`);
    process.exit(1);
  }
}

main();
