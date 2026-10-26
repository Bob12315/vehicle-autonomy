from copy import deepcopy
from dataclasses import replace
import unittest
from tests.world_navigation.test_streams import stamp
from vehicle_autonomy.contracts.streams import FrameDescriptor,DataReference,SampleHeader,StreamObservation,DataKind,SourceKind
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.world.perception.vision.detection_input import validate_detection

class DetectionInputTests(unittest.TestCase):
    def setUp(self):
        header=SampleHeader('camera','camera',DataKind.IMAGE,'camera-epoch',1,100,'ros-simulation',stamp(11),stamp(10),FrameDescriptor('camera_optical','camera_optical','origin'),'calibration',SourceKind.SIMULATION,QualityState.VALID)
        original=StreamObservation(header,DataReference('slot-0','0'*64,60000,'application/x-raw-rgb8',(100,200,3)))
        out=replace(header,source_id='detector',sensor_id='detections',kind=DataKind.DETECTIONS,generation='detector-epoch',received_at=stamp(25),frame=FrameDescriptor('camera_optical','image_pixels','origin',units='pixels'),confidence=.9)
        self.item=StreamObservation(out,DataReference('slot-0','1'*64,100,'application/test'))
        self.value=dict(schema=1,detections=[dict(class_id=5,label='bus',confidence=.9,xyxy=[10.,10.,190.,90.])],primary_label='bus',detected=True,image_header=to_json_value(header),image_reference=to_json_value(original.data),captured_at=to_json_value(header.captured_at),source_frame='camera_optical',model_id='opencv-zoo-yolox-2022nov',model_version='model-sha',inference_backend='opencv_dnn_cpu',opencv_version='actual-version',inference_ns=5,inference_started_ns=20,completed_ns=25,world_positions_available=False)
        self.expected=dict(camera_source='camera',camera_generation='camera-epoch',model_sha256='model-sha')
    def test_qualified_actual_frame_contract_and_no_detection(self):
        self.assertIs(validate_detection(self.item,self.value,**self.expected),self.value)
        empty=deepcopy(self.value);empty.update(detections=[],detected=False,primary_label=None)
        item=replace(self.item,header=replace(self.item.header,confidence=0.))
        self.assertIs(validate_detection(item,empty,**self.expected),empty)
    def test_retimed_wrong_epoch_model_backend_or_spatial_claim_rejected(self):
        for change in ({'captured_at':to_json_value(stamp(12))},{'model_version':'wrong'},{'inference_backend':'mock'},{'world_positions_available':True},{'world_position':[1,2,3]}):
            value=dict(self.value,**change)
            with self.assertRaises(ValueError):validate_detection(self.item,value,**self.expected)
        expected=dict(self.expected,camera_generation='old')
        with self.assertRaises(ValueError):validate_detection(self.item,self.value,**expected)
    def test_forged_label_coordinates_confidence_and_presence_rejected(self):
        for change in ({'xyxy':[-1.,0.,50.,20.]},{'label':'person'},{'confidence':.4},{'xyxy':[True,0.,50.,20.]}):
            value=deepcopy(self.value);value['detections'][0].update(change)
            with self.assertRaises(ValueError):validate_detection(self.item,value,**self.expected)
        with self.assertRaises(ValueError):validate_detection(self.item,dict(self.value,detected=False),**self.expected)
