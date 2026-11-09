#!/usr/bin/env python3
"""Verify sandbox/BUNDLE.json against the repository and, optionally, the private mirror.

Standard library only, no network. Every difference is reported as `ÉCART : ...` and the
exit code is 1. A corrupted archive never produces a traceback.

  verify_bundle.py                      pointer vs the files in this repository
  verify_bundle.py --livrable DIR       also the mirror in DIR: tarball SHA-256 first, opened only if it matches

The repository is the source of truth; the mirror in claude-memory is a copy.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
POINTER = "sandbox/BUNDLE.json"
ARCHIVE_ERRORS = (tarfile.TarError, KeyError, OSError, EOFError, zlib.error, zipfile.BadZipFile)


def say(text=""):
    sys.stdout.write(text + "\n")


def sha_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def lock_inputs(root):
    """Pinned inputs: requirements.txt, skills-lock.json, vendor/PROVENANCE.json, vendor/requirements*.lock.txt."""
    names = ["requirements.txt", "skills-lock.json", "vendor/PROVENANCE.json"]
    names += sorted(p.relative_to(root).as_posix() for p in (root / "vendor").glob("requirements*.lock.txt"))
    return [n for n in names if (root / n).is_file()]


def tree_sha256(entries):
    """Same recipe as vendor/PROVENANCE.json: sorted 'sha256  relative/path' lines, hashed."""
    lines = "".join(f"{sha}  {rel}\n" for rel, sha in sorted(entries.items(), key=lambda kv: PurePosixPath(kv[0])))
    return sha_bytes(lines.encode())


def load_pointer(root, gaps):
    try:
        data = json.loads((root / POINTER).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        gaps.append(f"{POINTER} illisible ({error.__class__.__name__}: {error})")
        return None
    if not isinstance(data, dict) or data.get("schema") != 1:
        gaps.append(f"{POINTER}: schema 1 attendu")
        return None
    for key in ("upstream_base", "python", "lockfiles_sha256", "bundle"):
        if key not in data:
            gaps.append(f"{POINTER}: clé manquante '{key}'")
    return data if not gaps else None


def check_repo(root, pointer, gaps):
    expected = pointer["lockfiles_sha256"]
    actual = lock_inputs(root)
    for name in sorted(set(actual) ^ set(expected)):
        gaps.append(f"jeu de lockfiles différent : '{name}' " + ("absent du pointeur" if name in actual else "absent du dépôt"))
    for name in sorted(set(actual) & set(expected)):
        found = sha_file(root / name)
        if found != expected[name]:
            gaps.append(f"{name}: sha256 {found[:12]} != pointeur {str(expected[name])[:12]}")
    python = pointer["python"]
    minimum = tuple(int(part) for part in str(python.get("minimum", "0")).split("."))
    if sys.version_info[: len(minimum)] < minimum:
        gaps.append(f"Python {sys.version_info[0]}.{sys.version_info[1]} < minimum {python.get('minimum')}")
    version_file = root / "vendor" / "PYTHON_VERSION"
    if version_file.is_file() and version_file.read_text(encoding="utf-8").strip() != str(python.get("version", "")):
        gaps.append("vendor/PYTHON_VERSION != pointeur")


def read_sums(folder):
    sums = {}
    path = folder / "SHA256SUMS"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            digest, _, name = line.partition("  ")
            sums[name.strip()] = digest
    return sums


def check_tarball(root, pointer, folder, gaps):
    bundle = pointer["bundle"]
    tarball = folder / bundle.get("tarball", "?")
    if not tarball.is_file():
        gaps.append(f"tarball absent : {tarball}")
        return
    found = sha_file(tarball)
    if found != bundle.get("tarball_sha256"):
        gaps.append(f"{tarball.name}: sha256 {found[:12]} != pointeur {str(bundle.get('tarball_sha256'))[:12]} (archive non ouverte)")
        return
    listed = read_sums(folder).get(tarball.name)
    if listed is not None and listed != found:
        gaps.append(f"SHA256SUMS: ligne de {tarball.name} différente de l'archive")
    try:
        with tarfile.open(tarball, "r:gz") as archive:
            comment = archive.pax_headers.get("comment")
            if comment and comment != bundle.get("source_commit"):
                gaps.append(f"commit dans l'archive {comment[:12]} != source_commit {str(bundle.get('source_commit'))[:12]}")
            members = {PurePosixPath(m.name).relative_to(*PurePosixPath(m.name).parts[:1]).as_posix(): m for m in archive.getmembers() if m.isfile()}
            for name, expected in pointer["lockfiles_sha256"].items():
                handle = archive.extractfile(members[name]) if name in members else None
                if handle is None:
                    gaps.append(f"{name}: absent de l'archive")
                elif sha_bytes(handle.read()) != expected:
                    gaps.append(f"{name}: différent dans l'archive")
            if POINTER in members:
                gaps.append(f"{POINTER} ne doit pas être dans l'archive (empreinte circulaire)")
    except ARCHIVE_ERRORS as error:
        gaps.append(f"{tarball.name}: archive illisible ({error.__class__.__name__})")


def check_full_bundle(root, pointer, folder, gaps):
    full = pointer.get("full_bundle")
    if not full:
        return
    path = folder / full["file"]
    if not path.is_file():
        say(f"info : {full['file']} absent, bundle complet non vérifié")
        return
    found = sha_file(path)
    if found != full.get("sha256"):
        gaps.append(f"{path.name}: sha256 {found[:12]} != pointeur {str(full.get('sha256'))[:12]} (archive non ouverte)")
        return
    try:
        provenance = json.loads((root / "vendor" / "PROVENANCE.json").read_text(encoding="utf-8"))
        with zipfile.ZipFile(path) as package:
            prefix = "awesome-motion-design-sandbox/vendor/remotion-skills/remotion-best-practices/"
            entries = {n[len(prefix):]: sha_bytes(package.read(n)) for n in package.namelist() if n.startswith(prefix) and not n.endswith("/")}
        if len(entries) != provenance.get("fileCount") or tree_sha256(entries) != provenance.get("treeSha256"):
            gaps.append(f"{path.name}: contenu de vendor/remotion-skills différent de PROVENANCE.json")
    except (ValueError, *ARCHIVE_ERRORS) as error:
        gaps.append(f"{path.name}: archive illisible ({error.__class__.__name__})")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--livrable", type=Path, help="directory of the mirror (tarball, SHA256SUMS)")
    args = parser.parse_args()
    root = args.root.resolve()
    gaps = []
    pointer = load_pointer(root, gaps)
    if pointer:
        check_repo(root, pointer, gaps)
        if args.livrable:
            check_tarball(root, pointer, args.livrable.resolve(), gaps)
            check_full_bundle(root, pointer, args.livrable.resolve(), gaps)
    for gap in gaps:
        say(f"ÉCART : {gap}")
    if not gaps:
        scope = "dépôt + livrable" if args.livrable else "dépôt"
        say(f"OK : BUNDLE.json cohérent ({scope}, {len(pointer['lockfiles_sha256'])} lockfiles)")
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main())
