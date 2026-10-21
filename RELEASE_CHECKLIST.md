# Terraproof v0.2.0 Release Checklist

This checklist defines the mandatory verification and release steps for publishing Terraproof v0.2.0 to npm and GitHub.

---

## 1. Pre-Release Verification

- [x] **Skill Inventory Integrity**:
  - All 15 registered skills validated against disk paths in `routing/registry.json`.
  - Zero broken references in `routing/collections.json` (3 preset collections).
  - Validated via `python tests/validate_repo.py` and `node bin/terraproof.js validate`.
- [x] **Smart Router Test Suite**:
  - Core Scenario Suite (41 scenarios in `tests/router/scenarios.json`): 100% pass rate.
  - Real-World Benchmark Suite (14 scenarios in `tests/router/real-world-scenarios.json`): 100% pass rate.
  - Determinism check: 100% identical composition and scores across consecutive runs.
  - CLI argument validation tests (`tests/router/cli.test.ts`).
  - Overall accuracy: 55/55 scenarios (100.0%; 41 core, 14 real-world).
- [x] **License & Provenance Compliance**:
  - Every vendored skill includes `UPSTREAM.md` with source repository, commit SHA, and license terms.
  - Third-party licenses and notices maintained in `third_party/`.
  - Upstream source map and licensing catalog maintained in `sources/SOURCES.md`.
- [ ] **GitHub Actions CI**:
  - `.github/workflows/ci.yml` runs repository validation and the router suite (Node 24), and the `package-smoke` matrix (Ubuntu, Windows, macOS × Node 20, 22, 24). Confirm a green run on the release commit.

---

## 2. Packaging & Tarball Verification

- [x] **`package.json` Package Shape**:
  - `name`: `terraproof`
  - `version`: `0.2.0`
  - `bin`: `{"terraproof": "./bin/terraproof.js"}`
  - `main` and `exports`: `./dist/router/index.js` (compiled router)
  - `engines.node`: `>=20`
  - `files`: explicitly restricted to `bin/`, `dist/`, `routing/`, `skills/`, `instructions/`, `third_party/`, `sources/`, `README.md`, `LICENSE`.
- [x] **Build**:
  - `npm run build` compiles `router/` to `dist/router/` (`tsconfig.build.json`). `prepack` runs the build before `npm pack` and `npm publish`.
- [x] **Installed Package Smoke Test**:
  - `npm run test:package` packs the repository, installs the tarball into a fresh project, and runs `--version`, `route --format json`, `validate`, and unknown-collection rejection.
- [ ] **Tarball Size**:
  - Re-measure with `npm pack` before release (v0.1.0 was about 560 kB across 330 files). Confirm no test files, temporary files, or OS artifacts are packaged.

---

## 3. Package Name & Registry Strategy

> [!IMPORTANT]
> The unscoped npm package name `terraproof` has not been checked or claimed from this repository yet.
>
> **Before publishing:**
> - Check availability with `npm view terraproof` (a 404 means the name is free).
> - If it is taken, publish a scoped package instead: `@<owner>/terraproof`.
>   1. Set `"name": "@<owner>/terraproof"` in `package.json`.
>   2. Run `npm publish --access public`.

---

## 4. Release Procedure

1. **Tag the Release**:
   ```bash
   git tag -a v0.2.0 -m "Terraproof v0.2.0 — evidence-graded skills, tools, and checks for mapping and remote-sensing AI agents"
   git push origin v0.2.0
   ```
2. **Publish to NPM**:
   ```bash
   npm publish --access public
   ```
3. **Create GitHub Release**:
   - Title: `Terraproof v0.2.0`
   - Attach tarball `terraproof-0.2.0.tgz` generated via `npm pack`.
   - Include release notes highlighting the rename, the compiled package fix, strict CLI validation, and the CI package smoke test.

---

## 5. Post-Release Smoke Testing

- [ ] Run `npx terraproof --version` in a blank directory (or `npx @<owner>/terraproof --version` if scoped).
- [ ] Run `npx terraproof route "Reproject a GeoTIFF to EPSG:3857 and build a COG with GDAL"` to verify global routing.
