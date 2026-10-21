import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import type { SkillLayer, SkillMetadata, SkillSection } from "./types.ts";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Source-checkout tool: router/ sits directly under the repository root.
const defaultRoot = path.resolve(__dirname, "..");

const VALID_LAYERS: SkillLayer[] = ["process", "domain", "implementation", "risk", "verification"];
const MANIFEST_FIELDS = [
  "name",
  "layer",
  "domains",
  "capabilities",
  "triggers",
  "recommended",
  "requires",
  "conflicts",
  "explanation",
  "sections",
  "checks"
];
const LIST_FIELDS = ["domains", "capabilities", "triggers", "recommended", "requires", "conflicts", "checks"];
const RELATION_FIELDS = ["recommended", "requires", "conflicts"] as const;

export interface RegistryCheck {
  ok: boolean;
  errors: string[];
  warnings: string[];
  summary: string[];
  skillCount: number;
}

export interface RegistryBuild {
  errors: string[];
  warnings: string[];
  skills: string[];
  // Generated routing/registry.json content; null when the manifests have errors.
  text: string | null;
}

// GitHub-style heading anchor: lowercase, punctuation dropped (hyphens and underscores kept), spaces become hyphens.
export function githubSlug(heading: string): string {
  return heading.trim().toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, "").replace(/ /g, "-");
}

