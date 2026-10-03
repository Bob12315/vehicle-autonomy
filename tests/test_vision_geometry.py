import unittest,math
from contracts.core.geometry import Transform3,Vector3,Quaternion
from perception.vision.projection import PlaneCalibration
from perception.vision.yolox import PixelDetection

class VisionGeometryTests(unittest.TestCase):
    def test_calibrated_plane_and_unlocated_cases(self):
        calibration=PlaneCalibration(810,1080,600,600,405,540,Transform3(Vector3(2,1.2,3),Quaternion(1,0,0,0)),.05,'explicit virtual rig','v1')
        box=PixelDetection(5,.95,(10.,230.,800.,725.))
        position=calibration.project(box,(810,1080));self.assertAlmostEqual(position.x,2);self.assertAlmostEqual(position.y,1.2-185*2.95/600)
        with self.assertRaises(ValueError):calibration.project(box,(640,640))
        with self.assertRaises(ValueError):calibration.project(PixelDetection(5,.9,(-1,0,10,10)),(810,1080))
        upward=PlaneCalibration(810,1080,600,600,405,540,Transform3(Vector3(2,1.2,3),Quaternion(0,0,0,1)),.05,'upwards','v2')
        with self.assertRaises(ValueError):upward.project(box,(810,1080))
    def test_missing_and_invalid_calibration_or_detection(self):
        with self.assertRaises(ValueError):PlaneCalibration(810,1080,0,600,405,540,Transform3(Vector3(0,0,0),Quaternion(0,0,0,1)),0,'','')
        for args in ((5,math.nan,(1,1,2,2)),(5,.5,(1,1,0,2)),(5,1.1,(1,1,2,2))):
            with self.assertRaises(ValueError):PixelDetection(*args)
