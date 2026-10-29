"""Locked third-party asset cache and dependency inspection.

Only entries from the trusted lock can be downloaded. Fuel references must have
an exact version and a lock mapping to a local model; unresolved references stay
missing rather than fetching a moving latest version during a run.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from vehicle_autonomy._resources import resource_root


MAX_FILE_BYTES=128*1024*1024


def digest(path):
    hasher=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):hasher.update(chunk)
    return hasher.hexdigest()


def _relative(value):
    path=Path(value)
    if path.is_absolute() or not path.parts or '..' in path.parts or '\\' in value:raise ValueError('asset paths must remain inside their installation')
    return path


def model_sdf(directory):
    """Select the highest model.config SDF version supported by Harmonic."""
    directory=Path(directory)
    config=directory/'model.config'
    if not config.is_file():return directory/'model.sdf'
    candidates=[]
    for node in ET.parse(config).findall('.//sdf'):
        if not node.text:continue
        try:version=tuple(int(part) for part in node.get('version','1.0').split('.'))
        except ValueError:continue
        if version<=(1,10):candidates.append((version,directory/node.text.strip()))
    return max(candidates,key=lambda item:item[0])[1] if candidates else directory/'model.sdf'


class AssetManager:
    def __init__(self, cache_dir, *, lock_path=None):
        self.root=Path(cache_dir).expanduser().resolve()
        self.lock_path=Path(lock_path) if lock_path else resource_root()/'simulation/scenarios/assets.lock.json'
        lock=json.loads(self.lock_path.read_text())
        if lock.get('schema')!=1:raise ValueError('unsupported asset lock schema')
        self._entries={entry['id']:entry for entry in lock['assets']}
        self._status_cache={}
        if len(self._entries)!=len(lock['assets']):raise ValueError('duplicate locked asset')
        for entry in self._entries.values():
            if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}',entry['id']):raise ValueError('invalid locked asset id')
            _relative(entry.get('world','world.sdf'))
            if entry.get('build_directory'):_relative(entry['build_directory'])
            for file in entry['files']:
                _relative(file['path'])
                url=urllib.parse.urlsplit(file['url'])
                if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError('locked downloads require HTTPS')
                if not re.fullmatch(r'[0-9a-f]{64}',file['sha256']):raise ValueError('locked SHA256 required')
                if type(file['size']) is not int or not 0<=file['size']<=MAX_FILE_BYTES:raise ValueError('locked file size exceeds bound')

        def validate_dependencies(identifier, trail):
            if identifier in trail:raise ValueError('cyclic locked asset dependencies')
            for dependency in self._entries[identifier].get('requires',[]):
                if dependency not in self._entries:raise ValueError('missing locked dependency')
                validate_dependencies(dependency,trail+(identifier,))
        for identifier in self._entries:validate_dependencies(identifier,())

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True,exist_ok=True)
        with (self.root/'.asset-manager.lock').open('a') as stream:
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('asset cache is in use by a scene or another mutation') from None
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def acquire_usage(self):
        """Retain a shared cache lease until the scene has retired its readers."""
        self.root.mkdir(parents=True,exist_ok=True)
        stream=(self.root/'.asset-manager.lock').open('a')
        try:fcntl.flock(stream,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:
            stream.close()
            raise ValueError('asset cache mutation is running; retry scene creation after it completes') from None
        return stream

    def _get(self,identifier):
        try:return self._entries[identifier]
        except KeyError:raise ValueError('unknown locked asset identifier') from None

    def list_assets(self):return [self.status(identifier) for identifier in self._entries]

    def status(self, identifier):
        entry=self._get(identifier)
        installed=self.root/'installed'/identifier
        def stamp(path):
            try:
                info=path.stat();return (str(path),info.st_size,info.st_mtime_ns)
            except OSError:return (str(path),None,None)
        checked=[entry]+[self._entries[key] for key in entry.get('requires',[])]
        signature=tuple(stamp(self.root/'installed'/item['id']/_relative(file['path'])) for item in checked for file in item['files'])
        for item in self._entries.values():
            if item.get('build_directory'):
                directory=self.root/_relative(item['build_directory'])
                signature+=(stamp(directory/'build-manifest.json'),)
                signature+=tuple(stamp(binary) for binary in sorted(directory.glob('*.so')))
        signature+=(os.environ.get('GZ_SIM_RESOURCE_PATH',''),os.environ.get('GZ_SIM_SYSTEM_PLUGIN_PATH',''))
        previous=self._status_cache.get(identifier)
        if previous is not None and previous[0]==signature:return deepcopy(previous[1])
        files=[]
        for file in entry['files']:
            path=installed/_relative(file['path'])
            state='MISSING' if not path.is_file() else 'PASS' if path.stat().st_size==file['size'] and digest(path)==file['sha256'] else 'CORRUPT'
            files.append(dict(path=file['path'],status=state))
        complete=all(file['status']=='PASS' for file in files)
        result=deepcopy(entry)
        result.update(installed=complete,status='INSTALLED' if complete else 'CORRUPT' if any(file['status']=='CORRUPT' for file in files) else 'AVAILABLE',file_status=files)
        world=installed/entry.get('world','world.sdf')
        context=self.dependency_context()
        result['dependencies']=inspect_sdf(world,**context) if complete and world.is_file() else None
        result['ready']=bool(complete and result['dependencies'] and result['dependencies']['status']=='PASS')
        self._status_cache[identifier]=(signature,deepcopy(result))
        return result

    def install(self, identifier, *, cancelled=lambda:False):
        entry=self._get(identifier)
        for dependency in entry.get('requires',[]):
            if cancelled():raise InterruptedError('asset installation cancelled')
            self.install(dependency,cancelled=cancelled)
        with self._locked():
            if cancelled():raise InterruptedError('asset installation cancelled')
            blobs=self.root/'blobs';blobs.mkdir(exist_ok=True)
            temporary=Path(tempfile.mkdtemp(prefix='install-',dir=self.root))
            try:
                for file in entry['files']:
                    if cancelled():raise InterruptedError('asset installation cancelled')
                    blob=blobs/file['sha256']
                    if not blob.is_file() or digest(blob)!=file['sha256']:
                        staging=temporary/'download'
                        request=urllib.request.Request(file['url'],headers={'User-Agent':'Vehicle-Autonomy-Asset-Manager/1'})
                        with urllib.request.urlopen(request,timeout=30) as response, staging.open('wb') as output:
                            if urllib.parse.urlsplit(response.url).scheme!='https':raise ValueError('HTTPS redirect required')
                            count=0
                            while True:
                                if cancelled():raise InterruptedError('asset installation cancelled')
                                block=response.read(min(1024*1024,file['size']+1-count))
                                if not block:break
                                count+=len(block)
                                if count>file['size']:raise ValueError('download exceeds locked size')
                                output.write(block)
                        if staging.stat().st_size!=file['size'] or digest(staging)!=file['sha256']:raise ValueError('asset SHA256/size mismatch')
                        os.replace(staging,blob)
                    target=temporary/'tree'/_relative(file['path']);target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(blob,target)
                if cancelled():raise InterruptedError('asset installation cancelled')
                target=self.root/'installed'/identifier;target.parent.mkdir(exist_ok=True)
                # Existing installs stay usable until every new file has verified.
                backup=self.root/('backup-'+identifier)
                if backup.exists():shutil.rmtree(backup)
                if target.exists():os.replace(target,backup)
                try:os.replace(temporary/'tree',target)
                except BaseException:
                    if backup.exists():os.replace(backup,target)
                    raise
                if backup.exists():shutil.rmtree(backup)
            finally:shutil.rmtree(temporary,ignore_errors=True)
        self._status_cache.clear()
        return self.status(identifier)

    def uninstall(self, identifier):
        self._get(identifier)
        with self._locked():
            target=self.root/'installed'/identifier
            if target.is_symlink():raise ValueError('refuse symlink installation')
            if target.exists():shutil.rmtree(target)
        self._status_cache.clear()
        return self.status(identifier)

    @property
    def plugin_paths(self):
        paths=[]
        for entry in self._entries.values():
            if entry.get('kind')!='plugin' or not entry.get('build_directory'):continue
            directory=self.root/_relative(entry['build_directory'])
            manifest=directory/'build-manifest.json'
            if not manifest.is_file():continue
            try:
                record=json.loads(manifest.read_text())
                binary=directory/_relative(record['binary_name'])
                source_matches=all((self.root/'installed'/entry['id']/_relative(file['path'])).is_file() and digest(self.root/'installed'/entry['id']/_relative(file['path']))==file['sha256'] for file in entry['files'])
                if record['source_version']==entry['version'] and record['gz_sim_major']==8 and binary.is_file() and digest(binary)==record['binary_sha256'] and source_matches:paths.append(directory)
            except (OSError,ValueError,KeyError):continue
        return paths

    def dependency_context(self):
        models={};pins={};names={};roots=[]
        for entry in self._entries.values():
            installed=self.root/'installed'/entry['id']
            roots.append(installed)
            if entry.get('fuel_uri'):
                canonical=entry['fuel_uri']
                models[canonical]=installed
                for alias in entry.get('fuel_aliases',[]):pins[alias]=canonical
                names[entry['name']]=installed
        return dict(search_paths=roots,fuel_models=models,fuel_pins=pins,model_paths=names,plugin_paths=self.plugin_paths)

    def world_path(self,identifier):
        entry=self._get(identifier)
        status=self.status(identifier)
        if not status['ready']:raise ValueError('BLOCKED: asset resources/plugins incomplete; inspect dependency report')
        return self.root/'installed'/identifier/entry.get('world','world.sdf')


def inspect_sdf(path, *, search_paths=(), fuel_models=None, fuel_pins=None, model_paths=None, plugin_paths=()):
    """Recursively inspect model/include/mesh and texture references without fetching.

    fuel_models is a trusted versioned-URI -> local model directory mapping.
    Plugin presence is a file check, not proof that its ABI or behavior works.
    """
    path=Path(path)
    roots=[Path(root) for root in search_paths]
    roots.extend(Path(item) for item in os.environ.get('GZ_SIM_RESOURCE_PATH','').split(os.pathsep) if item)
    normalize=lambda value:urllib.parse.unquote(value).rstrip('/').casefold()
    fuel_models={normalize(key):Path(value) for key,value in (fuel_models or {}).items()}
    fuel_pins={normalize(key):value for key,value in (fuel_pins or {}).items()}
    model_paths={key.casefold():Path(value) for key,value in (model_paths or {}).items()}
    references=[];missing=[];plugins=[];visited=set();errors=[];adaptations=[]
    plugin_roots=[Path(item) for item in plugin_paths]+[Path('/usr/lib/x86_64-linux-gnu/gz-sim-8/plugins'),Path('/usr/lib/aarch64-linux-gnu/gz-sim-8/plugins')]
    plugin_roots.extend(Path(item) for item in os.environ.get('GZ_SIM_SYSTEM_PLUGIN_PATH','').split(os.pathsep) if item)

    def resolve(uri,source):
        parsed=urllib.parse.urlsplit(uri)
        if parsed.scheme in ('http','https'):
            canonical=fuel_pins.get(normalize(uri),uri)
            pinned=bool(re.search(r'/models/[^/]+/[0-9]+/?$',canonical,re.I))
            candidate=fuel_models.get(normalize(canonical)) if pinned else None
            return Path(candidate) if candidate else None, 'fuel-pinned' if pinned else 'remote-unlocked'
        if uri.startswith('model://'):
            relative=uri[len('model://'):]
            name,separator,tail=relative.partition('/')
            if name.casefold() in model_paths:
                target=model_paths[name.casefold()]/tail if separator else model_paths[name.casefold()]
                if target.exists():return target,'model-pinned'
            return next((root/relative for root in roots if (root/relative).exists()),None),'model'
        if uri.startswith('file://'):return Path(urllib.request.url2pathname(parsed.path)),'file'
        if parsed.scheme:return None,'unsupported-uri'
        candidate=Path(uri)
        if candidate.is_absolute():
            if not candidate.exists() and (source.parent/str(candidate).lstrip('/')).exists():return source.parent/str(candidate).lstrip('/'),'legacy-root-relative'
            return candidate,'absolute'
        return next((p for p in [source.parent/candidate]+[root/candidate for root in roots] if p.exists()),source.parent/candidate),'relative'

    def scan(source):
        source=source.resolve()
        if source in visited:return
        visited.add(source)
        if len(visited)>512:errors.append('dependency recursion/file limit exceeded');return
        try:tree=ET.parse(source)
        except (OSError,ET.ParseError) as exc:errors.append(str(source)+': '+str(exc));return
        for plugin in tree.findall('.//plugin'):
            filename=plugin.get('filename','')
            names=(filename,filename+'.so','lib'+filename+'.so')
            available=any((root/name).is_file() for root in plugin_roots for name in names)
            classic=filename.startswith('libgazebo') or plugin.get('name','').startswith('gazebo::')
            plugins.append(dict(filename=filename,name=plugin.get('name'),available=available,classic=classic))
            if classic or not available:missing.append(dict(uri=filename,reason='Gazebo Classic plugin requires migration' if classic else 'plugin file not found'))
        parents={node:parent for parent in tree.iter() for node in parent}
        tags={'uri','albedo_map','normal_map','metalness_map','roughness_map','environment_map','emissive_map'}
        for element in tree.iter():
            tag=element.tag.rsplit('}',1)[-1]
            if tag not in tags or not (element.text or '').strip():continue
            uri=element.text.strip()
            owner=parents.get(element);material=parents.get(owner) if owner is not None else None
            if uri=='file://media/materials/scripts/gazebo.material' and owner is not None and owner.tag=='script' and material is not None and (material.find('diffuse') is not None or material.find('pbr') is not None):
                adaptations.append(dict(source=str(source),kind='remove_optional_classic_material_script',reason='retain existing diffuse/PBR fallback for Harmonic'))
                continue
            target,kind=resolve(uri,source)
            exists=target is not None and target.exists()
            references.append(dict(uri=uri,kind=kind,resolved=str(target) if target else None,exists=exists,source=str(source)))
            if not exists:missing.append(dict(uri=uri,reason='unresolved resource',source=str(source)));continue
            if target.is_dir():
                try:scan(model_sdf(target))
                except ET.ParseError as exc:errors.append(str(exc))
            elif target.suffix.lower()=='.sdf':scan(target)
            elif target.suffix.lower()=='.dae':
                try:
                    for image in ET.parse(target).iter():
                        if image.tag.rsplit('}',1)[-1]!='image':continue
                        for texture in image:
                            if texture.tag.rsplit('}',1)[-1]=='init_from' and texture.text and not texture.text.startswith('#'):
                                ref=target.parent/urllib.parse.unquote(texture.text.strip())
                                if not ref.exists():missing.append(dict(uri=str(ref),reason='Collada texture missing',source=str(target)))
                except ET.ParseError as exc:errors.append(str(exc))
    scan(path)
    return dict(status='PASS' if not missing and not errors else 'BLOCKED',references=references,missing=missing,plugins=plugins,errors=errors,checked_files=len(visited),adaptations=adaptations,scope='dependency and plugin file presence; Gazebo execution required separately')
