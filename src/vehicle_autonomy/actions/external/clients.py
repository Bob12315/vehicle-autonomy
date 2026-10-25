"""Bounded external process/API clients; no vehicle protocol dependencies."""
import json
import os
from pathlib import Path
from queue import Empty,Queue
import subprocess
from threading import RLock,Thread
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.engine.action.external_lifecycle import register_job,require_job_scope


class ProcessJob:
    @staticmethod
    def _locator(command,env):
        # The supported process client is the known ROS worker. Arbitrary
        # commands cannot supply a claimed endpoint that differs from what is
        # actually launched. Custom SDK work uses the managed Native contract.
        import argparse
        from vehicle_autonomy._resources import resource_root
        if (len(command)<5 or Path(command[0]).resolve()!=(resource_root()/'scripts/with_ros2.sh').resolve()
                or command[1]!='/usr/bin/python3'):raise ActionAdmissionRejected('unregistered external worker command')
        if command[2:4]==['-m','vehicle_autonomy.actions.external.ros_worker']:args=command[4:]
        elif Path(command[2]).resolve()==Path(__file__).with_name('ros_worker.py').resolve():args=command[3:]
        else:raise ActionAdmissionRejected('external worker provenance not verified')
        parser=argparse.ArgumentParser(exit_on_error=False,add_help=False)
        parser.add_argument('--name',required=True);parser.add_argument('--duration');parser.add_argument('--result-timeout');parser.add_argument('--service',action='store_true')
        if args.count('--name')!=1:raise ActionAdmissionRejected('one canonical ROS endpoint required')
        try:parsed=parser.parse_args(args);domain=int((env or os.environ)['ROS_DOMAIN_ID']);name=parsed.name
        except (SystemExit,ValueError,KeyError,argparse.ArgumentError) as exc:
            raise ActionAdmissionRejected('invalid external worker identity arguments') from exc
        if not 0<=domain<=232 or not name.startswith('/') or '//' in name or '..' in name or name.endswith('/'):
            raise ActionAdmissionRejected('canonical local ROS identity required')
        return f'ros2:{domain}:{name}'

    def __init__(self,command,*,env=None):
        self._lock=RLock();self._status={'state':'RUNNING'};self._done=False
        register_job(self,'ros2',self._locator(command,env))
        self.process=subprocess.Popen(command,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,bufsize=1,start_new_session=True)
        self._reader=Thread(target=self._read,daemon=True);self._reader.start()
    def _read(self):
        try:
            for line in iter(lambda:self.process.stdout.readline(65537),''):
                if len(line)>65536:raise ValueError('external response budget')
                value=json.loads(line)
                if value.get('state') not in ('RUNNING','SUCCEEDED','FAILED','CANCELLED','UNKNOWN'):raise ValueError('external state contract')
                with self._lock:
                    if self._status['state']=='RUNNING':self._status=value
            with self._lock:
                if self._status['state']=='RUNNING':self._status={'state':'UNKNOWN','error':'external worker disconnected'}
        except Exception:
            with self._lock:self._status={'state':'UNKNOWN','error':'external worker protocol failed'}
    def poll(self):
        with self._lock:return dict(self._status)
    def cancel(self):
        try:self.process.stdin.write('cancel\n');self.process.stdin.flush()
        except (BrokenPipeError,OSError):pass
    def close(self):
        if self.process.poll() is None:
            try:self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)
        self._reader.join(1)
        self.process.stdout.close();self.process.stdin.close()


