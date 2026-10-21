# Terraproof Behavioral Tests

This directory will contain behavioral test scenarios used to evaluate whether Terraproof instructions and skills improve AI coding-agent behavior, precision, and adherence to engineering best practices.

---

## Evaluation Concept

Each scenario will compare agent responses with and without specific Terraproof skills loaded.

### Example Scenario

```text
Scenario:
A user reports an intermittent authentication failure.

Without skill:
Does the agent immediately guess and modify code?

With systematic-debugging:
Does the agent reproduce, gather evidence, identify the root cause,
apply a targeted fix, and verify it?
```

---

## Automated Repository Validation Suite

Terraproof includes automated integrity validators that check skill frontmatter, path resolution, routing references, and link validity.

### Running Locally

**Python:**
```bash
python tests/validate_repo.py
```

**PowerShell:**
```powershell
powershell -ExecutionPolicy Bypass -File tests/validate_repo.ps1
```

### What It Validates
1. **Skill Frontmatter**: Ensures every `skills/*/SKILL.md` contains valid YAML frontmatter with `name` and `description`.
2. **Link Integrity**: Scans all Markdown files to ensure relative paths resolve to real files and flags any machine-specific links (`file:///`).
3. **Domain Routing**: Confirms all instructions and skills referenced in `routing/DOMAIN_ROUTING.md` exist on disk.
4. **Placeholder Detection**: Emits warnings for unpopulated scaffold skills.

---

> **Note:** End-to-end LLM behavioral benchmark harnesses will be expanded in a future phase.
