import json,os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from vehicle_autonomy.actions.navigation.native_job import NativeNavigationJob
from vehicle_autonomy.world.mapping.grid import atomic_json

class NativeJobReaderTests(unittest.TestCase):
    def test_atomic_replacement_after_open_preserves_original_sample_and_age(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';atomic_json(path,{'source_ns':100})
            original=os.fstat;once=[]
            def replace_after_open(fd):
                if not once:once.append(True);atomic_json(path,{'source_ns':200})
                return original(fd)
            with patch('vehicle_autonomy.actions.navigation.native_job.os.fstat',replace_after_open):
                self.assertEqual(NativeNavigationJob._read(path),{'source_ns':100})
            self.assertEqual(NativeNavigationJob._read(path),{'source_ns':200})
    def test_hard_link_and_symlink_are_rejected(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'state.json';atomic_json(path,{'source_ns':100})
            os.link(path,path.with_name('other'))
            with self.assertRaises(ValueError):NativeNavigationJob._read(path)
            path.unlink();path.symlink_to(path.with_name('other'))
            with self.assertRaises(OSError):NativeNavigationJob._read(path)
