#!/usr/bin/env python3
"""Hermetic snapshot tooling: checksum manifest, integrity check, deterministic ZIP. No network.

  snapshot.py create [--upstream-repo R --upstream-sha S] [--vendor NAME=REPO@SHA ...]
  snapshot.py verify [--strict]      modified or missing files fail; new files only warn (fail with --strict)
  snapshot.py pack OUT.zip           deterministic archive of the snapshot under one top-level folder
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {".git", "dist", "out", "__pycache__", "node_modules", ".pytest_cache"}
EXCLUDE_FILES = {".env", "MANIFEST.sha256", "SNAPSHOT.json", "BUNDLE.json"}
FIXED_DATE = (2026, 1, 1, 0, 0, 0)
TOP = "awesome-motion-design-sandbox"


def files(root):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not (set(rel.parts) & EXCLUDE_DIRS) and rel.name not in EXCLUDE_FILES and not rel.name.endswith(".pyc"):
            yield rel


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(root):
    entries = {}
    for line in (root / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        entries[name] = digest
    return entries


def create(root, args):
    previous = {}
    if (root / "SNAPSHOT.json").exists():
        previous = json.loads((root / "SNAPSHOT.json").read_text(encoding="utf-8"))
    lines = [f"{sha(root / rel)}  {rel.as_posix()}\n" for rel in files(root)]
    (root / "MANIFEST.sha256").write_text("".join(lines), encoding="utf-8")
    vendor = dict(previous.get("vendored", {}))
    for item in args.vendor:
        name, _, rest = item.partition("=")
        repo, _, commit = rest.partition("@")
        vendor[name] = {"repository": repo, "commit": commit}
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    created = (datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc) if epoch
               else datetime.datetime.now(datetime.timezone.utc)).replace(microsecond=0).isoformat()
    meta = {
        "schemaVersion": 1,
        "createdAt": created,
        "upstream": {
            "repository": args.upstream_repo or previous.get("upstream", {}).get("repository", "local"),
            "commit": args.upstream_sha or previous.get("upstream", {}).get("commit", "unknown"),
        },
        "vendored": vendor,
        "fileCount": len(lines),
        "manifestSha256": hashlib.sha256("".join(lines).encode()).hexdigest(),
        "network": "none required: stdlib Python 3 only, no package manager step",
    }
    (root / "SNAPSHOT.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"snapshot: {len(lines)} files, manifest sha256 {meta['manifestSha256'][:12]}")
    return 0


def verify(root, args):
    if not (root / "MANIFEST.sha256").exists():
        print("ERR: MANIFEST.sha256 missing (run: make snapshot)", file=sys.stderr)
        return 1
    expected, actual = read_manifest(root), {rel.as_posix(): sha(root / rel) for rel in files(root)}
    modified = sorted(n for n in expected if n in actual and expected[n] != actual[n])
    missing = sorted(n for n in expected if n not in actual)
    extra = sorted(n for n in actual if n not in expected)
    for label, names in (("MODIFIED", modified), ("MISSING", missing)):
        for name in names:
            print(f"{label}: {name}")
    for name in extra:
        print(f"{'EXTRA' if args.strict else 'new'}: {name}")
    bad = bool(modified or missing or (args.strict and extra))
    print("FAIL: snapshot differs" if bad else f"OK: {len(expected)} files match the snapshot" + (f" ({len(extra)} new, not in snapshot)" if extra else ""))
    return 1 if bad else 0


def pack(root, args):
    out = args.output.resolve()
    members = list(files(root)) + [Path("MANIFEST.sha256"), Path("SNAPSHOT.json")]
    with zipfile.ZipFile(out, "w") as package:
        for rel in sorted(set(members)):
            source = root / rel
            if not source.exists():
                continue
            info = zipfile.ZipInfo(f"{TOP}/{rel.as_posix()}", FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if os.access(source, os.X_OK) else 0o100644) << 16
            package.writestr(info, source.read_bytes())
    print(f"pack: {out} ({out.stat().st_size // 1024} KiB)")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--upstream-repo", default=None, help="default: keep the one in SNAPSHOT.json")
    c.add_argument("--upstream-sha", default=None)
    c.add_argument("--vendor", action="append", default=[])
    v = sub.add_parser("verify")
    v.add_argument("--strict", action="store_true")
    p = sub.add_parser("pack")
    p.add_argument("output", type=Path)
    args = parser.parse_args()
    return {"create": create, "verify": verify, "pack": pack}[args.cmd](args.root.resolve(), args)


if __name__ == "__main__":
    sys.exit(main())