class ApiJob:
    """Explicit configured job API: POST jobs, GET status, POST cancel.

    A lost response cannot prove whether the external operation ran. Timeouts
    therefore retain UNKNOWN; killing a local client never claims remote stop.
    """
    def __init__(self,base,parameters,*,token=None):
        self._validate_base(base)
        self.base=base.rstrip('/');self.token=token;self._lock=RLock();self._status={'state':'RUNNING'}
        self._cancel=False;self._stop=False;self._id=None
        self._recovery_thread=None;self._last_recovery=0.
        require_job_scope()
        try:identity=self.identity(self.base,token=token)
        except Exception as exc:raise RuntimeError('provider identity unavailable; managed admission incomplete') from exc
        register_job(self,'http_job',self.base,provider_id=identity['provider_id'],provider_epoch=identity['provider_epoch'])
        self._thread=Thread(target=self._run,args=(parameters,),daemon=True);self._thread.start()
    def _request(self,path,payload=None):
        headers={'Content-Type':'application/json'}
        if self.token:headers['Authorization']='Bearer '+self.token
        with urlopen(Request(self.base+path,data=None if payload is None else json.dumps(payload).encode(),headers=headers),timeout=1) as r:
            raw=r.read(65537)
            if len(raw)>65536:raise ValueError('external response budget')
            return json.loads(raw)
    def _run(self,p):
        import time
        try:
            self._id=self._request('/jobs',p)['id']
            if not isinstance(self._id,str) or not self._id.isalnum() or len(self._id)>64:raise ValueError('invalid job identifier')
            cancelled=False
            while not self._stop:
                if self._cancel and not cancelled:self._request('/jobs/'+self._id+'/cancel',{});cancelled=True
                value=self._request('/jobs/'+self._id)
                if value.get('state') not in ('RUNNING','SUCCEEDED','FAILED','CANCELLED','UNKNOWN'):raise ValueError('external state contract')
                with self._lock:self._status=value
                if value['state']!='RUNNING':return
                time.sleep(.05)
        except Exception:
            with self._lock:self._status={'state':'UNKNOWN','error':'external API outcome unconfirmed'}
    def poll(self):
        with self._lock:return dict(self._status)
    def cancel(self):self._cancel=True
    def close(self):self._stop=True;self._thread.join(2)

    @staticmethod
    def identity(base,*,token=None):
        """Public read-only identity: no EEPROM, secrets, POST or job creation."""
        ApiJob._validate_base(base)
        headers={'Authorization':'Bearer '+token} if token else {}
        with urlopen(Request(base.rstrip('/')+'/identity',headers=headers),timeout=1) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('provider identity response budget')
            value=json.loads(raw)
        if (type(value) is not dict or set(value)!={'provider_id','provider_epoch','resource_id'}
                or value.get('resource_id')!='jobs' or any(not isinstance(v,str) or not v or len(v)>256 for v in value.values())):
            raise ValueError('verified HTTP job provider identity required')
        return value

    @staticmethod
    def _validate_base(base):
        parsed=urlsplit(base)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('explicit credential-free provider endpoint required')

    def recovery_descriptor(self):
        with self._lock:return {'protocol':'http_job','endpoint':self.base,'job_id':self._id}

    @staticmethod
    def query_existing(descriptor,*,token=None):
        if descriptor.get('protocol')!='http_job':raise ValueError('not an HTTP job record')
        base=descriptor['endpoint'];identifier=descriptor.get('job_id');ApiJob._validate_base(base)
        if not isinstance(identifier,str) or not identifier.isalnum() or len(identifier)>64:
            raise ValueError('known provider job ID required; no implicit re-submission')
        headers={'Authorization':'Bearer '+token} if token else {}
        with urlopen(Request(base+'/jobs/'+identifier,headers=headers),timeout=1) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('external response budget')
            value=json.loads(raw)
        if value.get('state') not in ('RUNNING','SUCCEEDED','FAILED','CANCELLED','UNKNOWN'):raise ValueError('invalid provider result')
        return value

    def reconcile(self):
        # Runtime polling must not block on a remote network request. At most
        # one bounded read-only reconciliation is active; POST is never retried.
        import time
        def refresh():
            try:value=self.query_existing(self.recovery_descriptor(),token=self.token)
            except Exception:return
            if value['state'] in ('SUCCEEDED','FAILED','CANCELLED'):
                with self._lock:self._status=value
        with self._lock:
            if self._status['state'] not in ('SUCCEEDED','FAILED','CANCELLED'):
                if (self._recovery_thread is None or not self._recovery_thread.is_alive()) and time.monotonic()-self._last_recovery>=1:
                    self._last_recovery=time.monotonic();self._recovery_thread=Thread(target=refresh,daemon=True)
                    self._recovery_thread.start()
            return dict(self._status)
