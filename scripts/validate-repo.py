#!/usr/bin/env python3
"""Validate SKILL.md frontmatter, JSON manifests and public-safety, with no network.

This is the logic that used to live inline in .github/workflows/skills-validate.yml.
CI and `make validate` now run the same script.
"""

import argparse
import json
from pathlib import Path
import re
import sys

SKIP_DIRS = {".git", "node_modules", "dist", "out", "vendor", "__pycache__"}
LEAK = re.compile(r"[A-Za-z]:\\Users\\|/Users/[A-Za-z]+/|/home/[a-z]+/")
MANIFESTS = (".claude-plugin/marketplace.json", ".claude-plugin/plugin.json", "skills-lock.json")


def walk(root):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not (set(path.relative_to(root).parts) & SKIP_DIRS):
            yield path


def check_skills(root):
    errors = []
    for skill in sorted(root.glob("skills/*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not match:
            errors.append(f"{skill}: missing YAML frontmatter")
            continue
        fields = dict(re.findall(r"^(\w[\w-]*):\s*(.+)$", match.group(1), re.M))
        name, desc = fields.get("name", "").strip(), fields.get("description", "").strip()
        if name != skill.parent.name:
            errors.append(f"{skill}: name '{name}' != folder '{skill.parent.name}'")
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
            errors.append(f"{skill}: name must be kebab-case, <=64 chars")
        if not desc or len(desc) > 1024:
            errors.append(f"{skill}: description missing or >1024 chars")
    return errors


def check_json(root):
    errors = []
    for path in walk(root):
        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception as error:  # noqa: BLE001 - report any parse failure
                errors.append(f"{path.relative_to(root)}: invalid JSON ({error})")
    for manifest in MANIFESTS:
        if not (root / manifest).exists():
            errors.append(f"{manifest}: missing")
    return errors


def check_public_safety(root):
    errors = []
    for path in walk(root):
        if path.suffix in {".md", ".json", ".yml", ".yaml"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number, line in enumerate(text.splitlines(), 1):
                if LEAK.search(line):
                    errors.append(f"{path.relative_to(root)}:{number}: private local path")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    errors = check_skills(root) + check_json(root) + check_public_safety(root)
    print("\n".join(errors) if errors else "OK: skills, manifests, public-safety")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
