"""Trusted scene registry; metadata never grants vehicle admission.

Specialized R/C/F configurations are separate from upstream source worlds. The
latter report installation and dependency state independently from acceptance.
"""
from copy import deepcopy
import json
import os
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from vehicle_autonomy._resources import resource_root as default_resource_root
from .assets import AssetManager, inspect_sdf, model_sdf
from .scenarios import generate_world, validate_parameters


class SceneRegistry:
    def __init__(self, resource_root=None, *, asset_cache=None):
        self.root=Path(resource_root) if resource_root is not None else default_resource_root()
        catalog=json.loads((self.root/'simulation/scenarios/center_catalog.json').read_text())
        if catalog.get('schema')!=1:raise ValueError('unsupported scene catalog schema')
        self._scenes={scene['id']:scene for scene in catalog['scenes']}
        if len(self._scenes)!=len(catalog['scenes']):raise ValueError('duplicate scene identifier')
        lock=self.root/'simulation/scenarios/assets.lock.json'
        default_cache=os.environ.get('VAF_SIM_ASSET_CACHE')
        if not default_cache:
            default_cache=(self.root/'simulation/world_registry/assets/center-source' if (self.root/'pyproject.toml').is_file() else Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))/'vehicle-autonomy/simulation-assets')
        self.assets=AssetManager(asset_cache or default_cache,lock_path=lock) if lock.is_file() else None
        legacy=self.root/'simulation/world_registry/catalog.yaml'
        self._legacy=json.loads(legacy.read_text())['scenes'] if legacy.is_file() else {}

    def list_scenes(self):
        result=deepcopy(list(self._scenes.values()))
        if self.assets is not None:
            result.extend(self._upstream(entry) for entry in self.assets.list_assets() if entry.get('kind','world')=='world')
        result.extend(self._historical(identifier) for identifier in self._legacy)
        return result

    def _upstream(self, entry):
        return dict(id='U_'+entry['id'],name=entry['name'],category='upstream',vehicles=[],world_id=entry['id'],scenario_id=None,
            source=entry['source'],version=entry['version'],license=entry['license'],description='第三方独立 World；不含本框架车辆准入。',extent_m=None,
            spawn=None,targets=[],recommended_tests=['world smoke'],limitations=entry['limitations'],parameter_schema={},
            asset_id=entry['id'],installed=entry['installed'],download_status=entry['status'],compatibility_status='DEPENDENCIES_PRESENT' if entry['ready'] else 'BLOCKED',
            ready=entry['ready'],dependencies=entry['dependencies'],verification={f'L{n}':'NOT_TESTED' for n in range(1,7)})

    def _legacy_path(self, identifier):
        relative=self._legacy[identifier].get('sdf')
        if not relative:return None
        path=(self.root/'simulation/world_registry'/relative).resolve()
        if not path.is_relative_to((self.root/'simulation/world_registry').resolve()):raise ValueError('legacy source escapes registry')
        return path

    def _legacy_roots(self):
        roots=[self.root/'simulation/world_registry/assets/adapter_models',self.root/'simulation/world_registry/assets',self.root/'simulation/models']
        # This explicit local dependency matches the audited legacy registry;
        # no archived source or unrelated project is imported or modified.
        local=Path('/home/level6/gz_ws/src/ardupilot_gazebo/models')
        if local.is_dir():roots.append(local)
        return roots

    def _historical(self, identifier):
        entry=self._legacy[identifier];path=self._legacy_path(identifier)
        installed=path is not None and path.is_file()
        # Historical status does not become a current L1/L2 acceptance claim.
        return dict(id='H_'+identifier,name=entry['name'],category='historical',vehicles=[],world_id=identifier,scenario_id=None,
            source=entry['source'],version=entry.get('commit'),license=entry['license'],description='上一轮已下载/适配入口；历史实测单独保留。',
            extent_m=None,spawn=None,targets=[],recommended_tests=['world smoke'],parameter_schema={},installed=installed,
            download_status='INSTALLED' if installed else 'MISSING',compatibility_status='HISTORICAL_ONLY',ready=installed,
            limitations=[entry['limitations'],'历史证据不计入本轮 PASS；实际资源/插件须重新检查。'],historical_verification=entry.get('verified',[]),
            verification={f'L{n}':'NOT_TESTED' for n in range(1,7)})

    def get(self, scene_id):
        if not isinstance(scene_id,str):raise ValueError('scene identifier must be a string')
        if scene_id in self._scenes:return deepcopy(self._scenes[scene_id])
        if scene_id.startswith('U_') and self.assets is not None:
            entry=self.assets.status(scene_id[2:])
            if entry.get('kind','world')!='world':raise ValueError('asset is not a world scene')
            return self._upstream(entry)
        if scene_id.startswith('H_') and scene_id[2:] in self._legacy:return self._historical(scene_id[2:])
        raise ValueError('unknown scene identifier')

    def validate(self, scene_id, *, seed=0, parameters=None):
        scene=self.get(scene_id)
        if type(seed) is not int or not 0<=seed<=2**32-1:raise ValueError('seed must be an unsigned 32-bit integer')
        return validate_parameters(scene,parameters)

    def generate(self, scene_id, output_path, *, seed=0, parameters=None):
        scene=self.get(scene_id)
        self.validate(scene_id,seed=seed,parameters=parameters)
        if scene_id in self._scenes:return generate_world(scene,output_path,seed=seed,parameters=parameters)
        if scene_id.startswith('U_'):
            path=self.assets.world_path(scene_id[2:]);context=self.assets.dependency_context()
        else:
            path=self._legacy_path(scene_id[2:]);context=dict(search_paths=self._legacy_roots())
            if path is None or not path.is_file():raise ValueError('BLOCKED: historical source missing')
        report=inspect_sdf(path,**context)
        if report['status']!='PASS':raise ValueError('BLOCKED: source resources/plugins incomplete; inspect dependency report')
        destination=Path(output_path);destination.parent.mkdir(parents=True,exist_ok=True)
        dependency_dir=destination.parent/(destination.stem+'-resources')
        references={}
        for ref in report['references']:
            if ref['exists'] and ref['resolved']:
                references.setdefault(ref['source'],{})[ref['uri']]=Path(ref['resolved']).resolve()
        written={}

        def model_file(target):
            return model_sdf(target) if target.is_dir() else target

        def rewrite(source, target):
            source=source.resolve()
            if source in written:return written[source]
            written[source]=target
            tree=ET.parse(source)
            for material in tree.findall('.//material'):
                for script in material.findall('script'):
                    if script.findtext('uri')=='file://media/materials/scripts/gazebo.material' and (material.find('diffuse') is not None or material.find('pbr') is not None):material.remove(script)
            world=tree.find('world')
            if world is not None:
                physics=world.find('physics')
                gravity=None if physics is None else physics.find('gravity')
                if gravity is not None:physics.remove(gravity);world.append(gravity)
            for link in tree.findall('.//link'):
                collisions={item.get('name') for item in link.findall('collision')}
                for visual in link.findall('visual'):
                    if visual.get('name') in collisions:visual.set('name','visual_'+visual.get('name'))
            for element in tree.iter():
                uri=(element.text or '').strip()
                resolved=references.get(str(source),{}).get(uri)
                if element.tag not in ('uri','albedo_map','normal_map','metalness_map','roughness_map','emissive_map') or resolved is None:continue
                candidate=model_file(resolved)
                if candidate.suffix.lower()=='.sdf':
                    dependency_dir.mkdir(exist_ok=True)
                    filename=hashlib.sha256(str(candidate).encode()).hexdigest()[:16]+'.sdf'
                    candidate=rewrite(candidate,dependency_dir/filename)
                element.text=candidate.resolve().as_uri()
            tree.write(target,encoding='utf-8',xml_declaration=True)
            return target
        return rewrite(path,destination)
