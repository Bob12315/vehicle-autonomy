"""Opt-in sensor assembly, only over already verified owned SDF copies."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pose(element):
    pose = element.find('pose')
    if pose is None:
        return [0.] * 6
    # These two locked vehicles have axis-aligned fixed body origins. Do not
    # silently approximate new frame conventions or arbitrary nested rotations.
    if pose.attrib:
        raise ValueError('MID-360 body frame requires an audited SDF pose format')
    values = list(map(float, pose.text.split()))
    if len(values) != 6 or any(values[3:]):
        raise ValueError('MID-360 body origin requires an audited zero rotation')
    return values


def assemble(root, directory, prepared, world):
    root, directory = Path(root), Path(directory).resolve()
    kind = prepared['kind']
    config_path = root/'configs/mid360-simulation.json'
    config = json.loads(config_path.read_text())
    if kind not in config['mounts']:
        raise ValueError('MID-360 simulation supports only ordinary Rover/Copter')
    mount = config['mounts'][kind]
    entity = prepared['entity_name']
    namespace = '/vaf/' + entity + '/sensors/mid360'
    path = Path(prepared['model_path']).resolve()
    top = path
    offsets = [0.] * 3
    chain = []
    for name in mount['scope']:
        if not path.is_relative_to(directory):
            raise ValueError('MID-360 assembly requires owned model copies')
        model = ET.parse(path).find('model')
        include = next((i for i in model.findall('include')
                        if (i.findtext('name') or Path(i.findtext('uri')).parent.name) == name), None)
        if include is None:
            raise ValueError('audited MID-360 body scope missing')
        offsets = [a+b for a, b in zip(offsets, _pose(include)[:3])]
        path = Path(include.findtext('uri')).resolve()
        chain.append(name)
    if not path.is_relative_to(directory) or path.is_symlink():
        raise ValueError('MID-360 assembly requires owned model copies')
    tree = ET.parse(path)
    model = tree.find('model')
    link = model.find(f"link[@name='{mount['link']}']")
    if link is None or link.find("sensor[@name='mid360']") is not None:
        raise ValueError('audited MID-360 body link missing or already assembled')
    offsets = [a+b for a, b in zip(offsets, _pose(model)[:3])]
    offsets = [a+b for a, b in zip(offsets, _pose(link)[:3])]
    recipe = root/'simulation/sensors/mid360-approx-v1.sdf'
    sensor = ET.parse(recipe).getroot()
    ET.SubElement(sensor, 'pose').text = ' '.join(map(str, mount['xyz_rpy']))
    ET.SubElement(sensor, 'topic').text = namespace + '/gz_scan'
    ET.SubElement(sensor, 'gz_frame_id').text = entity + '/mid360'
    link.append(sensor)
    imu = ET.SubElement(link, 'sensor', name='mid360_imu', type='imu')
    ET.SubElement(imu, 'pose').text = ' '.join(map(str, mount['xyz_rpy']))
    ET.SubElement(imu, 'always_on').text = 'true'
    ET.SubElement(imu, 'update_rate').text = '200'
    ET.SubElement(imu, 'topic').text = namespace + '/gz_imu'
    ET.SubElement(imu, 'imu')
    housing = ET.SubElement(link, 'visual', name='mid360_housing')
    ET.SubElement(housing, 'pose').text = ' '.join(map(str, mount['xyz_rpy']))
    cylinder = ET.SubElement(ET.SubElement(housing, 'geometry'), 'cylinder')
    ET.SubElement(cylinder, 'radius').text = '0.0325'
    ET.SubElement(cylinder, 'length').text = '0.06'
    ET.SubElement(ET.SubElement(housing, 'material'), 'diffuse').text = '0.25 0.25 0.28 1'
    before = digest(path)
    tree.write(path, encoding='utf-8', xml_declaration=True)
    result = dict(schema=1, id='mid360-approx', version='1.0.0', kind=kind,
        backend=config['backend'], source='gazebo-live', world=world, entity=entity,
        namespace=namespace, body_scope=chain, body_link=mount['link'],
        model_to_body=offsets, mount=deepcopy(mount['xyz_rpy']),
        points_gz=namespace+'/gz_scan/points', imu_gz=namespace+'/gz_imu',
        world_frame=entity+'/world', model_frame=entity+'/model',
        base_frame=entity+'/base_link', lidar_frame=entity+'/mid360',
        modified_file=str(path.relative_to(directory)), before_sha256=before, after_sha256=digest(path),
        recipe_sha256=digest(recipe), config_sha256=digest(config_path),
        base_fingerprint=prepared['fingerprint'], limitations=config['limitations'])
    (directory/'mid360-assembly.json').write_text(json.dumps(result, indent=2)+'\n')
    # The separately recorded sensor assembly is not the immutable base hash.
    prepared['pre_mid360_prepared_hash'] = prepared['prepared_model_hash']
    prepared['prepared_model_hash'] = digest(top)
    prepared['mid360_assembly'] = dict(manifest='mid360-assembly.json', derived_file=result['modified_file'],
                                     derived_sha256=result['after_sha256'])
    (directory/'vehicle.json').write_text(json.dumps(prepared, indent=2, default=str)+'\n')
    return result
