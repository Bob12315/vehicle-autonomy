"""Map integrity and bounded accumulation, independent of estimator fixtures."""
import json,unittest,time
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
from vehicle_autonomy.world.mapping.cloud_maps import MapCatalog,VoxelMap,pcd_bytes,read_pcd,load_limits


class CloudMaps(unittest.TestCase):
    def test_operator_map_configuration_applies_and_rejects_unbounded_or_ambiguous_budgets(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'configs/mid360-map.json';path.parent.mkdir()
            limits=dict(resolution=.3,max_points=2000,radius=15.,min_observations=4)
            path.write_text(json.dumps(limits));mapper=VoxelMap(**load_limits(tmp))
            for _ in range(4):mapper.update([[1.,1.,1.,10.],[1.1,1.,1.,20.]])
            self.assertEqual(len(mapper.points()),1)
            self.assertEqual(mapper.max_points,2000);self.assertEqual(mapper.radius,15.)
            for changes in ({'max_points':500001},{'max_points':2000.},{'resolution':True},{'radius':float('nan')},{'min_observations':0},{'unknown':1}):
                path.write_text(json.dumps(dict(limits,**changes)))
                with self.assertRaises(ValueError):load_limits(tmp)

    def metadata(self):
        return dict(vehicle='rover',sensor={'version':'fixture'},world={'scene':'fixture'},algorithm={'name':'fixture'},
            frame_id='lio_fixture/map',frame_epoch='fixture',source_capture_ros_ns=100,created_at='2026-11-07T12:00:00+00:00')

    def test_roundtrip_content_and_metadata_integrity(self):
        values=np.array([[1.,2.,3.,4.],[5.,6.,7.,8.]],dtype=np.float32);data=pcd_bytes(values)
        with TemporaryDirectory() as tmp:
            catalog=MapCatalog(tmp);saved=catalog.save('geometry',data,self.metadata())
            loaded,body=catalog.load(saved['id']);self.assertEqual(saved,loaded);self.assertEqual(body,data)
            np.testing.assert_array_equal(read_pcd(body),values)
            metadata=Path(tmp)/saved['id']/'metadata.json';document=json.loads(metadata.read_text())
            document['frame_id']='another_frame';metadata.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError,'metadata checksum'):catalog.load(saved['id'])
            metadata.write_text(json.dumps(saved));pcd=metadata.with_name('map.pcd');pcd.write_bytes(data[:-1]+b'X')
            with self.assertRaisesRegex(ValueError,'checksum'):catalog.load(saved['id'])

    def test_rejects_symlink_and_unregistered_paths(self):
        with TemporaryDirectory() as tmp:
            catalog=MapCatalog(tmp);saved=catalog.save('a',pcd_bytes([[1,2,3,4]]),self.metadata())
            folder=Path(tmp)/saved['id'];pcd=folder/'map.pcd';pcd.rename(folder/'payload');pcd.symlink_to(folder/'payload')
            with self.assertRaises(OSError):catalog.load(saved['id'])
            for invalid in ('../../etc/passwd','map3d-abc',''):
                with self.assertRaises(ValueError):catalog.load(invalid)

    def test_rejects_truncation_bad_layout_and_nonfinite(self):
        data=pcd_bytes([[1,2,3,4]])
        for bad in (data[:-1],data+b'x',data.replace(b'VERSION .7',b'VERSION .8'),data.replace(b'WIDTH 1',b'WIDTH 2')):
            with self.assertRaises(ValueError):read_pcd(bad)
        with self.assertRaises(ValueError):pcd_bytes([[float('nan'),1,2,3]])
        with self.assertRaises(ValueError):pcd_bytes([[1001,1,2,3]])

    def test_voxel_dedup_pause_filter_and_capacity_stop(self):
        mapping=VoxelMap(resolution=.1,max_points=1000,radius=10,min_observations=1)
        mapping.update([[1,1,1,1],[1.01,1,1,3],[99,99,99,1],[float('nan'),0,0,0]])
        self.assertEqual(len(mapping.cells),1);self.assertEqual(mapping.filtered,2)
        mapping.paused=True;mapping.update([[2,2,2,1]]);self.assertEqual(len(mapping.cells),1)
        mapping.paused=False;mapping.update([[1.02,1,1,5]])
        self.assertAlmostEqual(float(mapping.points()[0,0]),1.0125,places=5)
        grid=np.array([[i*.2,j*.2,0.,1.] for i in range(34) for j in range(34)])
        mapping.update(grid);self.assertIn('capacity',mapping.error);self.assertEqual(len(mapping.cells),1)

    def test_map_rejects_single_observation_noise_without_truth_filtering(self):
        mapping=VoxelMap(min_observations=3)
        for i in range(3):mapping.update([[1.,1.,1.,10.],[2.+i,3.,2.,10.]])
        self.assertEqual(len(mapping.points()),1)
        self.assertEqual(len(mapping.cells),4)

    def test_process_pause_preserves_capture_and_resource_then_exits(self):
        from multiprocessing import get_context
        from queue import Empty
        from vehicle_autonomy.world.mapping.cloud_map_worker import accumulate
        with TemporaryDirectory() as tmp:
            ctx=get_context('spawn');inputs=ctx.Queue(2);outputs=ctx.Queue(2);stopping=ctx.Event()
            cfg=dict(generation='fixture',map_limits=dict(resolution=.1,max_points=1000,radius=10.,min_observations=1))
            process=ctx.Process(target=accumulate,args=(cfg,tmp,inputs,outputs,stopping));process.start()
            def receive(predicate):
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    try:state,payload=outputs.get(timeout=.2)
                    except Empty:continue
                    if predicate(state,payload):return state,payload
                self.fail('owned map process did not produce expected state')
            try:
                inputs.put((100,time.monotonic_ns(),np.array([[1.,2.,3.,4.]],dtype=np.float32)))
                first,payload=receive(lambda s,p:p is not None)
                self.assertEqual(first['map_export_capture_ros_ns'],100)
                self.assertEqual(first['map_export_revision'],1)
                (Path(tmp)/'pause').touch()
                inputs.put((200,time.monotonic_ns(),np.array([[4.,2.,3.,4.]],dtype=np.float32)))
                paused,_=receive(lambda s,p:s.get('map',{}).get('paused'))
                self.assertEqual(paused['map_reference'],first['map_reference'])
                self.assertEqual(paused['map_export_capture_ros_ns'],100)
                self.assertEqual(paused['map_export_revision'],1)
                stopping.set();process.join(5);self.assertFalse(process.is_alive())
                self.assertEqual(process.exitcode,0)
            finally:
                stopping.set()
                if process.is_alive():process.terminate();process.join(5)
                inputs.cancel_join_thread();outputs.cancel_join_thread();inputs.close();outputs.close()


if __name__=='__main__':unittest.main()
