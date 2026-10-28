"""Studio use cases; every execution delegates to the existing Mission service."""
from copy import deepcopy
from uuid import uuid4

from vehicle_autonomy.engine.mission.graph import validate
from vehicle_autonomy.engine.mission.studio_graph import TYPES,migrate
from .studio_library import StudioLibrary,graph_diff


class StudioService:
    def __init__(self,service,path):
        self.service=service;self.library=StudioLibrary(path)

    def compile(self,definition):
        return validate(definition,self.service.registry,self.service.drivers,resolve=self.library.publication)

    def catalog(self):
        return dict(node_types=deepcopy(TYPES),actions=self.service.registry.catalog(),vehicles=[dict(target=k,kind=d.context().target_kind,
            capabilities=sorted(d.context().capabilities),connected=d.info().get('connected',False)) for k,d in self.service.drivers.items()])

    def handle(self,operation,p):
        op=operation.removeprefix('studio-b.')
        if op=='catalog':return self.catalog()
        if op=='library':
            data=self.library.snapshot()
            runs=[{k:v.get(k) for k in ('id','target','state','release_safe','error','started_at')} for v in self.service.missions.views()]
            return dict(**data,runs=runs,legacy_versions=list(self.service.journal.data['versions'].values()))
        if op=='draft.save':
            if set(p)!={'definition','expected_revision'}:raise ValueError('strict draft save request required')
            return self.library.save(p['definition'],p['expected_revision'])
        if op=='draft.validate':
            if set(p)!={'mission_id','revision'}:raise ValueError('explicit stored draft revision required')
            item=self.library.snapshot()['drafts'][p['mission_id']]
            if item['definition']['revision']!=p['revision']:
                from .studio_library import RevisionConflict
                raise RevisionConflict(p['revision'],item)
            compiled=self.compile(item['definition']);document=compiled.to_dict()
            report=dict(valid=True,definition_hash=document['studio']['definition_hash'],compiled_nodes=len(document['nodes']),
                dependencies=list(document['studio']['dependencies']),resources=list(document['studio']['definition']['resource_requirements']))
            return self.library.validated(p['mission_id'],p['revision'],item['definition_hash'],report)
        if op=='draft.publish':
            if set(p)!={'mission_id','revision'}:raise ValueError('explicit stored draft revision required')
            item=self.library.snapshot()['drafts'][p['mission_id']];compiled=self.compile(item['definition'])
            return self.library.publish(p['mission_id'],p['revision'],compiled)
        if op in ('draft.clone','draft.restore','template.apply'):
            if set(p)!={'source','new_mission_id'}:raise ValueError('explicit copy source and fresh Mission ID required')
            data=self.library.snapshot()
            source=data['templates'][p['source']]['definition'] if op=='template.apply' else (data['publications'][p['source']]['definition'] if op=='draft.restore' else data['drafts'][p['source']]['definition'])
            if p['new_mission_id'] in data['drafts']:raise ValueError('copy requires a new Mission ID')
            d=deepcopy(source);d.update(mission_id=p['new_mission_id'],revision=0);d['name']+=' (copy)'
            return self.library.save(d,0)
        if op=='draft.import':
            if set(p)!={'definition','new_mission_id'}:raise ValueError('explicit import source and fresh Mission ID required')
            d=deepcopy(p['definition'])
            if d.get('schema_version')==1:d=migrate(d)
            d.update(mission_id=p['new_mission_id'],revision=0)
            if p['new_mission_id'] in self.library.snapshot()['drafts']:raise ValueError('import requires a new Mission ID')
            return self.library.save(d,0)
        if op=='template.save':
            if set(p)-{'mission_id','template_id','expected_hash'}:raise ValueError('strict template request required')
            d=self.library.snapshot()['drafts'][p['mission_id']]['definition']
            return self.library.template(p['template_id'],d,expected_hash=p.get('expected_hash'))
        if op=='diff':
            if set(p)!={'left','right'}:raise ValueError('two stored definition references required')
            data=self.library.snapshot()
            def get(key):
                for collection in ('drafts','publications','templates'):
                    if key in data[collection]:return data[collection][key]['definition']
                raise ValueError('unknown definition reference')
            return graph_diff(get(p['left']),get(p['right']))
        if op=='run.start':
            if set(p)-{'publication','allow_send','debug'}:raise ValueError('strict publication run request required')
            self.service._require_operational();item=self.library.snapshot()['publications'][p['publication']]
            # Revalidate the stored compiled snapshot, including its pinned dependencies.
            return self.service.handle('mission.start',dict(spec=item['compiled'],allow_send=p.get('allow_send',False),debug=p.get('debug',False)))
        if op=='run.get':
            if set(p)!={'id'}:raise ValueError('one run ID required')
            result=self.service.missions.view(p['id']);evidence=[]
            for identifier in result['action_ids']:
                try:a=self.service.runtime.view(identifier)
                except KeyError:continue
                reader=getattr(self.service.drivers[a['target']],'command_feedback',None)
                evidence.append(dict(id=a['id'],name=a['name'],state=a['state'],error=a['error'],result=a['result'],
                    safety=a['safety'],command_results=a['command_results'],command_evidence=reader(a['id']) if callable(reader) else [],history=a['history'][-16:]))
            result['action_evidence']=evidence;return result
        if op=='run.cancel':
            if set(p)!={'id'}:raise ValueError('one run ID required')
            return self.service.handle('mission.cancel',p)
        if op=='run.debug':
            if set(p)-{'id','operation','node_id','parameters'}:raise ValueError('strict debug request required')
            self.service._require_operational()
            return self.service.missions.debug(p['id'],p['operation'],node_id=p.get('node_id'),parameters=p.get('parameters'))
        raise ValueError('unknown Mission Studio operation')

    def close(self):self.library.close()
