import { loadRoutingData, parseCliArgs } from "../../router/index.ts";

export function testCliArgs(): { passed: boolean; message: string } {
  const { registry, collections } = loadRoutingData();

  // Each case must be rejected, and the error must mention the given fragment.
  const invalidCases: Array<[string[], string]> = [
    [["route", "x", "--bogus"], "--bogus"],
    [["route", "x", "--yes"], "--yes"],
    [["route", "x", "-y"], "-y"],
    [["route", "x", "--target"], "--target"],
    [["route", "x", "--out"], "--out"],
    [["route", "x", "--include"], "--include"],
    [["route", "x", "--exclude"], "--exclude"],
    [["route", "x", "--collection"], "--collection"],
    [["route", "x", "--format"], "--format"],
    [["route", "x", "--out", "--format", "json"], "--out"],
    [["route", "x", "--format", "xml"], "xml"],
    [["route", "x", "--collection", "doesnotexist"], "doesnotexist"],
    [["route", "x", "--collection", "doesnotexist"], "gis, data-analysis, production"],
    [["route", "x", "--include", "nonexistent-skill-xyz"], "nonexistent-skill-xyz"],
    [["route", "x", "--exclude", "nonexistent-skill-xyz"], "nonexistent-skill-xyz"],
    [["route"], "task description"],
    [["bogus", "x"], "bogus"]
  ];

  for (const [args, fragment] of invalidCases) {
    const res = parseCliArgs(args, registry, collections);
    if (!("error" in res)) {
      return { passed: false, message: `CLI accepted invalid arguments: ${args.join(" ")}` };
    }
    if (!res.error.includes(fragment)) {
      return { passed: false, message: `CLI error for '${args.join(" ")}' does not mention '${fragment}': ${res.error}` };
    }
  }

  // One valid parse: flags, values, and overrides are read as before
  const valid = parseCliArgs(
    [
      "route",
      "Reproject a GeoTIFF to EPSG:3857 and build a COG with GDAL",
      "--include", "gdal",
      "--exclude", "geomaster",
      "--collection", "gis",
      "--format", "json",
      "--dry-run"
    ],
    registry,
    collections
  );
  if ("error" in valid) {
    return { passed: false, message: `Valid CLI arguments were rejected: ${valid.error}` };
  }
  const expectedInclude = JSON.stringify(["gdal"]);
  const expectedExclude = JSON.stringify(["geomaster"]);
  if (
    valid.command !== "route" ||
    valid.format !== "json" ||
    valid.options.dryRun !== true ||
    valid.options.collection !== "gis" ||
    JSON.stringify(valid.options.include) !== expectedInclude ||
    JSON.stringify(valid.options.exclude) !== expectedExclude
  ) {
    return { passed: false, message: "Valid CLI arguments parsed to unexpected options" };
  }

  const total = invalidCases.length + 1;
  return { passed: true, message: `CLI argument validation tests passed (${total}/${total})` };
}
