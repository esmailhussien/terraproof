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

  switch (skill.name) {
    case "brainstorming":
      return "Explores intent, requirements, and design choices before initiating construction.";
    case "writing-plans":
      return "Decomposes the task into an executable, task-by-task engineering plan.";
    case "systematic-debugging":
      return "Applies structured 4-phase root cause investigation for the reported bug/error.";
    case "geospatial-frontend":
      return "Configures MapLibre GL, interactive layers, and map dashboard interfaces.";
    case "design-postgis-tables":
      return "Architects PostGIS spatial tables, geometry/geography types, and spatial indexes.";
    case "gdal":
      return "Executes GDAL/OGR CLI operations for raster reprojection, clipping, and COG conversion.";
    case "geopandas":
      return "Processes vector spatial data, spatial joins, overlays, and coordinate transforms.";
    case "geomaster":
      return "Provides Earth observation, satellite imagery, remote sensing, and spatial ML guidance.";
    case "geoparquet-validation":
      return "Validates GeoParquet metadata and cloud-native vector distribution formatting.";
    case "geozarr":
      return "Handles multidimensional geospatial raster arrays and GeoZarr conventions.";
    case "geospatial-data-discovery":
      return "Sources open geospatial data (STAC, OSM, Sentinel, Landsat, DEMs).";
    case "statistical-analysis":
      return "Conducts hypothesis testing, ANOVA, regressions, and effect size calculations.";
    case "scientific-visualization":
      return "Generates publication-ready scientific figures with colorblind-safe palettes.";
    case "networkx":
      return "Executes graph analysis, centrality metrics, and community detection algorithms.";
    case "verification":
      return "Validates completion and truthfulness before marking the task complete.";
    default:
      return reasons.length > 0 ? reasons.join("; ") : "Selected based on domain matching.";
  }
}
