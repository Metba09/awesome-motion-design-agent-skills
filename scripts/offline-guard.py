#!/usr/bin/env python3
"""Static guard: fail if the tooling can reach the network. Nothing is executed.

Scans scripts/, tests/, setup.sh and Makefile for network imports (Python AST), network
commands (curl, wget, npx, gh, docker, git clone/fetch/pull/push) and package installs
that are not offline (`pip install` needs --no-index, `npm ci` needs --offline).
A few CI-only files are allowlisted below, each with its reason, and are never run by `make`.
"""

import argparse
import ast
from pathlib import Path
import re
import sys

ALLOW = {
    "scripts/release-policy.py": "CI-only: asks the GitHub API (gh) in the release workflow; its tests inject a fake fetch",
}
SELF = "scripts/offline-guard.py"
NET_MODULES = {"urllib.request", "http.client", "socket", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "telnetlib", "websocket", "websockets"}
NET_COMMANDS = {"curl", "wget", "npx", "gh", "docker", "ssh", "scp", "rsync"}
SHELL_RULES = [
    (re.compile(r"(?<![\w./-])(curl|wget|npx|docker|ssh|scp|rsync)\b"), "network/heavy command"),
    (re.compile(r"(?<![\w./-])gh\s+(api|release|issue|pr|repo|auth)\b"), "GitHub CLI"),
    (re.compile(r"\bgit\s+(clone|fetch|pull|push|ls-remote|submodule)\b"), "git remote operation"),
]


def python_findings(path):
    found = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [f"{node.module}.{alias.name}" for alias in node.names] + [node.module or ""]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in NET_COMMANDS:
            found.append((node.lineno, f"command string '{node.value}'"))
            continue
        else:
            continue
        for name in filter(None, names):
            # `import socket`, `from urllib.request import urlopen`, `from urllib import request`
            if any(name == m or name.startswith(m + ".") for m in NET_MODULES):
                found.append((node.lineno, f"network module '{name}'"))
    return found


def shell_findings(path):
    found = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        code = line.split("#", 1)[0] if not line.lstrip().startswith("echo") else ""
        if not code.strip():
            continue
        for pattern, why in SHELL_RULES:
            if pattern.search(code):
                found.append((number, why))
        if re.search(r"\bpip3?\s+install\b", code) and "--no-index" not in code:
            found.append((number, "pip install without --no-index"))
        if re.search(r"\bnpm\s+(install|i|ci)\b", code) and "--offline" not in code:
            found.append((number, "npm install/ci without --offline"))
    return found


def targets(root):
    for pattern in ("scripts/*.py", "scripts/*.sh", "tests/*.py", "setup.sh", "Makefile"):
        yield from sorted(root.glob(pattern))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    violations, allowed = [], []
    for path in targets(root):
        rel = path.relative_to(root).as_posix()
        if rel == SELF:
            continue
        findings = python_findings(path) if path.suffix == ".py" else shell_findings(path)
        if not findings:
            continue
        if rel in ALLOW:
            allowed.append(f"allowed {rel}: {ALLOW[rel]}")
        else:
            violations += [f"{rel}:{line}: {why}" for line, why in findings]
    for note in allowed:
        print(note)
    print("\n".join(violations) if violations else "OK: no network access in the sandbox tooling")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
