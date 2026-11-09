"""Readonly typed admission/withdrawal; fabricated fixtures are never accuracy evidence."""
import json,time,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from vehicle_autonomy.world.localization.lio_input import LioWorldSource
from tests.simulation.lio_accuracy import score


class LioLocalization(unittest.TestCase):
    def raw(self,now):
        return dict(generation='fixture',frame_id='local/map',revision=1,online=True,published_host_ns=now,
            localization=dict(captured_host_ns=now-10000000,published_host_ns=now-5000000,capture_ros_ns=1000000000,
                position=[1.,2.,3.],quaternion=[0.,0.,0.,1.],derived_twist=None))

    def test_typed_readonly_world_and_expiry(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp);raw=self.raw(time.monotonic_ns());(p/'state.json').write_text(json.dumps(raw))
            source=LioWorldSource(p,'fixture','local/map');snapshot=source.update(owner_running=True)
            self.assertIsNotNone(snapshot.localization);self.assertIsNone(snapshot.vehicle)
            self.assertIsNone(snapshot.localization.covariance);self.assertIsNone(snapshot.localization.twist)
            self.assertFalse(hasattr(source.reader(),'update_localization'))
            snapshot=source.update(owner_running=False);self.assertIsNone(snapshot.localization)
            raw['localization']['captured_host_ns']-=2_000_000_000;(p/'state.json').write_text(json.dumps(raw))
            self.assertIsNone(source.update(owner_running=True).localization)

    def test_generation_frame_and_reused_revision_fail_closed(self):
        for field,value in (('generation','another'),('frame_id','another')):
            with TemporaryDirectory() as tmp:
                p=Path(tmp);raw=self.raw(time.monotonic_ns());raw[field]=value;(p/'state.json').write_text(json.dumps(raw))
                source=LioWorldSource(p,'fixture','local/map');self.assertIsNone(source.update(owner_running=True).localization)
                raw[field]='fixture' if field=='generation' else 'local/map';(p/'state.json').write_text(json.dumps(raw))
                self.assertIsNone(source.update(owner_running=True).localization);self.assertIsNotNone(source.latched)
        with TemporaryDirectory() as tmp:
            p=Path(tmp);raw=self.raw(time.monotonic_ns());(p/'state.json').write_text(json.dumps(raw))
            source=LioWorldSource(p,'fixture','local/map');self.assertIsNotNone(source.update(owner_running=True).localization)
            raw['localization']['position'][0]+=1;(p/'state.json').write_text(json.dumps(raw))
            self.assertIsNone(source.update(owner_running=True).localization);self.assertIn('reused',source.latched)

    def test_map_reference_holds_its_original_capture_and_rejects_reused_version(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp);now=time.monotonic_ns();raw=self.raw(now)
            raw.update(map_reference={'sha256':'a'*64},map_export_revision=3,map_export_capture_host_ns=now-100000000)
            (p/'state.json').write_text(json.dumps(raw));source=LioWorldSource(p,'fixture','local/map')
            first=source.update(owner_running=True);self.assertIsNotNone(first.map)
            self.assertEqual(first.map.version.revision,3)
            raw['revision']=2;raw['localization']['capture_ros_ns']+=100000000
            (p/'state.json').write_text(json.dumps(raw));second=source.update(owner_running=True)
            self.assertEqual(first.map,second.map)
            raw['map_export_capture_host_ns']+=1;(p/'state.json').write_text(json.dumps(raw))
            rejected=source.update(owner_running=True);self.assertIsNone(rejected.map);self.assertIsNone(rejected.localization)

    def test_concurrent_publication_is_observed_after_read_not_falsely_future(self):
        import os
        with TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'state.json').write_text('{}');source=LioWorldSource(p,'fixture','local/map')
            original_read=os.read
            def concurrent_publication(fd,size):
                original_read(fd,size);time.sleep(.002)
                return json.dumps(self.raw(time.monotonic_ns())).encode()
            with patch('vehicle_autonomy.world.localization.lio_input.os.read',side_effect=concurrent_publication):
                self.assertIsNotNone(source.update(owner_running=True).localization)

    def test_atomic_replacement_after_open_keeps_owned_snapshot_but_rejects_hardlinks(self):
        import os
        with TemporaryDirectory() as tmp:
            p=Path(tmp);raw=self.raw(time.monotonic_ns());(p/'state.json').write_text(json.dumps(raw))
            source=LioWorldSource(p,'fixture','local/map');original_open=os.open
            def replace_after_open(path,*args,**kwargs):
                fd=original_open(path,*args,**kwargs)
                if path=='state.json':
                    replacement=p/'replacement';replacement.write_text(json.dumps(raw));replacement.replace(p/'state.json')
                    self.assertEqual(os.fstat(fd).st_nlink,0)
                return fd
            with patch('vehicle_autonomy.world.localization.lio_input.os.open',side_effect=replace_after_open):
                self.assertIsNotNone(source.update(owner_running=True).localization)
            os.link(p/'state.json',p/'unexpected-hardlink')
            self.assertIsNone(source.update(owner_running=True).localization)
            self.assertIn('invalid LIO exchange',source.error)

    def test_independent_judge_keeps_drift_instead_of_fitting_it_away(self):
        truth=[];est=[]
        for i in range(31):
            t=(i+1)*100000000
            truth.append(dict(simulation_ns=t,x_m=i*.1,y_m=0.,z_m=0.,quaternion_xyzw=[0.,0.,0.,1.]))
            est.append(dict(capture_ros_ns=t,position=[10+i*.11,20.,30.],quaternion=[0.,0.,0.,1.]))
        result=score(est,truth)
        self.assertGreater(result['ate_rmse_m'],.1);self.assertGreater(result['return_drift_m'],.25)
        self.assertAlmostEqual(result['attitude_rmse_deg'],0.)


if __name__=='__main__':unittest.main()
