import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import io
import struct
import tarfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import build_environment, destination, registry, revision
from release import completed_build
from targets import elf_details, inspect_binary, target_name
from build import Builder


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
        binary = bytearray(64)
        binary[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<HH', binary, 16, 3, 183)
        with tarfile.open(archive, 'w:gz') as output:
            info = tarfile.TarInfo('zlib/lib/libz.so')
            info.size = len(binary)
            output.addfile(info, io.BytesIO(binary))
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        (root / "zlib.tar.gz.sha256").write_text(sha + "  zlib.tar.gz\n")
        data = {"dependency": "zlib", "source_commit": "a" * 40, "host": "linux-x86_64",
                "architecture": "arm64", "libc": "bionic", "target": "android-arm64-bionic",
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


class TargetTests(unittest.TestCase):
    def test_builder_defaults_to_arm64_bionic(self):
        with tempfile.TemporaryDirectory() as temp:
            builder = Builder('zlib', '', root=temp)
            self.assertEqual('android-arm64-bionic', builder.target)
            self.assertEqual('bionic', builder.libc)

    def elf(self, machine=183, interpreter=None):
        binary = bytearray(64 if not interpreter else 120 + len(interpreter) + 1)
        binary[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<HH', binary, 16, 3, machine)
        if interpreter:
            struct.pack_into('<Q', binary, 32, 64)
            struct.pack_into('<HH', binary, 54, 56, 1)
            struct.pack_into('<IIQQQQQQ', binary, 64, 3, 0, 120, 0, 0, len(interpreter)+1, len(interpreter)+1, 1)
            binary[120:] = interpreter.encode()+b'\0'
        return bytes(binary)

    def test_arm64_is_fixed_across_libcs(self):
        self.assertEqual('android-arm64-bionic', target_name('bionic'))
        self.assertEqual('linux-arm64-glibc', target_name('glibc'))
        self.assertEqual('linux-arm64-musl', target_name('musl'))

    def test_rejects_x86_output(self):
        with self.assertRaises(ValueError):
            elf_details(self.elf(machine=62), 'bionic', 'wrong.so')

    def test_checks_bionic_interpreter(self):
        self.assertTrue(elf_details(self.elf(interpreter='/system/bin/linker64'), 'bionic', 'android-tool'))
        with self.assertRaises(ValueError):
            elf_details(self.elf(interpreter='/lib/ld-linux-aarch64.so.1'), 'bionic', 'desktop-tool')

    def test_checks_other_libc_interpreters(self):
        self.assertTrue(elf_details(self.elf(interpreter='/lib/ld-linux-aarch64.so.1'), 'glibc', 'glibc-tool'))
        self.assertTrue(elf_details(self.elf(interpreter='/lib/ld-musl-aarch64.so.1'), 'musl', 'musl-tool'))

    def test_rejects_x86_in_static_library(self):
        member = self.elf(machine=62)
        header = ('wrong.o/        '+str(0).ljust(12)+str(0).ljust(6)+str(0).ljust(6)+'100644  '+str(len(member)).ljust(10)+'`\n').encode()
        with self.assertRaises(ValueError):
            inspect_binary(b'!<arch>\n'+header+member, 'bionic', 'wrong.a')



if __name__ == "__main__":
    unittest.main()
