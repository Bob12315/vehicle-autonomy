"""Persistent anchors and the explicit, noncontrolling SLAM candidate boundary."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from contracts.core.geometry import Vector3
from contracts.core.quality import QualityState
from guidance.path_following import PlanarBinding
from integrations.ros2.run import boundary_overlay
from localization.slam_candidate import SlamCandidateAudit
from mapping.anchors import MapAnchor
from mapping.grid import pose_to_json
from tests import test_path_following as helpers


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.h=helpers.NavigationTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.context=self.h.supervisor.context;self.now=self.h.now
        self.vehicle=replace(self.h.world.vehicle,operation=replace(self.h.world.vehicle.operation,armed=False))
        self.home=SimpleNamespace(position=Vector3(0,0,0))
        self.environment=SimpleNamespace(resource_id='test.environment',content_hash='a'*64,
            frame_epoch=self.context.frame_epoch,home_name='HOME',home=lambda:self.home,validate_origin=lambda v:None)
        self.binding=PlanarBinding(0,0,0)
        self.health={'valid':True,'source_epoch':str(self.context.reference.version.generation_id),
            'frame_epoch':str(self.context.frame_epoch),'frame':'map','revision':self.context.reference.version.revision,
            'captured_ns':self.context.captured_at.monotonic_ns,
            'odom_in_map':pose_to_json(helpers.IDENTITY),'base_link_in_map':pose_to_json(helpers.IDENTITY)}

    def anchor(self):
        return MapAnchor.create(self.environment,self.context,self.binding,self.now,self.vehicle,
            system_send=False,action_send=False)

    def test_anchor_roundtrip_preserves_coordinates_and_requires_explicit_epoch_binding(self):
        anchor=self.anchor();path=Path(self.h.directory.name)/'anchor.json';anchor.save(path)
        self.assertEqual(MapAnchor.load(path),anchor)
        anchor.check(self.environment,self.context,self.binding,self.now)
        for context in (replace(self.context,frame_epoch='new-session'),
                replace(self.context,reference=replace(self.context.reference,version=replace(self.context.reference.version,generation_id='new-publisher')))):
            with self.assertRaises(ValueError):anchor.check(self.environment,context,self.binding,self.now)
        self.home.position=Vector3(1,0,0)
        with self.assertRaises(ValueError):anchor.check(self.environment,self.context,self.binding,self.now)

    def test_registration_cannot_bind_a_moving_authorized_or_unverified_vehicle(self):
        for flags in ({'system_send':True,'action_send':False},{'system_send':False,'action_send':True}):
            with self.assertRaises(ValueError):MapAnchor.create(self.environment,self.context,self.binding,self.now,self.vehicle,**flags)
        with self.assertRaises(ValueError):self.anchor().check(self.environment,self.context,PlanarBinding(.2,0,0),self.now)
        self.environment.validate_origin=lambda v:(_ for _ in ()).throw(ValueError('origin changed'))
        with self.assertRaises(ValueError):self.anchor()

    def test_slam_candidate_retains_source_time_has_no_control_authority_and_rejects_switch(self):
        audit=SlamCandidateAudit();audit.update(self.context,self.health,self.now,self.context.frame_epoch)
        self.assertIsNone(audit.error);self.assertEqual(audit.candidate.captured_at,self.context.captured_at)
        self.assertEqual(audit.candidate.quality,QualityState.VALID)
        later=replace(self.now,monotonic_ns=self.now.monotonic_ns+1_000_000_000)
        audit.update(self.context,self.health,later,self.context.frame_epoch)
        self.assertEqual(audit.candidate.quality,QualityState.DEGRADED)
        self.assertFalse(audit.view(later)['control_eligible'])
        context=replace(self.context,reference=replace(self.context.reference,version=replace(self.context.reference.version,generation_id='new')))
        audit.update(context,{**self.health,'source_epoch':'new'},later,context.frame_epoch)
        self.assertTrue(audit.latched);self.assertIsNone(audit.candidate)
        with self.assertRaises(ValueError):audit.reset(armed=True,system_send=False,action_send=False)
        audit.reset(armed=False,system_send=False,action_send=False)
        audit.update(context,{**self.health,'source_epoch':'new'},later,context.frame_epoch)
        self.assertIsNone(audit.error)

    def test_candidate_jump_clock_and_stale_data_are_rejected(self):
        audit=SlamCandidateAudit();audit.update(self.context,self.health,self.now,self.context.frame_epoch)
        jump=pose_to_json(replace(helpers.IDENTITY,position=Vector3(.3,0,0)))
        audit.update(self.context,{**self.health,'odom_in_map':jump},self.now,self.context.frame_epoch)
        self.assertTrue(audit.latched);self.assertIn('relocalization',audit.error)
        for now in (replace(self.now,monotonic_ns=self.now.monotonic_ns-1),
                    replace(self.now,monotonic_ns=self.now.monotonic_ns+3_000_000_000),replace(self.now,clock_domain_id='other')):
            audit=SlamCandidateAudit();audit.update(self.context,self.health,now,self.context.frame_epoch)
            self.assertIsNone(audit.candidate);self.assertIsNotNone(audit.error)

    def test_native_overlay_refuses_changed_library_or_runtime_abi(self):
        directory=Path(self.h.directory.name);prefix=directory/'ros';(prefix/'lib').mkdir(parents=True)
        files={name:prefix/'lib'/name for name in ('libtoolbox_common.so','libkartoSlamToolbox.so')}
        for p in files.values():p.write_bytes(b'base')
        library=directory/'overlay.so';library.write_bytes(b'overlay')
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        manifest={'schema':1,'upstream_version':'2.8.5','library_sha256':sha(library),
            'runtime_libraries':{k:sha(v) for k,v in files.items()}}
        (directory/'manifest.json').write_text(json.dumps(manifest))
        self.assertEqual(boundary_overlay(prefix,library),str(library))
        next(iter(files.values())).write_bytes(b'changed')
        with self.assertRaises(ValueError):boundary_overlay(prefix,library)

    def test_map_goal_binds_saved_coordinates_and_rejects_anchor_mutation(self):
        from tests.test_goal_navigation import GoalTests,Job
        from application.navigation_goals import GoalCatalog
        from deployment.goal_navigation import GoalNavigation
        helper=GoalTests();helper.setUp();self.addCleanup(helper.doCleanups)
        env=helper.app.environment
        env.content_hash='a'*64;env.frame_epoch=helper.app.vehicle.world_epoch;env.home_name='HOME'
        env.home=lambda:SimpleNamespace(position=Vector3(0,0,0))
        env.validate_origin=lambda state:None
        nav=helper.app.navigation;nav.binding=PlanarBinding(.1,0,0)
        anchor=MapAnchor.create(env,nav.context,nav.binding,helper.helper.now,helper.helper.world.vehicle,
            system_send=False,action_send=False)
        path=helper.directory/'anchor.json';anchor.save(path)
        helper.path.write_text(helper.path.read_text().replace('[[goals]]',f'anchor_path="{path}"\n[[goals]]').replace('frame="odom"','frame="map"'))
        helper.app.navigation_goals=GoalCatalog(helper.path)
        task=GoalNavigation(helper.app,'A',job_factory=Job)
        self.assertAlmostEqual(task.destination.x,.6)
        self.assertAlmostEqual(task.job.value.request.goal.x,.7)
        path.write_text(path.read_text()+'\n')
        task.job.done=True;task.tick(helper.app)
        self.assertEqual(task.status,'FAILED');self.assertIn('anchor_changed',task.error)
        self.assertIsNone(helper.child)
