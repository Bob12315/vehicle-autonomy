"""Recording observer contracts only; actual video uses owned native cameras."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from vehicle_autonomy.app.simulation.comparison_recording import CameraComparisonRecorder,same_capture


class Camera:
    def __init__(self,metadata):self.metadata=metadata;self.close_count=0
    def packet(self):return dict(self.metadata),b'\xff\xd8explicit-unit-fixture\xff\xd9'
    def close(self):self.close_count+=1


class ComparisonRecordingTests(unittest.TestCase):
    def metadata(self):
        raw=dict(sequence=3,captured_ns=100,received_ns=200,source='/owned/camera',capture_clock='gazebo-simulation')
        processed=dict(raw,original_received_ns=200,kind='stabilized',image_domain='virtual_nadir',rectification=dict(valid=True))
        return raw,processed

    def test_pairing_rejects_different_exposures_sources_or_failed_rectification(self):
        raw,processed=self.metadata();self.assertTrue(same_capture(raw,processed))
        for key,value in (('sequence',4),('captured_ns',101),('source','/other'),('capture_clock','unknown'),
                ('original_received_ns',201),('kind','yolo'),('rectification',{'valid':False})):
            self.assertFalse(same_capture(raw,dict(processed,**{key:value})),key)
        self.assertFalse(same_capture({},processed))

    def test_observer_writes_one_pair_and_never_closes_sources(self):
        raw,processed=map(Camera,self.metadata())
        with TemporaryDirectory() as folder:
            path=Path(folder)/'export';recorder=CameraComparisonRecorder(path,raw,processed,binding={'target':'test'})
            try:
                end=time.monotonic()+2
                while recorder.paired_count<1 and time.monotonic()<end:time.sleep(.01)
                recorder.update_phase('RUNNING',[dict(name='Land',state='RUNNING')])
            finally:report=recorder.close()
            recorder.close()
            self.assertEqual((report['raw_frames'],report['paired_frames']),(1,1))
            self.assertEqual(len((path/'raw.jsonl').read_text().splitlines()),1)
            saved=json.loads((path/'stabilized.jsonl').read_text());self.assertEqual(saved['metadata']['sequence'],3)
        self.assertEqual((raw.close_count,processed.close_count),(0,0))

    def test_mismatched_processed_frame_stops_recording_without_affecting_sources(self):
        original,processed=self.metadata();processed['source']='/another/camera'
        raw,derived=Camera(original),Camera(processed)
        with TemporaryDirectory() as folder:
            recorder=CameraComparisonRecorder(Path(folder)/'export',raw,derived,binding={'target':'test'})
            recorder.thread.join(2)
            with self.assertRaisesRegex(RuntimeError,'does not match'):recorder.close()
        self.assertEqual((raw.close_count,derived.close_count),(0,0))


if __name__=='__main__':unittest.main()
