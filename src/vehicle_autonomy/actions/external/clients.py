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


class ProviderIdentityError(ValueError):
    """A response cannot attest the provider/epoch that owns this job."""


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
        self._provider=tuple(identity[k] for k in self.IDENTITY_FIELDS)
        register_job(self,'http_job',self.base,provider_id=identity['provider_id'],provider_epoch=identity['provider_epoch'])
        self._thread=Thread(target=self._run,args=(parameters,),daemon=True);self._thread.start()

    IDENTITY_FIELDS=('provider_id','provider_epoch','resource_id')
    TERMINAL=frozenset({'SUCCEEDED','FAILED','CANCELLED'})

    def _identity(self):return dict(zip(self.IDENTITY_FIELDS,self._provider))

    def _request(self,path,payload=None):
        return self._bound_request(self.base,path,self._identity(),payload,token=self.token,
            job_id=None if path=='/jobs' else self._id)

    @staticmethod
    def _provider_identity(value):
        if (type(value) is not dict or set(value)!=set(ApiJob.IDENTITY_FIELDS)
                or value.get('resource_id')!='jobs'
                or any(not isinstance(v,str) or not v or len(v)>256 for v in value.values())):
            raise ProviderIdentityError('verified HTTP job provider identity required')
        return dict(value)

    @staticmethod
    def _bound_request(base,path,provider,payload=None,*,token=None,job_id=None):
        # The provider must check this fence BEFORE a POST side effect. Each
        # response also attests its actual identity, so an endpoint switch
        # between /identity and this request cannot supply another epoch's job.
        provider=ApiJob._provider_identity(provider)
        headers={'Content-Type':'application/json',
            'X-VAF-Expected-Provider':json.dumps(provider,ensure_ascii=True,separators=(',',':'))}
        if token:headers['Authorization']='Bearer '+token
        with urlopen(Request(base+path,data=None if payload is None else json.dumps(payload).encode(),headers=headers),timeout=1) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('external response budget')
            value=json.loads(raw)
        if type(value) is not dict or ApiJob._provider_identity(value.get('provider'))!=provider:
            raise ProviderIdentityError('HTTP job response provider identity/epoch mismatch')
        if job_id is not None and value.get('job_id')!=job_id:
            raise ProviderIdentityError('HTTP response belongs to a different job')
        return value

    def _publish(self,value):
        with self._lock:
            # A delayed RUNNING/error response cannot undo a verified terminal
            # result already obtained by the read-only recovery thread.
            if self._status['state'] not in self.TERMINAL:self._status=value
    def _run(self,p):
        import time
        try:
            identifier=self._request('/jobs',p)['id']
            if not isinstance(identifier,str) or not identifier.isalnum() or len(identifier)>64:raise ValueError('invalid job identifier')
            with self._lock:self._id=identifier
            cancelled=False
            while not self._stop:
                if self._cancel and not cancelled:self._request('/jobs/'+self._id+'/cancel',{});cancelled=True
                value=self._request('/jobs/'+self._id)
                if value.get('state') not in ('RUNNING','SUCCEEDED','FAILED','CANCELLED','UNKNOWN'):raise ValueError('external state contract')
                self._publish(value)
                if value['state']!='RUNNING':return
                time.sleep(.05)
        except Exception:
            self._publish({'state':'UNKNOWN','error':'external API outcome unconfirmed'})
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
            if response.headers.get('X-VAF-Job-Protocol')!='2':
                raise ProviderIdentityError('epoch-fenced HTTP job protocol v2 required')
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('provider identity response budget')
            value=json.loads(raw)
        return ApiJob._provider_identity(value)

    @staticmethod
    def _validate_base(base):
        parsed=urlsplit(base)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('explicit credential-free provider endpoint required')

    def recovery_descriptor(self):
        with self._lock:return {'protocol':'http_job','endpoint':self.base,'job_id':self._id,'provider':self._identity()}

    @staticmethod
    def query_existing(descriptor,*,token=None,expected_provider=None):
        if descriptor.get('protocol')!='http_job':raise ValueError('not an HTTP job record')
        base=descriptor['endpoint'];identifier=descriptor.get('job_id');ApiJob._validate_base(base)
        if not isinstance(identifier,str) or not identifier.isalnum() or len(identifier)>64:
            raise ValueError('known provider job ID required; no implicit re-submission')
        provider=ApiJob._provider_identity(expected_provider if expected_provider is not None else descriptor.get('provider'))
        if 'provider' in descriptor and ApiJob._provider_identity(descriptor['provider'])!=provider:
            raise ProviderIdentityError('recovery descriptor/provider reservation mismatch')
        if ApiJob.identity(base,token=token)!=provider:
            raise ProviderIdentityError('recovery provider identity/epoch mismatch')
        value=ApiJob._bound_request(base,'/jobs/'+identifier,provider,token=token,job_id=identifier)
        if value.get('state') not in ('RUNNING','SUCCEEDED','FAILED','CANCELLED','UNKNOWN'):raise ValueError('invalid provider result')
        return value

    def reconcile(self):
        # Runtime polling must not block on a remote network request. At most
        # one bounded read-only reconciliation is active; POST is never retried.
        import time
        def refresh():
            try:value=self.query_existing(self.recovery_descriptor(),token=self.token)
            except Exception:return
            if value['state'] in self.TERMINAL:self._publish(value)
        with self._lock:
            if self._status['state'] not in ('SUCCEEDED','FAILED','CANCELLED'):
                if (self._recovery_thread is None or not self._recovery_thread.is_alive()) and time.monotonic()-self._last_recovery>=1:
                    self._last_recovery=time.monotonic();self._recovery_thread=Thread(target=refresh,daemon=True)
                    self._recovery_thread.start()
            return dict(self._status)
