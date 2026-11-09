"""Tests for the offline tooling. Standard library only; every test works with no network."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True, cwd=cwd)


def mini_repo(base, files):
    for name, content in files.items():
        target = Path(base) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return Path(base)


class SchemaValidatorTests(unittest.TestCase):
    def setUp(self):
        self.mod = load("validate-json")
        self.schema = json.loads((ROOT / "schemas/media-job.schema.json").read_text(encoding="utf-8"))

    def test_sample_jobs_are_valid(self):
        for job in sorted((ROOT / "examples/media-jobs").glob("*.json")):
            with self.subTest(job=job.name):
                self.assertEqual(self.mod.validate(json.loads(job.read_text(encoding="utf-8")), self.schema), [])

    def test_invalid_fixtures_are_rejected_with_a_reason(self):
        expected = {
            "missing-routing": "missing required 'routing'",
            "bad-fps-enum": "not in",
            "extra-property": "unexpected property",
            "bad-id-pattern": "does not match",
        }
        for name, reason in expected.items():
            with self.subTest(fixture=name):
                data = json.loads((ROOT / f"tests/fixtures/invalid/{name}.json").read_text(encoding="utf-8"))
                errors = self.mod.validate(data, self.schema)
                self.assertTrue(any(reason in e for e in errors), errors)

    def test_boolean_is_not_an_integer_and_bad_date_is_caught(self):
        self.assertTrue(self.mod.validate(True, {"type": "integer"}))
        self.assertTrue(self.mod.validate("yesterday", {"type": "string", "format": "date-time"}))
        self.assertEqual(self.mod.validate("2026-11-08T09:00:00Z", {"type": "string", "format": "date-time"}), [])

    def test_cross_checks_report_no_drift(self):
        self.assertEqual(self.mod.cross_check(ROOT), [])


class RepoValidationTests(unittest.TestCase):
    def test_real_repository_passes(self):
        result = run("validate-repo.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_private_path_and_name_mismatch_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_repo(tmp, {
                "skills/alpha/SKILL.md": "---\nname: beta\ndescription: x\n---\nbody\n",
                "notes.md": "see /home/" + "someone/project\n",
                ".claude-plugin/marketplace.json": "{}",
                ".claude-plugin/plugin.json": "{}",
                "skills-lock.json": "{}",
            })
            result = run("validate-repo.py", "--root", tmp)
            self.assertEqual(result.returncode, 1)
            self.assertIn("name 'beta' != folder 'alpha'", result.stdout)
            self.assertIn("private local path", result.stdout)

    def test_vendor_directory_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_repo(tmp, {
                "vendor/third/notes.md": "/home/" + "someone/x\n",
                ".claude-plugin/marketplace.json": "{}",
                ".claude-plugin/plugin.json": "{}",
                "skills-lock.json": "{}",
            })
            self.assertEqual(run("validate-repo.py", "--root", tmp).returncode, 0)


class LinkCheckerTests(unittest.TestCase):
    def test_real_repository_links_resolve(self):
        result = run("check-links.py")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_missing_target_anchor_fence_and_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_repo(tmp, {
                "a.md": "# Title\n[ok](b.md#section-one) [gone](nope.md) [bad](b.md#missing)\n"
                        "```\n[ignored](also-missing.md)\n```\n[web](https://example.test/x)\n",
                "b.md": "## Section One\ntext\n",
            })
            out = Path(tmp) / "ext.json"
            result = run("check-links.py", "--root", tmp, "--external-json", str(out))
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing target: nope.md", result.stdout)
            self.assertIn("missing anchor: b.md#missing", result.stdout)
            self.assertNotIn("also-missing", result.stdout)
            self.assertNotIn("section-one", result.stdout)
            self.assertIn("https://example.test/x", json.loads(out.read_text(encoding="utf-8"))["urls"])


class MockProviderTests(unittest.TestCase):
    JOB = ROOT / "examples/media-jobs/social-vertical-remotion.json"

    def test_outputs_are_deterministic_and_honest(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            self.assertEqual(run("mock-provider.py", str(self.JOB), "--out", one).returncode, 0)
            self.assertEqual(run("mock-provider.py", str(self.JOB), "--out", two).returncode, 0)
            folder = "social-vertical-remotion"
            for name in ("poster.png", "preview.svg", "plan.json", "qa-report.json", "manifest.json"):
                self.assertEqual((Path(one) / folder / name).read_bytes(), (Path(two) / folder / name).read_bytes(), name)
            poster = (Path(one) / folder / "poster.png").read_bytes()
            self.assertTrue(poster.startswith(b"\x89PNG\r\n\x1a\n"))
            plan = json.loads((Path(one) / folder / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["networkCalls"], 0)
            self.assertEqual(plan["credentialsRead"], [])
            self.assertEqual(plan["realProviderOutputs"], [])
            qa = json.loads((Path(one) / folder / "qa-report.json").read_text(encoding="utf-8"))
            self.assertFalse(qa["evaluated"])

    def test_invalid_job_is_rejected_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run("mock-provider.py", str(ROOT / "tests/fixtures/invalid/bad-fps-enum.json"), "--out", tmp)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class PackagingTests(unittest.TestCase):
    def test_zips_verify_and_are_reproducible(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            self.assertEqual(run("build-skill-zips.py", "--dist", one).returncode, 0)
            self.assertEqual(run("build-skill-zips.py", "--dist", two).returncode, 0)
            names = sorted(p.name for p in Path(one).glob("*.zip"))
            self.assertEqual(len(names), 6)
            self.assertIn("all-skills.zip", names)
            for name in names:
                self.assertEqual(hashlib.sha256((Path(one) / name).read_bytes()).hexdigest(),
                                 hashlib.sha256((Path(two) / name).read_bytes()).hexdigest(), name)

    def test_vendor_is_never_packaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run("build-skill-zips.py", "--dist", tmp).returncode, 0)
            with zipfile.ZipFile(Path(tmp) / "all-skills.zip") as package:
                self.assertFalse([n for n in package.namelist() if "vendor" in n or "remotion-best-practices" in n])


class SnapshotTests(unittest.TestCase):
    def make(self, tmp):
        return mini_repo(tmp, {"a.txt": "one\n", "dir/b.txt": "two\n", "dist/ignored.txt": "x\n"})

    def test_create_verify_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make(tmp)
            self.assertEqual(run("snapshot.py", "--root", tmp, "create", "--upstream-repo", "r/x", "--upstream-sha", "abc").returncode, 0)
            manifest = (root / "MANIFEST.sha256").read_text(encoding="utf-8")
            self.assertIn("a.txt", manifest)
            self.assertNotIn("ignored.txt", manifest)
            self.assertEqual(run("snapshot.py", "--root", tmp, "verify").returncode, 0)
            (root / "new.txt").write_text("n\n", encoding="utf-8")
            self.assertEqual(run("snapshot.py", "--root", tmp, "verify").returncode, 0)
            self.assertEqual(run("snapshot.py", "--root", tmp, "verify", "--strict").returncode, 1)
            (root / "new.txt").unlink()
            (root / "a.txt").write_text("changed\n", encoding="utf-8")
            self.assertEqual(run("snapshot.py", "--root", tmp, "verify").returncode, 1)
            (root / "a.txt").write_text("one\n", encoding="utf-8")
            (root / "dir/b.txt").unlink()
            self.assertEqual(run("snapshot.py", "--root", tmp, "verify").returncode, 1)

    def test_recreate_keeps_upstream_and_pack_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            self.make(tmp)
            run("snapshot.py", "--root", tmp, "create", "--upstream-repo", "r/x", "--upstream-sha", "abc")
            run("snapshot.py", "--root", tmp, "create")
            meta = json.loads((Path(tmp) / "SNAPSHOT.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["upstream"], {"repository": "r/x", "commit": "abc"})
            a, b = Path(out) / "a.zip", Path(out) / "b.zip"
            run("snapshot.py", "--root", tmp, "pack", str(a))
            run("snapshot.py", "--root", tmp, "pack", str(b))
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with zipfile.ZipFile(a) as package:
                self.assertTrue(all(n.startswith("awesome-motion-design-sandbox/") for n in package.namelist()))


class GuardAndLintTests(unittest.TestCase):
    def test_real_tooling_is_network_free(self):
        self.assertEqual(run("offline-guard.py").returncode, 0)

    def test_violations_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_repo(tmp, {
                "scripts/bad.py": "import socket\nfrom urllib.request import urlopen\nfrom urllib.parse import quote\n",
                "setup.sh": "pip install foo\nnpm ci\n",
                "Makefile": "x:\n\tgit clone somewhere\n",
            })
            result = run("offline-guard.py", "--root", tmp)
            self.assertEqual(result.returncode, 1)
            for needle in ("network module 'socket'", "pip install without --no-index",
                           "npm install/ci without --offline", "git remote operation"):
                self.assertIn(needle, result.stdout)
            self.assertNotIn("urllib.parse", result.stdout)

    def test_lint_flags_and_fix_repairs_whitespace_but_keeps_hard_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(mini_repo(tmp, {"n.md": "line one  \nbad   \nlast"}) / "n.md")
            self.assertEqual(run("lint-docs.py", "--root", tmp).returncode, 1)
            self.assertEqual(run("lint-docs.py", "--root", tmp, "--fix").returncode, 0)
            self.assertEqual(note.read_text(encoding="utf-8"), "line one  \nbad\nlast\n")
            self.assertEqual(run("lint-docs.py", "--root", tmp).returncode, 0)

    def test_lint_detects_unclosed_fence_and_broken_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            mini_repo(tmp, {"n.md": "```\ncode\n", "s.py": "def (:\n"})
            result = run("lint-docs.py", "--root", tmp)
            self.assertEqual(result.returncode, 1)
            self.assertIn("unclosed code fence", result.stdout)
            self.assertIn("does not compile", result.stdout)


class SetupAndIsolationTests(unittest.TestCase):
    def test_setup_is_idempotent_and_keeps_an_existing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "repo"
            shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "dist", "out", ".env", "__pycache__", "vendor"))
            first = subprocess.run(["bash", "setup.sh"], cwd=work, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertTrue((work / ".env").exists())
            (work / ".env").write_text("MOTION_OFFLINE=1\nMY_NOTE=keep\n", encoding="utf-8")
            second = subprocess.run(["bash", "setup.sh"], cwd=work, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("conservé", second.stdout)
            self.assertIn("MY_NOTE=keep", (work / ".env").read_text(encoding="utf-8"))

    @unittest.skipUnless(shutil.which("unshare") and subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode == 0,
                         "network namespaces unavailable here")
    def test_run_offline_really_cuts_the_network(self):
        probe = "import socket,sys\ntry:\n    socket.create_connection(('1.1.1.1', 53), timeout=2)\nexcept OSError:\n    sys.exit(7)\nsys.exit(0)\n"
        result = subprocess.run(["bash", str(SCRIPTS / "run-offline.sh"), sys.executable, "-c", probe], capture_output=True, text=True)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
