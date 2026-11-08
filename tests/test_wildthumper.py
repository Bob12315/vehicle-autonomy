"""Official replacement integration, using small owned SDF contract fixtures."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import xml.etree.ElementTree as ET

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.simulation.camera_assembly import assemble as camera
from vehicle_autonomy.app.simulation.mid360_assembly import assemble as mid360
from vehicle_autonomy.world.sensors.lidar.mid360_worker import robot_description


class WildThumperAssemblyTests(unittest.TestCase):
    def test_new_base_origin_mount_and_schematic_do_not_reuse_old_chassis_offset(self):
        with TemporaryDirectory() as folder:
            directory=Path(folder);path=directory/'model.sdf'
            path.write_text('<sdf version="1.9"><model name="owned"><link name="base_link"/></model></sdf>')
            prepared=dict(kind='rover',model_name='wildthumper',model_path=path,entity_name='owned',fingerprint='fixed-source',prepared_model_hash='prior')
            optical=camera(resource_root(),directory,prepared,'world')
            sensor=mid360(resource_root(),directory,prepared,'world')
            self.assertEqual(len(optical['cameras']),1)
            self.assertEqual(sensor['model_to_body'],[0.,0.,0.])
            self.assertEqual(sensor['mount'],[0,0,.22,0,0,0])
            self.assertEqual(sensor['vehicle_model'],'wildthumper')
            robot=ET.fromstring(robot_description(sensor));body=robot.find('link')
            self.assertEqual(len([v for v in body.findall('visual') if v.get('name','').startswith('wheel_')]),6)
            support=ET.parse(path).find('.//visual[@name="mid360_mount_support"]')
            self.assertIsNotNone(support);self.assertFalse(ET.parse(path).findall('.//collision'))
            self.assertEqual(robot.find('joint/origin').get('xyz'),'0 0 0.22')


if __name__=='__main__':unittest.main()
