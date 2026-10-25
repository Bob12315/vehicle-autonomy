"""Actual file/MAC/owner recovery under partial writes and process death."""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

from pymavlink.dialects.v20 import ardupilotmega as mav
from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation,initialize_receive_floor
from vehicle_autonomy.engine.action.durable import DurableRecord
from tests.mavlink_fixture import TEST_KEY


def frame(timestamp):
    sender=mav.MAVLink(None,srcSystem=1,srcComponent=1)
    sender.signing.secret_key=TEST_KEY;sender.signing.sign_outgoing=True;sender.signing.timestamp=timestamp
    return sender.heartbeat_encode(10,3,0,4,4).pack(sender)


def message(timestamp):return mav.MAVLink(None).parse_buffer(frame(timestamp))[0]


def fixture(root):
    root=Path(root);binary=root/'ardurover';binary.write_bytes(b'owned storage test; no vehicle executable')
    private=root/'receive-signing.private'
    with os.fdopen(os.open(private,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
        json.dump({'key':TEST_KEY.hex(),'floor':100},f)
    state=root/'sitl_state';state.mkdir(mode=0o700);info=root.stat()
    records=[{'name':p.name,'kind':kind,'device':p.stat().st_dev,'inode':p.stat().st_ino}
        for p,kind in ((private,'file'),(state,'directory'))]
    manifest=dict(kind='rover',credential_root_identity={'device':info.st_dev,'inode':info.st_ino},
        ports={'tcp':5770},instance=1,world='storage-only',model='none',
        processes=[{'name':'sitl','exit_code':None},{'name':'gazebo','exit_code':None}],
        binary_path=str(binary),binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),owned_credential_resources=records)
    path=root/'manifest.json';path.write_text(json.dumps(manifest))
    initialize_receive_floor(root,TEST_KEY,100)
    return path


def owner(path):
    # Storage and MAC are production code; there is deliberately no vehicle.
    with patch.object(OwnedActionSimulation,'assert_alive',lambda _:None):return OwnedActionSimulation(path)


def crash_update(path,point):
    proof=owner(path);original=os.replace
    def replace(*args,**kwargs):
        if point=='before_replace':os.kill(os.getpid(),signal.SIGKILL)
        result=original(*args,**kwargs)
        os.kill(os.getpid(),signal.SIGKILL)
        return result
    with patch('vehicle_autonomy.engine.action.durable.os.replace',replace):
        proof.receive_signing.verify(message(230),system=1,component=1)


class DurableWatermarkTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
        self.path=fixture(self.root);self.proof=owner(self.path)
        self.assertEqual(self.proof.receive_signing.verify(message(101),system=1,component=1),101)
        self.assertEqual(self.floor(),229)
        self.addCleanup(self.cleanup)
    def cleanup(self):
        self.proof.close()
        p=self.root/'receive-signing.private'
        if p.exists():
            with p.open('r+b') as f:f.write(b'\0'*p.stat().st_size);f.flush();os.fsync(f.fileno())
            p.unlink()
        self.directory.cleanup()
    def floor(self):return DurableRecord(self.root/'action-receive-floor',limit=512).read()['floor']
    def restart(self):self.proof.close();self.proof=owner(self.path);return self.proof.receive_signing

    def test_valid_numeric_prefix_short_write_does_not_destroy_prior_floor(self):
        original=os.write
        with patch('vehicle_autonomy.engine.action.durable.os.write',side_effect=lambda fd,data:original(fd,data[:2])):
            with self.assertRaises(OSError):self.proof.receive_signing.verify(message(230),system=1,component=1)
        self.assertEqual(self.floor(),229)
        with self.assertRaises(OSError):self.proof.receive_signing.verify(message(500),system=1,component=1)
        receiver=self.restart()
        self.assertIsNone(receiver.verify(message(101),system=1,component=1))
        self.assertEqual(receiver.verify(message(230),system=1,component=1),230)

    def test_write_and_fsync_exception_do_not_admit_unpersisted_evidence(self):
        for operation in ('write','fsync','replace'):
            with self.subTest(operation=operation):
                receiver=self.restart();stamp=self.floor()+1
                before=receiver.accepted
                with patch('vehicle_autonomy.engine.action.durable.os.'+operation,side_effect=OSError('injected storage error')):
                    with self.assertRaises(OSError):receiver.verify(message(stamp),system=1,component=1)
                self.assertEqual(receiver.accepted,before)
                restarted=self.restart()
                self.assertIsNone(restarted.verify(message(101),system=1,component=1))
                self.assertIsNotNone(restarted.verify(message(self.floor()+1),system=1,component=1))

    def test_process_death_before_and_after_atomic_replace_keeps_replays_rejected(self):
        for point in ('before_replace','after_replace'):
            with self.subTest(point=point):
                self.proof.close()
                child=multiprocessing.get_context('fork').Process(target=crash_update,args=(self.path,point))
                child.start();child.join(3)
                self.assertEqual(child.exitcode,-signal.SIGKILL)
                receiver=self.restart()
                self.assertGreaterEqual(receiver.watermark,229)
                self.assertIsNone(receiver.verify(message(101),system=1,component=1))
                self.assertIsNotNone(receiver.verify(message(self.floor()+1),system=1,component=1))
                # Next crash must exercise an update above the current reservation.
                # Use a separate fresh fixture for the second crash point.
                if point=='before_replace':
                    self.cleanup()
                    self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
                    self.path=fixture(self.root);self.proof=owner(self.path)
                    self.proof.receive_signing.verify(message(101),system=1,component=1)

    def test_missing_truncated_corrupt_and_invalid_formats_fail_closed(self):
        good=(self.root/'action-receive-floor').read_bytes();self.proof.close()
        for raw in (None,b'',b'35',good[:15],good.replace(b'229',b'100'),b'{"floor":229}',b'NaN'):
            with self.subTest(kind='missing' if raw is None else str(len(raw))):
                p=self.root/'action-receive-floor'
                if p.exists():p.unlink()
                if raw is not None:
                    with os.fdopen(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:f.write(raw)
                with self.assertRaises(ValueError):owner(self.path)
                with self.assertRaises(ValueError):initialize_receive_floor(self.root,TEST_KEY,100)
        p=self.root/'action-receive-floor';p.unlink();p.write_bytes(good);p.chmod(0o600)
        self.proof=owner(self.path)
        self.assertIsNone(self.proof.receive_signing.verify(message(101),system=1,component=1))
        self.assertIsNotNone(self.proof.receive_signing.verify(message(500),system=1,component=1))

    def test_timestamp_regression_and_different_epoch_are_rejected(self):
        self.assertIsNone(self.proof.receive_signing.verify(message(99),system=1,component=1))
        with self.assertRaises(ValueError):self.proof._persist(100)
        self.proof.close()
        store=DurableRecord(self.root/'action-receive-floor',limit=512)
        # A valid checksum cannot make a different signing epoch trusted.
        store.write({'floor':500,'epoch':'wrong-epoch'})
        with self.assertRaises(ValueError):owner(self.path)
