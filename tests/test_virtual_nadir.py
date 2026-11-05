"""Virtual camera geometry/synchronization; no Gazebo truth enters production."""
from dataclasses import replace
from datetime import datetime,timezone
import json,math,unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.contracts.core.geometry import Pose3,Quaternion,Vector3
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.world.sensors.camera.motion import MotionHistory,MotionMatch,MotionPending,match_motion
from vehicle_autonomy.world.sensors.camera.virtual_nadir import VirtualNadir,rotation,validate_config
from vehicle_autonomy.world.perception.vision.rescue_geometry import project
from vehicle_autonomy.world.perception.vision.yolox import PixelDetection
from vehicle_autonomy.world.transform.tree import multiply_quaternions


def orientation(roll=0.,pitch=0.,yaw=0.):
    return multiply_quaternions(Quaternion(0,0,math.sin(yaw/2),math.cos(yaw/2)),
        multiply_quaternions(Quaternion(0,math.sin(pitch/2),0,math.cos(pitch/2)),Quaternion(math.sin(roll/2),0,0,math.cos(roll/2))))


def match(q=None,key=('world','session','clock')):
    return MotionMatch(Pose3(Vector3(.5,32.5,3),q or orientation(yaw=math.pi/2)),key,10.,(1,2),(1,2))


class VirtualCameraTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.image=np.full((480,640,3),110,np.uint8);self.camera=VirtualNadir()

    def test_calibration_matches_versioned_gazebo_sensor(self):
        root=ET.parse(resource_root()/'simulation/models/gimbal_cuadc2026_fixed_down/model.sdf')
        camera=root.find('.//sensor/camera')
        self.assertEqual(int(camera.findtext('image/width')),self.camera.width)
        self.assertEqual(int(camera.findtext('image/height')),self.camera.height)
        expected=640/(2*math.tan(float(camera.findtext('horizontal_fov'))/2))
        self.assertAlmostEqual(self.camera.k[0,0],expected)
        self.assertAlmostEqual(self.camera.k[1,1],expected)

    def test_level_camera_is_identity_and_input_is_untouched(self):
        import numpy as np
        self.image[100:120,200:225]=(230,50,100);before=self.image.copy()
        frame=self.camera.rectify(self.image,match())
        np.testing.assert_allclose(frame.homography,np.eye(3),atol=1e-10)
        np.testing.assert_array_equal(before,self.image);np.testing.assert_array_equal(frame.image,self.image)
        self.assertTrue((frame.valid_mask==255).all())

    def test_tilt_and_yaw_rectification_preserves_world_rays_without_double_compensation(self):
        import numpy as np
        self.camera.rectify(self.image,match())
        for roll,pitch,yaw in ((.2,0,0),(-.2,.15,.3),(0,-.25,-.4),(.1,.2,.6)):
            current=match(orientation(roll,pitch,math.pi/2+yaw))
            frame=self.camera.rectify(self.image,current)
            for label in ('bucket','H'):
                for u,v in ((320.,240.),(240.,190.),(390.,300.)):
                    original=PixelDetection(0,.9,(u-1,v-1,u+1,v+1))
                    pixel=frame.homography@np.array((u,v,1.));a,b=pixel[:2]/pixel[2]
                    virtual=PixelDetection(0,.9,(a-1,b-1,a+1,b+1))
                    expected=project(original,current.pose,label)
                    actual=project(virtual,current.pose,label,virtual_camera=frame.camera)
                    np.testing.assert_allclose((actual.x,actual.y,actual.z),(expected.x,expected.y,expected.z),atol=1e-10)
            self.assertAlmostEqual(frame.camera.yaw_ref_rad,math.pi/2)

    def test_border_pixels_and_excessive_tilt_cannot_become_detections(self):
        import numpy as np
        self.camera.rectify(self.image,match())
        frame=self.camera.rectify(self.image,match(orientation(.25,.1,math.pi/2+.4)))
        self.assertLess(np.count_nonzero(frame.valid_mask),frame.valid_mask.size)
        self.assertTrue(frame.accepts((300,220,340,260)))
        self.assertFalse(frame.accepts((0,0,640,480)))
        self.assertFalse(frame.accepts((-1,0,12,12)))
        with self.assertRaises(ValueError):self.camera.rectify(self.image,match(orientation(pitch=1.2)))

    def test_reference_is_pinned_to_owned_motion_epoch(self):
        reference=self.camera.rectify(self.image,match()).camera.reference_id
        self.assertEqual(self.camera.rectify(self.image,match()).camera.reference_id,reference)
        with self.assertRaises(ValueError):self.camera.rectify(self.image,match(key=('world','new-session','clock')))

    def test_only_reviewed_calibration_and_bounded_timing_are_admitted(self):
        config=json.loads((resource_root()/'configs/perception/rescue_2026_pt.json').read_text())['virtual_nadir']
        self.assertEqual(validate_config(config),config)
        for key,value in (('calibration_id','usb-uncalibrated'),('yaw_reference_mode','follow'),
                ('min_attitude_rate_hz',0),('max_bracket_span_ms',999),('max_sample_distance_ms',True)):
            with self.assertRaises(ValueError):validate_config(dict(config,**{key:value}))


