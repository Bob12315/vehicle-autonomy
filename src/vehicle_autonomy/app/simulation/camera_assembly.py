"""Versioned camera-only assembly over an already verified owned model copy.

Never changes source models, mass, collisions, joints, actuator configuration or
vehicle-library locks. Topic remaps and the Rover optical sensor are separately
attested; the base fingerprint is not claimed to describe this derived SDF.
"""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assemble(root, directory, prepared, world):
    directory = Path(directory).resolve()
    path = Path(prepared['model_path']).resolve()
    entity = prepared['entity_name']
    cameras, changed, visited = [], [], set()
    recipe = Path(root)/'simulation/sensors/rover-front-v1.sdf'
    before = sha(path)

    def visit(path, scope=()):
        if not path.is_relative_to(directory) or path in visited:
            raise ValueError('camera assembly requires unique owned model copies')
        visited.add(path)
        tree = ET.parse(path); model = tree.find('model')
        if prepared['kind'] == 'rover' and not scope:
            if model.find('.//sensor[@type="camera"]') is not None:
                raise ValueError('Rover base unexpectedly already has a camera')
            model.find('link[@name="base_link"]').append(ET.parse(recipe).getroot())
        for link in model.findall('link'):
            for sensor in link.findall('sensor[@type="camera"]'):
                slot = '-'.join((*scope, sensor.get('name')))
                topic = f'/vaf/camera/{world}/{entity}/{slot}/image'
                topic_node = sensor.find('topic')
                if topic_node is None: topic_node = ET.SubElement(sensor, 'topic')
                original_topic = topic_node.text
                topic_node.text = topic
                info = sensor.find('camera/camera_info_topic')
                if info is not None: info.text = topic.removesuffix('/image')+'/camera_info'
                # Disable optional legacy UDP video output in this owned copy;
                # preview subscribes to Gazebo Image, never an unscoped port.
                removed = []
                for plugin in list(sensor.findall('plugin')):
                    if plugin.get('name') == 'GstCameraPlugin':
                        removed.append(plugin.get('name')); sensor.remove(plugin)
                cameras.append(dict(slot=slot, topic=topic, original_topic=original_topic,
                    parent_link=link.get('name'), model_scope=list(scope), removed_plugins=removed,
                    source_configuration=ET.tostring(sensor, encoding='unicode')))
        tree.write(path, encoding='utf-8', xml_declaration=True)
        changed.append(dict(path=str(path.relative_to(directory)), sha256=sha(path)))
        for include in model.findall('include'):
            child = Path(include.findtext('uri')).resolve()
            visit(child, (*scope, include.findtext('name') or child.parent.name))
    visit(path)
    result = dict(id='camera-preview', version='1.0.0', base_fingerprint=prepared['fingerprint'],
        base_prepared_sha256=before, derived_prepared_sha256=sha(path),
        rover_sensor_recipe_sha256=sha(recipe), files=changed, cameras=cameras)
    (directory/'camera-assembly.json').write_text(json.dumps(result, indent=2)+'\n')
    if 'prepared_model_hash' in prepared:
        prepared['base_prepared_model_hash'] = prepared['prepared_model_hash']
        prepared['prepared_model_hash'] = result['derived_prepared_sha256']
        prepared['camera_assembly'] = dict(id=result['id'],version=result['version'],manifest='camera-assembly.json')
        (directory/'vehicle.json').write_text(json.dumps(prepared,indent=2,default=str)+'\n')
    return result
