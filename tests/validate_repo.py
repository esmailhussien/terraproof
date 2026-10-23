#!/usr/bin/env python3
"""
Terraproof Repository Integrity & Frontmatter Validator.
Zero-dependency validator designed for local testing and CI workflows.
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple

# Base repository root directory
REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories whose markdown is not repository content (VCS data, virtualenvs, dependencies, build output).
SKIPPED_DIR_NAMES = frozenset({".git", ".venv", "venv", "node_modules", "dist", "build", ".pytest_cache", ".terracache"})


def extract_frontmatter(content: str) -> Tuple[dict, str]:
    """Extract YAML frontmatter between --- markers at start of file."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    fm_text = parts[1]
    body = parts[2]

    fm = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip().strip("'\"")
    return fm, body


def strip_code_blocks(markdown_text: str) -> str:
    """Remove fenced code blocks (```...```) to avoid false link matches in code."""
    return re.sub(r'```[\s\S]*?```', '', markdown_text)


def validate_skills(errors: List[str], warnings: List[str]):
    """Validate all skills in skills/ directory."""
    skills_dir = REPO_ROOT / "skills"
    if not skills_dir.exists():
        errors.append("skills/ directory not found.")
        return

    skill_folders = [d for d in skills_dir.iterdir() if d.is_dir()]
    if not skill_folders:
        errors.append("No skills found in skills/ directory.")
        return

    for skill_path in sorted(skill_folders):
        skill_name = skill_path.name
        skill_md = skill_path / "SKILL.md"
        upstream_md = skill_path / "UPSTREAM.md"

        if not skill_md.exists():
            errors.append(f"Skill '{skill_name}' is missing SKILL.md")
            continue

        content = skill_md.read_text(encoding="utf-8")
        fm, body = extract_frontmatter(content)

        if not fm:
            errors.append(f"Skill '{skill_name}': SKILL.md missing valid YAML frontmatter (--- delimiters)")
        else:
            if "name" not in fm or not fm["name"]:
                errors.append(f"Skill '{skill_name}': Frontmatter missing required 'name' property")
            if "description" not in fm or not fm["description"]:
                errors.append(f"Skill '{skill_name}': Frontmatter missing required 'description' property")

        # Check for placeholder skills
        if "TODO" in content and "Goal\nTODO" in content:
            warnings.append(f"Skill '{skill_name}' appears to be an unpopulated placeholder with TODO sections.")

        if not upstream_md.exists():
            warnings.append(f"Skill '{skill_name}' does not have an UPSTREAM.md provenance record.")


def validate_markdown_links(errors: List[str], warnings: List[str]):
    """Validate relative markdown links across all .md files in the repository."""
    md_files = [
        f for f in REPO_ROOT.rglob("*.md")
        if not SKIPPED_DIR_NAMES.intersection(f.relative_to(REPO_ROOT).parts[:-1])
    ]

    # Regex matching markdown links [text](target)
    link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')

    for md_file in md_files:
        rel_file = md_file.relative_to(REPO_ROOT)
        content = md_file.read_text(encoding="utf-8", errors="replace")

        # Check for hardcoded local absolute file:/// or C: / D: paths
        if re.search(r'file:///[a-zA-Z]:/', content):
            errors.append(f"File '{rel_file}' contains machine-specific 'file:///' link.")
        if re.search(r'\[.*?\]\([a-zA-Z]:[/\\]', content):
            errors.append(f"File '{rel_file}' contains absolute local drive link.")

        # Strip fenced code blocks before checking standard markdown links
        text_without_code = strip_code_blocks(content)

        for match in link_pattern.finditer(text_without_code):
            label = match.group(1)
            target = match.group(2).strip()

            # Ignore external URLs, emails, anchor-only links
            if target.startswith(("http://", "https://", "mailto:", "#", "ftp://")):
                continue

            # Strip anchor query/fragment if present
            target_path_str = target.split("#")[0].split("?")[0].strip()
            if not target_path_str:
                continue  # Target was just an anchor like `#section`

            # Resolve target relative to the markdown file's directory
            target_resolved = (md_file.parent / target_path_str).resolve()

            if not target_resolved.exists():
                errors.append(
                    f"Broken link in '{rel_file}': target '{target}' does not exist on disk."
                )


def validate_domain_routing(errors: List[str], warnings: List[str]):
    """Validate cross-references inside routing/DOMAIN_ROUTING.md."""
    routing_file = REPO_ROOT / "routing" / "DOMAIN_ROUTING.md"
    if not routing_file.exists():
        warnings.append("routing/DOMAIN_ROUTING.md not found.")
        return

    content = routing_file.read_text(encoding="utf-8")

    # Check referenced instructions (e.g. instructions/engineering.md)
    instruction_refs = re.findall(r'instructions/[\w-]+\.md', content)
    for ref in set(instruction_refs):
        inst_path = REPO_ROOT / ref
        if not inst_path.exists():
            errors.append(f"DOMAIN_ROUTING.md references missing instruction: '{ref}'")

    # Check referenced skills (e.g. skills/gdal)
    skill_refs = re.findall(r'skills/([\w-]+)', content)
    for skill in set(skill_refs):
        skill_dir = REPO_ROOT / "skills" / skill
        if not skill_dir.exists():
            errors.append(f"DOMAIN_ROUTING.md references missing skill: 'skills/{skill}'")


def main():
    print("=" * 60)
    print("Terraproof Repository Integrity & Verification Suite")
    print(f"Repository Root: {REPO_ROOT}")
    print("=" * 60)

    errors: List[str] = []
    warnings: List[str] = []

    print("[1/3] Validating skills and frontmatter...")
    validate_skills(errors, warnings)

    print("[2/3] Validating markdown links and references...")
    validate_markdown_links(errors, warnings)

    print("[3/3] Validating domain routing references...")
    validate_domain_routing(errors, warnings)

    print("-" * 60)
    if warnings:
        print(f"⚠️  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")
        print("-" * 60)

    if errors:
        print(f"❌ FAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        print("=" * 60)
        sys.exit(1)
    else:
        print("✅ SUCCESS: All skills, frontmatter, and link references passed validation!")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    main()
