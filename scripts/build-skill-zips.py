#!/usr/bin/env python3
"""Build the six skill ZIPs offline, reproducibly, then verify them. No network.

Same layout as .github/workflows/skills-release.yml (dist/<skill>.zip, dist/all-skills.zip,
SHA256SUMS, release-provenance.json) with fixed timestamps so identical sources give
identical bytes. Only skills/ is packaged: vendor/ is never part of a release.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIXED_DATE = (2026, 1, 1, 0, 0, 0)


def add(package, arcname, data):
    info = zipfile.ZipInfo(arcname, FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100644) << 16
    package.writestr(info, data)


def build(root, dist):
    dist.mkdir(parents=True, exist_ok=True)
    for old in dist.glob("*.zip"):
        old.unlink()
    skills = sorted(p for p in (root / "skills").iterdir() if p.is_dir())
    for target, folders in [(p.name, [p]) for p in skills] + [("all-skills", skills)]:
        with zipfile.ZipFile(dist / f"{target}.zip", "w") as package:
            for folder in folders:
                for file in sorted(folder.rglob("*")):
                    if file.is_file():
                        add(package, f"{folder.name}/{file.relative_to(folder).as_posix()}", file.read_bytes())


def provenance(root, dist):
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dist.glob("*.zip"))}
    (dist / "SHA256SUMS").write_text("".join(f"{value}  {name}\n" for name, value in hashes.items()), encoding="utf-8")
    snapshot = root / "SNAPSHOT.json"
    meta = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.exists() else {}
    record = {
        "schemaVersion": 1,
        "repository": meta.get("upstream", {}).get("repository", "local"),
        "sourceRevision": meta.get("upstream", {}).get("commit", "unknown"),
        "createdAt": meta.get("createdAt") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "archives": hashes,
        "payloadFiles": {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted((root / "skills").rglob("*")) if p.is_file()},
        "verification": "Built offline. Source payloads and actual archive content verified by scripts/verify-skill-packages.py.",
    }
    (dist / "release-provenance.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dist", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    dist = (args.dist or root / "dist").resolve()
    build(root, dist)
    provenance(root, dist)
    check = subprocess.run([sys.executable, str(root / "scripts/verify-skill-packages.py"), "--root", str(root), "--archives", str(dist)])
    if check.returncode == 0:
        print(f"OK: {len(list(dist.glob('*.zip')))} ZIPs + SHA256SUMS + release-provenance.json in {dist}")
    return check.returncode


if __name__ == "__main__":
    sys.exit(main())
