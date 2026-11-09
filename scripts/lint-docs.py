#!/usr/bin/env python3
"""Explicit lint/format checks (replaces hooks): no network, no third-party packages.

  lint-docs.py           report problems (exit 1 on errors)
  lint-docs.py --fix     also rewrite the mechanical ones: trailing whitespace, final newline

Checks: Python compiles, shell parses (bash -n), unclosed code fences, tabs in Markdown prose,
trailing whitespace (an exact two-space Markdown line break is allowed), final newline.
vendor/ is third-party and never rewritten.
"""

import argparse
from pathlib import Path
import py_compile
import re
import subprocess
import sys
import tempfile

SKIP = {".git", "node_modules", "dist", "out", "vendor", "__pycache__", "fixtures"}
TEXT = {".md", ".json", ".py", ".sh", ".yml", ".yaml", ".txt", ".example"}


def tracked(root):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not (set(path.relative_to(root).parts) & SKIP):
            if path.suffix in TEXT or path.name in {"Makefile", ".gitignore"}:
                yield path


def lint_file(path, root, fix):
    problems = []
    rel = path.relative_to(root).as_posix()
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    changed = False
    fenced = False
    for number, line in enumerate(lines, 1):
        if re.match(r"^\s{0,3}(```|~~~)", line):
            fenced = not fenced
        if path.suffix == ".md" and not fenced and "\t" in line and not line.lstrip().startswith("|"):
            problems.append(f"{rel}:{number}: tab in Markdown prose")
        stripped = line.rstrip(" \t")
        keep_break = path.suffix == ".md" and line.endswith("  ") and not line.endswith("   ") and stripped
        if stripped != line and not keep_break:
            problems.append(f"{rel}:{number}: trailing whitespace")
            lines[number - 1] = stripped
            changed = True
    if path.suffix == ".md" and fenced:
        problems.append(f"{rel}: unclosed code fence")
    if raw and not raw.endswith("\n"):
        problems.append(f"{rel}: missing final newline")
        lines.append("")
        changed = True
    if path.suffix == ".py":
        try:
            with tempfile.TemporaryDirectory() as scratch:
                py_compile.compile(str(path), cfile=str(Path(scratch) / "x.pyc"), doraise=True)
        except py_compile.PyCompileError as error:
            problems.append(f"{rel}: does not compile: {str(error).splitlines()[-1]}")
    if path.suffix == ".sh" or path.name == "setup.sh":
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        if result.returncode:
            problems.append(f"{rel}: bash -n: {result.stderr.strip()}")
    if fix and changed:
        path.write_text("\n".join(lines), encoding="utf-8")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    problems = [p for path in tracked(root) for p in lint_file(path, root, args.fix)]
    mechanical = [p for p in problems if "trailing whitespace" in p or "final newline" in p]
    remaining = problems if not args.fix else [p for p in problems if p not in mechanical]
    print("\n".join(problems) if problems else "OK: lint (python, shell, markdown, whitespace)")
    if args.fix and mechanical:
        print(f"fixed: {len(mechanical)} mechanical issue(s)")
    return 1 if remaining else 0


if __name__ == "__main__":
    sys.exit(main())
