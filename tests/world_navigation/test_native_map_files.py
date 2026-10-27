import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vehicle_autonomy.world.mapping.native_files import (
    MAX_NATIVE_FILE_BYTES, inspect_native_map, prepare_native_map,
)


class NativeMapFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def files(self):
        for suffix in (".posegraph", ".data"):
            (self.root / ("survey" + suffix)).write_bytes(suffix.encode())

    def test_fresh_destination_and_real_bounded_file_digests(self):
        base, paths = prepare_native_map(self.root, "survey")
        self.assertEqual(base, self.root / "survey")
        self.assertEqual(len(paths), 2)
        self.assertFalse(any(p.exists() for p in paths))
        self.files()
        result = inspect_native_map(self.root, "survey")
        self.assertEqual(result["survey.data"], dict(
            bytes=5, sha256=hashlib.sha256(b".data").hexdigest()))

    def test_existing_or_broken_symlink_cannot_be_overwritten(self):
        self.files()
        with self.assertRaises(ValueError):
            prepare_native_map(self.root, "survey")
        (self.root / "other.data").symlink_to(self.root / "absent")
        with self.assertRaises(ValueError):
            prepare_native_map(self.root, "other")

    def test_names_cannot_escape_private_parent(self):
        for name in ("../outside", "/absolute", "", "a/b", "a" * 65):
            with self.subTest(name=name), self.assertRaises(ValueError):
                prepare_native_map(self.root, name)

    def test_insecure_directory_or_wrong_owner_rejected(self):
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):
            prepare_native_map(self.root, "survey")
        self.root.chmod(0o700)
        with patch("os.getuid", return_value=os.getuid() + 1):
            with self.assertRaises(ValueError):
                prepare_native_map(self.root, "survey")

    def test_parent_symlink_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            prepare_native_map(alias, "survey")

    def test_symlink_and_hardlink_are_not_map_evidence(self):
        self.files()
        target = self.root / "survey.data"
        target.unlink()
        target.symlink_to(self.root / "survey.posegraph")
        with self.assertRaises((OSError, ValueError)):
            inspect_native_map(self.root, "survey")
        target.unlink()
        os.link(self.root / "survey.posegraph", target)
        with self.assertRaises(ValueError):
            inspect_native_map(self.root, "survey")

    def test_empty_missing_and_oversize_are_rejected(self):
        with self.assertRaises(FileNotFoundError):
            inspect_native_map(self.root, "survey")
        self.files()
        target = self.root / "survey.data"
        target.write_bytes(b"")
        with self.assertRaises(ValueError):
            inspect_native_map(self.root, "survey")
        with target.open("wb") as file:
            file.truncate(MAX_NATIVE_FILE_BYTES + 1)
        with self.assertRaises(ValueError):
            inspect_native_map(self.root, "survey")

    def test_concurrent_truncation_is_not_reported_as_valid_digest(self):
        self.files()
        real_read = os.read
        changed = False

        def interrupted(fd, size):
            nonlocal changed
            data = real_read(fd, size)
            if data and not changed:
                changed = True
                (self.root / "survey.posegraph").write_bytes(b"x")
            return data

        with patch("os.read", side_effect=interrupted):
            with self.assertRaises(ValueError):
                inspect_native_map(self.root, "survey")
