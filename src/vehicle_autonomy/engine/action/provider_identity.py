"""One trusted local deployment registry, independent of per-application ledgers.

This is not a distributed lock. The OS deployment fixes this root for all its
processes; an Action, target alias, scope or state_dir cannot select another.
Ordinary application startup never creates or repairs the registry.
"""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import os
from pathlib import Path
import pwd
import stat

from vehicle_autonomy.engine.action.durable import DurableRecord,durable_directories


class ProviderRegistry:
    # One OS-account deployment identity, shared by source/wheel applications.
    # No Action, state_dir, scope, environment variable or per-driver parameter
    # can select another root. Isolated tests patch only this private location.
    _root=Path(pwd.getpwuid(os.getuid()).pw_dir)/'.local/state/vehicle-autonomy/provider-registry'

    def __init__(self):
        self.root=self._root.absolute()

    @staticmethod
    def identity(root):return {'path':str(root),'device':root.stat().st_dev,'inode':root.stat().st_ino}

    def anchor(self):
        return DurableRecord(self.root.parent/('.vaf-provider-'+hashlib.sha256(str(self.root).encode()).hexdigest()+'.anchor'))

    @classmethod
    def initialize(cls):
        """Explicit trusted bootstrap of a fresh local deployment, never recovery."""
        result=cls();root=result.root
        if root.resolve()!=root:raise ValueError('real provider registry required')
        durable_directories(root.parent)
        if root.exists() or result.anchor().path.exists():raise ValueError('provider registry already established')
        root.mkdir(mode=0o700)
        fd=os.open(root/'registry.lock',os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            result.anchor().write(result.identity(root),create=True)
            DurableRecord(root/'bindings.json').write({'bindings':[]},create=True)
        finally:os.close(fd)
        return result

    @contextmanager
    def transaction(self):
        root=self.root;info=root.lstat()
        if (root.resolve()!=root or not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid()
                or stat.S_IMODE(info.st_mode)!=0o700):raise ValueError('private provider registry required')
        fd=os.open(root/'registry.lock',os.O_RDWR|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
                    or stat.S_IMODE(info.st_mode)!=0o600):raise ValueError('invalid provider registry lock')
            fcntl.flock(fd,fcntl.LOCK_EX)
            if self.anchor().read()!=self.identity(root):raise ValueError('provider registry identity changed')
            store=DurableRecord(root/'bindings.json');data=store.read()
            if type(data) is not dict or set(data)!={'bindings'} or type(data['bindings']) is not list or len(data['bindings'])>4096:
                raise ValueError('invalid provider registry')
            keys=set();ledgers=set()
            for b in data['bindings']:
                if (type(b) is not dict or set(b)!={'provider_id','provider_epoch','resource_id','protocol','locator','ledger','scope','resources'}
                        or any(not isinstance(b[k],str) or not b[k] or len(b[k])>4096 for k in ('provider_id','provider_epoch','resource_id','protocol','locator','ledger','scope'))
                        or type(b['resources']) is not list or not b['resources']):raise ValueError('invalid provider binding')
                for r in b['resources']:
                    if (type(r) is not dict or set(r)!={'name','mode','conflict_group'} or r['mode'] not in ('shared','exclusive')
                            or not isinstance(r['name'],str) or not r['name'] or not isinstance(r['conflict_group'],str)):
                        raise ValueError('invalid bound resource')
                key=(b['provider_id'],b['resource_id'])
                if key in keys or b['ledger'] in ledgers:raise ValueError('duplicate provider/ledger binding')
                keys.add(key);ledgers.add(b['ledger'])
            yield data,store
        finally:os.close(fd)

    def find(self,directory,scope):
        with self.transaction() as (data,_):return self.validate(data,directory,scope)

    @staticmethod
    def validate(data,directory,scope):
        binding=next((b for b in data['bindings'] if b['ledger']==str(directory)),None)
        if binding is None or binding['scope']!=scope:raise ValueError('ledger/scope has no trusted provider binding')
        return deepcopy(binding)

    @staticmethod
    def register(data,store,binding):
        for old in data['bindings']:
            if ((old['provider_id'],old['resource_id'])==(binding['provider_id'],binding['resource_id'])
                    or old['ledger']==binding['ledger']
                    or (old['protocol'],old['locator'],old['resource_id'])==(binding['protocol'],binding['locator'],binding['resource_id'])):
                raise ValueError('provider/resource already bound to its unique ledger; no alternate initialization')
            if old['protocol']==binding['protocol']=='ros2' and (
                    old['locator'].startswith(binding['locator']+'/') or binding['locator'].startswith(old['locator']+'/')):
                raise ValueError('overlapping ROS provider namespaces cannot form separate conflict domains')
        if len(data['bindings'])>=4096:raise ValueError('provider binding budget exhausted')
        data['bindings'].append(binding);store.write(data)
