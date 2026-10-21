import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import type { RegistryData, CollectionsData, RoutingRules, RouteOptions, RouteResult, SkillLayer } from "./types.ts";
import { resolveRoute } from "./resolve.ts";
import { validateRegistry } from "./validate.ts";
import { applySkills, bundleSkills, type ApplyResult } from "./apply.ts";

export { applySkills, bundleSkills, type ApplyResult };

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Walk up to the package root. From source this file lives in router/ (root is one level up);
// from the compiled build it lives in dist/router/ (root is two levels up).
function findPackageRoot(startDir: string): string {
  let dir = startDir;
  for (;;) {
    if (fs.existsSync(path.join(dir, "package.json")) && fs.existsSync(path.join(dir, "routing", "registry.json"))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      throw new Error(`Terraproof package root not found above ${startDir}`);
    }
    dir = parent;
  }
}

const workspaceRoot = findPackageRoot(__dirname);

export function loadRoutingData(baseDir = workspaceRoot): {
  registry: RegistryData;
  collections: CollectionsData;
  rules: RoutingRules;
} {
  const registryPath = path.join(baseDir, "routing", "registry.json");
  const collectionsPath = path.join(baseDir, "routing", "collections.json");
  const rulesPath = path.join(baseDir, "routing", "rules.json");

  const registry: RegistryData = JSON.parse(fs.readFileSync(registryPath, "utf-8"));
  const collections: CollectionsData = JSON.parse(fs.readFileSync(collectionsPath, "utf-8"));
  const rules: RoutingRules = JSON.parse(fs.readFileSync(rulesPath, "utf-8"));

  return { registry, collections, rules };
}

export function route(prompt: string, options: RouteOptions = {}, baseDir = workspaceRoot): RouteResult {
  const { registry, collections, rules } = loadRoutingData(baseDir);
  return resolveRoute(prompt, registry, collections, rules, options);
}

