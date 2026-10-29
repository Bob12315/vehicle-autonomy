"""Offline safety/lifecycle contracts, distinct from native Gazebo acceptance."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vehicle_autonomy.app.simulation.manager import SimulationManager
from vehicle_autonomy.app.simulation.faults import FaultSettings, SoftwareFaultLink
from vehicle_autonomy.app.simulation.runtime import duration, number
from vehicle_autonomy.app.bootstrap.qgc_simulation import Session


class ByteFixture:
    def __init__(self):self.reads=[b'one',b'two',b'three'];self.writes=[];self.closed=False
    def read(self,max_bytes=4096):return self.reads.pop(0) if self.reads else None
    def write(self,data):self.writes.append(data)
    def close(self):self.closed=True


class ManagerContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.manager=SimulationManager(Path(self.temp.name)/'sessions')

    def tearDown(self):
        self.manager.close();self.temp.cleanup()

    def test_creation_generates_replayable_world_without_processes(self):
        record=self.manager.create(dict(scene_id='R01',seed=12))
        self.assertEqual(record['state'],'CREATED')
        self.assertEqual(record['levels']['L4'],'NOT_TESTED')
        self.assertEqual(self.manager.owners,{})
        self.assertTrue((self.manager.directory/record['id']/'scenario.sdf').is_file())
        self.assertFalse(self.manager.allow_send)

    def test_unsupported_pair_does_not_create_session(self):
        with self.assertRaisesRegex(ValueError,'BLOCKED'):
            self.manager.create(dict(scene_id='R02',vehicle='rover'))
        self.assertEqual(self.manager.records,{})

    def test_browser_paths_commands_and_deployment_send_are_rejected(self):
        for extra in ('path','command','argv','allow_send','instance','system_id'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.manager.create(dict(scene_id='R01',**{extra:'x'}))

    def test_seed_and_scene_validation(self):
        for seed in (-1,2**32,False,float('nan')):
            with self.subTest(seed=seed),self.assertRaises(ValueError):
                self.manager.create(dict(scene_id='R01',seed=seed))
        with self.assertRaises(ValueError):self.manager.create(dict(scene_id='../R01'))

    def test_unknown_environment_parameter_cleans_directory(self):
        with self.assertRaises(ValueError):
            self.manager.create(dict(scene_id='R01',parameters={'shell':'touch /tmp/no'}))
        self.assertEqual([p.name for p in self.manager.directory.iterdir()],['owner.lock'])

    def test_stop_before_start_cancels_without_process(self):
        record=self.manager.create(dict(scene_id='R01'))
        closed=self.manager.stop(record['id'])
        self.assertEqual(closed['state'],'CANCELLED')
        self.assertEqual(closed['cleanup'],'COMPLETE')
        with self.assertRaises(ValueError):self.manager.start(record['id'])

    def test_restart_fences_nonterminal_and_does_not_adopt_processes(self):
        record=self.manager.create(dict(scene_id='R01'))
        self.manager.close()
        # Simulate the nonterminal report left by an exited old owner.
        (self.manager.directory/record['id']/'report.json').write_text(json.dumps(record))
        recovered=SimulationManager(self.manager.directory)
        self.assertEqual(recovered.sample(record['id'])['state'],'FAILED')
        self.assertEqual(recovered.sample(record['id'])['cleanup'],'UNKNOWN')
        self.assertEqual(recovered.owners,{})
        recovered.close()

    def test_second_manager_cannot_rewrite_live_owner_reports(self):
        record=self.manager.create(dict(scene_id='R01'))
        path=self.manager.directory/record['id']/'report.json'
        original=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'live manager'):
            SimulationManager(self.manager.directory)
        self.assertEqual(path.read_bytes(),original)

    def test_stopping_persistence_failure_still_closes_owned_runtime(self):
        record=self.manager.create(dict(scene_id='R01'))
        self.manager.stops[record['id']]=Event()
        owner=SimpleNamespace(driver=None,target='none',closed=False)
        def close():owner.closed=True
        owner.close=close
        owner.start=lambda *a:(_ for _ in ()).throw(RuntimeError('startup failed'))
        save=self.manager._save
        def fail_stopping(item):
            if item['state']=='STOPPING':raise OSError('disk unavailable')
            save(item)
        with patch('vehicle_autonomy.app.simulation.manager.LocalRuntime',return_value=owner), \
                patch('vehicle_autonomy.app.simulation.manager.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')), \
                patch.object(self.manager,'_save',side_effect=fail_stopping):
            self.manager._run(record['id'])
        self.assertTrue(owner.closed)
        result=self.manager.sample(record['id'])
        self.assertEqual((result['state'],result['cleanup']),('FAILED','COMPLETE'))
        self.assertTrue(result['persistence_errors'])

    def test_cancel_during_readiness_sample_never_admits_target(self):
        record=self.manager.create(dict(scene_id='R01'))
        self.manager.stops[record['id']]=Event()
        self.manager.records[record['id']]['state']='STARTING'
        owner=SimpleNamespace(driver=None,target='none',closed=False)
        owner.start=lambda *a:None
        def close():owner.closed=True
        owner.close=close
        def sample():
            self.manager.stop(record['id'])
            return dict(error_lines=[],metrics={'sim_seconds':1})
        owner.sample=sample
        with patch('vehicle_autonomy.app.simulation.manager.LocalRuntime',return_value=owner), \
                patch('vehicle_autonomy.app.simulation.manager.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')), \
                patch.object(self.manager,'_attach') as attach:
            self.manager._run(record['id'])
        attach.assert_not_called()
        self.assertTrue(owner.closed)
        value=self.manager.sample(record['id'])
        self.assertEqual(value['state'],'CANCELLED')
        self.assertFalse({'READY','RUNNING'}&{h['state'] for h in value['history']})

    def test_report_is_a_copy(self):
        record=self.manager.create(dict(scene_id='R01'))
        record['state']='RUNNING'
        self.assertEqual(self.manager.sample(record['id'])['state'],'CREATED')

    def test_log_streams_cannot_escape_session(self):
        record=self.manager.create(dict(scene_id='R01'))
        for stream in ('../../private','receive-signing','manifest','/etc/passwd'):
            with self.subTest(stream=stream), self.assertRaises(ValueError):
                self.manager.handle('simulation.logs',dict(id=record['id'],stream=stream))
        path=self.manager.directory/record['id']/'gazebo.log'
        path.write_text('abcdef')
        value=self.manager.handle('simulation.logs',dict(id=record['id'],offset=2,limit=2))
        self.assertEqual((value['text'],value['next_offset']),('cd',4))

    def test_controls_require_running_owned_session(self):
        record=self.manager.create(dict(scene_id='R01'))
        for operation in ('pause','resume','reset','test'):
            with self.subTest(operation=operation),self.assertRaises(ValueError):
                self.manager.handle('simulation.'+operation,dict(id=record['id']))

    def test_simulation_test_cannot_bypass_browser_control_owner(self):
        record=self.manager.create(dict(scene_id='R01'))
        for payload in (dict(name='Arm'),dict(allow_send=True),dict(parameters={'value':1})):
            with self.subTest(payload=payload),self.assertRaisesRegex(ValueError,'read-only'):
                self.manager.handle('simulation.test',dict(id=record['id'],**payload))

    def test_existing_lifecycle_accepts_world_only_manifest_without_provisioning(self):
        directory=Path(self.temp.name)/'world-only';directory.mkdir()
        manifest=dict(framework_runtime=False,kind='world',world='test',partition='test',
            processes=[],system_id=0,instance=0,ready=False)
        session=Session(directory,{},manifest)
        self.assertIsNone(session.credentials)
        self.assertFalse((directory/'manifest.json').exists())
        session.close()
        saved=json.loads((directory/'session.json').read_text())
        self.assertEqual(saved['remaining_process_groups'],[])

    def test_catalog_distinguishes_candidate_and_adapted(self):
        catalog={r['id']:r for r in self.manager.catalog()}
        self.assertFalse(catalog['R02']['vehicle_support']['rover']['available'])
        self.assertFalse(catalog['F07']['vehicle_support']['vtol']['available'])


class FaultContracts(unittest.TestCase):
    def test_timeout_never_forwards_or_retries_a_write(self):
        source=ByteFixture();link=SoftwareFaultLink(source)
        link.configure(dict(command_timeout=True))
        with self.assertRaises(TimeoutError):link.write(b'command')
        self.assertEqual(source.writes,[])
        link.configure({});link.write(b'fresh')
        self.assertEqual(source.writes,[b'fresh'])

    def test_receive_delay_does_not_delay_writes(self):
        source=ByteFixture();now=[0]
        link=SoftwareFaultLink(source,clock=lambda:now[0])
        link.configure(dict(delay_ms=500))
        self.assertIsNone(link.read())
        link.write(b'now');self.assertEqual(source.writes,[b'now'])
        now[0]=.6;self.assertEqual(link.read(),b'one')

    def test_loss_interruption_freeze_and_recovery(self):
        source=ByteFixture();link=SoftwareFaultLink(source)
        link.configure(dict(loss=1));self.assertIsNone(link.read())
        self.assertEqual(link.dropped,1)
        link.configure(dict(freeze=True));self.assertEqual(link.read(),b'two')
        self.assertEqual(link.read(),b'two')
        link.configure(dict(sensor_interruption=True));self.assertIsNone(link.read())
        link.configure({});self.assertIsNone(link.read())

    def test_unsupported_sensor_fault_and_nonfinite_values_rejected(self):
        for payload in (dict(gps_failure=True),dict(loss=1.1),dict(delay_ms=float('nan')),
                        dict(delay_ms=2001),dict(freeze=1),dict(loss=True)):
            with self.subTest(payload=payload),self.assertRaises(ValueError):FaultSettings.parse(payload)

    def test_duration_parser_and_unavailable_fields(self):
        self.assertEqual(duration('sim_time { sec: 12 nsec: 500000000 }','sim_time'),12.5)
        self.assertIsNone(duration('','sim_time'))
        self.assertIsNone(number('','real_time_factor'))


if __name__=='__main__':unittest.main()
