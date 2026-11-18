import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import build_environment, destination, registry, revision
from release import completed_build


class RevisionTests(unittest.TestCase):
    def test_commit_and_tag(self):
        self.assertEqual(("a" * 40, "commit"), revision("A" * 40))
        self.assertEqual(("v1.3.1", "tag"), revision("v1.3.1"))

    def test_rejects_command_and_ref_injection(self):
        for text in ("--upload-pack=evil", "v1; touch x", "$(whoami)", "tag\nOTHER=1", "../main", "x..y", "x@{1}"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                revision(text)

    def test_build_child_has_no_github_credentials(self):
        with patch.dict(os.environ, {"GH_TOKEN": "test-only", "GITHUB_TOKEN": "test-only",
                         "RELEASE_TOKEN": "test-only", "GIT_CONFIG_COUNT": "1",
                         "GIT_CONFIG_KEY_0": "http.extraheader", "GIT_CONFIG_VALUE_0": "test-only"}):
            env = build_environment()
            self.assertFalse(any(key in env for key in ("GH_TOKEN", "GITHUB_TOKEN", "RELEASE_TOKEN", "GIT_CONFIG_COUNT", "GIT_CONFIG_VALUE_0")))


class RegistryTests(unittest.TestCase):
    def test_sources_are_pinned_and_graph_is_acyclic(self):
        entries = registry()
        visited = set()
        active = set()

        def walk(name):
            self.assertIn(name, entries)
            if name in visited:
                return
            self.assertNotIn(name, active)
            active.add(name)
            spec = entries[name]
            self.assertTrue(spec["url"].startswith("https://"))
            self.assertNotIn("@", spec["url"].split("//", 1)[1].split("/", 1)[0])
            self.assertEqual("commit", revision(spec["default_ref"])[1])
            for dependency in spec.get("dependencies", []):
                walk(dependency)
            for placement in spec.get("source_dependencies", []):
                self.assertIn(placement["dependency"], entries)
                self.assertFalse(Path(placement["path"]).is_absolute())
                self.assertNotIn("..", Path(placement["path"]).parts)
            active.remove(name)
            visited.add(name)

        for name in entries:
            walk(name)

    def test_current_and_future_release_destinations(self):
        self.assertEqual("owner/main", destination("zlib", current="owner/main"))
        self.assertEqual("owner/zlib", destination("zlib", override="owner/zlib", current="owner/main"))
        for value in ("https://github.com/owner/repo", "owner/repo\nX=1", "../repo", "owner/../repo"):
            with self.assertRaises(ValueError):
                destination("zlib", override=value)


class ReleaseAssetTests(unittest.TestCase):
    def fixture(self, root):
        archive = root / "zlib.tar.gz"
        archive.write_bytes(b"fixture build output")
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        (root / "zlib.tar.gz.sha256").write_text(sha + "  zlib.tar.gz\n")
        data = {"dependency": "zlib", "source_commit": "a" * 40, "host": "linux-x86_64",
                "assets": ["zlib.tar.gz", "zlib.tar.gz.sha256"], "archive_sha256": sha}
        (root / "build.json").write_text(json.dumps(data))
        return data

    def test_accepts_completed_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            metadata, assets = completed_build(root)
            self.assertEqual("zlib", metadata["dependency"])
            self.assertEqual(2, len(assets))

    def test_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "zlib.tar.gz").write_bytes(b"modified")
            with self.assertRaises(ValueError):
                completed_build(root)

    def test_rejects_asset_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = self.fixture(root)
            data["assets"][0] = "../outside.tar.gz"
            (root / "build.json").write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                completed_build(root)

    def test_rejects_symlink_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "outside").write_bytes(b"fixture build output")
            (root / "zlib.tar.gz").unlink()
            (root / "zlib.tar.gz").symlink_to(root / "outside")
            with self.assertRaises(ValueError):
                completed_build(root)


if __name__ == "__main__":
    unittest.main()