// Lines outside fenced code blocks, so a "## " inside a code sample is not a heading.
function proseLines(markdown: string): string[] {
  const out: string[] = [];
  let fence: string | null = null;
  for (const line of markdown.split(/\r?\n/)) {
    const marker = line.match(/^\s*(```|~~~)/);
    if (marker) {
      if (fence === null) fence = marker[1];
      else if (fence === marker[1]) fence = null;
      continue;
    }
    if (fence === null) out.push(line);
  }
  return out;
}

// The anchors GitHub generates for the "## " headings of a markdown file; repeats get -1, -2 suffixes.
export function level2Anchors(markdown: string): Set<string> {
  const anchors = new Set<string>();
  const seen = new Map<string, number>();
  for (const line of proseLines(markdown)) {
    const m = line.match(/^## (?!#)(.+?)\s*$/);
    if (!m) continue;
    const base = githubSlug(m[1]);
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    anchors.add(n === 0 ? base : `${base}-${n}`);
  }
  return anchors;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function readJson(filePath: string): { value?: unknown; error?: string } {
  try {
    return { value: JSON.parse(fs.readFileSync(filePath, "utf-8")) };
  } catch (err) {
    return { error: (err as Error).message };
  }
}

function loadCheckIds(root: string, errors: string[]): Set<string> {
  const checksPath = path.join(root, "routing", "checks.json");
  if (!fs.existsSync(checksPath)) {
    errors.push("routing/checks.json is missing");
    return new Set();
  }
  const parsed = readJson(checksPath);
  if (parsed.error !== undefined) {
    errors.push(`routing/checks.json is not valid JSON: ${parsed.error}`);
    return new Set();
  }
  const checks = (parsed.value as { checks?: Record<string, unknown> }).checks ?? {};
  return new Set(Object.keys(checks));
}

// Validates one skill.json. Returns the registry entry when valid, otherwise null with errors added.
function validateManifest(
  dirName: string,
  skillDir: string,
  raw: unknown,
  checkIds: Set<string>,
  errors: string[]
): SkillMetadata | null {
  const where = `skills/${dirName}/skill.json`;
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    errors.push(`${where}: must be a JSON object`);
    return null;
  }
  const obj = raw as Record<string, unknown>;
  const before = errors.length;

  for (const key of Object.keys(obj)) {
    if (!MANIFEST_FIELDS.includes(key)) errors.push(`${where}: unknown field '${key}' (routing data must match the schema)`);
  }
  for (const field of MANIFEST_FIELDS) {
    if (!(field in obj)) errors.push(`${where}: missing required field '${field}'`);
  }

  if (obj.name !== dirName) {
    errors.push(`${where}: name must equal the directory name '${dirName}'`);
  }
  if (typeof obj.layer !== "string" || !VALID_LAYERS.includes(obj.layer as SkillLayer)) {
    errors.push(`${where}: invalid layer '${String(obj.layer)}' (expected one of ${VALID_LAYERS.join(", ")})`);
  }
  for (const field of LIST_FIELDS) {
    if (field in obj && !isStringArray(obj[field])) errors.push(`${where}: '${field}' must be an array of strings`);
  }
  if (typeof obj.explanation !== "string" || obj.explanation.trim() === "") {
    errors.push(`${where}: 'explanation' must be a non-empty string`);
  }

  const sections: SkillSection[] = [];
  if (!Array.isArray(obj.sections)) {
    errors.push(`${where}: 'sections' must be an array`);
  } else {
    const skillMdPath = path.join(skillDir, "SKILL.md");
    const anchors = fs.existsSync(skillMdPath) ? level2Anchors(fs.readFileSync(skillMdPath, "utf-8")) : null;
    if (anchors === null) errors.push(`skills/${dirName}/SKILL.md is missing`);
    const ids = new Set<string>();
    for (const section of obj.sections as unknown[]) {
      const s = (typeof section === "object" && section !== null ? section : {}) as Record<string, unknown>;
      const { id, title, source } = s;
      if (typeof id !== "string" || typeof title !== "string" || typeof source !== "string" || !id || !title || !source) {
        errors.push(`${where}: each section needs non-empty string 'id', 'title', and 'source'`);
        continue;
      }
      if (ids.has(id)) errors.push(`${where}: duplicate section id '${id}'`);
      ids.add(id);

      if (source.startsWith("SKILL.md#")) {
        const anchor = source.slice("SKILL.md#".length);
        if (anchor !== id) errors.push(`${where}: section '${id}' must use its SKILL.md anchor as id (got '${anchor}')`);
        if (anchors !== null && !anchors.has(anchor)) {
          errors.push(`${where}: section '${id}' points to '${source}', but SKILL.md has no '## ' heading with that anchor`);
        }
      } else if (source.startsWith("references/") && source.endsWith(".md")) {
        const stem = path.basename(source, ".md");
        // A reference uses its file stem as id; if a SKILL.md heading already uses that id, "-reference" is appended.
        const collides = anchors !== null && anchors.has(stem);
        const expected = collides ? `${stem}-reference` : stem;
        if (id !== expected) {
          errors.push(`${where}: section '${id}' must use id '${expected}' (file stem '${stem}'${collides ? ", suffixed because a SKILL.md heading has that id" : ""})`);
        }
        const target = path.resolve(skillDir, source);
        if (!target.startsWith(path.resolve(skillDir) + path.sep)) {
          errors.push(`${where}: section source '${source}' escapes the skill directory`);
        } else if (!fs.existsSync(target)) {
          errors.push(`${where}: section source '${source}' does not exist on disk`);
        }
      } else {
        errors.push(`${where}: section '${id}' source must be 'SKILL.md#<anchor>' or 'references/<file>.md'`);
      }
      sections.push({ id, title, source });
    }
  }

  if (isStringArray(obj.checks)) {
    for (const check of obj.checks) {
      if (!checkIds.has(check)) errors.push(`${where}: unknown check id '${check}' (not in routing/checks.json)`);
    }
  }

  if (errors.length > before) return null;
  const list = (field: string) => obj[field] as string[];
  return {
    name: dirName,
    path: `skills/${dirName}`,
    layer: obj.layer as SkillLayer,
    domains: list("domains"),
    capabilities: list("capabilities"),
    triggers: list("triggers"),
    recommended: list("recommended"),
    requires: list("requires"),
    conflicts: list("conflicts"),
    explanation: obj.explanation as string,
    sections,
    checks: list("checks")
  };
}

// Builds the registry from skills/*/skill.json. Does not write anything.
export function buildRegistry(root = defaultRoot): RegistryBuild {
  const errors: string[] = [];
  const warnings: string[] = [];
  const skillsDir = path.join(root, "skills");
  const registryPath = path.join(root, "routing", "registry.json");

  const checkIds = loadCheckIds(root, errors);

  let schema = "./registry.schema.json";
  let version = "1.0.0";
  if (fs.existsSync(registryPath)) {
    const current = readJson(registryPath);
    if (current.error !== undefined) {
      errors.push(`routing/registry.json is not valid JSON: ${current.error}`);
    } else {
      const header = current.value as { $schema?: unknown; version?: unknown };
      if (typeof header.$schema === "string") schema = header.$schema;
      if (typeof header.version === "string") version = header.version;
    }
  }

  if (!fs.existsSync(skillsDir)) {
    errors.push("skills/ directory is missing");
    return { errors, warnings, skills: [], text: null };
  }

  const dirs = fs
    .readdirSync(skillsDir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort();

  const manifests = new Map<string, SkillMetadata>();
  const declared = new Set<string>();
  const relations: Array<{ from: string; field: string; target: string }> = [];
  for (const dirName of dirs) {
    const skillDir = path.join(skillsDir, dirName);
    const manifestPath = path.join(skillDir, "skill.json");
    if (!fs.existsSync(manifestPath)) {
      warnings.push(`skills/${dirName} has no skill.json; it is skipped and not routed.`);
      continue;
    }
    declared.add(dirName);
    const parsed = readJson(manifestPath);
    if (parsed.error !== undefined) {
      errors.push(`skills/${dirName}/skill.json is not valid JSON: ${parsed.error}`);
      continue;
    }
    const entry = validateManifest(dirName, skillDir, parsed.value, checkIds, errors);
    if (entry) manifests.set(dirName, entry);
    // Relations are checked against every declared skill, so one invalid manifest does not hide the others.
    const obj = (typeof parsed.value === "object" && parsed.value !== null ? parsed.value : {}) as Record<string, unknown>;
    for (const field of RELATION_FIELDS) {
      if (isStringArray(obj[field])) {
        for (const target of obj[field] as string[]) relations.push({ from: dirName, field, target });
      }
    }
  }
  for (const rel of relations) {
    if (!declared.has(rel.target)) {
      errors.push(`skills/${rel.from}/skill.json: ${rel.field} references unknown skill '${rel.target}'`);
    }
  }

  if (errors.length > 0) return { errors, warnings, skills: [], text: null };

  const skills: Record<string, SkillMetadata> = {};
  for (const name of [...manifests.keys()].sort()) {
    skills[name] = manifests.get(name)!;
  }
  const registry = { $schema: schema, version, skills };
  return {
    errors,
    warnings,
    skills: Object.keys(skills),
    text: JSON.stringify(registry, null, 2) + "\n"
  };
}

// Describes how the committed registry differs from the generated one, one line per difference.
function describeDrift(currentText: string | null, expectedText: string): string[] {
  if (currentText === null) return ["routing/registry.json does not exist"];
  let current: { $schema?: unknown; version?: unknown; skills?: Record<string, Record<string, unknown>> };
  try {
    current = JSON.parse(currentText);
  } catch (err) {
    return [`routing/registry.json is not valid JSON: ${(err as Error).message}`];
  }
  const expected = JSON.parse(expectedText) as typeof current;
  const lines: string[] = [];

  for (const key of ["$schema", "version"] as const) {
    if (JSON.stringify(current[key]) !== JSON.stringify(expected[key])) {
      lines.push(`${key}: ${JSON.stringify(current[key])} -> ${JSON.stringify(expected[key])}`);
    }
  }

  const currentSkills = current.skills ?? {};
  const expectedSkills = expected.skills ?? {};
  for (const name of Object.keys(expectedSkills)) {
    if (!Object.hasOwn(currentSkills, name)) lines.push(`+ skill added: ${name}`);
  }
  for (const name of Object.keys(currentSkills)) {
    if (!Object.hasOwn(expectedSkills, name)) lines.push(`- skill removed: ${name}`);
  }
  for (const name of Object.keys(expectedSkills)) {
    if (!Object.hasOwn(currentSkills, name)) continue;
    const want = expectedSkills[name];
    const have = currentSkills[name];
    const changed = Object.keys({ ...want, ...have }).filter(
      (field) => JSON.stringify(have[field]) !== JSON.stringify(want[field])
    );
    if (changed.length > 0) lines.push(`~ ${name}: ${changed.join(", ")}`);
  }

  if (lines.length === 0) {
    lines.push("skill order or JSON formatting differs");
  }
  return lines;
}

// Verifies that routing/registry.json matches what the manifests generate.
export function checkRegistry(root = defaultRoot): RegistryCheck {
  const build = buildRegistry(root);
  if (build.text === null) {
    return { ok: false, errors: build.errors, warnings: build.warnings, summary: [], skillCount: 0 };
  }
  const registryPath = path.join(root, "routing", "registry.json");
  // Line endings are normalized so a CRLF working copy (core.autocrlf) compares equal to the LF output.
  const currentText = fs.existsSync(registryPath)
    ? fs.readFileSync(registryPath, "utf-8").replace(/\r\n/g, "\n")
    : null;
  if (currentText === build.text) {
    return { ok: true, errors: [], warnings: build.warnings, summary: [], skillCount: build.skills.length };
  }
  return {
    ok: false,
    errors: [],
    warnings: build.warnings,
    summary: describeDrift(currentText, build.text),
    skillCount: build.skills.length
  };
}

function runCli(args: string[]): number {
  const unknown = args.filter((arg) => arg !== "--check");
  if (unknown.length > 0) {
    console.error(`Unknown argument(s): ${unknown.join(" ")}. Usage: node router/build-registry.ts [--check]`);
    return 1;
  }

  if (args.includes("--check")) {
    const report = checkRegistry();
    for (const w of report.warnings) console.warn(`⚠ ${w}`);
    if (report.errors.length > 0) {
      console.error(`✗ Skill manifests are invalid (${report.errors.length} error(s)):`);
      for (const e of report.errors) console.error(`  - ${e}`);
      return 1;
    }
    if (!report.ok) {
      console.error(`✗ routing/registry.json is out of date:`);
      for (const line of report.summary) console.error(`  ${line}`);
      console.error(`  Run "npm run registry:build" and commit the result.`);
      return 1;
    }
    console.log(`✓ routing/registry.json is up to date (${report.skillCount} skills).`);
    return 0;
  }

  const build = buildRegistry();
  for (const w of build.warnings) console.warn(`⚠ ${w}`);
  if (build.text === null) {
    console.error(`✗ Skill manifests are invalid (${build.errors.length} error(s)); registry not written:`);
    for (const e of build.errors) console.error(`  - ${e}`);
    return 1;
  }
  fs.writeFileSync(path.join(defaultRoot, "routing", "registry.json"), build.text, "utf-8");
  console.log(`✓ Wrote routing/registry.json (${build.skills.length} skills).`);
  return 0;
}

// CLI auto-run when invoked directly
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(__filename)) {
  process.exitCode = runCli(process.argv.slice(2));
}