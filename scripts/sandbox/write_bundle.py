#!/usr/bin/env python3
"""(Re)write sandbox/BUNDLE.json from the real files. Nothing is typed by hand.

  write_bundle.py --tarball T.tar.gz --source-commit SHA [--full-bundle B.zip] [--livrable-path P]

The tarball must be built from SOURCE_COMMIT (`git archive`), i.e. BEFORE this file exists:
a file cannot contain the hash of an archive that contains it. Run verify_bundle.py after.
"""

import argparse
import json
from pathlib import Path
import platform
import re
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_bundle as vb  # noqa: E402

PREFIX = "awesome-motion-design-sandbox/vendor/remotion-skills/remotion-best-practices/"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=vb.ROOT)
    parser.add_argument("--tarball", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--full-bundle", type=Path)
    parser.add_argument("--repo", default="Metba09/claude-memory (privé)")
    parser.add_argument("--livrable-path", default="livrables/awesome-motion-sandbox/")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    root = args.root.resolve()

    snapshot = json.loads((root / "SNAPSHOT.json").read_text(encoding="utf-8"))
    provenance = json.loads((root / "vendor" / "PROVENANCE.json").read_text(encoding="utf-8"))
    setup = (root / "setup.sh").read_text(encoding="utf-8")
    found = re.search(r"version_info >= \((\d+), (\d+)\)", setup)
    if not found:
        sys.stderr.write("setup.sh: minimum Python introuvable\n")
        return 1

    pointer = {
        "schema": 1,
        "note": "Le dépôt est la source de vérité ; le livrable est un miroir. Ce fichier est committé APRÈS le tarball : il n'y est donc pas (empreinte circulaire).",
        "upstream_base": snapshot["upstream"]["commit"],
        "branch": args.branch,
        "python": {"minimum": f"{found.group(1)}.{found.group(2)}", "tested": platform.python_version(), "source": "setup.sh"},
        "wheelhouse": {
            "packages": 0, "source": None, "verified_by": None, "stored_in_git": False, "size_bytes": 0, "refetch": None,
            "note": "Aucune dépendance Python ni Node : bibliothèque standard uniquement (requirements.txt ne contient que des commentaires). Rien à re-télécharger.",
        },
        "lockfiles_sha256": {name: vb.sha_file(root / name) for name in vb.lock_inputs(root)},
        "bundle": {
            "repo": args.repo, "path": args.livrable_path, "tarball": args.tarball.name,
            "tarball_sha256": vb.sha_file(args.tarball), "source_commit": args.source_commit,
        },
    }
    if args.full_bundle:
        with zipfile.ZipFile(args.full_bundle) as package:
            names = [n for n in package.namelist() if n.startswith(PREFIX) and not n.endswith("/")]
            entries = {n[len(PREFIX):]: vb.sha_bytes(package.read(n)) for n in names}
            size = sum(package.getinfo(n).file_size for n in names)
        if len(entries) != provenance["fileCount"] or vb.tree_sha256(entries) != provenance["treeSha256"]:
            sys.stderr.write("vendor/remotion-skills du ZIP != PROVENANCE.json : pointeur non écrit\n")
            return 1
        pointer["full_bundle"] = {
            "file": args.full_bundle.name, "sha256": vb.sha_file(args.full_bundle),
            "adds": "vendor/remotion-skills/ (privé uniquement, licence amont non explicite)",
        }
        pointer["third_party_vendored"] = [{
            "name": provenance["name"], "repository": provenance["source"]["repository"], "commit": provenance["source"]["commit"],
            "files": len(entries), "size_bytes": size, "tree_sha256": provenance["treeSha256"], "stored_in_git": False,
        }]
        pointer["not_vendored"] = "Les autres skills et dépôts tiers cités dans README.md ne sont pas vendorisés."
    (root / vb.POINTER).parent.mkdir(exist_ok=True)
    (root / vb.POINTER).write_text(json.dumps(pointer, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    vb.say(f"écrit {vb.POINTER} ({len(pointer['lockfiles_sha256'])} lockfiles, tarball {pointer['bundle']['tarball_sha256'][:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
