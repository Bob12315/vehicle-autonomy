"""Lifecycle/authentication contracts; native acceptance lives in tests/control_center."""
import json
import os
from pathlib import Path
import tempfile
from threading import Event,RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from vehicle_autonomy.app.control_center.registry import configuration,definitions
from vehicle_autonomy.app.control_center.service import ControlCenter
from vehicle_autonomy.app.control_center.desktop import diagnostic
from vehicle_autonomy.app.control_center.supervisor import service_command,unit_name,lock_workspace
from tests.web_ui.helpers import Harness

ROOT=Path(__file__).resolve().parents[1]


class SupervisorContracts(unittest.TestCase):
    def test_launcher_defaults_to_owned_simulation_authorization_with_read_only_override(self):
        from vehicle_autonomy.app.control_center.launcher import parse_args
        self.assertTrue(parse_args([]).allow_send)
        self.assertTrue(parse_args(['--allow-send']).allow_send)
        self.assertFalse(parse_args(['--read-only']).allow_send)
        with patch('sys.stderr'),self.assertRaises(SystemExit):parse_args(['--read-only','--allow-send'])

    def test_kernel_cleanup_boundary_and_no_restart(self):
        command=service_command(ROOT,Path('/tmp/center-evidence'),[],123,'456')
        for argument in ('--property=KillMode=mixed','--property=ExitType=main','--property=SendSIGKILL=yes','--property=Restart=no'):
            self.assertIn(argument,command)
        self.assertFalse(any('xdg-open' in part for part in command))
        self.assertEqual(unit_name(ROOT),unit_name(ROOT/'.'))
        self.assertNotEqual(unit_name(ROOT),unit_name(ROOT/'another'))

    def test_workspace_lock_does_not_adopt_other_processes(self):
        with tempfile.TemporaryDirectory() as root:
            handle=lock_workspace(root,'backend')
            try:
                with self.assertRaisesRegex(ValueError,'已在运行'):lock_workspace(root,'backend')
            finally:handle.close()
            lock_workspace(root,'backend').close()

    def test_no_desktop_does_not_claim_gui(self):
        result=diagnostic({})
        self.assertFalse(result['available']);self.assertIn('DISPLAY',result['error'])
        self.assertFalse(diagnostic({'DISPLAY':':1','QT_QPA_PLATFORM':'offscreen'})['available'])

    def test_local_configuration_is_bounded_and_not_shell(self):
        base=configuration(ROOT)
        self.assertEqual(set(base['tools']),{'rviz2','gazebo-gui','qgroundcontrol'})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            for change in ('extra-tool','relative-executable','invalid-env'):
                data=json.loads(json.dumps(base))
                if change=='extra-tool':data['tools']['shell']={}
                elif change=='relative-executable':data['tools']['rviz2']['executable']='sh'
                else:data['tools']['rviz2']['env']={'invalid-key':'x'}
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):configuration(ROOT,path)

    def test_stale_epoch_and_arbitrary_commands_rejected_before_launch(self):
        center=object.__new__(ControlCenter);center.session_id='current';center.stop=Event();center.closed=Event();center.lock=RLock();center.worker=None
        for payload in (dict(session_id='old',action='start',tool_id='rviz2'),
                dict(session_id='current',action='start',tool_id='shell'),
                dict(session_id='current',action='start',tool_id='rviz2',argv=['sh'])):
            with self.assertRaises(ValueError):center.handle('center.tool',payload)
        self.assertFalse(center.stop.is_set())
        with self.assertRaises(ValueError):center.handle('center.shutdown',dict(session_id='old'))

    def test_qgc_settings_are_project_owned_and_keep_unrelated_settings(self):
        center=object.__new__(ControlCenter);center.root=ROOT;center.host={'config':{'qgc_port':14550}}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'QGroundControl.ini';path.write_text('[UserPreference]\nexample=keep\n')
            center._qgc_config(path)
            value=path.read_text();self.assertIn('example=keep',value)
            self.assertIn('autoConnectPixhawk=false',value);self.assertIn('udpListenPort=14550',value)
            self.assertFalse(path.with_suffix('.tmp').exists())


    def test_poststop_removes_only_inode_registered_credentials_and_marks_unknown(self):
        from vehicle_autonomy.app.control_center.finalize import finalize
        from vehicle_autonomy.app.bootstrap.simulation_credentials import OwnedCredentials
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);directory=root/'runtime/control-center/cc-test'
            vehicle=directory/'application/simulation/sim-test/vehicle-test';vehicle.mkdir(parents=True)
            value={'framework_runtime':True};owner=OwnedCredentials(vehicle,value)
            sitl=owner.create_state('');(sitl/'eeprom.bin').write_bytes(b'local-test')
            key=vehicle/'receive-signing.private';fd=os.open(key,os.O_CREAT|os.O_WRONLY,0o600)
            owner.register_private(key.name,fd);os.close(fd)
            (vehicle/'session.json').write_text(json.dumps(value))
            state={'state':'READY','session_id':'current','cgroup':'/owned-test'}
            (directory/'state.json').write_text(json.dumps(state))
            (directory.parent/'current.json').write_text(json.dumps(state))
            unowned=root/'unowned.private';unowned.write_text('keep')
            with patch('vehicle_autonomy.app.control_center.finalize.process_table',return_value=[]):finalize(root,directory)
            self.assertFalse(key.exists());self.assertFalse(sitl.exists());self.assertEqual(unowned.read_text(),'keep')
            closed=json.loads((directory/'state.json').read_text());self.assertEqual(closed['state'],'CRASHED')
            self.assertEqual(closed['physical_stop'],'UNCONFIRMED');self.assertEqual(closed['os_cleanup']['credential_errors'],[])

    def test_poststop_never_destroys_resources_while_members_remain(self):
        from vehicle_autonomy.app.control_center.finalize import finalize
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);directory=root/'runtime/control-center/cc-test';directory.mkdir(parents=True)
            state={'state':'READY','session_id':'current','cgroup':'/owned-test'}
            (directory/'state.json').write_text(json.dumps(state));feed=directory/'visualization.private';feed.write_text('keep')
            with patch('vehicle_autonomy.app.control_center.finalize.process_table',return_value=[dict(pid=os.getpid()+1)]):finalize(root,directory)
            self.assertTrue(feed.exists())
            self.assertTrue(json.loads((directory/'os-cleanup.json').read_text())['remaining_owned_processes'])


