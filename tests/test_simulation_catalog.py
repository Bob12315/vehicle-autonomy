"""Scene construction and locked asset safety, without claiming Gazebo execution."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from vehicle_autonomy.app.simulation.catalog import SceneRegistry
from vehicle_autonomy.app.simulation.assets import AssetManager, inspect_sdf


class SceneRegistryTests(unittest.TestCase):
    def setUp(self):self.registry=SceneRegistry()

    def test_twenty_four_specialized_worlds_are_distinct_and_vehicle_free(self):
        with tempfile.TemporaryDirectory() as directory:
            contents=[]
            scenes=[x for x in self.registry.list_scenes() if len(x['id'])==3 and x['id'][0] in 'RCF']
            self.assertEqual(24,len(scenes))
            for scene in scenes:
                file=self.registry.generate(scene['id'],Path(directory)/(scene['id']+'.sdf'),seed=42)
                world=ET.parse(file).find('world')
                self.assertEqual('vaf_'+scene['id'].lower(),world.get('name'))
                self.assertEqual([],world.findall('include'))
                self.assertIsNotNone(world.find('spherical_coordinates'))
                self.assertTrue(world.findall('.//collision'))
                names=[model.get('name') for model in world.findall('model')]
                self.assertEqual(len(names),len(set(names)))
                contents.append(file.read_bytes())
            self.assertEqual(24,len(set(contents)))

    def test_seed_replay_and_bounded_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            first=self.registry.generate('R01',Path(directory)/'a.sdf',seed=12)
            second=self.registry.generate('R01',Path(directory)/'b.sdf',seed=12)
            self.assertEqual(first.read_bytes(),second.read_bytes())
            second=self.registry.generate('R01',second,seed=13)
            self.assertNotEqual(first.read_bytes(),second.read_bytes())
            for parameters in ({'obstacle_count':-1},{'obstacle_count':3.5},{'wind_speed':float('nan')},{'friction':0},{'command':'sh'},{'gps_failure':True}):
                with self.assertRaises(ValueError):self.registry.generate('R01',first,parameters=parameters)
            for seed in (-1,True,2**32):
                with self.assertRaises(ValueError):self.registry.generate('R01',first,seed=seed)

    def test_dynamic_targets_have_force_plugin_and_physical_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            path=self.registry.generate('R05',Path(directory)/'world.sdf')
            world=ET.parse(path)
            model=world.find(".//model[@name='moving_target_0']")
            self.assertEqual('false',model.findtext('static'))
            self.assertIsNotNone(model.find('.//collision'))
            self.assertEqual('gz::sim::systems::TrajectoryFollower',model.find('plugin').get('name'))

    def test_registry_returns_copies_and_rejects_arbitrary_paths(self):
        scene=self.registry.get('R01');scene['name']='changed'
        self.assertNotEqual('changed',self.registry.get('R01')['name'])
        for identifier in ('../../etc/passwd','r01','R09'):
            with self.assertRaises(ValueError):self.registry.get(identifier)


class AssetManagerTests(unittest.TestCase):
    def test_local_verified_blob_install_corruption_and_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=b'<sdf version="1.9"><world name="empty"/></sdf>'
            sha=hashlib.sha256(data).hexdigest()
            lock={'schema':1,'assets':[dict(id='sample',source='https://example.org',version='123',license='test',world='world.sdf',files=[dict(path='world.sdf',url='https://example.org/locked/world.sdf',sha256=sha,size=len(data))])]}
            path=root/'lock.json';path.write_text(json.dumps(lock))
            manager=AssetManager(root/'cache',lock_path=path)
            blobs=manager.root/'blobs';blobs.mkdir(parents=True);(blobs/sha).write_bytes(data)
            self.assertEqual('AVAILABLE',manager.status('sample')['status'])
            self.assertTrue(manager.install('sample')['ready'])
            world=manager.world_path('sample');world.write_text('corrupt')
            self.assertEqual('CORRUPT',manager.status('sample')['status'])
            with self.assertRaises(ValueError):manager.world_path('sample')
            self.assertTrue(manager.install('sample')['ready'])
            lease=manager.acquire_usage()
            try:
                with self.assertRaisesRegex(ValueError,'in use'):manager.uninstall('sample')
                with self.assertRaisesRegex(ValueError,'in use'):manager.install('sample')
            finally:lease.close()
            self.assertEqual('AVAILABLE',manager.uninstall('sample')['status'])
            self.assertTrue((blobs/sha).exists())
            with self.assertRaises(ValueError):manager.uninstall('../../anything')

    def test_manifest_rejects_escape_and_unlocked_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'lock.json'
            base=dict(path='../escape',url='https://example.org/a',sha256='a'*64,size=1)
            for patch in ({},{'path':'safe','sha256':'latest'},{'path':'safe','url':'http://example.org/a'},{'path':'safe','size':200000000}):
                path.write_text(json.dumps({'schema':1,'assets':[dict(id='asset',files=[dict(base,**patch)])]}))
                with self.assertRaises(ValueError):AssetManager(root/'cache',lock_path=path)

    def test_recursive_missing_and_locked_fuel_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);model=root/'box';model.mkdir()
            (model/'model.sdf').write_text('<sdf version="1.9"><model name="box"><link name="link"><visual name="v"><geometry><mesh><uri>missing.dae</uri></mesh></geometry></visual></link></model></sdf>')
            uri='https://fuel.gazebosim.org/1.0/OpenRobotics/models/Box/2'
            world=root/'world.sdf';world.write_text('<sdf version="1.9"><world name="w"><include><uri>'+uri+'</uri></include></world></sdf>')
            self.assertEqual('BLOCKED',inspect_sdf(world)['status'])
            result=inspect_sdf(world,fuel_models={uri:model})
            self.assertEqual(2,result['checked_files'])
            self.assertTrue(any(x['uri']=='missing.dae' for x in result['missing']))
            (model/'missing.dae').write_text('<COLLADA/>')
            self.assertEqual('PASS',inspect_sdf(world,fuel_models={uri:model})['status'])

    def test_versioned_fuel_file_requires_exact_model_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);model=root/'model';(model/'meshes').mkdir(parents=True)
            (model/'meshes'/'Box.obj').write_text('v 0 0 0\n')
            uri='https://fuel.gazebosim.org/1.0/OpenRobotics/models/Box/2'
            world=root/'world.sdf'
            content='<sdf version="1.9"><world name="w"><model name="m"><link name="l"><visual name="v"><geometry><mesh><uri>'+uri+'/files/meshes/Box.obj</uri></mesh></geometry></visual></link></model></world></sdf>'
            world.write_text(content)
            self.assertEqual('PASS',inspect_sdf(world,fuel_models={uri:model})['status'])
            world.write_text(content.replace('/2/files','/3/files'))
            self.assertEqual('BLOCKED',inspect_sdf(world,fuel_models={uri:model})['status'])

    def test_cancellation_preserves_previous_install_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=b'<sdf version="1.9"><world name="empty"/></sdf>'
            sha=hashlib.sha256(data).hexdigest()
            entry=dict(id='sample',world='world.sdf',files=[dict(path='world.sdf',url='https://example.org/world.sdf',sha256=sha,size=len(data))])
            lock=root/'lock.json';lock.write_text(json.dumps({'schema':1,'assets':[entry]}))
            manager=AssetManager(root/'cache',lock_path=lock)
            blobs=manager.root/'blobs';blobs.mkdir(parents=True);(blobs/sha).write_bytes(data)
            manager.install('sample')
            with self.assertRaises(InterruptedError):manager.install('sample',cancelled=lambda:True)
            self.assertTrue(manager.status('sample')['ready'])
            self.assertEqual([],list(manager.root.glob('install-*')))

    def test_locked_dependency_cycles_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);lock=root/'lock.json'
            lock.write_text(json.dumps({'schema':1,'assets':[dict(id='a',requires=['b'],files=[]),dict(id='b',requires=['a'],files=[])]}))
            with self.assertRaises(ValueError):AssetManager(root/'cache',lock_path=lock)

    def test_nested_source_uses_latest_sdf_and_rebases_resource_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);scenario=root/'simulation/scenarios';scenario.mkdir(parents=True)
            (scenario/'center_catalog.json').write_text(json.dumps({'schema':1,'scenes':[]}))
            cache=root/'cache';install=cache/'installed/source'
            values={'world.sdf':'<sdf version="1.9"><world name="w"><include><uri>model://nested</uri></include></world></sdf>',
                'nested/model.config':'<model><sdf version="1.2">old.sdf</sdf><sdf version="1.9">model.sdf</sdf></model>',
                'nested/old.sdf':'<sdf version="1.2"><model name="old"><include><uri>missing</uri></include></model></sdf>',
                'nested/model.sdf':'<sdf version="1.9"><model name="new"><link name="link"/></model></sdf>'}
            files=[]
            for name,text in values.items():
                path=install/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
                files.append(dict(path=name,url='https://example.org/'+name,sha256=hashlib.sha256(text.encode()).hexdigest(),size=len(text.encode())))
            entry=dict(id='source',name='Source',source='https://example.org',version='1',license='test',world='world.sdf',files=files,limitations=[])
            (scenario/'assets.lock.json').write_text(json.dumps({'schema':1,'assets':[entry]}))
            registry=SceneRegistry(root,asset_cache=cache)
            result=registry.generate('U_source',root/'output/world.sdf')
            uri=ET.parse(result).findtext('.//include/uri')
            self.assertTrue(uri.startswith('file:///'))
            from urllib.parse import urlsplit,unquote
            rewritten=Path(unquote(urlsplit(uri).path))
            self.assertTrue(rewritten.is_file())
            self.assertEqual('new',ET.parse(rewritten).find('model').get('name'))
            self.assertEqual(values['world.sdf'],(install/'world.sdf').read_text())

    def test_classic_material_fallback_is_explicitly_adaptable(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'world.sdf'
            path.write_text('<sdf version="1.9"><world name="w"><model name="m"><link name="l"><visual name="v"><material><diffuse>.5 .5 .5 1</diffuse><script><uri>file://media/materials/scripts/gazebo.material</uri><name>Gazebo/Grey</name></script></material></visual></link></model></world></sdf>')
            report=inspect_sdf(path)
            self.assertEqual('PASS',report['status'])
            self.assertEqual('remove_optional_classic_material_script',report['adaptations'][0]['kind'])

    def test_classic_plugins_not_assumed_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'world.sdf'
            path.write_text('<sdf version="1.9"><world name="w"><plugin filename="libgazebo_ros_api_plugin.so" name="gazebo::Classic"/></world></sdf>')
            report=inspect_sdf(path)
            self.assertEqual('BLOCKED',report['status'])
            self.assertTrue(report['plugins'][0]['classic'])


if __name__=='__main__':unittest.main()
