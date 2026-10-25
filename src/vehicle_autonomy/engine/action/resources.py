"""Per-target resource arbitration; no vehicle authorization is granted here."""
from dataclasses import dataclass
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import os
from pathlib import Path
import stat
from uuid import uuid4

from vehicle_autonomy.contracts.action import ActionResource, ActionSafety, ResourceMode
from vehicle_autonomy.engine.action.durable import DurableRecord,durable_directories


class PersistentResources:
    """External-effect reservations, not vehicle leases or authorization.

    A stable deployment directory/scope must be reused across application
    processes. Established missing/corrupt files fail closed; there is no reset
    or force-release operation. The same OS owner/storage is trusted.
    """
    def __init__(self,directory,scope='external'):
        self.root=Path(directory).absolute();self.scope=scope
        if not isinstance(scope,str) or not scope or len(scope)>256:raise ValueError('stable external resource scope required')

    @staticmethod
    def _anchor(root):
        return DurableRecord(root.parent/('.vaf-resource-'+hashlib.sha256(str(root).encode()).hexdigest()+'.anchor'))

    @classmethod
    def initialize(cls,directory,verify_quiescent,scope='external'):
        """Explicit deployment bootstrap for a verified fresh/quiescent provider.

        Never called by Runtime, acquisition, ordinary startup or recovery.
        No force/reset flag: existing/lost established state is not overwritten.
        """
        from vehicle_autonomy.contracts.core.serialization import to_json_value
        assessment=verify_quiescent()
        evidence=to_json_value(assessment.evidence) if isinstance(assessment,ActionSafety) else None
        if (not isinstance(assessment,ActionSafety) or not assessment.release_safe or type(evidence) is not dict
                or evidence.get('quiescent') is not True or not isinstance(evidence.get('provider_epoch'),str)
                or not evidence['provider_epoch']):raise ValueError('trusted provider quiescence and epoch required')
        result=cls(directory,scope);root=result.root
        if root.resolve()!=root:raise ValueError('real state namespace required')
        durable_directories(root.parent);anchor=cls._anchor(root)
        if root.exists() or anchor.path.exists():raise ValueError('external state already established; cannot initialize/reset')
        root.mkdir(mode=0o700)
        fd=os.open(root/'owner.lock',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            DurableRecord(root/'claims.json').write({'claims':[]},create=True)
            anchor.write({'device':root.stat().st_dev,'inode':root.stat().st_ino,'path':str(root),
                'provider_epoch':evidence['provider_epoch']},create=True)
        finally:os.close(fd)
        return result

    @contextmanager
    def _transaction(self):
        if self.root.resolve()!=self.root:raise ValueError('real external resource directory required')
        anchor=self._anchor(self.root)
        info=self.root.lstat()
        if (self.root.resolve()!=self.root or not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid()
                or stat.S_IMODE(info.st_mode)!=0o700):raise ValueError('private external resource directory required')
        flags=os.O_RDWR|os.O_NOFOLLOW
        fd=os.open(self.root/'owner.lock',flags)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:
                raise ValueError('invalid external resource lock')
            fcntl.flock(fd,fcntl.LOCK_EX)
            store=DurableRecord(self.root/'claims.json')
            identity={'device':self.root.stat().st_dev,'inode':self.root.stat().st_ino,'path':str(self.root)}
            saved=anchor.read()
            if (type(saved) is not dict or set(saved)!={'device','inode','path','provider_epoch'}
                    or any(saved.get(k)!=v for k,v in identity.items()) or not isinstance(saved['provider_epoch'],str)
                    or not saved['provider_epoch']):raise ValueError('external resource directory identity changed')
            data=store.read()
            if type(data) is not dict or set(data)!={'claims'} or type(data['claims']) is not list or len(data['claims'])>4096:
                raise ValueError('external resource state invalid')
            ids=set()
            for r in data['claims']:
                if (type(r) is not dict or set(r)!={'owner','runtime','pid','start_ticks','scope','target','resources','metadata','descriptor','retained','phase'}
                        or not all(isinstance(r[k],str) and r[k] for k in ('owner','runtime','scope','target','phase'))
                        or r['phase'] not in ('RESERVED','ACTIVE','UNKNOWN') or r['owner'] in ids
                        or type(r['pid']) is not int or r['pid']<=0 or not isinstance(r['start_ticks'],str) or not r['start_ticks'].isdigit()
                        or type(r['metadata']) is not dict or type(r['descriptor']) is not dict
                        or r['retained'] is not None and not isinstance(r['retained'],str)
                        or type(r['resources']) is not list or not r['resources']):raise ValueError('external claim record invalid')
                ids.add(r['owner'])
                for resource in r['resources']:
                    if (type(resource) is not dict or set(resource)!={'name','mode','conflict_group'}
                            or not isinstance(resource['name'],str) or not resource['name']
                            or not isinstance(resource['conflict_group'],str) or resource['mode'] not in ('shared','exclusive')):
                        raise ValueError('external resource descriptor invalid')
            yield data,store
        finally:os.close(fd)

    def records(self):
        with self._transaction() as (data,_):return deepcopy([r for r in data['claims'] if r['scope']==self.scope])

    def acquire(self,owner,runtime,target,resources,metadata):
        requested=[dict(name=r.name,mode=r.mode.value,conflict_group=r.conflict_group) for r in resources]
        with self._transaction() as (data,store):
            for old in data['claims']:
                if old['scope']!=self.scope:continue
                if old['owner']==owner:return old['runtime']==runtime
                for a in requested:
                    for b in old['resources']:
                        if ((a['conflict_group'] or a['name'])==(b['conflict_group'] or b['name'])
                                and 'exclusive' in (a['mode'],b['mode'])):return False
            if len(data['claims'])>=4096:raise ValueError('external resource record budget exhausted')
            ticks=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]
            data['claims'].append(dict(owner=owner,runtime=runtime,pid=os.getpid(),start_ticks=ticks,
                scope=self.scope,target=target,resources=requested,metadata=metadata,descriptor={},retained=None,phase='RESERVED'))
            store.write(data)
            return True

    def update(self,owner,runtime,**fields):
        with self._transaction() as (data,store):
            record=next((r for r in data['claims'] if r['owner']==owner and r['scope']==self.scope),None)
            if record is None or record['runtime']!=runtime:raise ValueError('external reservation owner changed')
            if any(record.get(k)!=v for k,v in fields.items()):record.update(fields);store.write(data)

    def release(self,owner,runtime,*,safety=None,no_effects=False):
        with self._transaction() as (data,store):
            r=next((r for r in data['claims'] if r['owner']==owner and r['scope']==self.scope),None)
            if r is None:return
            if r['runtime']!=runtime:raise ValueError('recovered external reservation requires provider reconciliation')
            if not (isinstance(safety,ActionSafety) and safety.release_safe) and not (no_effects and r['phase']=='RESERVED'):
                raise ValueError('trusted exit evidence required to release external resource')
            data['claims'].remove(r);store.write(data)

    def reconcile(self,owner,verify,*,runtime_id=None):
        """Deployment-supplied read-only provider verification, never a UI bool.

        Keep the lock across verification: the old process cannot change its
        reservation during release. Verification must be bounded and must not
        resubmit the remote operation.
        """
        with self._transaction() as (data,store):
            r=next((r for r in data['claims'] if r['owner']==owner and r['scope']==self.scope),None)
            if r is None:raise ValueError('external reservation not found')
            if r['runtime']!=runtime_id:
                try:
                    fields=(Path('/proc')/str(r['pid'])/'stat').read_text().rsplit(')',1)[1].split()
                    if fields[0]!='Z' and fields[19]==str(r['start_ticks']):return False
                except FileNotFoundError:pass
                except (OSError,ValueError,IndexError):return False
            evidence=verify(deepcopy(r))
            from vehicle_autonomy.contracts.core.serialization import to_json_value
            proof=to_json_value(evidence.evidence) if isinstance(evidence,ActionSafety) else None
            if (not isinstance(evidence,ActionSafety) or not evidence.release_safe or type(proof) is not dict
                    or proof.get('owner')!=owner or proof.get('scope')!=self.scope or proof.get('terminal') is not True):
                return False
            data['claims'].remove(r);store.write(data);return True


