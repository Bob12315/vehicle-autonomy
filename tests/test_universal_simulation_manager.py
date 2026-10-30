"""Offline multi-vehicle lifecycle regressions; no native processes are run."""
from pathlib import Path
import tempfile
from threading import Event, RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from vehicle_autonomy.app.simulation.manager import SimulationManager
from vehicle_autonomy.app.simulation.universal_runtime import LocalRuntime


class _Clock:
    def elapsed_ns_since(self, point):
        return 1_000_000_000 - point


class _Child:
    def __init__(self, identifier):
        self.id = identifier
        self.target = 'target-' + identifier
        self.slot_id = 'slot-' + identifier
        self.vehicle = 'rover'
        self.spawn = dict(x=0, y=0, z=0, heading_deg=0, preset_id='center')
        self.state = 'RUNNING'
        self.stages = dict(plugin_connected=True, framework_controlled=True)
        self.info = dict(connected=True, owned_simulation=True, fault=None)
        self.vehicle_state = SimpleNamespace(
            health=SimpleNamespace(quality=SimpleNamespace(value='VALID')),
            operation=SimpleNamespace(armed=False), published_at=1_000_000_000,
            reported_pose=SimpleNamespace(captured_at=1_000_000_000,
                value=SimpleNamespace(position=SimpleNamespace(z=0))),
            reported_twist=SimpleNamespace(captured_at=1_000_000_000,
                value=SimpleNamespace(linear=SimpleNamespace(x=0,y=0,z=0))))
        self.driver = SimpleNamespace(
            set_retiring=Mock(), clock=lambda: _Clock(),
            read_view=lambda: (self.info, SimpleNamespace(vehicle=self.vehicle_state)),
            info=lambda: self.info)
        self.proof = self.link = self.model = None

    def view(self):
        return dict(id=self.id, target=self.target, slot_id=self.slot_id,
            kind=self.vehicle, state=self.state, spawn=self.spawn,
            stages=dict(self.stages), logs={'sitl': self.id+'/sitl.log'})


class UniversalManagerContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = SimulationManager(Path(self.temp.name)/'sessions')
        value = self.manager.create({'scene_id': 'R01'})
        self.identifier = value['id']
        self.record = self.manager.records[self.identifier]
        self.manager.stops[self.identifier] = Event()

    def tearDown(self):
        self.manager.application = None
        self.manager.close()
        self.temp.cleanup()

    def _running_owner(self, count=1):
        children = [_Child(str(index)) for index in range(count)]
        owner = SimpleNamespace(vehicles={child.id:child for child in children},
            retired=[], driver=children[0].driver, target=children[0].target,
            link=None, closed=False, world='offline-world', _state_lock=RLock())
        def close():
            owner.closed = True
            for child in children:
                child.info['connected'] = False
                child.state = 'FINISHED'
        owner.close = close
        owner.truth = lambda identifier=None: {'source':'offline-fixture'}
        for child in children:
            child.owner = owner
        self.manager.owners[self.identifier] = owner
        self.record.update(state='RUNNING',vehicles=[child.view() for child in children],
            vehicle='rover',target=children[0].target)
        return owner, children

    def test_failed_remove_dispatch_signals_stop_before_any_worker_exists(self):
        owner, children = self._running_owner()
        with patch.object(self.manager, '_save', side_effect=OSError('disk unavailable')), \
                patch('vehicle_autonomy.app.simulation.manager.Thread') as thread:
            with self.assertRaises(OSError):
                self.manager.handle('simulation.remove_vehicle',
                    {'id':self.identifier,'vehicle_id':children[0].id})
        thread.assert_not_called()
        self.assertTrue(self.manager.stops[self.identifier].is_set())
        self.assertEqual('FAILED',self.record['state'])
        self.assertIn('persistence',self.record['failure_domain'])
        children[0].driver.set_retiring.assert_called_with(True)
        self.assertNotIn(self.identifier,self.manager.operation_threads)
        self.assertFalse(owner.closed)

    def test_failed_switch_dispatch_stops_old_world_without_starting_new_epoch(self):
        owner, children = self._running_owner()
        save = self.manager._save
        def save_destination_only(record):
            if record['id'] == self.identifier:
                raise OSError('old World report unavailable')
            save(record)
        with patch.object(self.manager, '_save', side_effect=save_destination_only), \
                patch('vehicle_autonomy.app.simulation.manager.Thread') as thread:
            with self.assertRaises(OSError):
                self.manager.handle('simulation.switch',{'id':self.identifier,'scene_id':'R04'})
        thread.assert_not_called()
        self.assertTrue(self.manager.stops[self.identifier].is_set())
        self.assertEqual('FAILED',self.record['state'])
        self.assertEqual(2,len(self.manager.records))
        destination = next(record for identifier,record in self.manager.records.items() if identifier != self.identifier)
        self.assertEqual('CANCELLED',destination['state'])
        self.assertNotIn(destination['id'],self.manager.owners)
        self.assertFalse(owner.closed)

    def test_nonfirst_expired_vehicle_fails_world_and_cleans_both_children(self):
        owner, children = self._running_owner(2)
        owner.start = lambda *args: None
        samples = []
        def sample():
            samples.append(True)
            if len(samples) > 1:
                children[1].vehicle_state.reported_pose.captured_at = -4_000_000_000
            return dict(error_lines=[],metrics={'sim_seconds':len(samples)})
        owner.sample = sample
        reply = SimpleNamespace(returncode=0,stdout='',stderr='')
        with patch('vehicle_autonomy.app.simulation.manager.LocalRuntime',return_value=owner), \
                patch('vehicle_autonomy.app.simulation.manager.subprocess.run',return_value=reply), \
                patch('vehicle_autonomy.app.simulation.manager.HostEnvironment.available',return_value=True), \
                patch('vehicle_autonomy.app.simulation.manager.to_json_value',return_value={'fixture':True}):
            self.manager._run(self.identifier)
        self.assertEqual(2,len(samples))
        self.assertEqual('FAILED',self.record['state'])
        self.assertEqual('framework',self.record['failure_domain'])
        self.assertEqual('COMPLETE',self.record['cleanup'])
        self.assertTrue(owner.closed)
        self.assertTrue(all(not child.info['connected'] for child in children))

    def test_old_unresolved_safety_barrier_is_not_hidden_by_display_limit(self):
        _, children = self._running_owner()
        child = children[0]
        actions = [dict(id='unresolved',target=child.target,state='UNKNOWN',safety={'release_safe':False})]
        actions.extend(dict(id='query-'+str(index),target=child.target,state='SUCCEEDED',safety={'release_safe':True}) for index in range(64))
        self.manager.application = SimpleNamespace(_control_lock=RLock(),
            runtime=SimpleNamespace(views=lambda:actions), missions=SimpleNamespace(views=lambda:[]))
        # Reports may stay bounded, but epoch retirement must inspect every
        # unresolved execution barrier, including the 65th-most-recent Action.
        with self.assertRaisesRegex(ValueError,'safety barrier'):
            self.manager._require_safe(child)


