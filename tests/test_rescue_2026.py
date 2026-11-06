"""Rescue migration contracts, observed-target gates and physical exit requests."""
from dataclasses import replace
import json,math,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.actions.catalog import register_standard,capabilities
from vehicle_autonomy.actions.composite.rescue import (QueryInstance,CaptureParameters,FuseParameters,SelectParameters,
    ConfirmParameters,encode_target,current_target,AlignInstance,AlignParameters,ReleaseFactory,ReleaseParameters,ServoOutput)
from vehicle_autonomy.app.scenarios.cuadc.rescue import template
from vehicle_autonomy.app.simulation.catalog import SceneRegistry
from vehicle_autonomy.app.simulation.world_spawns import WorldSpawnRegistry
from vehicle_autonomy.contracts.action import ActionContext
from vehicle_autonomy.contracts.core.geometry import Vector3,Quaternion,Pose3
from vehicle_autonomy.contracts.core.stamped import Stamped
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.decision import ActionOutcome,ExitReason
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.mission.graph import validate
from vehicle_autonomy.world.model.models import WorldObject
from vehicle_autonomy.world.perception.vision.rescue_geometry import project
from vehicle_autonomy.world.perception.vision.yolox import PixelDetection
from tests import test_basic_actions as basic_tests


class RescueTests(unittest.TestCase):
    def setUp(self):
        self.h=basic_tests.BasicActionTests();self.h.setUp();self.addCleanup(self.h.tearDown)
        self.world=self.h.sample(.1,Vector3(0,32.5,3))
        self.obj=WorldObject('vision.pt:test:bucket1','bucket',Stamped('odom',self.world.published_at,Vector3(0,32.5,.105)),.9,QualityState.VALID,'obs','vision.pt:test')
        self.world=replace(self.world,objects=(self.obj,));self.target=encode_target(self.world,self.obj)
    def registry(self):
        r=ActionRegistry();register_standard(r);return r
    def test_map_preserves_target_geometry_and_has_separate_ground_vehicle_admission(self):
        root=resource_root();source=ET.parse(root/'simulation/models/cuadc2026_field/model.sdf').find('model')
        with tempfile.TemporaryDirectory() as folder:
            world=ET.parse(SceneRegistry().generate('CUADC2026',Path(folder)/'world.sdf')).find('world')
        self.assertFalse(world.findall('include'));self.assertFalse(world.findall('.//plugin[@name="ArduPilotPlugin"]'))
        migrated=world.find("model[@name='cuadc2026_field']")
        for name in ['drop_bucket_1','drop_bucket_2','drop_bucket_3','recon_target_5']:
            a=source.find("link[@name='"+name+"']");b=migrated.find("link[@name='"+name+"']")
            self.assertIsNotNone(a,name)
            self.assertEqual(ET.canonicalize(ET.tostring(a,encoding='unicode'),strip_text=True),
                ET.canonicalize(ET.tostring(b,encoding='unicode'),strip_text=True))
        r=WorldSpawnRegistry();definition=dict(id='fixture',family='copter',radius=.5,clearance_z=.195,height=.4)
        self.assertEqual(r.validate('CUADC2026',definition)['heading_deg'],90)
        with self.assertRaises(ValueError):r.validate('CUADC2026',definition,{'x':0,'y':32.5,'z':.195,'heading_deg':90})
    def test_template_compiles_only_with_explicit_rescue_capabilities(self):
        r=self.registry();definition=template('v')
        ctx=ActionContext('v','copter',capabilities('copter')|{'rescue_flight','rescue_vision','rescue_payload'},True)
        self.assertTrue(validate(definition,r,{'v':SimpleNamespace(context=lambda:ctx)}))
        normal=replace(ctx,capabilities=capabilities('copter'))
        with self.assertRaises(ValueError):validate(definition,r,{'v':SimpleNamespace(context=lambda:normal)})
        nodes={n['node_id']:n for n in definition['nodes']}
        self.assertEqual(nodes['takeoff_4_5m']['parameters']['height_m'],4.5)
        recon=[n['parameters'] for n in definition['nodes'] if n['node_id'].startswith('recon_scan_goto_')]
        self.assertEqual([(p['x_m'],p['y_m'],p['z_m']) for p in recon],[(-3,56,3),(3,56,3),(3,59,3),(-3,59,3)])
        self.assertTrue(all(p['speed_mps']==5 for p in recon))
        self.assertEqual(nodes['goto_drop_center_5m']['parameters']['speed_mps'],10)
        self.assertEqual(nodes['drop_approach']['parameters']['speed_mps'],5)
        self.assertEqual(nodes['select_gps_drop_targets']['parameters'],dict(first_release_target_ey=-.5,second_release_target_ey=.5))
        self.assertEqual(nodes['drop_release']['input_bindings']['release_target_ey'],{'ref':'loop.current_item.release_target_ey'})
        self.assertEqual(json.loads((resource_root()/'simulation/missions/cuadc2026/rescue_2026_full_auto.json').read_text()),template())
    def test_rescue_calibration_rejects_other_spawns_before_starting_a_vehicle(self):
        from vehicle_autonomy.app.simulation.manager import SimulationManager
        manager=SimulationManager.__new__(SimulationManager)
        manager.vehicle_registry=SimpleNamespace(get=lambda _:dict(status='READY',family='copter'))
        manager.world_spawns=SimpleNamespace(validate=lambda *a,**k:dict(x=.5,y=0.,z=.195,heading_deg=90.))
        with self.assertRaisesRegex(ValueError,'fixed home spawn'):
            manager._specifications('CUADC2026',[dict(kind='copter_rescue')],{},0)
    def test_observation_selection_single_bucket_two_outputs_and_no_unobserved_fallback(self):
        capture=QueryInstance('CaptureView',CaptureParameters(),self.world).tick(self.world)
        self.assertEqual(len(capture.result['objects']),1)
        selected=QueryInstance('SelectDropTargets',SelectParameters((self.target,)),self.world).tick(self.world)
        self.assertEqual([s['channel'] for s in selected.result['targets'][0]['servo_outputs']],[8,9])
        empty=QueryInstance('SelectDropTargets',SelectParameters(()),self.world).tick(self.world)
        self.assertEqual(empty.outcome,ActionOutcome.FAILED)
        for obj in (replace(self.obj,producer_id='oracle'),replace(self.obj,quality=QualityState.DEGRADED)):
            value=QueryInstance('CaptureView',CaptureParameters(),self.world).tick(replace(self.world,objects=(obj,)))
            self.assertFalse(value.result['objects'])
    def test_configured_drop_offsets_reach_release_without_rewriting_the_observed_target(self):
        from vehicle_autonomy.actions.composite.rescue import ReleaseInstance,release_aim_offset
        other=replace(self.obj,object_id='vision.pt:test:bucket2',confidence=.8,
            position=replace(self.obj.position,value=Vector3(2,32.5,.105)))
        world=replace(self.world,objects=(self.obj,other))
        selected=QueryInstance('SelectDropTargets',SelectParameters((self.target,encode_target(world,other)),
            first_release_target_ey=-.5,second_release_target_ey=.5),world).tick(world)
        self.assertEqual([d['release_target_ey'] for d in selected.result['targets']],[-.5,.5])
        for ey in (-.5,.5):
            effect=ReleaseInstance(ReleaseParameters(self.target,(ServoOutput(8,1800,1370),),True,ey),world).tick(world).effects[0]
            self.assertEqual(effect.target_position,self.obj.position.value)
            self.assertEqual(effect.aim_offset,release_aim_offset(ey,3.-.105))

    def test_faster_waypoints_are_not_silently_clamped_to_the_old_two_mps_limit(self):
        from vehicle_autonomy.actions.copter.rescue import GotoInstance,GotoParameters,MotionInstance
        world=self.h.sample(.1,Vector3(0,0,3))
        effect=GotoInstance(GotoParameters(0,32.5,5,10),world).tick(world).effects[0]
        v=effect.target_twist.linear;speed=math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)
        self.assertGreater(speed,9);self.assertLessEqual(speed,10)
        self.assertEqual(MotionInstance(world).speed_limit_mps,1.99)

    def test_rescue_bucket_surface_rejects_ground_letters_without_merging_ambiguous_boxes(self):
        import cv2,numpy as np
        from vehicle_autonomy.world.perception.vision.rescue_bucket import has_bucket_surface
        image=np.full((100,100,3),(75,145,155),np.uint8)
        cv2.putText(image,'500',(10,60),cv2.FONT_HERSHEY_SIMPLEX,1,(15,15,15),2)
        candidate=PixelDetection(0,.6,(5,20,90,80))
        self.assertFalse(has_bucket_surface(image,candidate))
        cv2.ellipse(image,(50,50),(20,25),0,0,360,(170,170,170),-1)
        self.assertTrue(has_bucket_surface(image,candidate))
        self.assertFalse(has_bucket_surface(image,PixelDetection(0,.9,(-20,-20,-10,-10))))
        image[:]=(75,145,155)
        cv2.circle(image,(50,50),5,(90,130,140),1)
        self.assertTrue(has_bucket_surface(image,PixelDetection(0,.4,(44,44,57,57))))
    def test_alignment_loss_fails_and_exit_requests_existing_stop_barrier(self):
        action=AlignInstance(AlignParameters(self.target),self.world)
        decision=action.tick(self.world);self.assertEqual(decision.outcome,ActionOutcome.RUNNING)
        self.assertEqual(type(decision.effects[0]).__name__,'TwistTargetEffect')
        lost=action.tick(replace(self.world,objects=()))
        self.assertEqual(lost.outcome,ActionOutcome.RUNNING)
        self.assertEqual(lost.effects[0].target_twist.linear,Vector3(0,0,0))
        expired=action.tick(self.h.sample(4.,Vector3(0,32.5,3)))
        self.assertEqual(expired.outcome,ActionOutcome.FAILED)
        stop=action.exit(self.world,ExitReason.FAILED)
        self.assertFalse(stop.complete);self.assertEqual(type(stop.effects[0]).__name__,'StopMotionEffect')
        stale=replace(self.world,published_at=replace(self.world.published_at,monotonic_ns=self.world.published_at.monotonic_ns+1_100_000_000))
        self.assertIsNone(current_target(stale,self.target))
    def test_release_requires_alignment_and_exact_servo_mapping(self):
        r=self.registry();context=ActionContext('v','copter',frozenset({'rescue_payload'}),True)
        with self.assertRaises(ValueError):ServoOutput(10,1800,1600)
        with self.assertRaises(ValueError):ReleaseFactory().validate_context(ReleaseParameters(self.target,(ServoOutput(8,1800,1370),)),self.world,context)
        p=ReleaseParameters(self.target,(ServoOutput(8,1800,1370),),True)
        action=ReleaseFactory().start_with_context(p,self.world,context)
        self.assertEqual(action.tick(self.world).effects[0].payload_id,'payload_1')
        self.assertEqual(action.tick(self.world).outcome,ActionOutcome.RUNNING)
        self.assertNotIn('rescue_payload',capabilities('copter'))
    def test_reacquisition_requires_unique_nearby_same_source_and_class(self):
        query=QueryInstance('ConfirmTarget',ConfirmParameters(self.target),self.world)
        new=replace(self.obj,object_id='vision.pt:test:new-track')
        observed=query.tick(replace(self.world,objects=(new,)))
        self.assertEqual(observed.outcome,ActionOutcome.SUCCEEDED)
        self.assertEqual(observed.result['target']['target_id'],new.object_id)
        for objects in ((replace(new,producer_id='vision.pt:other'),),(replace(new,label='H'),),(self.obj,new)):
            self.assertEqual(query.tick(replace(self.world,objects=objects)).outcome,ActionOutcome.RUNNING)
        expired=replace(self.world,published_at=replace(self.world.published_at,monotonic_ns=self.world.published_at.monotonic_ns+4_000_000_000),objects=())
        self.assertEqual(query.tick(expired).outcome,ActionOutcome.FAILED)
    def test_detector_exchange_rejects_retiming_wrong_epoch_and_bad_pixel_geometry(self):
        from copy import deepcopy
        from vehicle_autonomy.app.bootstrap.rescue_runtime import validate_result
        value=dict(schema=2,worker_epoch='a'*32,world_generation='world',camera_source='/owned/camera',sequence=1,
            image_domain='virtual_nadir',calibration_id='cuadc2026-fixed-down-v1',reference_id='d'*32,
            captured_ns=1_000_000_000,received_ns=1_100_000_000,model_sha256='b'*64,backend='ultralytics_pt',marker_backend='yellow_disc_h_shape_v1',error=None,
            objects=[dict(id='target-1',label='bucket',position=[0.,32.5,.105],confidence=.9,xyxy=[310.,230.,330.,250.],detector='pt')])
        arguments=dict(digest='b'*64,topic='/owned/camera',generation='world',now_ns=1_200_000_000)
        self.assertEqual(len(validate_result(value,**arguments)),1)
        for changes in ({'captured_ns':2_000_000_000},{'world_generation':'other'},{'camera_source':'/other'},{'model_sha256':'c'*64},{'sequence':True},
                {'image_domain':'raw'},{'calibration_id':'physical-camera'},{'reference_id':''}):
            with self.assertRaises(ValueError):validate_result(dict(value,**changes),**arguments)
        bad=deepcopy(value);bad['objects'][0]['xyxy'][2]=999.
        with self.assertRaises(ValueError):validate_result(bad,**arguments)
    def test_camera_assembly_allows_shared_sensor_free_bottles_but_rejects_shared_cameras(self):
        from vehicle_autonomy.app.simulation.camera_assembly import assemble
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);bottle=folder/'bottle.sdf';camera=folder/'camera.sdf';model=folder/'model.sdf'
            bottle.write_text('<sdf><model name="bottle"><link name="body"/></model></sdf>')
            camera.write_text('<sdf><model name="camera"><link name="body"><sensor name="camera" type="camera"/></link></model></sdf>')
            def write(repeat):
                model.write_text('<sdf><model name="vehicle">'+''.join('<include><uri>'+str(p)+'</uri><name>part'+str(i)+'</name></include>' for i,p in enumerate((repeat,repeat,camera)))+'</model></sdf>')
            prepared=dict(model_path=model,kind='copter',entity_name='owned',fingerprint='fixture')
            write(bottle);self.assertEqual(len(assemble(resource_root(),folder,prepared,'world')['cameras']),1)
            write(camera)
            with self.assertRaises(ValueError):assemble(resource_root(),folder,prepared,'world')
    def test_fixed_down_projection_uses_calibrated_axes_and_rejects_upward_camera(self):
        box=PixelDetection(0,.9,(310.,230.,330.,250.))
        pose=Pose3(Vector3(0,32.5,3),Quaternion(0,0,math.sin(math.pi/4),math.cos(math.pi/4)))
        point=project(box,pose,'bucket')
        self.assertAlmostEqual(point.x,.01,places=5);self.assertAlmostEqual(point.y,32.5,places=5)
        with self.assertRaises(ValueError):project(box,replace(pose,orientation=Quaternion(1,0,0,0)),'bucket')
    def test_yellow_h_marker_is_pixel_geometry_not_a_bucket_label_alias(self):
        import cv2,numpy as np
        from vehicle_autonomy.world.perception.vision.landing_marker import detect_h
        image=np.full((480,640,3),110,np.uint8);cv2.circle(image,(320,240),80,(10,220,240),-1)
        self.assertFalse(detect_h(image))
        cv2.rectangle(image,(284,196),(298,284),(15,15,15),-1)
        cv2.rectangle(image,(342,196),(356,284),(15,15,15),-1)
        cv2.rectangle(image,(284,232),(356,248),(15,15,15),-1)
        self.assertEqual(len(detect_h(image)),1)
        near=np.full((480,640,3),(10,220,240),np.uint8)
        cv2.rectangle(near,(60,0),(160,479),(15,15,15),-1);cv2.rectangle(near,(480,0),(580,479),(15,15,15),-1)
        cv2.rectangle(near,(60,190),(580,290),(15,15,15),-1)
        self.assertEqual(len(detect_h(near)),1)

    def test_sync_fault_invalidates_existing_world_observations_without_retiming(self):
        self._assert_sync_fault(display_valid=False)

    def test_position_or_inference_fault_preserves_fresh_display_but_invalidates_control(self):
        self._assert_sync_fault(display_valid=True)

    def _assert_sync_fault(self,*,display_valid):
        from collections import deque
        from vehicle_autonomy.app.bootstrap.rescue_runtime import RescueRuntime
        from vehicle_autonomy.contracts.sensor import Observation,DetectedObject
        from vehicle_autonomy.world.sensors.camera.motion import MotionHistory
        now=self.world.published_at
        observed=Observation('obs',self.world.schema_version,'vision.pt:test',1,now,now,QualityState.VALID,
            DetectedObject('target-1','bucket',Vector3(0,32.5,.105),.9),'odom')
        published=[];runtime=RescueRuntime.__new__(RescueRuntime)
        with tempfile.TemporaryDirectory() as directory:
            runtime.root=Path(directory)
            (runtime.root/'health.json').write_text(json.dumps(dict(published_ns=now.monotonic_ns,rectification_valid=False,error='position gap')))
            if display_valid:
                (runtime.root/'stabilization-health.json').write_text(json.dumps(dict(published_ns=now.monotonic_ns,
                    rectification_valid=True,stabilization=dict(reference_id='reference'))))
            runtime.runtime=SimpleNamespace(world_snapshot=lambda:self.world,clock=lambda:now,telemetry_snapshot=lambda:None,motion_history=lambda:None,
                ingest_observation=published.append)
            runtime.motion=MotionHistory();runtime.active={('vision.pt:test','target-1'):observed}
            runtime.observations=deque([(observed,self.world.version.generation_id,self.world.environment)])
            runtime.sequence=1;runtime.stabilization=dict(valid=True)
            runtime.port=SimpleNamespace(poll=lambda _:());runtime.execution=SimpleNamespace(tick=lambda _:None)
            runtime.poll()
        self.assertEqual(len(published),1);self.assertEqual(published[0].quality,QualityState.INVALID)
        self.assertEqual(published[0].captured_at,observed.captured_at)
        self.assertEqual(published[0].data,observed.data);self.assertGreater(published[0].sequence,observed.sequence)
        self.assertFalse(runtime.observations);self.assertFalse(runtime.active)
        self.assertEqual(runtime.stabilization['valid'],display_valid)
        self.assertIsNotNone(runtime.last_error)
