"""Versioned immutable vehicle definitions, independent of every World.

This registry describes local simulation inputs. READY means the locked inputs
exist, never a claim of flight, Framework readiness, or hardware qualification.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from .spawner import bind_model


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _xml(element):
    return ET.tostring(element, encoding='unicode') if element is not None else None


def _pose(element):
    if element is None:
        return {'value': '0 0 0 0 0 0', 'degrees': False, 'relative_to': None}
    return {'value': (element.text or '').strip(), 'degrees': element.get('degrees') == 'true',
            'relative_to': element.get('relative_to')}


class VehicleRegistry:
    def __init__(self, root=None, *, ardupilot_root=None, plugin_root=None, twin_root=None):
        self.root = Path(root or resource_root()).resolve()
        host = HostEnvironment(self.root)
        self.ardupilot_root = host.path('ardupilot_root', ardupilot_root)
        self.plugin_root = host.path('gazebo_plugin_root', plugin_root)
        self.twin_root = host.path('fixedwing_root', twin_root)
        self.roots = {'root': self.root, 'ardupilot': self.ardupilot_root,
                      'plugin': self.plugin_root, 'twin': self.twin_root}
        self.catalog = json.loads((self.root / 'simulation/vehicles/catalog.json').read_text())

    def _path(self, reference):
        owner, relative = reference.split(':', 1)
        path = (self.roots[owner] / relative).resolve()
        if not path.is_relative_to(self.roots[owner]):
            raise ValueError('Vehicle source escapes configured root')
        return path

    def _reference(self, path):
        path = Path(path).resolve()
        for owner, root in sorted(self.roots.items(), key=lambda item: len(item[1].parts), reverse=True):
            if path.is_relative_to(root):
                return owner + ':' + path.relative_to(root).as_posix()
        raise ValueError('Vehicle resource outside configured roots: ' + str(path))

    def _model_dependencies(self, model):
        roots = [self.root / 'simulation/models', self.plugin_root / 'models', self.twin_root / 'models']
        directories, files, parsed, visiting = set(), {}, {}, set()

        def visit(path):
            path = path.resolve()
            if path in visiting:
                raise ValueError('Recursive vehicle model include cycle')
            if path in parsed:
                return
            visiting.add(path)
            tree = ET.parse(path)
            if tree.getroot().find('model') is None:
                raise ValueError('Vehicle include must contain a model: ' + str(path))
            parsed[path] = tree
            directory = path.parent
            if directory not in directories:
                directories.add(directory)
                for item in sorted(directory.rglob('*')):
                    if item.is_file():
                        files[self._reference(item)] = item
            for element in tree.findall('.//uri'):
                uri = (element.text or '').strip()
                if uri.startswith('model://'):
                    relative = uri.removeprefix('model://')
                    candidates = [(root / relative).resolve() for root in roots]
                    candidate = next((p for p in candidates if p.exists()), None)
                    if candidate is None:
                        raise ValueError('Missing recursive vehicle resource: ' + uri)
                    if not any(candidate.is_relative_to(root.resolve()) for root in roots):
                        raise ValueError('Vehicle resource escapes model roots')
                    if candidate.is_dir():
                        visit(candidate / 'model.sdf')
                    else:
                        # Meshes may belong to another model without an include.
                        asset_root = next(root for root in roots if candidate.is_relative_to(root.resolve()))
                        asset_directory = asset_root / relative.split('/')[0]
                        if asset_directory not in directories:
                            directories.add(asset_directory)
                            for item in sorted(asset_directory.rglob('*')):
                                if item.is_file():
                                    files[self._reference(item)] = item
                elif '://' in uri:
                    raise ValueError('Vehicle resource must be locally locked: ' + uri)
                elif uri:
                    candidate = (directory / uri).resolve()
                    if not candidate.exists():
                        raise ValueError('Missing local vehicle resource: ' + str(candidate))
                    self._reference(candidate)
                    if candidate.is_dir():
                        visit(candidate / 'model.sdf')
                    else:
                        files[self._reference(candidate)] = candidate
            visiting.remove(path)
        visit(model)
        return directories, files, parsed

    def _describe(self, model_path, parsed):
        sensors, inertials, joints, dynamics, actuators = [], [], [], [], []

        def walk(path, chain):
            model = parsed[path.resolve()].getroot().find('model')
            scope = '::'.join([item['name'] for item in chain])
            for link in model.findall('link'):
                inertials.append({'scope': scope, 'link': link.get('name'),
                                  'link_pose': _pose(link.find('pose')),
                                  'inertial': _xml(link.find('inertial')),
                                  'collisions': [_xml(item) for item in link.findall('collision')]})
                for sensor in link.findall('sensor'):
                    sensors.append({'scope': scope, 'name': sensor.get('name'), 'type': sensor.get('type'),
                                    'parent_link': link.get('name'), 'include_chain': chain,
                                    'model_pose': _pose(model.find('pose')),
                                    'link_pose': _pose(link.find('pose')),
                                    'sensor_pose': _pose(sensor.find('pose')),
                                    'configuration': _xml(sensor),
                                    'frames': [_xml(item) for item in model.findall('frame')]})
            joints.extend({'scope': scope, 'configuration': _xml(j)} for j in model.findall('joint'))
            for plugin in model.findall('plugin'):
                if plugin.get('name') == 'ArduPilotPlugin':
                    actuators.extend({'scope': scope, 'channel': c.get('channel'),
                                      'mapping': _xml(c)} for c in plugin.findall('control'))
                else:
                    dynamics.append({'scope': scope, 'name': plugin.get('name'),
                                     'filename': plugin.get('filename'), 'configuration': _xml(plugin)})
            for include in model.findall('include'):
                uri = (include.findtext('uri') or '').strip()
                name = uri.removeprefix('model://')
                child = next((p for p in parsed if p.parent.name == name), None)
                if child:
                    walk(child, chain + [{'name': include.findtext('name') or name,
                                          'pose': _pose(include.find('pose'))}])
        walk(model_path, [])
        return {'links': inertials, 'joints': joints, 'plugins': dynamics}, sensors, actuators

    def list_vehicles(self):
        return [self.get(kind) for kind in self.catalog['vehicles']]

    def get(self, kind):
        if kind not in self.catalog['vehicles']:
            raise ValueError('Unknown registered simulation vehicle: ' + str(kind))
        entry = self.catalog['vehicles'][kind]
        family = entry.get('family', kind)
        result = dict(entry, id=kind, kind=family, family=family, status='BLOCKED', reason=entry.get('reason'),
                      physics={}, sensors=[], actuators=[], fingerprint=None, model_hash=None,
                      parameters_hash=None, sensor_hash=None, source_files={})
        result.pop('locks', None)
        for name in ('model_path', 'profile_path', 'binary'):
            result[name] = str(self._path(entry[name])) if entry.get(name) else None
        result['parameters'] = [str(self._path(p)) for p in entry.get('parameters', [])]
        result['resource_paths'] = []
        result['plugin_paths'] = [str(self.plugin_root / 'build')]
        result['plugin_root'] = str(self.plugin_root)
        result['twin_root'] = str(self.twin_root) if family == 'plane' else None
        if family == 'vtol':
            return result
        try:
            model = Path(result['model_path'])
            directories, files, parsed = self._model_dependencies(model)
            models = {key: digest(path) for key, path in files.items()}
            result['resource_paths'] = sorted({str(p.parent) for p in directories})
            physics, sensors, actuators = self._describe(model, parsed)
            result.update(physics=physics, sensors=sensors, actuators=actuators,
                          model_hash=_hash(models), sensor_hash=_hash(sensors))
            inputs = {self._reference(Path(p)): Path(p) for p in [result['binary'], result['profile_path'], *result['parameters']]}
            requirements = [self.plugin_root / 'build/libArduPilotPlugin.so',
                            self.plugin_root / 'src/ArduPilotPlugin.cc', self.plugin_root / 'CMakeLists.txt']
            if family == 'plane':
                requirements += [self.twin_root / 'plugins/TwinPayload.cc', self.twin_root / 'plugins/CMakeLists.txt']
                result['plugin_paths'].insert(0, str(self.twin_root / 'plugins/build'))
                result['payload_source'] = str(self.twin_root / 'plugins')
            inputs.update({self._reference(p): p for p in requirements})
            hashes = {key: digest(path) for key, path in inputs.items()}
            result['source_files'] = dict(models, **hashes)
            result['parameters_hash'] = _hash([hashes[p] for p in entry['parameters']])
            result['fingerprint'] = _hash({'version': entry['version'], 'sources': result['source_files']})
            if not os.access(result['binary'], os.X_OK):
                raise ValueError('Registered SITL binary is not executable')
            if len(parsed[model.resolve()].findall('.//plugin[@name="ArduPilotPlugin"]')) != 1:
                raise ValueError('Exactly one ArduPilotPlugin required')
            expected = entry.get('locks', {})
            if result['source_files'] != expected:
                changed = sorted(key for key in set(expected) | set(result['source_files'])
                                 if expected.get(key) != result['source_files'].get(key))
                raise ValueError('Fixed vehicle source lock mismatch: ' + ', '.join(changed[:5]))
            result.update(status='READY', reason=None)
        except (OSError, ValueError, ET.ParseError) as exc:
            result['reason'] = str(exc)
        return result

    def prepare(self, kind, directory, *, entity_name, instance, system_id):
        definition = self.get(kind)
        if definition['status'] != 'READY':
            raise ValueError(definition['reason'] or 'Vehicle inputs are blocked')
        directory = Path(directory).resolve()
        # Reject reuse before copying or writing any source inputs.
        if directory.exists() and any(directory.iterdir()):
            raise ValueError('Vehicle preparation requires a new empty owned directory')
        for root in (self.ardupilot_root, self.plugin_root, self.twin_root,
                     self.root / 'simulation/models', self.root / 'simulation/vehicles'):
            if directory.is_relative_to(root):
                raise ValueError('Vehicle output cannot modify a source resource tree')
        directory.mkdir(parents=True, exist_ok=True)
        model = Path(definition['model_path'])
        directories, _, _ = self._model_dependencies(model)
        resources = directory / 'resources'
        resources.mkdir()
        if len({p.name for p in directories}) != len(directories):
            raise ValueError('Ambiguous recursive vehicle model directory names')
        for source in sorted(directories):
            shutil.copytree(source, resources / source.name)
        # Resolve all model URIs inside the owned snapshot. Gazebo's process
        # environment predates dynamic spawning, and must not select external
        # mutable meshes instead of this instance's fixed copies. Absolute
        # includes also support standalone libsdformat without a Gazebo callback.
        for source in sorted(directories):
            copied = resources / source.name / 'model.sdf'
            if not copied.is_file():
                continue
            tree = ET.parse(copied)
            modified = False
            for uri in tree.findall('.//uri'):
                text = (uri.text or '').strip()
                if text.startswith('model://'):
                    destination = resources / text.removeprefix('model://')
                    if destination.is_dir():
                        destination = destination / 'model.sdf'
                    if not destination.is_file():
                        raise ValueError('Unresolved owned vehicle resource: ' + text)
                    uri.text = str(destination)
                    modified = True
            if modified:
                tree.write(copied, encoding='utf-8', xml_declaration=True)
        model_path = directory / 'model.sdf'
        binding = bind_model(resources / model.parent.name / model.name, model_path,
                             entity_name=entity_name, instance=instance, system_id=system_id)
        parameters = []
        for index, source in enumerate(definition['parameters']):
            destination = directory / f'defaults-{index}-{Path(source).name}'
            shutil.copyfile(source, destination)
            parameters.append(destination)
        profile = directory / 'profile.toml'
        shutil.copyfile(definition['profile_path'], profile)
        # Detect a mutable external source changing during preparation.
        after = self.get(kind)
        if after['status'] != 'READY' or after['fingerprint'] != definition['fingerprint']:
            raise ValueError('Vehicle source changed while preparing owned instance')
        result = dict(definition, **binding)
        result.update(model_path=model_path, parameters=tuple(parameters), profile_path=profile,
                      binary=Path(definition['binary']), resource_paths=[resources],
                      source_model_path=definition['model_path'], prepared_model_hash=digest(model_path))
        (directory / 'vehicle.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
        return result
