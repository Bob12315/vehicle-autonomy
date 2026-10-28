"""Agent-local registry, process ownership, dependency and readiness checks."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import shutil
import selectors
import signal
import socket
import subprocess
import sys
from threading import Event, RLock, Thread
import time
from uuid import uuid4

from .schema import compatibility, context, fingerprint, identifier, manifest, object_fields


class LocalTools:
    def __init__(self, manifests, store, *, environment=None):
        self.store = store; self.env = dict(os.environ if environment is None else environment)
        self.registry = {}
        for item in manifests:
            item = manifest(item)
            if item['id'] in self.registry: raise ValueError('duplicate tool ID')
            self.registry[item['id']] = item
        if len(self.registry) > 48: raise ValueError('tool budget exceeded')
        self.lock = RLock(); self.instances = {}; self.readers = []; self.closed = Event()
        self.observations = {}; self.counter = 0
        self.monitor = Thread(target=self._monitor, name='tool-health', daemon=True); self.monitor.start()

    def _environment(self, profile, ctx):
        env = dict(self.env); env.update(profile['env'])
        env.update(ROS_NAMESPACE=ctx['ros_namespace'], ROS_DOMAIN_ID=str(ctx['ros_domain_id']))
        env.update(VAF_VEHICLE_ID=ctx['vehicle_id'],VAF_VEHICLE_TYPE=ctx['vehicle_type'],VAF_ENVIRONMENT=ctx['environment'])
        return env

    @staticmethod
    def _expand(command, ctx):
        # Only these validated scalar fields can enter trusted argv templates.
        return [v.replace('{namespace}/',ctx['ros_namespace'].rstrip('/')+'/').replace('{namespace}', ctx['ros_namespace']).replace('{domain_id}', str(ctx['ros_domain_id'])) for v in command]

    @staticmethod
    def _which(value, env):
        return shutil.which(value, path=env.get('PATH', os.defpath))

    def check(self, tool_id, profile_id):
        tool = self.registry[identifier(tool_id)]; profile = tool['profiles'][identifier(profile_id)]
        env = dict(self.env); env.update(profile['env'])
        missing = []
        os_id = platform.freedesktop_os_release() if hasattr(platform, 'freedesktop_os_release') else {}
        version = os_id.get('ID', '') + '-' + os_id.get('VERSION_ID', '')
        if 'linux' not in tool['supported_os'] and version not in tool['supported_os']: missing.append('OS: ' + version)
        deps = tool['install_detection'] + tool['dependencies'] + profile.get('requires', [])
        if profile['argv']: deps += [dict(kind='executable', value=profile['argv'][0])]
        for dep in deps:
            kind, value = dep['kind'], dep['value']
            present = (self._which(value, env) is not None if kind == 'executable' else
                       bool(env.get(value)) if kind == 'environment' else
                       Path(value).is_file() if kind == 'file' else Path(value).is_dir())
            if not present: missing.append(kind + ': ' + value)
        desktop = bool(env.get('DISPLAY') or env.get('WAYLAND_DISPLAY'))
        if 'desktop' in tool['permissions'] and not desktop: missing.append('desktop session: choose a Desktop Agent with DISPLAY/WAYLAND_DISPLAY')
        if tool['id'] == 'qgroundcontrol' and (profile['connection'].get('telemetry_only') is not True or 'telemetry_only' not in tool['permissions']):
            missing.append('QGC requires an operator-provisioned telemetry-only relay profile')
        current=self.instances.get(tool_id)
        if not current or current['profile_id']!=profile_id or current['process'].poll() is not None:
            for port in profile.get('exclusive_ports',[]):
                with socket.socket(socket.AF_INET,socket.SOCK_STREAM if port['protocol']=='tcp' else socket.SOCK_DGRAM) as sock:
                    if port['protocol']=='tcp':sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                    try:sock.bind(('127.0.0.1',port['port']))
                    except OSError:missing.append(f"busy simulation {port['protocol']} port: {port['port']} (no external process stopped)")
        result = dict(installed=not any(not m.startswith(('desktop session:','busy simulation ')) for m in missing),
                      launchable=not missing and profile.get('observe_only') is not True,
                      missing=missing, desktop=desktop)
        return result

    def discover(self, tool_id):
        tool = self.registry[tool_id]
        names = set(tool.get('process_names', []))
        commands = [p['argv'] for p in tool['profiles'].values() if p['argv']]
        # Executable identities only; never inspect arbitrary files or signal a
        # discovered PID. Exclude this Agent's supervisor-owned tools.
        owned = {v.get('pid') for v in self.instances.values()}
        found = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit() or int(entry.name) in owned: continue
            try:
                if entry.stat().st_uid != os.getuid() or os.getpgid(int(entry.name)) in owned: continue
                executable = (entry / 'exe').readlink().name
                raw=(entry/'cmdline').read_bytes()[:16384].split(b'\0')
                args=[v.decode(errors='replace') for v in raw if v]
                matched=executable in names
                for command in commands:
                    # Match trusted argv prefixes, including script interpreters.
                    # A Python/ROS process sharing only an interpreter is not
                    # automatically the same registered tool.
                    for offset in (0,1):
                        if len(args)<len(command)+offset:continue
                        if Path(args[offset]).name!=Path(command[0]).name:continue
                        if all(a==b for a,b in zip(args[offset+1:offset+len(command)],command[1:]) if '{namespace}' not in b and '{domain_id}' not in b):matched=True
                if matched: found.append(int(entry.name))
            except (OSError, ValueError): pass
            if len(found) >= 16: break
        return found

    def _record(self, tool_id, profile_id, ctx, state):
        self.counter += 1
        return dict(tool_id=tool_id, profile_id=profile_id, context=compatibility(ctx),
                    instance_id=f'{os.getpid()}-{self.counter}', state=state, owned=True,
                    process_running=False, service_health='UNKNOWN', ready=False,
                    connection='UNKNOWN', error=None, pid=None, returncode=None,
                    cleanup_confirmed=True, started_at=time.time(), started_mono=time.monotonic(), logs=deque(maxlen=24),
                    process=None, last_probe=0., stopping=False,startup_complete=False,ownership_marker=uuid4().hex)

    def execute(self, operation, tool_id, profile_id, ctx):
        ctx = context(ctx)
        with self.lock:
            tool = self.registry[identifier(tool_id)]; p = tool['profiles'][identifier(profile_id)]
            self.store.audit('tool.intent', operation_name=operation, tool=tool_id, profile=profile_id, vehicle=ctx['vehicle_id'])
            try:
                if operation == 'check': return self.check(tool_id, profile_id)
                if operation == 'connect':
                    return dict(observed=self.discover(tool_id), connection=p['connection'], owned=False,connection_established=False,
                                instruction='Observation/connection metadata only; configure the registered application endpoint explicitly')
                current = self.instances.get(tool_id)
                active = current and current['process'] and current['process'].poll() is None
                if operation in ('stop', 'restart'):
                    if not current or not active:
                        if current and not current['cleanup_confirmed']:raise ValueError('supervisor cleanup unconfirmed; owned instance remains UNKNOWN')
                        if operation == 'stop': return dict(stopped=True, owned=bool(current))
                    else:
                        if current['profile_id'] != profile_id or current['context'] != compatibility(ctx):
                            raise ValueError('owned profile/context mismatch')
                        if operation == 'restart': current['restart'] = (profile_id, ctx)
                        self._stop(current)
                        return self._view(current)
                if operation not in ('launch', 'restart', 'open'): raise ValueError('unsupported tool operation')
                if active:
                    if current['stopping'] or current['profile_id'] != profile_id or current['context'] != compatibility(ctx):
                        raise ValueError('tool is stopping or incompatible; explicit stop required')
                    if operation == 'open': raise ValueError('window activation unsupported; the existing window is on the Agent desktop')
                    return self._view(current)
                if current and not current['cleanup_confirmed']: raise ValueError('prior process cleanup unconfirmed')
                if self.discover(tool_id): raise ValueError('external process discovered; observation/connection only')
                check = self.check(tool_id, profile_id)
                if not check['launchable']:
                    raise ValueError('Missing Dependency: ' + '; '.join(check['missing']) if check['missing'] else 'profile is observation-only')
                command = self._expand(p['argv'], ctx)
                exe = self._which(command[0], self._environment(p, ctx))
                command[0] = exe
                record = self._record(tool_id, profile_id, ctx, 'STARTING')
                working=p.get('cwd')
                if not working:
                    parent=self.store.root/'instances';parent.mkdir(mode=0o700,exist_ok=True)
                    if parent.is_symlink():raise ValueError('instance directory symlink rejected')
                    working=parent/record['instance_id'];working.mkdir(mode=0o700)
                configuration=json.dumps(dict(argv=command,env=dict(self._environment(p,ctx),VAF_TOOL_OWNERSHIP=record['ownership_marker']),
                    cwd=str(working),stop_timeout_s=p.get('stop_timeout_s',3)))+'\n'
                if len(configuration.encode())>262000:raise ValueError('bounded supervisor configuration exceeded')
                # Audit precedes spawn. Profile contents never originate in HTTP.
                process = subprocess.Popen([sys.executable, '-m', 'vehicle_autonomy.app.tools.process_worker'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    start_new_session=True, text=True, bufsize=1)
                record['process'] = process; record['cleanup_confirmed'] = False
                self.instances[tool_id] = record
                reader = Thread(target=self._read, args=(record,), daemon=True, name='tool-output')
                self.readers.append(reader); reader.start()
                try:process.stdin.write(configuration);process.stdin.flush()
                except (OSError,ValueError):self._stop(record);raise
                return self._view(record)
            except Exception as exc:
                self.store.audit('tool.rejected', tool=tool_id, error=str(exc)[:500])
                raise

    def _stop(self, record):
        if record['stopping']: return
        record.update(stopping=True, state='STOPPING', ready=False, service_health='UNKNOWN')
        process = record['process']
        try: process.stdin.write('stop\n'); process.stdin.flush()
        except (BrokenPipeError, OSError): pass

    def _read(self, record):
        process = record['process']; exit_seen = False
        try:
            for line in process.stdout:
                event = json.loads(line)
                with self.lock:
                    if event['event'] == 'spawned':
                        record.update(pid=event['pid'], process_running=True, state='STOPPING' if record['stopping'] else 'RUNNING')
                        self.store.audit('tool.running', tool=record['tool_id'], instance_id=record['instance_id'], pid=event['pid'])
                    elif event['event'] == 'log': record['logs'].append(event['text'][:2048])
                    elif event['event'] == 'error': record['error'] = event['error']
                    elif event['event'] == 'exit':
                        exit_seen = True
                        record.update(process_running=False, ready=False, service_health='UNKNOWN',
                            connection='DISCONNECTED', returncode=event['returncode'], cleanup_confirmed=event['cleanup_confirmed'])
                        record['state'] = ('STOPPED' if record['stopping'] and not record['error'] else 'FAILED') if event['cleanup_confirmed'] else 'UNKNOWN'
                        if not record['stopping'] and not record['error']: record['error'] = 'process exited unexpectedly'
                        self.store.audit('tool.exit', tool=record['tool_id'], state=record['state'], returncode=event['returncode'], cleanup_confirmed=event['cleanup_confirmed'])
        except Exception as exc:
            with self.lock:
                record['error'] = 'supervisor output/audit: ' + type(exc).__name__
                self._stop(record)
        finally:
            process.stdout.close()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait();exit_seen=False
            process.stdin.close()
            with self.lock:
                if not exit_seen:record.update(state='UNKNOWN',cleanup_confirmed=False,ready=False,service_health='UNKNOWN',connection='UNKNOWN',error='supervisor lost; cleanup unconfirmed')
            if not exit_seen:
                clean=self._cleanup_lost(record)
                with self.lock:
                    record.update(state='FAILED' if clean else 'UNKNOWN',cleanup_confirmed=clean,process_running=False if clean else None,
                        error='supervisor lost; owned processes cleaned' if clean else 'supervisor lost; cleanup unconfirmed')
                    try:self.store.audit('tool.supervisor_lost',tool=record['tool_id'],cleanup_confirmed=clean)
                    except OSError:record['error']+='; audit unavailable'

    def _cleanup_lost(self,record):
        """Only signal processes with this instance's unguessable inherited marker.

        pidfds pin each actual process across PID reuse. Matching a program name
        or an old process-group number never authorizes a fallback kill.
        """
        marker=('VAF_TOOL_OWNERSHIP='+record['ownership_marker']).encode()
        def owned():
            result=[]
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():continue
                try:
                    if entry.stat().st_uid==os.getuid() and marker in (entry/'environ').read_bytes().split(b'\0'):result.append(int(entry.name))
                except OSError:pass
            return result
        end=time.monotonic()+3;seen=set()
        while time.monotonic()<end:
            pids=owned();seen.update(pids)
            for pid in pids:
                descriptor=None
                try:
                    descriptor=os.pidfd_open(pid)
                    if marker in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'):signal.pidfd_send_signal(descriptor,signal.SIGKILL)
                except OSError:pass
                finally:
                    if descriptor is not None:os.close(descriptor)
            for pid in seen|({record['pid']} if record['pid'] else set()):
                try:os.waitpid(pid,os.WNOHANG)
                except ChildProcessError:pass
            if not pids:
                if record['pid'] is None:return True
                try:os.killpg(record['pid'],0)
                except ProcessLookupError:return True
            time.sleep(.04)
        return False

    def _probe(self, p, ctx, env):
        if p is None: return None
        command = self._expand(p['argv'], ctx)
        command[0] = self._which(command[0], env) or command[0]
        process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
        output = bytearray(); end = time.monotonic() + p.get('timeout_s', 2)
        try:
            while time.monotonic() < end:
                for key, _ in selector.select(.05):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk: selector.unregister(key.fileobj)
                    else: output.extend(chunk)
                if len(output) > 65536: return False
                if process.poll() is not None and not selector.get_map():
                    text = output.decode(errors='replace')
                    return process.returncode == 0 and all(v.replace('{namespace}', ctx['ros_namespace']) in text for v in p['contains'])
            return False
        finally:
            selector.close()
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait(); process.stdout.close()

    def _monitor(self):
        while not self.closed.wait(.1):
            with self.lock: records = list(self.instances.values())
            for record in records:
                p = self.registry[record['tool_id']]['profiles'][record['profile_id']]
                with self.lock:
                    if record.get('restart') and not record['process_running'] and record['process'].poll() is not None and record['cleanup_confirmed']:
                        profile, ctx = record.pop('restart')
                        try: self.execute('launch', record['tool_id'], profile, ctx)
                        except Exception as exc: record['error'] = str(exc)[:500]
                        continue
                    if record['stopping'] or not record['process_running'] or time.monotonic() - record['last_probe'] < 1: continue
                    record['last_probe'] = time.monotonic()
                try:
                    env = self._environment(p, record['context'])
                    health = self._probe(p['health'], record['context'], env)
                    ready = self._probe(p['ready'], record['context'], env)
                    with self.lock:
                        if record['stopping'] or not record['process_running']: continue
                        record.update(service_health='UNKNOWN' if health is None else 'HEALTHY' if health else 'UNHEALTHY',
                                      ready=ready is True and health is not False,
                                      connection='CONNECTED' if ready is True and health is not False else 'UNKNOWN',
                                      state='READY' if ready is True and health is not False else 'RUNNING')
                        if record['ready']:
                            record['startup_complete'] = True
                            if str(record['error'] or '').startswith('health probe:'): record['error'] = None
                        if p['ready'] and not record['startup_complete'] and time.monotonic() - record['started_mono'] > p.get('startup_timeout_s', 20):
                            record['error'] = 'startup/readiness timeout'; self._stop(record)
                except Exception as exc:
                    with self.lock:
                        if record['stopping'] or not record['process_running']: continue
                        record.update(service_health='UNHEALTHY', ready=False, connection='UNKNOWN',state='RUNNING',error='health probe: ' + type(exc).__name__)
                        if p['ready'] and not record['startup_complete'] and time.monotonic()-record['started_mono']>p.get('startup_timeout_s',20):
                            record['error']='startup/readiness timeout after probe failure';self._stop(record)

    @staticmethod
    def _view(record):
        resource=dict(rss_bytes=None,cpu_time_s=None,scope='primary process only')
        if record['pid'] and record['process_running']:
            try:
                status=Path(f"/proc/{record['pid']}/status").read_text().splitlines()
                rss=next(line.split()[1] for line in status if line.startswith('VmRSS:'))
                fields=Path(f"/proc/{record['pid']}/stat").read_text().rsplit(')',1)[1].split()
                resource.update(rss_bytes=int(rss)*1024,cpu_time_s=(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK'))
            except (OSError,StopIteration,ValueError):pass
        return {k: deepcopy(v) for k, v in record.items() if k not in ('process', 'logs', 'last_probe', 'restart', 'started_mono','startup_complete','ownership_marker')} | dict(logs=list(record['logs']),resource=resource)

    def snapshot(self):
        with self.lock:
            return [dict(manifest=self.public_manifest(tool), checks={name:self.check(tool_id, name) for name in tool['profiles']},
                external_pids=self.discover(tool_id), instance=None if tool_id not in self.instances else self._view(self.instances[tool_id]))
                for tool_id, tool in self.registry.items()]

    @staticmethod
    def public_manifest(tool):
        result = {k:deepcopy(tool[k]) for k in ('schema', 'id', 'name', 'type', 'version', 'supported_os', 'integrations', 'agent_requirements', 'permissions', 'stop_strategy')}
        result['profiles'] = {name:dict(connection=deepcopy(p['connection']), readiness_probe=p['ready'] is not None,
            observe_only=p.get('observe_only', False)) for name, p in tool['profiles'].items()}
        return result

    def close(self):
        self.closed.set()
        with self.lock:
            for record in self.instances.values():
                if record['process'].poll() is None: self._stop(record)
        for reader in self.readers: reader.join(20)
        self.monitor.join(12)
        if any(reader.is_alive() for reader in self.readers) or self.monitor.is_alive():
            raise RuntimeError('tool worker cleanup unconfirmed')
