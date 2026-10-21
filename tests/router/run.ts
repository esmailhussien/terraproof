import { validateRegistry } from "../../router/validate.ts";
import { testClassification } from "./classification.test.ts";
import { testConflictsAndOverrides } from "./conflicts.test.ts";
import { testCollections } from "./collections.test.ts";
import { testCliArgs } from "./cli.test.ts";
import { testApplyAndBundle } from "./apply.test.ts";
import { runScenarioTests } from "./resolution.test.ts";
import * as path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..", "..");

console.log("\n================================================================================");
console.log("                   Terraproof Smart Router Test Suite");
console.log("================================================================================\n");

let allPassed = true;

// 1. Registry Validation
console.log("[1/8] Validating Registry & Skill Paths...");
const regReport = validateRegistry(workspaceRoot);
if (regReport.valid) {
  console.log(`  ✓ Registry valid (${regReport.skillsCount} skills, ${regReport.collectionsCount} collections)`);
  if (regReport.warnings.length > 0) {
    for (const w of regReport.warnings) {
      console.log(`    ⚠ ${w}`);
    }
  }
} else {
  console.error(`  ✗ Registry validation failed:`, regReport.errors);
  allPassed = false;
}

// 2. Classification Tests
console.log("\n[2/8] Running Task Classification Tests...");
const classRes = testClassification();
if (classRes.passed) {
  console.log(`  ✓ ${classRes.message}`);
} else {
  console.error(`  ✗ ${classRes.message}`);
  allPassed = false;
}

// 3. Conflicts & Overrides Tests
console.log("\n[3/8] Running Conflicts & Overrides Tests...");
const confRes = testConflictsAndOverrides();
if (confRes.passed) {
  console.log(`  ✓ ${confRes.message}`);
} else {
  console.error(`  ✗ ${confRes.message}`);
  allPassed = false;
}

// 4. Collections Tests
console.log("\n[4/8] Running Preset Collections Tests...");
const collRes = testCollections();
if (collRes.passed) {
  console.log(`  ✓ ${collRes.message}`);
} else {
  console.error(`  ✗ ${collRes.message}`);
  allPassed = false;
}

// 5. CLI Argument Validation Tests
console.log("\n[5/8] Running CLI Argument Validation Tests...");
const cliRes = testCliArgs();
if (cliRes.passed) {
  console.log(`  ✓ ${cliRes.message}`);
} else {
  console.error(`  ✗ ${cliRes.message}`);
  allPassed = false;
}

// 6. Apply & Bundle Integration Tests
console.log("\n[6/8] Running Apply & Bundle Integration Tests...");
const applyRes = testApplyAndBundle();
if (applyRes.passed) {
  console.log(`  ✓ ${applyRes.message}`);
} else {
  console.error(`  ✗ ${applyRes.message}`);
  allPassed = false;
}

// 7. Core Scenario Suite
console.log("\n[7/8] Running Core Scenario Suite (14 Scenarios)...");
const coreReport = runScenarioTests(path.join(__dirname, "scenarios.json"));

for (const sc of coreReport.results) {
  if (sc.passed) {
    console.log(`  ✓ [${sc.id}] "${sc.prompt.slice(0, 48)}..." -> [${sc.selectedSkills.join(", ")}]`);
  } else {
    console.error(`  ✗ [${sc.id}] "${sc.prompt}"`);
    if (sc.missingExpected.length > 0) {
      console.error(`      Missing expected: ${sc.missingExpected.join(", ")}`);
    }
    if (sc.unexpectedIncluded.length > 0) {
      console.error(`      Unexpected included (over-selected): ${sc.unexpectedIncluded.join(", ")}`);
    }
    if (sc.maxExceeded) {
      console.error(`      Max skills exceeded`);
    }
    console.error(`      Actual selected: ${sc.selectedSkills.join(", ")}`);
    allPassed = false;
  }
}

// 8. Real-World Scenario Suite
console.log("\n[8/8] Running Real-World Benchmark Suite (14 Scenarios)...");
const rwReport = runScenarioTests(path.join(__dirname, "real-world-scenarios.json"));

for (const sc of rwReport.results) {
  if (sc.passed) {
    console.log(`  ✓ [${sc.id}] "${sc.prompt.slice(0, 48)}..." -> [${sc.selectedSkills.join(", ")}]`);
  } else {
    console.error(`  ✗ [${sc.id}] "${sc.prompt}"`);
    if (sc.missingExpected.length > 0) {
      console.error(`      Missing expected: ${sc.missingExpected.join(", ")}`);
    }
    if (sc.unexpectedIncluded.length > 0) {
      console.error(`      Unexpected included (over-selected): ${sc.unexpectedIncluded.join(", ")}`);
    }
    if (sc.maxExceeded) {
      console.error(`      Max skills exceeded`);
    }
    console.error(`      Actual selected: ${sc.selectedSkills.join(", ")}`);
    allPassed = false;
  }
}

const totalScenarios = coreReport.total + rwReport.total;
const totalPassed = coreReport.passed + rwReport.passed;
const totalFailed = coreReport.failed + rwReport.failed;
const combinedAvg = Number(((coreReport.averageSkillCount * coreReport.total + rwReport.averageSkillCount * rwReport.total) / totalScenarios).toFixed(1));

console.log("\n--------------------------------------------------------------------------------");
console.log("                           Router Quality Metrics");
console.log("--------------------------------------------------------------------------------");
console.log(`Total Scenarios Tested : ${totalScenarios}`);
console.log(`Scenarios Passed       : ${totalPassed} (${((totalPassed / totalScenarios) * 100).toFixed(1)}%)`);
console.log(`Scenarios Failed       : ${totalFailed}`);
console.log(`Core Suite Pass Rate   : ${((coreReport.passed / coreReport.total) * 100).toFixed(1)}% (${coreReport.passed}/${coreReport.total})`);
console.log(`Real-World Pass Rate   : ${((rwReport.passed / rwReport.total) * 100).toFixed(1)}% (${rwReport.passed}/${rwReport.total})`);
console.log(`Average Skill Count    : ${combinedAvg} skills/task (Core: ${coreReport.averageSkillCount}, RW: ${rwReport.averageSkillCount})`);
console.log(`Median Skill Count     : ${rwReport.medianSkillCount}`);
console.log(`95th Percentile Count  : ${rwReport.p95SkillCount}`);
console.log(`Deterministic (2x run) : ${coreReport.determinismPassed && rwReport.determinismPassed ? "PASSED (100% Deterministic)" : "FAILED"}`);
console.log(`Over-Selection Warns   : ${coreReport.overSelectionWarnings + rwReport.overSelectionWarnings}`);
console.log("================================================================================\n");

if (!allPassed) {
  process.exit(1);
} else {
  process.exit(0);
}
