import type { SkillMetadata, TaskClassification } from "./types.ts";

export function generateSkillExplanation(
  skill: SkillMetadata,
  classification: TaskClassification,
  reasons: string[],
  isAutoInjected = false
): string {
  if (reasons.some((r) => r.includes("Explicitly included"))) {
    return "Explicitly requested by manual --include override.";
  }

  if (skill.explanation) {
    return skill.explanation;
  }

  return reasons.length > 0 ? reasons.join("; ") : "Selected based on domain matching.";
}