export function printRouteResult(result: RouteResult, format: "table" | "json" = "table"): void {
  if (format === "json") {
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  console.log("\n================================================================================");
  console.log("                      Terraproof Smart Skill Router");
  console.log("================================================================================");
  console.log(`Task Prompt : "${result.prompt}"`);
  console.log(`Confidence  : ${(result.confidence * 100).toFixed(0)}%`);
  console.log(`Selected    : ${result.skills.length} skill(s)`);
  if (result.dryRun) {
    console.log(`Mode        : DRY RUN (No changes made)`);
  }
  console.log("--------------------------------------------------------------------------------");

  if (result.warning) {
    console.log(`\n⚠️  ${result.warning}`);
  }

  const layerLabels: Record<SkillLayer, string> = {
    process: "1. Process & Planning",
    domain: "2. Domain Knowledge",
    implementation: "3. Implementation & Architecture",
    risk: "4. Risk & Security Audit",
    verification: "5. Testing & Verification"
  };

  const layers: SkillLayer[] = ["process", "domain", "implementation", "risk", "verification"];

  for (const layer of layers) {
    const skillsInLayer = result.skillsByLayer[layer];
    if (skillsInLayer.length > 0) {
      console.log(`\n[ ${layerLabels[layer]} ]`);
      for (const skill of skillsInLayer) {
        console.log(`  * ${skill.name.padEnd(30)} (Score: ${skill.score})`);
        console.log(`    -> ${skill.reason}`);
      }
    }
  }

  if (result.dryRun && result.dropped && result.dropped.length > 0) {
    console.log("\n[ Diagnostic: Dropped / Suppressed Candidates ]");
    for (const d of result.dropped.slice(0, 8)) {
      console.log(`  - ${d.skill.padEnd(30)}: ${d.reason}`);
    }
  }

  console.log("\n================================================================================\n");
}

export interface ParsedCliArgs {
  command: "route" | "apply" | "bundle";
  prompt: string;
  options: RouteOptions;
  format: "table" | "json";
  doApply: boolean;
  doBundle: boolean;
  targetDir: string;
  outFile?: string;
}

const FLAG_OPTIONS = ["--dry-run", "--apply", "-a", "--bundle", "-b"];
const VALUE_OPTIONS = ["--target", "--out", "--include", "--exclude", "--collection", "--format"];

// Pure argument parser: args are the raw CLI arguments with the command first.
// Returns the parsed options, or { error } describing the first invalid input.
export function parseCliArgs(
  args: string[],
  registry: RegistryData,
  collections: CollectionsData
): ParsedCliArgs | { error: string } {
  const command = args[0];
  if (command !== "route" && command !== "apply" && command !== "bundle") {
    return { error: `Unknown command '${command}'. Expected route, apply, bundle, or validate.` };
  }

  const prompt = args[1];
  if (!prompt || prompt.startsWith("-")) {
    return { error: "Please provide a task description string." };
  }

  const include: string[] = [];
  const exclude: string[] = [];
  const parsed: ParsedCliArgs = {
    command,
    prompt,
    options: { include, exclude, dryRun: false },
    format: "table",
    doApply: command === "apply",
    doBundle: command === "bundle",
    targetDir: ".agents/skills"
  };

  for (let i = 2; i < args.length; i++) {
    const arg = args[i];

    if (FLAG_OPTIONS.includes(arg)) {
      if (arg === "--dry-run") {
        parsed.options.dryRun = true;
      } else if (arg === "--apply" || arg === "-a") {
        parsed.doApply = true;
      } else {
        parsed.doBundle = true;
      }
      continue;
    }

    if (VALUE_OPTIONS.includes(arg)) {
      const value = args[i + 1];
      if (!value || value.startsWith("-")) {
        return { error: `Option ${arg} requires a value.` };
      }
      i++;

      if (arg === "--target") {
        parsed.targetDir = value;
      } else if (arg === "--out") {
        parsed.outFile = value;
      } else if (arg === "--include" || arg === "--exclude") {
        if (!Object.hasOwn(registry.skills, value)) {
          return { error: `Unknown skill '${value}' for ${arg}. Registered skills are listed in routing/registry.json.` };
        }
        if (arg === "--include") {
          include.push(value);
        } else {
          exclude.push(value);
        }
      } else if (arg === "--collection") {
        if (!Object.hasOwn(collections.collections, value)) {
          const available = Object.keys(collections.collections).join(", ");
          return { error: `Unknown collection '${value}'. Available collections: ${available}.` };
        }
        parsed.options.collection = value;
      } else {
        if (value !== "json" && value !== "table") {
          return { error: `Invalid --format '${value}'. Use json or table.` };
        }
        parsed.format = value;
      }
      continue;
    }

    if (arg.startsWith("-")) {
      return { error: `Unknown option '${arg}'.` };
    }
    return { error: `Unexpected argument '${arg}'. Put the task description in quotes, then options.` };
  }

  return parsed;
}

export function runCli(args = process.argv.slice(2)): void {
  if (args.includes("--version") || args.includes("-v")) {
    const pkgPath = path.join(workspaceRoot, "package.json");
    const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf-8"));
    console.log(`terraproof v${pkg.version}`);
    process.exit(0);
  }

  if (args.length === 0 || args.includes("--help") || args.includes("-h")) {
    console.log(`
Terraproof Smart Router & Skills CLI

Usage:
  terraproof route "<task>" [options]
  terraproof apply "<task>" [options]
  terraproof bundle "<task>" [options]
  terraproof validate
  node router/index.ts route "<task>" [options]   (from a source checkout)

Commands:
  route "<prompt>"       Calculate optimal skill composition for a task
  apply "<prompt>"       Calculate and copy selected skills to target (.agents/skills)
  bundle "<prompt>"      Output concatenated markdown of instructions & selected skills
  validate               Verify skill registry integrity and disk paths

Options:
  --apply, -a            Install/copy selected skills to target directory
  --target <dir>         Target directory for skills (default: .agents/skills)
  --bundle, -b           Generate unified markdown prompt/context
  --out <file>           Write bundled markdown output to file
  --dry-run              Display recommendation without modifying project
  --include <skill>      Force inclusion of a specific skill (can repeat)
  --exclude <skill>      Force exclusion of a specific skill (can repeat)
  --collection <name>    Seed from a preset collection (gis, data-analysis, production, remote-sensing)
  --format <json|table>  Output format (default: table)
  --version, -v          Show version number
  --help, -h             Show this help message

Examples:
  terraproof route "Reproject a GeoTIFF to EPSG:3857 and build a COG with GDAL"
  terraproof apply "Design a PostGIS schema for GPS tracks"
  terraproof bundle "Compute NDVI change for 2020-2024" --out context.md
  node router/index.ts route "Compute NDVI change for 2020-2024" --dry-run
`);
    process.exit(0);
  }

  const command = args[0];

  if (command === "validate") {
    if (args.length > 1) {
      console.error(`Error: 'validate' takes no options (unexpected '${args[1]}').`);
      process.exit(1);
    }
    console.log("Validating Terraproof skill registry...");
    const report = validateRegistry(workspaceRoot);
    if (report.valid) {
      console.log(`✓ Registry validation passed: ${report.skillsCount} skills, ${report.collectionsCount} collections.`);
      process.exit(0);
    } else {
      console.error(`✗ Registry validation failed with ${report.errors.length} error(s):`);
      for (const err of report.errors) {
        console.error(`  - ${err}`);
      }
      process.exit(1);
    }
  }

  const { registry, collections } = loadRoutingData(workspaceRoot);
  const parsed = parseCliArgs(args, registry, collections);
  if ("error" in parsed) {
    console.error(`Error: ${parsed.error}`);
    process.exit(1);
  }

  const result = route(parsed.prompt, parsed.options);

  if (parsed.doBundle) {
    const bundle = bundleSkills(result, workspaceRoot, true);
    if (parsed.outFile) {
      fs.writeFileSync(path.resolve(process.cwd(), parsed.outFile), bundle, "utf-8");
      console.log(`✓ Composed bundle written to: ${parsed.outFile} (${result.skills.length} skills, ${bundle.length} bytes)`);
    } else {
      console.log(bundle);
    }
    return;
  }

  printRouteResult(result, parsed.format);

  if (parsed.doApply && !parsed.options.dryRun) {
    console.log(`\nApplying ${result.skills.length} skill(s) to '${parsed.targetDir}'...`);
    const applyRes = applySkills(result, parsed.targetDir, process.cwd(), workspaceRoot);
    if (applyRes.errors.length > 0) {
      console.error(`⚠️  Some skills had errors during install:`);
      for (const err of applyRes.errors) {
        console.error(`  - ${err}`);
      }
    }
    console.log(`✓ Installed ${applyRes.appliedSkills.length} skill(s) to '${applyRes.targetDir}'.`);
    if (applyRes.instructionsCopied) {
      console.log(`✓ Copied universal engineering instructions.`);
    }
    if (applyRes.manifestWritten) {
      console.log(`✓ Generated skills manifest (AGENTS.md).`);
    }
    console.log(
      `\nNothing loads these skills automatically. Reference '${applyRes.targetDir}' from your agent's instruction file (for example, a root AGENTS.md).`
    );
  }
}

// CLI auto-run when invoked directly
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(__filename)) {
  runCli();
}
