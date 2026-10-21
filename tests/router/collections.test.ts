import { route } from "../../router/index.ts";

export function testCollections(): { passed: boolean; message: string } {
  // Test 1: GIS collection
  const res1 = route("My GIS project", { collection: "gis" });
  const names1 = res1.skills.map((s) => s.name);
  const expectedGis = ["geomaster", "geopandas", "gdal", "geospatial-data-discovery", "verification"];
  for (const exp of expectedGis) {
    if (!names1.includes(exp)) {
      return { passed: false, message: `Collection 'gis' missing expected base skill: ${exp}` };
    }
  }

  // Test 2: Data-analysis collection
  const res2 = route("My data analysis project", { collection: "data-analysis" });
  const names2 = res2.skills.map((s) => s.name);
  const expectedData = ["statistical-analysis", "scientific-visualization", "verification"];
  for (const exp of expectedData) {
    if (!names2.includes(exp)) {
      return { passed: false, message: `Collection 'data-analysis' missing expected base skill: ${exp}` };
    }
  }

  // Test 3: Production collection
  const res3 = route("My production project", { collection: "production" });
  const names3 = res3.skills.map((s) => s.name);
  const expectedProd = ["brainstorming", "writing-plans", "systematic-debugging", "verification"];
  for (const exp of expectedProd) {
    if (!names3.includes(exp)) {
      return { passed: false, message: `Collection 'production' missing expected base skill: ${exp}` };
    }
  }

  // Test 4: Remote-sensing collection
  const res4 = route("My remote sensing project", { collection: "remote-sensing" });
  const names4 = res4.skills.map((s) => s.name);
  const expectedRs = ["geospatial-data-discovery", "satellite-preprocessing", "spectral-indices", "raster-processing", "verification"];
  for (const exp of expectedRs) {
    if (!names4.includes(exp)) {
      return { passed: false, message: `Collection 'remote-sensing' missing expected base skill: ${exp}` };
    }
  }

  return { passed: true, message: "Collections tests passed (4/4 collections verified)" };
}
