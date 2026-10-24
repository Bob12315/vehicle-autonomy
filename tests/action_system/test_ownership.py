"""OS ownership exclusion and durable anti-replay progress without credentials."""
import fcntl
import os
from pathlib import Path
import tempfile
import unittest

from pymavlink.dialects.v20 import ardupilotmega as mav
from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation,_DurableSigning
from tests.mavlink_fixture import TEST_KEY,pack


class OwnershipTests(unittest.TestCase):
    def test_same_fixture_has_one_cross_process_style_owner_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            proof=OwnedActionSimulation.__new__(OwnedActionSimulation);proof.root=Path(directory)
            one,_=proof._owned_file('action-owner.lock');two,_=proof._owned_file('action-owner.lock')
            try:
                fcntl.flock(one,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):fcntl.flock(two,fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(one,fcntl.LOCK_UN);fcntl.flock(two,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally:os.close(one);os.close(two)
    def test_owned_epoch_files_reject_symlinks_hardlinks_and_public_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);proof=OwnedActionSimulation.__new__(OwnedActionSimulation);proof.root=root
            target=root/'other';target.write_text('untouched')
            (root/'symlink').symlink_to(target);os.link(target,root/'hardlink')
            for name in ('symlink','hardlink','other'):
                with self.assertRaises((ValueError,OSError)):proof._owned_file(name)
            self.assertEqual(target.read_text(),'untouched')
    def test_receive_progress_is_durable_before_acceptance_and_survives_new_receiver(self):
        with tempfile.TemporaryDirectory() as directory:
            proof=OwnedActionSimulation.__new__(OwnedActionSimulation);proof.root=Path(directory)
            proof._floorfd,_=proof._owned_file('action-receive-floor');proof._lockfd=None
            try:
                proof._persist(0);receiver=_DurableSigning(TEST_KEY,initial_timestamp=0,persist=proof._persist)
                sender=mav.MAVLink(None,srcSystem=1,srcComponent=1)
                raw=pack(sender.heartbeat_encode(2,3,0,4,3),sender);message=mav.MAVLink(None).parse_buffer(raw)[0]
                stamp=receiver.verify(message,system=1,component=1)
                floor=int((proof.root/'action-receive-floor').read_text());self.assertGreaterEqual(floor,stamp)
                self.assertLessEqual(floor-stamp,128)
                restarted=_DurableSigning(TEST_KEY,initial_timestamp=floor,persist=proof._persist)
                self.assertIsNone(restarted.verify(message,system=1,component=1))
                self.assertEqual(restarted.rejected['replay'],1)
                following=mav.MAVLink(None).parse_buffer(pack(sender.heartbeat_encode(2,3,0,4,3),sender))[0]
                self.assertIsNotNone(receiver.verify(following,system=1,component=1))
                self.assertEqual(int((proof.root/'action-receive-floor').read_text()),floor)
            finally:proof.close()
    def test_persistence_failure_cannot_return_verified_evidence(self):
        receiver=_DurableSigning(TEST_KEY,initial_timestamp=0,persist=lambda _:(_ for _ in ()).throw(OSError('full')))
        sender=mav.MAVLink(None,srcSystem=1,srcComponent=1)
        message=mav.MAVLink(None).parse_buffer(pack(sender.heartbeat_encode(2,3,0,4,3),sender))[0]
        with self.assertRaises(OSError):receiver.verify(message,system=1,component=1)


if __name__=='__main__':unittest.main()