@dataclass(frozen=True,slots=True)
class Claim:
    owner: str
    target: str
    resource: ActionResource


class ActionResources:
    def __init__(self,stores=None):
        self._claims: list[Claim] = []
        self._guards: dict[str,str] = {}
        self._stores=dict(stores or {});self._persistent={};self.runtime_id=uuid4().hex
        self._failed_stores=set()

    @staticmethod
    def _key(target,resource):return target,resource.conflict_group or resource.name

    def acquire(self,owner,target,resources,*,continuation_of=None,persistent=False,metadata=None):
        if any(not isinstance(r,ActionResource) for r in resources):raise TypeError('typed resources required')
        if any(c.owner==owner for c in self._claims):return True
        for requested in resources:
            for existing in self._claims:
                if (existing.owner!=continuation_of and self._key(target,requested)==self._key(existing.target,existing.resource)
                        and (requested.mode is ResourceMode.EXCLUSIVE or existing.resource.mode is ResourceMode.EXCLUSIVE)):
                    return False
        if persistent and resources and target in self._stores:
            store=self._stores[target]
            if store.root in self._failed_stores:raise ValueError('external persistence failed; reconcile before reuse')
            if continuation_of:raise ValueError('external restart is not a continuation grant')
            if not store.acquire(owner,self.runtime_id,target,resources,metadata or {}):return False
            self._persistent[owner]=store
        self._claims.extend(Claim(owner,target,r) for r in resources)
        return True

    def release(self,owner,*,safety=None,no_effects=False):
        if owner in self._guards and not (isinstance(safety,ActionSafety) and safety.release_safe):
            raise ValueError('uncertain resources require trusted reconciliation')
        store=self._persistent.get(owner)
        if store:
            try:store.release(owner,self.runtime_id,safety=safety,no_effects=no_effects)
            except Exception:
                self._failed_stores.add(store.root)
                raise
            self._failed_stores.discard(store.root)
            self._persistent.pop(owner,None)
        self._claims[:]=[c for c in self._claims if c.owner!=owner]
        self._guards.pop(owner,None)

    def started(self,owner):
        if owner in self._persistent:
            store=self._persistent[owner]
            try:store.update(owner,self.runtime_id,phase='ACTIVE')
            except Exception:
                self._failed_stores.add(store.root)
                raise

    def describe(self,owner,descriptor):
        if owner in self._persistent:
            store=self._persistent[owner]
            try:store.update(owner,self.runtime_id,descriptor=descriptor)
            except Exception:
                self._failed_stores.add(store.root)
                raise

    def retain(self,owner,reason):
        self._guards[owner]=reason
        if owner in self._persistent:
            store=self._persistent[owner]
            try:store.update(owner,self.runtime_id,phase='UNKNOWN',retained=reason)
            except Exception:self._failed_stores.add(store.root)  # Prior durable reservation still blocks reuse.

    def reconcile(self,owner,verify):
        for store in self._stores.values():
            if any(r['owner']==owner for r in store.records()):
                if not store.reconcile(owner,verify,runtime_id=self.runtime_id):return False
                self._claims[:]=[c for c in self._claims if c.owner!=owner]
                self._guards.pop(owner,None);self._persistent.pop(owner,None)
                self._failed_stores.discard(store.root)
                return True
        raise ValueError('external reservation not found')

    def view(self):
        result=[dict(owner=c.owner,target=c.target,name=c.resource.name,mode=c.resource.mode.value,
                     conflict_group=c.resource.conflict_group,retained=self._guards.get(c.owner)) for c in self._claims if c.owner not in self._persistent]
        seen=set()
        for store in self._stores.values():
            key=(store.root,store.scope)
            if key in seen:continue
            seen.add(key)
            try:records=store.records()
            except Exception:
                result.append(dict(owner='unavailable',target=store.scope,name='external.state',mode='exclusive',
                    conflict_group='',retained='persistent resource state unavailable; new side effects blocked'))
                continue
            for r in records:
                for resource in r['resources']:
                    result.append(dict(owner=r['owner'],target=r['target'],**resource,
                        retained=r['retained'] or self._guards.get(r['owner']) or ('external effect from another application remains unconfirmed' if r['runtime']!=self.runtime_id else None),
                        scope=r['scope'],phase=r['phase'],metadata=r['metadata'],descriptor=r['descriptor']))
        return result
