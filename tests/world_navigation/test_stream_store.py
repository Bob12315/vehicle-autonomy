from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from vehicle_autonomy.world.sensors.stream_store import StreamStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'payloads';self.store=StreamStore(self.root,slots=4,max_bytes=64)
    def test_channel_isolation_bounded_storage_and_expired_reference(self):
        image=self.store.put(b'image','image/raw',channel='camera')
        scan=self.store.put(b'scan','application/scan',channel='lidar')
        for i in range(1000):self.store.put(str(i).encode(),'application/scan',channel='lidar')
        self.assertEqual(self.store.load(image),b'image')
        with self.assertRaises(ValueError):self.store.load(scan)
        self.assertLessEqual(len(list(self.root.iterdir())),4)
        with self.assertRaises(ValueError):self.store.put(b'other','application/other',channel='other')
    def test_changed_payload_bad_size_and_path_escape_rejected(self):
        ref=self.store.put(b'hello','image/raw')
        for candidate in (replace(ref,reference_id='../outside'),replace(ref,byte_size=1)):
            with self.assertRaises(ValueError):self.store.load(candidate)
        (self.root/ref.reference_id).write_bytes(b'jello')
        with self.assertRaises(ValueError):self.store.load(ref)
        with self.assertRaises(ValueError):self.store.put(bytes(65),'image/raw')
    def test_existing_directory_symlink_and_fifo_not_adopted(self):
        with self.assertRaises(FileExistsError):StreamStore(self.root)
        ref=self.store.put(b'ok','image/raw');p=self.root/ref.reference_id;p.unlink()
        external=Path(self.tmp.name)/'external';external.write_bytes(b'ok');p.symlink_to(external)
        with self.assertRaises(OSError):self.store.load(ref)
        p.unlink()
        import os
        os.mkfifo(p)
        with self.assertRaises(ValueError):self.store.load(ref)

class ReaderTests(unittest.TestCase):
    def test_read_only_existing_store_and_replaced_root(self):
        from vehicle_autonomy.world.sensors.stream_store import StreamReader
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'stream';store=StreamStore(root);ref=store.put(b'real','application/test')
            reader=StreamReader(root);self.assertFalse(hasattr(reader,'put'));self.assertEqual(reader.load(ref),b'real')
            root.rename(Path(tmp)/'old');replacement=StreamStore(root);replacement.put(b'real','application/test')
            with self.assertRaises(ValueError):reader.load(ref)
