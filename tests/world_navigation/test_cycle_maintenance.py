import unittest
from unittest.mock import patch

from vehicle_autonomy.app.bootstrap.cycle_maintenance import CycleMaintenance


class CycleMaintenanceTests(unittest.TestCase):
    def test_preserves_disabled_or_not_due_automatic_policy(self):
        for enabled, count, threshold in ((False, 99, 10), (True, 0, 10), (True, 99, 0)):
            with self.subTest(enabled=enabled, count=count, threshold=threshold):
                with patch('gc.isenabled', return_value=enabled), patch('gc.get_count', return_value=(0,0,count)), patch('gc.get_threshold', return_value=(700,10,threshold)), patch('gc.collect') as collect, patch('gc.disable') as disable, patch('gc.set_threshold') as change:
                    CycleMaintenance().run()
                    collect.assert_not_called();disable.assert_not_called();change.assert_not_called()

    def test_collection_exception_does_not_leave_maintenance_lock_held(self):
        with patch('gc.isenabled', return_value=True), patch('gc.get_count', return_value=(0,0,5)), patch('gc.get_threshold', return_value=(700,10,10)):
            item=CycleMaintenance()
            with patch('gc.collect', side_effect=RuntimeError('injected')):
                with self.assertRaises(RuntimeError):item.run()
            with patch('gc.collect') as collect:
                item.run();collect.assert_called_once_with(2)
            self.assertEqual(item.collections,1)

    def test_delayed_maintenance_cannot_make_expired_writer_request_valid(self):
        from tests import test_p5_mavlink as fixtures
        from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
        f=fixtures.P5MavlinkTests();f.setUp();f.connect()
        old=f.execution.dispatch(fixtures.effect(1,ArmEffect()),fixtures.world(),fixtures.at(100)).receipt
        def collect(_):f.now_ns=181
        with patch('gc.isenabled', return_value=True), patch('gc.get_count', return_value=(0,0,5)), patch('gc.get_threshold', return_value=(700,10,10)), patch('gc.collect',side_effect=collect):
            CycleMaintenance().run()
        # The original old caller time cannot survive maintenance. The real
        # writer samples its own current clock and performs no transport call.
        f.port.write_next(fixtures.at(100))
        self.assertEqual(f.port.status(old.command_id).phase.value,'REJECTED')
        self.assertEqual(f.transport.attempts,[])
        fresh=f.execution.dispatch(fixtures.effect(2,ArmEffect(),deadline=199),fixtures.world(),fixtures.at(181)).receipt
        self.assertIsNotNone(fresh)
        f.port.write_next(fixtures.at(181))
        self.assertEqual(len(f.transport.attempts),1)
        self.assertEqual(f.port.status(fresh.command_id).phase.value,'TRANSMITTED')