class MotionHistoryTests(unittest.TestCase):
    def envelope(self):
        history=MotionHistory()
        for i in range(11):
            ns=1_000_000_000+i*100_000_000
            stamp=TimePoint(ns,datetime.now(timezone.utc),'host-monotonic-simulation')
            q=orientation(yaw=math.radians(170+2*i))
            fields={'ATTITUDE':SimpleNamespace(quality=QualityState.VALID,captured_at=stamp,
                value=SimpleNamespace(orientation_flu_enu=q)),
                'LOCAL_POSITION_NED':SimpleNamespace(quality=QualityState.VALID,captured_at=stamp,
                    value=SimpleNamespace(position_enu_m=Vector3(i,0,3)))}
            telemetry=SimpleNamespace(link_session_id='session',published_at=stamp,field=fields.__getitem__)
            self.assertTrue(history.update(telemetry,'world',ns))
            self.assertFalse(history.update(telemetry,'world',ns+1))
        return history,telemetry

    def test_interpolates_real_source_samples_and_wraps_yaw_over_pi(self):
        history,_=self.envelope();value=history.envelope(2_000_000_000)
        result=match_motion(value,1_550_000_000,2_000_000_000)
        self.assertAlmostEqual(result.pose.position.x,5.5)
        r=rotation(result.pose.orientation)
        self.assertAlmostEqual(math.atan2(r[1,0],r[0,0]),math.radians(-179))
        self.assertAlmostEqual(result.attitude_rate_hz,10.)
        self.assertEqual(result.attitude_bracket_ns,(1_500_000_000,1_600_000_000))

    def test_no_extrapolation_no_retiming_and_no_cross_session_matching(self):
        history,_=self.envelope();value=history.envelope(2_000_000_000)
        with self.assertRaises(MotionPending):match_motion(value,2_010_000_000,2_020_000_000)
        with self.assertRaises(ValueError):match_motion(value,1_550_000_000,3_000_000_000)
        with self.assertRaises(ValueError):match_motion(value,1_550_000_000,2_000_000_000,expected_key=('other','session','clock'))
        value['attitudes']=value['attitudes'][::2]
        with self.assertRaises(ValueError):match_motion(value,1_550_000_000,2_000_000_000)

    def test_history_rejects_source_reordering_and_session_replacement(self):
        history,telemetry=self.envelope()
        telemetry.link_session_id='different'
        with self.assertRaises(ValueError):history.update(telemetry,'world',2_000_000_000)
        telemetry.link_session_id='session'
        for kind in ('ATTITUDE','LOCAL_POSITION_NED'):
            field=telemetry.field(kind);field.captured_at=replace(field.captured_at,monotonic_ns=1_900_000_000)
        with self.assertRaises(ValueError):history.update(telemetry,'world',2_000_000_000)

    def test_invalid_motion_payload_cannot_create_a_camera_pose(self):
        from copy import deepcopy
        history,_=self.envelope();original=history.envelope(2_000_000_000)
        for change in ('duplicate','overflow','nonfinite','quaternion'):
            value=deepcopy(original)
            if change=='duplicate':value['attitudes'][5]=value['attitudes'][4]
            if change=='overflow':value['attitudes']*=20
            if change=='nonfinite':value['positions'][5][1]=float('nan')
            if change=='quaternion':value['attitudes'][5][1:]=[0,0,0,2]
            with self.subTest(change=change),self.assertRaises(ValueError):match_motion(value,1_550_000_000,2_000_000_000)

    def test_receiver_batch_is_not_reduced_to_latest_publication_sample(self):
        from vehicle_autonomy.contracts.core.stamped import Stamped
        from vehicle_autonomy.contracts.vehicle.telemetry import MotionTelemetryHistory
        source,telemetry=self.envelope();value=source.envelope(2_000_000_000)
        def stamp(ns):return TimePoint(ns,datetime.now(timezone.utc),'host-monotonic-simulation')
        history=MotionTelemetryHistory('session',
            tuple(Stamped('odom',stamp(row[0]),Vector3(*row[1:])) for row in value['positions']),
            tuple(Stamped('odom',stamp(row[0]),Quaternion(*row[1:])) for row in value['attitudes']))
        destination=MotionHistory()
        self.assertTrue(destination.update(telemetry,'world',2_000_000_000,source_history=history))
        self.assertEqual(len(destination.attitudes),11)
        self.assertEqual(match_motion(destination.envelope(2_000_000_000),1_550_000_000,2_000_000_000).pose.position.x,5.5)
        self.assertFalse(destination.update(telemetry,'world',2_000_000_001,source_history=history))


class AssociationTests(unittest.TestCase):
    def test_brief_outage_requires_new_detection_and_does_not_publish_old_targets(self):
        from vehicle_autonomy.world.perception.vision.association import TargetAssociator
        tracker=TargetAssociator();sample=(Vector3(0,32,.1),'bucket','pt')
        first=tracker.update([sample],1_000_000_000)
        self.assertEqual(tracker.update([],1_200_000_000),[])
        self.assertEqual(tracker.update([sample],3_500_000_000),first)
        self.assertNotEqual(tracker.update([sample],9_000_000_000),first)

    def test_ambiguous_duplicate_wrong_label_backend_and_distant_detections_do_not_adopt_identity(self):
        from vehicle_autonomy.world.perception.vision.association import TargetAssociator
        sample=(Vector3(0,32,.1),'bucket','pt')
        for observations in ([sample,sample],[(Vector3(1,32,.1),'bucket','pt')],
                [(Vector3(0,32,.1),'H','h_marker')],[(Vector3(0,32,.1),'bucket','other')]):
            tracker=TargetAssociator();first=tracker.update([sample],1_000_000_000)
            self.assertFalse(set(first)&set(tracker.update(observations,1_100_000_000)))

    def test_ambiguous_frame_cannot_poison_a_later_unique_fresh_match(self):
        from vehicle_autonomy.world.perception.vision.association import TargetAssociator
        tracker=TargetAssociator();sample=(Vector3(0,32,.1),'bucket','pt')
        first=tracker.update([sample],1_000_000_000)
        ambiguous=tracker.update([sample,sample],1_100_000_000)
        self.assertFalse(set(first)&set(ambiguous))
        self.assertEqual(tracker.update([sample],1_200_000_000),first)


if __name__=='__main__':unittest.main()
