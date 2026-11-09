#!/usr/bin/env python3
"""Offline Markdown link checker: local files, images and #anchors. No network.

External http(s) links are never fetched. They are only inventoried
(`--external-json`) so that you know what will not resolve offline.
"""

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

SKIP_DIRS = {".git", "node_modules", "dist", "out", "__pycache__"}
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REFDEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
HTML = re.compile(r"<(?:a|img|source|video)\b[^>]*?\b(?:href|src)=[\"']([^\"']+)[\"']", re.I)
HTML_ID = re.compile(r"<[^>]+\b(?:id|name)=[\"']([^\"']+)[\"']", re.I)
FENCE = re.compile(r"^\s{0,3}(```|~~~)")


def slug(heading):
    text = re.sub(r"`|\*|_(?=\S)|<[^>]+>", "", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def scan(path):
    """Return (targets, anchors) for one Markdown file; fenced code is ignored."""
    targets, anchors, seen, fenced = [], set(), {}, False
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
        if heading:
            base = slug(heading.group(1))
            count = seen.get(base, 0)
            seen[base] = count + 1
            anchors.add(base if count == 0 else f"{base}-{count}")
        anchors.update(HTML_ID.findall(line))
        found = LINK.findall(line) + HTML.findall(line)
        ref = REFDEF.match(line)
        if ref:
            found.append(ref.group(1))
        targets.extend((number, target) for target in found)
    return targets, anchors


def markdown_files(root, include_vendor):
    for path in sorted(root.rglob("*.md")):
        parts = set(path.relative_to(root).parts)
        if parts & SKIP_DIRS or (not include_vendor and "vendor" in parts):
            continue
        yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--include-vendor", action="store_true", help="also check vendor/")
    parser.add_argument("--external-json", type=Path, help="write the inventory of external URLs")
    args = parser.parse_args()
    root = args.root.resolve()

    files = list(markdown_files(root, args.include_vendor))
    parsed = {path: scan(path) for path in files}
    errors, external = [], {}
    for path, (targets, _anchors) in parsed.items():
        rel = path.relative_to(root).as_posix()
        for number, target in targets:
            parts = urlsplit(target)
            if parts.scheme in {"http", "https"}:
                kind = "remote-image" if "img.shields.io" in target or target.endswith((".png", ".svg", ".jpg", ".gif")) else "link"
                external.setdefault(target, {"kind": kind, "where": []})["where"].append(f"{rel}:{number}")
                continue
            if parts.scheme in {"mailto", "tel", "data"}:
                continue
            relative = unquote(parts.path)
            if relative.startswith("/"):
                dest = (root / relative.lstrip("/")).resolve()
            else:
                dest = (path.parent / relative).resolve() if relative else path
            if relative and not dest.exists():
                errors.append(f"{rel}:{number}: missing target: {target}")
                continue
            if parts.fragment and dest.suffix == ".md" and dest.is_file():
                anchors = parsed[dest][1] if dest in parsed else scan(dest)[1]
                if parts.fragment.lower() not in {a.lower() for a in anchors} and unquote(parts.fragment) not in anchors:
                    errors.append(f"{rel}:{number}: missing anchor: {target}")

    if args.external_json:
        inventory = {
            "note": "External URLs are NOT fetched offline; this is an inventory, not a verdict.",
            "count": len(external),
            "urls": {url: external[url] for url in sorted(external)},
        }
        args.external_json.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\n".join(errors) if errors else f"OK: {len(files)} Markdown files, local links and anchors resolve ({len(external)} external URLs not checked)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
