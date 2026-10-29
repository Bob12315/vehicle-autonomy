"""Data-driven ground spawn admission, independent of vehicle construction.

An available pairing is a configuration admission, not a motion test result.
Unknown terrain, external includes and unreviewed meshes fail closed. Generated
primitive worlds are inspected again for the requested seed/environment values.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from .catalog import SceneRegistry


_FAMILIES = ('rover', 'copter', 'plane', 'vtol')


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' must be a finite number')
    return float(value)


def _numbers(text, count, name):
    try:
        values = [float(item) for item in (text or '').split()]
    except ValueError as exc:
        raise ValueError('BLOCKED: invalid ' + name) from exc
    if len(values) != count or not all(math.isfinite(item) for item in values):
        raise ValueError('BLOCKED: invalid ' + name)
    return values


def _rotation(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
    return ((cy*cp, cy*sp*sr-sy*cr, cy*sp*cr+sy*sr),
            (sy*cp, sy*sp*sr+cy*cr, sy*sp*cr-cy*sr),
            (-sp, cp*sr, cp*cr))


def _transform(parent, element):
    pose = element.find('pose')
    if pose is not None and (pose.get('relative_to') or pose.get('degrees') or pose.get('rotation_format')):
        raise ValueError('BLOCKED: unreviewed SDF pose frame/format')
    values = [0.] * 6 if pose is None else _numbers(pose.text, 6, 'pose')
    rotation = _rotation(*values[3:])
    old_pos, old_rot = parent
    pos = tuple(old_pos[i] + sum(old_rot[i][j] * values[j] for j in range(3)) for i in range(3))
    rot = tuple(tuple(sum(old_rot[i][k] * rotation[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    return pos, rot


def _bounds(position, rotation, half):
    extent = [sum(abs(rotation[i][j]) * half[j] for j in range(3)) for i in range(3)]
    return tuple(position[i] - extent[i] for i in range(3)) + tuple(position[i] + extent[i] for i in range(3))


def _intersects_xy(bounds, x, y, radius):
    nearest_x = max(bounds[0], min(x, bounds[3]))
    nearest_y = max(bounds[1], min(y, bounds[4]))
    return math.hypot(x-nearest_x, y-nearest_y) <= radius + 1e-8


class WorldSpawnRegistry:
    def __init__(self, scene_registry=None):
        self.scenes = scene_registry if scene_registry is not None else SceneRegistry()
        path = Path(self.scenes.root) / 'simulation/scenarios/world_spawns.json'
        data = json.loads(path.read_text())
        if data.get('schema') != 1 or not isinstance(data.get('worlds'), dict):
            raise ValueError('unsupported World spawn registry schema')
        self._data = data
        self._cache = {}

    def _audit(self, scene_id, *, parameters=None, seed=0):
        scene = self.scenes.get(scene_id)
        params = self.scenes.validate(scene_id, parameters=parameters, seed=seed)
        entry = self._data['worlds'].get(scene_id)
        if entry is None:
            raise ValueError('BLOCKED: World has no reviewed ground spawn regions; loading a World does not grant vehicle admission')
        if entry.get('audit') != 'generated-flat-primitives-v1':
            raise ValueError('BLOCKED: unsupported World geometry audit')
        key = (scene_id, seed, json.dumps(params, sort_keys=True))
        if key in self._cache:
            return self._cache[key]
        with tempfile.TemporaryDirectory(prefix='vaf-spawn-audit-') as directory:
            path = self.scenes.generate(scene_id, Path(directory)/'world.sdf', parameters=params, seed=seed)
            root = ET.parse(path).getroot()
        world = root.find('world')
        if world is None or world.findall('.//include') or world.findall('.//model/model') or world.findall('frame'):
            raise ValueError('BLOCKED: World has unreviewed includes, nesting or frames')
        spherical = world.find('spherical_coordinates')
        if spherical is None or spherical.findtext('surface_model') != 'EARTH_WGS84':
            raise ValueError('BLOCKED: World geographic reference is unknown')
        reference = {'surface_model': 'EARTH_WGS84'}
        for name in ('latitude_deg', 'longitude_deg', 'elevation', 'heading_deg'):
            reference[name] = _numbers(spherical.findtext(name), 1, 'geographic reference')[0]
        extent = scene.get('extent_m')
        if not isinstance(extent, list) or len(extent) != 2 or any(_number(v, 'World extent') <= 0 for v in extent):
            raise ValueError('BLOCKED: finite World extent is unknown')
        solids = []
        admission_blocker = None
        identity = ((0., 0., 0.), _rotation(0, 0, 0))
        for model in world.findall('model'):
            if model.findtext('static') != 'true':
                admission_blocker = 'BLOCKED: World contains a dynamic collision envelope without reviewed bounds'
            model_transform = _transform(identity, model)
            for link in model.findall('link'):
                link_transform = _transform(model_transform, link)
                for collision in link.findall('collision'):
                    position, rotation = _transform(link_transform, collision)
                    geo = collision.find('geometry')
                    if geo is None or len(geo) != 1:
                        raise ValueError('BLOCKED: collision geometry is unknown')
                    shape = geo[0]
                    if shape.tag == 'box':
                        size = _numbers(shape.findtext('size'), 3, 'box dimensions')
                        half = [item/2 for item in size]
                    elif shape.tag == 'cylinder':
                        radius = _numbers(shape.findtext('radius'), 1, 'cylinder radius')[0]
                        length = _numbers(shape.findtext('length'), 1, 'cylinder length')[0]
                        half = [radius, radius, length/2]
                    elif shape.tag == 'sphere':
                        half = _numbers(shape.findtext('radius'), 1, 'sphere radius') * 3
                    else:
                        raise ValueError('BLOCKED: mesh/terrain/unknown collision has no reviewed safe region')
                    if any(item <= 0 for item in half):
                        raise ValueError('BLOCKED: nonpositive collision dimensions')
                    name = model.get('name', '')
                    bounds = _bounds(position, rotation, half)
                    horizontal = abs(rotation[2][0]) < 1e-8 and abs(rotation[2][1]) < 1e-8
                    support_name = name in ('ground', 'road', 'runway') or name.startswith('runway_mark_')
                    support = (support_name and shape.tag == 'box' and horizontal and
                               -.05 <= bounds[5] <= .1 and bounds[5]-bounds[2] <= .600001)
                    solids.append({'name': name, 'bounds': bounds, 'support': support})
        grounds = [item for item in solids if item['name'] == 'ground' and item['support']]
        if len(grounds) != 1:
            raise ValueError('BLOCKED: reviewed ground collision is missing')
        ground = grounds[0]['bounds']
        expected = (-extent[0]/2, -extent[1]/2, extent[0]/2, extent[1]/2)
        if any(abs(a-b) > 1e-6 for a,b in zip((ground[0], ground[1], ground[3], ground[4]), expected)) or abs(ground[5]) > 1e-6:
            raise ValueError('BLOCKED: World ground no longer matches the reviewed finite flat area')
        result = {'scene': scene, 'entry': entry, 'solids': solids, 'extent': extent,
                  'admission_blocker': admission_blocker,
                  'geographic_reference': reference, 'ground_height': ground[5]}
        # Bound the cache for long-running managers accepting many random seeds.
        if len(self._cache) >= 64:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = result
        return result

    def _support(self, audit, x, y, radius):
        return max([audit['ground_height']] + [item['bounds'][5] for item in audit['solids']
                   if item['support'] and _intersects_xy(item['bounds'], x, y, radius)])

    def describe(self, scene_id):
        scene = self.scenes.get(scene_id)
        entry = self._data['worlds'].get(scene_id)
        audit = None
        try:
            audit = self._audit(scene_id)
            reason = audit['admission_blocker']
        except ValueError as exc:
            reason = str(exc)
        support = {}
        for family in _FAMILIES:
            available = audit is not None and reason is None and family in entry.get('allowed_families', [])
            support[family] = {'available': available, 'reason': ('CONFIGURATION_ADMITTED: ground geometry only; motion not certified' if available else
                reason or entry.get('blocked_reasons', {}).get(family, 'BLOCKED: family not admitted'))}
        presets = []
        if audit is not None:
            for preset in entry.get('presets', []):
                item = deepcopy(preset)
                item['ground_z'] = self._support(audit, item['x'], item['y'], 0.)
                presets.append(item)
        return {'scene_id': scene_id,
                'geographic_reference': deepcopy(audit['geographic_reference']) if audit else None,
                'extent_m': deepcopy(scene.get('extent_m')),
                'ground_height': audit['ground_height'] if audit else None,
                'spawn_presets': presets, 'vehicle_support': support,
                'constraints': {'admission_only': True, 'ground_spawn_only': True,
                    'custom_region_required': True, 'minimum_peer_margin_m': self._data['minimum_peer_margin_m'],
                    'ground_tolerance_m': self._data['ground_tolerance_m'],
                    'regions': deepcopy(entry.get('regions', [])) if entry else [],
                    'runway': deepcopy(entry.get('runway')) if entry else None,
                    'blocked_reason': reason}}

    @staticmethod
    def _definition(definition):
        if not isinstance(definition, dict) or not isinstance(definition.get('id'), str):
            raise ValueError('vehicle definition requires a registered id')
        family = definition.get('family', definition.get('kind', definition.get('category')))
        if family not in _FAMILIES:
            raise ValueError('unknown vehicle family')
        radius = _number(definition.get('radius'), 'vehicle radius')
        clearance = _number(definition.get('clearance_z'), 'vehicle clearance_z')
        height = _number(definition.get('height', {'rover': .8, 'copter': .8, 'plane': 1.5, 'vtol': 1.5}[family]), 'vehicle height')
        if radius <= 0 or clearance < 0 or height <= 0:
            raise ValueError('invalid vehicle collision envelope')
        return family, radius, clearance, height

    def validate(self, scene_id, vehicle_definition, spawn=None, *, peers=(), parameters=None, seed=0):
        family, radius, clearance, height = self._definition(vehicle_definition)
        audit = self._audit(scene_id, parameters=parameters, seed=seed)
        if audit['admission_blocker']:
            raise ValueError(audit['admission_blocker'])
        entry = audit['entry']
        if family not in entry['allowed_families']:
            raise ValueError(entry.get('blocked_reasons', {}).get(family, 'BLOCKED: vehicle family not admitted'))
        preset_id = None
        if spawn is None:
            spawn = {'id': entry['presets'][0]['id']}
        if not isinstance(spawn, dict):
            raise ValueError('spawn must be an object')
        if set(spawn) == {'id'}:
            preset = next((item for item in entry['presets'] if item['id'] == spawn['id']), None)
            if preset is None:
                raise ValueError('unknown World spawn preset')
            x, y, heading = (_number(preset[name], name) for name in ('x', 'y', 'heading_deg'))
            preset_id = preset['id']
            requested_z = None
        elif set(spawn) == {'x', 'y', 'z', 'heading_deg'}:
            x, y, requested_z, heading = (_number(spawn[name], name) for name in ('x', 'y', 'z', 'heading_deg'))
        else:
            raise ValueError('spawn requires only {id} or exactly {x,y,z,heading_deg}')
        sx, sy = audit['extent']
        if abs(x)+radius > sx/2 or abs(y)+radius > sy/2:
            raise ValueError('BLOCKED: vehicle footprint is outside the finite World ground')
        regions = [region for region in entry['regions'] if family in region['families']]
        if not any(region['bounds'][0] <= x-radius and x+radius <= region['bounds'][1] and
                   region['bounds'][2] <= y-radius and y+radius <= region['bounds'][3] for region in regions):
            raise ValueError('BLOCKED: vehicle footprint is outside reviewed ground spawn regions')
        ground_z = self._support(audit, x, y, radius)
        if ground_z-audit['ground_height'] > self._data['maximum_surface_step_m']:
            raise ValueError('BLOCKED: ground surface step exceeds reviewed ground tolerance')
        z = ground_z + clearance
        if requested_z is not None and abs(requested_z-z) > self._data['ground_tolerance_m']:
            raise ValueError('BLOCKED: z must equal World ground height plus fixed vehicle clearance; airborne spawns are unsupported')
        for solid in audit['solids']:
            bounds = solid['bounds']
            if not solid['support'] and bounds[5] > ground_z+.01 and bounds[2] < ground_z+height and _intersects_xy(bounds, x, y, radius):
                raise ValueError('BLOCKED: spawn collision with World object '+solid['name'])
        if family == 'plane':
            runway = entry['runway']
            difference = (heading-runway['heading_deg']+180) % 360 - 180
            if abs(difference) > runway['heading_tolerance_deg']:
                raise ValueError('BLOCKED: Plane heading must align with the audited runway')
            # Ground corridor is along World +X. The declaration supplies its
            # dimensions; actual generated collisions are always checked again.
            corridor = (x-radius, y-max(radius, runway['half_width_m']), ground_z+.05,
                        x+runway['forward_length_m'], y+max(radius, runway['half_width_m']),
                        ground_z+runway['clear_height_m'])
            runway_surface = next((item['bounds'] for item in audit['solids'] if item['name'] == runway['surface'] and item['support']), None)
            if runway_surface is None or any((corridor[0] < runway_surface[0], corridor[1] < runway_surface[1], corridor[3] > runway_surface[3], corridor[4] > runway_surface[4])):
                raise ValueError('BLOCKED: finite runway does not contain the forward ground corridor')
            for solid in audit['solids']:
                bounds = solid['bounds']
                if not solid['support'] and all(bounds[i] < corridor[i+3] and corridor[i] < bounds[i+3] for i in range(3)):
                    raise ValueError('BLOCKED: Plane forward runway collision with '+solid['name'])
        if not isinstance(peers, (tuple, list)):
            raise ValueError('peers must contain previously validated spawn/definition objects')
        for peer in peers:
            if not isinstance(peer, dict) or set(peer) != {'spawn', 'definition'} or not isinstance(peer['spawn'], dict):
                raise ValueError('invalid peer spawn record')
            _, other_radius, _, _ = self._definition(peer['definition'])
            other_x = _number(peer['spawn'].get('x'), 'peer x')
            other_y = _number(peer['spawn'].get('y'), 'peer y')
            if math.hypot(x-other_x, y-other_y) < radius+other_radius+self._data['minimum_peer_margin_m']:
                raise ValueError('BLOCKED: spawn separation from another vehicle is too small')
        return {'x': x, 'y': y, 'z': z, 'heading_deg': heading % 360,
                'preset_id': preset_id}
