import * as fs from "fs";
import * as path from "path";
import type { RegistryData, CollectionsData, SkillLayer } from "./types.ts";

const VALID_LAYERS: SkillLayer[] = ["process", "domain", "implementation", "risk", "verification"];

export interface ValidationReport {
  valid: boolean;
  errors: string[];
  warnings: string[];
  skillsCount: number;
  collectionsCount: number;
}

export function validateRegistry(workspaceRoot: string): ValidationReport {
  const errors: string[] = [];
  const warnings: string[] = [];

  const registryPath = path.join(workspaceRoot, "routing", "registry.json");
  const collectionsPath = path.join(workspaceRoot, "routing", "collections.json");

  if (!fs.existsSync(registryPath)) {
    return { valid: false, errors: [`Missing registry.json at ${registryPath}`], warnings: [], skillsCount: 0, collectionsCount: 0 };
  }

  const registry: RegistryData = JSON.parse(fs.readFileSync(registryPath, "utf-8"));
  const collections: CollectionsData = fs.existsSync(collectionsPath)
    ? JSON.parse(fs.readFileSync(collectionsPath, "utf-8"))
    : { version: "1.0.0", collections: {} };

  const skillNames = Object.keys(registry.skills);

  for (const [name, skill] of Object.entries(registry.skills)) {
    // Check name consistency
    if (skill.name !== name) {
      errors.push(`Skill key '${name}' does not match skill.name '${skill.name}'`);
    }

    // Check layer
    if (!VALID_LAYERS.includes(skill.layer)) {
      errors.push(`Skill '${name}' has invalid layer '${skill.layer}'`);
    }

    // Check disk existence
    const skillDir = path.join(workspaceRoot, skill.path);
    if (!fs.existsSync(skillDir)) {
      errors.push(`Skill '${name}' specified path '${skill.path}' does not exist on disk`);
    } else {
      const skillMd = path.join(skillDir, "SKILL.md");
      if (!fs.existsSync(skillMd)) {
        errors.push(`Skill '${name}' is missing SKILL.md in '${skill.path}'`);
      }
    }

    // Ensure placeholders are not registered
    if (name === "ai-chat" || name === "ai-tools") {
      errors.push(`Placeholder '${name}' must not be registered in registry.json`);
    }

    // Every registered skill needs its own explanation; routed output reads it from the registry.
    if (!skill.explanation || skill.explanation.trim() === "") {
      errors.push(`Skill '${name}' has no explanation in routing/registry.json`);
    }

    // Warn on low trigger count
    if (skill.triggers.length < 2) {
      warnings.push(`Skill '${name}' has only ${skill.triggers.length} trigger(s); may under-match.`);
    }

    // Validate relationships
    for (const req of skill.requires || []) {
      if (!registry.skills[req]) {
        errors.push(`Skill '${name}' requires unknown skill '${req}'`);
      }
    }
    for (const rec of skill.recommended || []) {
      if (!registry.skills[rec]) {
        errors.push(`Skill '${name}' recommends unknown skill '${rec}'`);
      }
    }
    for (const conf of skill.conflicts || []) {
      if (!registry.skills[conf]) {
        errors.push(`Skill '${name}' lists unknown conflict '${conf}'`);
      }
    }
  }

  // Validate collections
  for (const [cName, coll] of Object.entries(collections.collections)) {
    for (const sName of coll.base) {
      if (!registry.skills[sName]) {
        errors.push(`Collection '${cName}' references unknown skill '${sName}'`);
      }
    }
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
    skillsCount: skillNames.length,
    collectionsCount: Object.keys(collections.collections).length
  };
}