class CenterWebContracts(unittest.TestCase):
    def setUp(self):
        self.h=Harness(kinds=('rover','copter'));self.addCleanup(self.h.close)
        self.a=self.h.client();self.a.login();self.b=self.h.client();self.b.login()
        self.center=SimpleNamespace(handle=Mock(return_value={'accepted':True}),session_id='epoch',stop=Event())
        self.h.lab.control_center=self.center

    def test_existing_auth_csrf_and_origin_protect_shutdown_and_tools(self):
        anonymous=self.h.client()
        self.assertEqual(anonymous.call('/api/center/state')[0],401)
        self.assertEqual(self.a.call('/center')[0],200)
        self.assertEqual(self.a.call('/api/center/state')[0],200)
        for route in ('tool','shutdown','logs'):
            path='/api/center/'+route
            self.assertEqual(self.a.call(path,{},headers={'X-VAF-CSRF':''})[0],403)
            self.assertEqual(self.a.call(path,{},headers={'Origin':'http://evil.invalid'})[0],403)
        self.assertFalse(any(d.writes for d in self.h.drivers.values()))

    def test_console_shutdown_cannot_bypass_another_vehicle_owner(self):
        self.a.acquire('rover');self.b.acquire('copter');self.center.handle.reset_mock()
        payload=dict(session_id='epoch')
        self.assertEqual(self.a.call('/api/center/shutdown',payload)[0],409)
        self.assertEqual(self.b.call('/api/center/shutdown',payload)[0],409)
        self.center.handle.assert_not_called()
        self.a.call('/api/control/release',{'target':'rover'});self.b.call('/api/control/release',{'target':'copter'})
        self.assertEqual(self.a.call('/api/center/shutdown',payload)[0],200)
        self.center.handle.assert_called_once_with('center.shutdown',payload)
        self.assertFalse(any(d.writes for d in self.h.drivers.values()))

    def test_existing_rviz_entry_uses_same_local_tool_owner(self):
        self.assertEqual(self.a.call('/api/visualization/open',dict(target='copter'))[0],200)
        self.center.handle.assert_called_once_with('center.tool',dict(session_id='epoch',tool_id='rviz2',action='start',target='copter'))
