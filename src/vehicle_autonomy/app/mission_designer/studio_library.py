"""Private durable drafts, immutable publications and definition-only templates."""
from copy import deepcopy
from datetime import datetime,timezone
import fcntl
from pathlib import Path
from threading import RLock

from vehicle_autonomy.engine.action.durable import DurableRecord,durable_directories
from vehicle_autonomy.engine.mission.studio_graph import normalize,digest


class RevisionConflict(ValueError):
    def __init__(self,expected,current):
        super().__init__('draft revision conflict; reload or explicitly merge')
        self.details=dict(expected_revision=expected,current=deepcopy(current))


class StudioLibrary:
    def __init__(self,path):
        self.path=Path(path).absolute();self.mutex=RLock();anchor=self.path.parent/('.'+self.path.name+'.anchor')
        fresh=not self.path.exists() and not anchor.exists()
        if fresh:durable_directories(self.path)
        if not self.path.is_dir():raise ValueError('established Studio library missing')
        self.owner=(self.path/'owner.lock').open('a+b')
        try:
            fcntl.flock(self.owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
            identity=dict(path=str(self.path),inode=self.path.stat().st_ino)
            self.record=DurableRecord(self.path/'library.json')
            if fresh:
                DurableRecord(anchor).write(identity,create=True)
                self.record.write(dict(format=1,drafts={},publications={},templates={}),create=True)
            if DurableRecord(anchor).read()!=identity:raise ValueError('Studio library identity changed')
            self.data=self.record.read()
            if set(self.data)!={'format','drafts','publications','templates'} or self.data['format']!=1:raise ValueError('invalid Studio library')
        except BaseException:self.close();raise

    def close(self):
        if getattr(self,'owner',None):self.owner.close();self.owner=None

    def transaction(self,fn):
        with self.mutex:
            value=deepcopy(self.data);result=fn(value);self.record.write(value);self.data=value
            return deepcopy(result)

    def save(self,definition,expected_revision):
        d=normalize(definition)
        if type(expected_revision) is not int or expected_revision<0:raise ValueError('explicit expected draft revision required')
        def change(data):
            old=data['drafts'].get(d['mission_id']);revision=0 if old is None else old['definition']['revision']
            if expected_revision!=revision:raise RevisionConflict(expected_revision,old)
            if old is None and len(data['drafts'])>=256:raise ValueError('draft library budget exhausted')
            d['revision']=revision+1
            item=dict(definition=d,state='Draft',definition_hash=digest(d),updated_at=datetime.now(timezone.utc).isoformat())
            data['drafts'][d['mission_id']]=item;return item
        return self.transaction(change)

    def validated(self,identifier,revision,definition_hash,report):
        def change(data):
            item=data['drafts'][identifier]
            if item['definition']['revision']!=revision or item['definition_hash']!=definition_hash:raise RevisionConflict(revision,item)
            item.update(state='Validated',validation=deepcopy(report));return item
        return self.transaction(change)

    def publish(self,identifier,revision,compiled):
        def change(data):
            item=data['drafts'][identifier]
            if item['definition']['revision']!=revision:raise RevisionConflict(revision,item)
            definition=compiled.to_dict()['studio']['definition'];key=identifier+'@'+definition['version']
            value=dict(key=key,definition=definition,compiled=compiled.to_dict(),definition_hash=digest(definition),published_at=datetime.now(timezone.utc).isoformat())
            old=data['publications'].get(key)
            if old:
                if old['definition_hash']!=value['definition_hash']:raise ValueError('published version immutable; select a new semantic version')
                return old
            if len(data['publications'])>=256:raise ValueError('publication library budget exhausted')
            data['publications'][key]=value;item.update(state='Published',publication=key);return value
        return self.transaction(change)

    def publication(self,identifier,version):
        with self.mutex:
            value=self.data['publications'].get(identifier+'@'+version)
            return None if value is None else deepcopy(value['definition'])

    def template(self,identifier,definition,*,expected_hash=None):
        d=normalize(definition)
        def change(data):
            old=data['templates'].get(identifier)
            if old and expected_hash!=old['definition_hash']:raise ValueError('template changed; explicitly select its current hash')
            if old is None and len(data['templates'])>=128:raise ValueError('template budget exhausted')
            value=dict(id=identifier,definition=d,definition_hash=digest(d));data['templates'][identifier]=value;return value
        return self.transaction(change)

    def snapshot(self):
        with self.mutex:return deepcopy(self.data)


def graph_diff(left,right):
    def indexed(items,key):return {v[key]:v for v in items}
    nodes_a=indexed(left['nodes'],'node_id');nodes_b=indexed(right['nodes'],'node_id');edges_a=indexed(left['edges'],'edge_id');edges_b=indexed(right['edges'],'edge_id')
    changes=[]
    def compare(a,b,path,depth=0):
        if a==b:return
        if depth<12 and type(a) is dict and type(b) is dict:
            for key in sorted(a.keys()|b.keys()):compare(a.get(key),b.get(key),path+'.'+key,depth+1)
        else:changes.append(dict(path=path,before=deepcopy(a),after=deepcopy(b)))
    for key in nodes_a.keys()&nodes_b.keys():compare(nodes_a[key],nodes_b[key],'nodes.'+key)
    for key in edges_a.keys()&edges_b.keys():compare(edges_a[key],edges_b[key],'edges.'+key)
    compare({k:v for k,v in left.items() if k not in ('nodes','edges')},{k:v for k,v in right.items() if k not in ('nodes','edges')},'mission')
    return dict(nodes_added=sorted(nodes_b.keys()-nodes_a.keys()),nodes_removed=sorted(nodes_a.keys()-nodes_b.keys()),
        edges_added=sorted(edges_b.keys()-edges_a.keys()),edges_removed=sorted(edges_a.keys()-edges_b.keys()),changes=changes)