class UniversalRuntimeRollbackContracts(unittest.TestCase):
    def _runtime(self):
        runtime = LocalRuntime.__new__(LocalRuntime)
        runtime._state_lock = RLock()
        first = _Child('existing')
        runtime.vehicles = {first.id:first}
        runtime.retired = []
        runtime.directory = Path('/offline/no-files-created')
        runtime._aliases()
        return runtime, first

    def test_world_only_sampling_does_not_wait_for_nonexistent_dynamic_pose_topic(self):
        runtime=LocalRuntime.__new__(LocalRuntime)
        runtime._state_lock=RLock();runtime.vehicles={}
        with patch('vehicle_autonomy.app.simulation.runtime.LocalRuntime.sample',return_value={'metrics':{'sim_seconds':1}}), \
                patch('vehicle_autonomy.app.simulation.universal_runtime.subprocess.run') as run:
            self.assertEqual([],runtime.sample()['vehicles'])
        run.assert_not_called()

    def test_prepare_failure_rolls_back_only_new_child(self):
        runtime, existing = self._runtime()
        failed = _Child('new-failure')
        failed.start = Mock(side_effect=OSError('immutable model preparation failed'))
        failed.close = Mock()
        with patch('vehicle_autonomy.app.simulation.universal_runtime.VehicleInstance',return_value=failed):
            with self.assertRaisesRegex(OSError,'model preparation'):
                runtime.add({'kind':'rover','slot_id':'new','spawn':{}})
        failed.close.assert_called_once_with()
        self.assertEqual({existing.id},set(runtime.vehicles))
        self.assertIs(existing.driver,runtime.driver)
        self.assertEqual('FAILED',runtime.retired[0]['state'])

    def test_unconfirmed_partial_model_cleanup_retains_ownership_for_world_shutdown(self):
        runtime, existing = self._runtime()
        failed = _Child('unremoved')
        failed.start = Mock(side_effect=OSError('plugin startup failed'))
        failed.close = Mock(side_effect=RuntimeError('entity remove unconfirmed'))
        with patch('vehicle_autonomy.app.simulation.universal_runtime.VehicleInstance',return_value=failed):
            with self.assertRaisesRegex(OSError,'plugin startup'):
                runtime.add({'kind':'rover','slot_id':'new','spawn':{}})
        self.assertEqual({existing.id,failed.id},set(runtime.vehicles))
        self.assertEqual('FAILED',failed.state)
        self.assertEqual([],runtime.retired)


if __name__ == '__main__':
    unittest.main()
