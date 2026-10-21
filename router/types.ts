export type SkillLayer = "process" | "domain" | "implementation" | "risk" | "verification";

export interface SkillMetadata {
  name: string;
  path: string;
  layer: SkillLayer;
  domains: string[];
  capabilities: string[];
  triggers: string[];
  recommended: string[];
  requires: string[];
  conflicts: string[];
  explanation?: string;
  sections?: SkillSection[];
  checks?: string[];
}

export interface SkillSection {
  id: string;
  title: string;
  source: string;
}

export interface CheckMetadata {
  family: string;
  description: string;
}

export interface ChecksData {
  version: string;
  checks: Record<string, CheckMetadata>;
}

export interface RegistryData {
  version: string;
  skills: Record<string, SkillMetadata>;
}

export interface CollectionMetadata {
  name: string;
  description: string;
  base: string[];
}

export interface CollectionsData {
  version: string;
  collections: Record<string, CollectionMetadata>;
}

export interface RoutingRules {
  version: string;
  weights: {
    technologyExactMatch: number;
    capabilityMatch: number;
    domainMatch: number;
    strongTriggerMatch: number;
    weakTriggerMatch: number;
    recommendedBonus: number;
    requiredDependency: number;
    explicitInclusion: number;
    explicitExclusion: number;
    conflictPenalty: number;
  };
  layerOrder: SkillLayer[];
  thresholds: {
    selectionMinimumScore: number;
    highConfidenceThreshold: number;
  };
  intentRules: Record<string, { triggers: string[]; injectProcess?: string[]; injectSkills?: string[]; suppressProcess?: string[]; suppressRisk?: string[] }>;
  riskBoundaries: Record<string, { triggers: string[]; injectRisk?: string[] }>;
  verificationRules: Record<string, { triggers?: string[]; injectVerification: string[] }>;
}

export interface TaskClassification {
  rawPrompt: string;
  intents: string[];
  domains: string[];
  technologies: string[];
  capabilities: string[];
  isTrivial: boolean;
  hasRiskBoundary: boolean;
  needsBrowserTesting: boolean;
  needsIntegrationTesting: boolean;
  needsUnitTesting: boolean;
}

export interface ScoredSkill {
  name: string;
  layer: SkillLayer;
  score: number;
  reasons: string[];
}

export interface SelectedSkill {
  name: string;
  layer: SkillLayer;
  score: number;
  reason: string;
  path: string;
}

export interface RouteOptions {
  include?: string[];
  exclude?: string[];
  collection?: string;
  dryRun?: boolean;
  minScore?: number;
}

export interface DroppedSkill {
  skill: string;
  reason: string;
}

export interface RouteResult {
  prompt: string;
  classification: TaskClassification;
  skills: SelectedSkill[];
  skillsByLayer: Record<SkillLayer, SelectedSkill[]>;
  dropped: DroppedSkill[];
  confidence: number;
  dryRun: boolean;
  warning?: string;
  summary: string;
}
