"""Tests for sandbox/BUNDLE.json: writer, verifier, tampering. Standard library only, offline."""

import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "scripts" / "sandbox"
COMMIT = "b" * 40
TOP = "awesome-motion-design-sandbox/"
VENDOR_PREFIX = TOP + "vendor/remotion-skills/remotion-best-practices/"


def load_verify():
    spec = importlib.util.spec_from_file_location("verify_bundle", SANDBOX / "verify_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VB = load_verify()


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, str(SANDBOX / script), *args], capture_output=True, text=True, cwd=cwd)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Fixture:
    """A miniature repo + mirror: lock inputs, a source tarball, a full ZIP with a vendored tree."""

    def __init__(self, base):
        self.base = Path(base)
        self.repo = self.base / "repo"
        self.mirror = self.base / "mirror"
        self.vendor = {"a.md": b"alpha\n", "dir/b.md": b"beta\n"}
        tree = VB.tree_sha256({name: sha(data) for name, data in self.vendor.items()})
        files = {
            "requirements.txt": "# none\n",
            "skills-lock.json": "{}\n",
            "setup.sh": "x -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'\n",
            "SNAPSHOT.json": json.dumps({"upstream": {"repository": "o/r", "commit": "a" * 40}}),
            "vendor/PROVENANCE.json": json.dumps({
                "name": "demo", "source": {"repository": "x/y", "commit": "c" * 40}, "fileCount": 2, "treeSha256": tree}),
        }
        for name, text in files.items():
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self.mirror.mkdir()
        self.tarball = self.mirror / "src.tar.gz"
        self.zip = self.mirror / "full.zip"
        self.build_tarball()
        with zipfile.ZipFile(self.zip, "w") as package:
            for name, data in self.vendor.items():
                package.writestr(VENDOR_PREFIX + name, data)

    def build_tarball(self, extra=None, commit=COMMIT):
        with tarfile.open(self.tarball, "w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": commit}) as archive:
            for name in ("requirements.txt", "skills-lock.json", "vendor/PROVENANCE.json"):
                data = (self.repo / name).read_bytes()
                info = tarfile.TarInfo(TOP + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            for name, data in (extra or {}).items():
                info = tarfile.TarInfo(TOP + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def write_pointer(self):
        result = run("write_bundle.py", "--root", str(self.repo), "--tarball", str(self.tarball),
                     "--source-commit", COMMIT, "--full-bundle", str(self.zip))
        assert result.returncode == 0, result.stdout + result.stderr

    def verify(self, *extra):
        return run("verify_bundle.py", "--root", str(self.repo), *extra)

    def pointer(self):
        return json.loads((self.repo / "sandbox/BUNDLE.json").read_text(encoding="utf-8"))

    def set_pointer(self, **changes):
        data = self.pointer()
        data["bundle"].update(changes)
        (self.repo / "sandbox/BUNDLE.json").write_text(json.dumps(data), encoding="utf-8")


class BundlePointerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fx = Fixture(self.tmp.name)
        self.fx.write_pointer()

    def assertNoTraceback(self, result):
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_consistent_pointer_passes_with_and_without_mirror(self):
        self.assertEqual(self.fx.verify().returncode, 0)
        result = self.fx.verify("--livrable", str(self.fx.mirror))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("dépôt + livrable", result.stdout)

    def test_pointer_records_honest_facts(self):
        pointer = self.fx.pointer()
        self.assertEqual(pointer["schema"], 1)
        self.assertEqual(pointer["wheelhouse"]["packages"], 0)
        self.assertFalse(pointer["wheelhouse"]["stored_in_git"])
        self.assertEqual(pointer["python"]["minimum"], "3.9")
        self.assertEqual(pointer["upstream_base"], "a" * 40)
        self.assertEqual(pointer["bundle"]["tarball_sha256"], sha(self.fx.tarball.read_bytes()))
        self.assertEqual(pointer["third_party_vendored"][0]["files"], 2)
        self.assertEqual(set(pointer["lockfiles_sha256"]), {"requirements.txt", "skills-lock.json", "vendor/PROVENANCE.json"})

    def test_changed_lockfile_is_reported(self):
        (self.fx.repo / "requirements.txt").write_text("# none\nx", encoding="utf-8")
        result = self.fx.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ÉCART : requirements.txt", result.stdout)
        self.assertNoTraceback(result)

    def test_added_or_removed_lockfile_changes_the_set(self):
        (self.fx.repo / "vendor" / "requirements-gpu.lock.txt").write_text("foo==1 --hash=sha256:00\n", encoding="utf-8")
        result = self.fx.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("jeu de lockfiles différent", result.stdout)

    def test_flipped_byte_in_tarball_is_caught_before_opening(self):
        data = bytearray(self.fx.tarball.read_bytes())
        data[len(data) // 2] ^= 1
        self.fx.tarball.write_bytes(bytes(data))
        result = self.fx.verify("--livrable", str(self.fx.mirror))
        self.assertEqual(result.returncode, 1)
        self.assertIn("archive non ouverte", result.stdout)
        self.assertNoTraceback(result)

    def test_corrupt_archives_with_a_matching_hash_never_traceback(self):
        raw_tar = tarfile.TarInfo.__name__.encode() * 400
        cases = {
            "truncated gzip (EOFError)": self.fx.tarball.read_bytes()[:60],
            "gzip of garbage (TarError)": gzip.compress(raw_tar),
            "not gzip at all (OSError)": b"plain text, not an archive",
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                self.fx.tarball.write_bytes(data)
                self.fx.set_pointer(tarball_sha256=sha(data))  # the hash matches, so the archive IS opened
                result = self.fx.verify("--livrable", str(self.fx.mirror))
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("ÉCART", result.stdout)
                self.assertNoTraceback(result)

    def test_lockfile_altered_inside_a_consistent_archive(self):
        self.fx.build_tarball()
        # rebuild the archive with a different requirements.txt while keeping the pointer's lockfile hashes
        with tarfile.open(self.fx.tarball, "w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": COMMIT}) as archive:
            for name, data in (("requirements.txt", b"changed\n"), ("skills-lock.json", b"{}\n"),
                               ("vendor/PROVENANCE.json", (self.fx.repo / "vendor/PROVENANCE.json").read_bytes())):
                info = tarfile.TarInfo(TOP + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        self.fx.set_pointer(tarball_sha256=sha(self.fx.tarball.read_bytes()))
        result = self.fx.verify("--livrable", str(self.fx.mirror))
        self.assertEqual(result.returncode, 1)
        self.assertIn("requirements.txt: différent dans l'archive", result.stdout)

    def test_pointer_inside_the_archive_is_a_circular_hash(self):
        self.fx.build_tarball(extra={"sandbox/BUNDLE.json": b"{}"})
        self.fx.set_pointer(tarball_sha256=sha(self.fx.tarball.read_bytes()))
        result = self.fx.verify("--livrable", str(self.fx.mirror))
        self.assertEqual(result.returncode, 1)
        self.assertIn("empreinte circulaire", result.stdout)

    def test_wrong_source_commit_inside_the_archive(self):
        self.fx.build_tarball(commit="d" * 40)
        self.fx.set_pointer(tarball_sha256=sha(self.fx.tarball.read_bytes()))
        result = self.fx.verify("--livrable", str(self.fx.mirror))
        self.assertEqual(result.returncode, 1)
        self.assertIn("source_commit", result.stdout)

    def test_full_bundle_is_hash_checked_then_tree_checked(self):
        original = self.fx.zip.read_bytes()
        data = bytearray(original)
        data[len(data) // 3] ^= 1
        self.fx.zip.write_bytes(bytes(data))
        result = self.fx.verify("--livrable", str(self.fx.mirror))
        self.assertEqual(result.returncode, 1)
        self.assertIn("archive non ouverte", result.stdout)
        # a ZIP whose hash matches but whose vendored tree differs from PROVENANCE.json
        with zipfile.ZipFile(self.fx.zip, "w") as package:
            package.writestr(VENDOR_PREFIX + "a.md", b"tampered\n")
            package.writestr(VENDOR_PREFIX + "dir/b.md", b"beta\n")
        data = json.loads((self.fx.repo / "sandbox/BUNDLE.json").read_text(encoding="utf-8"))
        data["full_bundle"]["sha256"] = sha(self.fx.zip.read_bytes())
        (self.fx.repo / "sandbox/BUNDLE.json").write_text(json.dumps(data), encoding="utf-8")
        result = self.fx.verify("--livrable", str(self.fx.mirror))
        self.assertEqual(result.returncode, 1)
        self.assertIn("différent de PROVENANCE.json", result.stdout)
        self.assertNoTraceback(result)

    def test_missing_mirror_file_and_bad_pointer(self):
        self.fx.tarball.unlink()
        self.assertIn("tarball absent", self.fx.verify("--livrable", str(self.fx.mirror)).stdout)
        (self.fx.repo / "sandbox/BUNDLE.json").write_text("{oops", encoding="utf-8")
        result = self.fx.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("illisible", result.stdout)
        self.assertNoTraceback(result)

    def test_writer_refuses_a_zip_that_contradicts_provenance(self):
        with zipfile.ZipFile(self.fx.zip, "w") as package:
            package.writestr(VENDOR_PREFIX + "a.md", b"only one file\n")
        result = run("write_bundle.py", "--root", str(self.fx.repo), "--tarball", str(self.fx.tarball),
                     "--source-commit", COMMIT, "--full-bundle", str(self.fx.zip))
        self.assertEqual(result.returncode, 1)
        self.assertIn("pointeur non écrit", result.stderr)


class RealRepositoryTests(unittest.TestCase):
    def test_committed_pointer_matches_the_repository(self):
        result = run("verify_bundle.py")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_snapshot_manifest_excludes_the_pointer(self):
        manifest = (ROOT / "MANIFEST.sha256").read_text(encoding="utf-8")
        self.assertNotIn("sandbox/BUNDLE.json", manifest)

    def test_lint_fails_when_the_pointer_goes_stale_then_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "repo"
            shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "dist", "out", ".env", "__pycache__", "remotion-skills"))
            ok = subprocess.run(["bash", "scripts/lint.sh"], cwd=work, capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            lock = work / "skills-lock.json"
            original = lock.read_text(encoding="utf-8")
            lock.write_text(original.rstrip("\n") + "\n\n", encoding="utf-8")
            stale = subprocess.run(["bash", "scripts/lint.sh"], cwd=work, capture_output=True, text=True)
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("ÉCART : skills-lock.json", stale.stdout)
            lock.write_text(original, encoding="utf-8")
            self.assertEqual(subprocess.run(["bash", "scripts/lint.sh"], cwd=work, capture_output=True, text=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
