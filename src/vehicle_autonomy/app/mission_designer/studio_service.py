"""Studio use cases; every execution delegates to the existing Mission service."""
from copy import deepcopy
from uuid import uuid4

from vehicle_autonomy.engine.mission.graph import validate
from vehicle_autonomy.engine.mission.studio_graph import TYPES,migrate
from .studio_library import StudioLibrary,graph_diff


class StudioService:
    def __init__(self,service,path):
        self.service=service;self.library=StudioLibrary(path)
        try:self.install_examples()
        except BaseException:self.library.close();raise

    def install_examples(self):
        from .studio_examples import cuadc,rover_inspection,copter_inspection,plane_inspection
        data=self.library.snapshot()
        for target,driver in self.service.drivers.items():
            data=self.library.snapshot()
            context=driver.context()
            if not context.owned_simulation:continue
            from .mission_examples import examples
            for definition in examples(target,context.target_kind):
                identifier=definition['mission_id']
                if identifier in data['templates']:continue
                try:
                    for n in definition['nodes']:
                        if n['type']=='Action':self.service.registry.resolve_typed(n['action_type'],n['action_contract_version'])
                except ValueError:continue
                self.library.template(identifier,definition)
                data=self.library.snapshot()
            if context.target_kind=='rover' and 'Rover_Inspection' not in data['templates']:
                try:self.service.registry.resolve_typed('Goto');self.service.registry.resolve_typed('Stop')
                except ValueError:continue
                self.library.template('Rover_Inspection',rover_inspection(target))
            if context.target_kind=='copter' and self.service.studio_demo:
                child,parent=cuadc(target)
                if 'HandleTarget@1.0.0' not in data['publications']:
                    if 'HandleTarget' in data['drafts']:raise ValueError('demo child ID occupied; existing user draft was preserved')
                    item=self.library.save(child,0);compiled=self.compile(item['definition']);self.library.publish('HandleTarget',1,compiled)
                if 'CUADC_MultiTarget_Simulation' not in data['templates']:self.library.template('CUADC_MultiTarget_Simulation',parent)
            if context.target_kind in ('copter','plane'):
                identifier=context.target_kind.title()+'_Inspection'
                if identifier not in data['templates']:
                    try:self.service.registry.resolve_typed('Takeoff');self.service.registry.resolve_typed('ReturnHome' if context.target_kind=='copter' else 'AutoLand')
                    except ValueError:continue
                    self.library.template(identifier,(copter_inspection if context.target_kind=='copter' else plane_inspection)(target))

    def compile(self,definition):
        for path in definition.get('metadata',{}).get('unresolved_tool_inputs',[]):
            identifier,field=path.split('.',1);node=next((n for n in definition['nodes'] if n['node_id']==identifier),{})
            if field not in node.get('parameters',{}) and field not in node.get('input_bindings',{}):raise ValueError('template Tool input needs explicit replacement: '+path)
        compiled=validate(definition,self.service.registry,self.service.drivers,resolve=self.library.publication)
        for n in compiled.to_dict()['nodes']:
            if n['type']=='Action' and not self.provider(n['action'],n['action_version'],definition['target'])['configured']:raise ValueError('Action Provider not bound: '+n['action'])
        return compiled

    def provider(self,name,version,target=None):
        entry=self.service.registry.resolve_typed(name,version)
        if entry.spec.external_lifecycle=='typed_only':return dict(configured=True,state='REGISTERED_IN_PROCESS',readiness='checked at Action admission')
        store=getattr(entry.factory,'resource_store',None) or getattr(self.service.drivers.get(target),'resource_store',None)
        try:bound=store is not None and store.binding() is not None
        except Exception:bound=False
        return dict(configured=bound,state='BOUND_EXTERNAL' if bound else 'UNAVAILABLE',readiness='checked at Action admission' if bound else 'no verified external Provider binding')

    def catalog(self):
        from vehicle_autonomy.engine.mission.studio_graph import WORLD_TYPES
        from .action_localization import catalog_entry,CATEGORIES,bilingual
        profiles={};libraries={}
        actions=[catalog_entry(self.service.registry,item) for item in self.service.registry.catalog()]
        for target,driver in self.service.drivers.items():
            context=driver.context();items=self.service.registry.catalog(vehicle_kind=context.target_kind,capabilities=context.capabilities)
            admitted={(item['name'],item['version']) for item in items}
            full=[]
            for original in actions:
                item=catalog_entry(self.service.registry,self.service.registry.metadata(original['name'],original['version'],vehicle_kind=context.target_kind))
                provider=self.provider(item['name'],item['version'],target)
                item['provider']=provider
                reasons=[]
                vehicles=item['presentation']['vehicles']
                if vehicles and context.target_kind not in vehicles:reasons.append(bilingual('不支持当前车辆类型','Unsupported vehicle type'))
                missing=set(item['required_capabilities'])-set(context.capabilities)
                if missing:reasons.append(bilingual('当前车辆缺少所需能力：'+', '.join(sorted(missing)),'Missing capabilities: '+', '.join(sorted(missing))))
                if item['presentation']['simulation_only'] and not context.owned_simulation:reasons.append(bilingual('仅支持明确自有的仿真环境','Requires an explicitly owned simulation'))
                if not provider['configured']:reasons.append(bilingual('能力提供方未绑定或生命周期契约不可验证','Provider is unbound or its lifecycle contract is not verified'))
                item['availability']=dict(configurable=not reasons,reasons=reasons,
                    note=bilingual('可配置；执行时仍须通过状态、控制权和安全检查','Configurable; execution still requires state, authority and safety admission'))
                full.append(item)
            libraries[target]=full
            profiles[target]=[item for item in full if (item['name'],item['version']) in admitted]
        return dict(node_types=deepcopy(TYPES),actions=actions,action_sets=profiles,library_sets=libraries,
            categories=deepcopy(CATEGORIES),locales=['zh-CN','en-US'],default_locale='zh-CN',world_bindings=deepcopy(WORLD_TYPES),vehicles=[dict(target=k,kind=d.context().target_kind,
            capabilities=sorted(d.context().capabilities),connected=d.info().get('connected',False)) for k,d in self.service.drivers.items()])

    def handle(self,operation,p):
        op=operation.removeprefix('studio-b.')
        if op=='catalog':return self.catalog()
        if op=='inputs.goals':
            if set(p)!={'target'} or p['target'] not in self.service.drivers:raise ValueError('one registered input target required')
            return dict(provider='navigation_goal',goals=self.service.visualization_goals.view(p['target']),
                limitations='Only current odom position proposals. Orientation and unqualified map transforms are not imported. QGC import is not installed.')
        if op=='library':
            # Control Center attaches explicitly owned Drivers after startup.
            # Seed definitions lazily; this never grants SEND or starts a Run.
            self.install_examples()
            data=self.library.snapshot()
            runs=[{k:v.get(k) for k in ('id','target','state','release_safe','error','started_at')} for v in self.service.missions.views()]
            return dict(**data,runs=runs,legacy_versions=list(self.service.journal.data['versions'].values()))
        if op=='draft.save':
            if set(p)!={'definition','expected_revision'}:raise ValueError('strict draft save request required')
            return self.library.save(p['definition'],p['expected_revision'])
        if op=='draft.extract':
            if set(p)!={'mission_id','revision','node_ids','sub_mission_id','name'}:raise ValueError('explicit extraction selection and revision required')
            item=self.library.snapshot()['drafts'][p['mission_id']]
            if item['definition']['revision']!=p['revision']:
                from .studio_library import RevisionConflict
                raise RevisionConflict(p['revision'],item)
            from .studio_extract import extract
            source=self.compile(item['definition']).to_dict()['studio']['definition']
            child,parent=extract(source,p['node_ids'],p['sub_mission_id'],p['name'],self.service.registry)
            self.compile(child)
            validate(parent,self.service.registry,self.service.drivers,resolve=lambda i,v:child if (i,v)==(child['mission_id'],child['version']) else self.library.publication(i,v))
            return self.library.extract(parent,p['revision'],child)
        if op=='draft.new_version':
            if set(p)!={'source','new_version','expected_revision'}:raise ValueError('explicit publication, version and current draft revision required')
            data=self.library.snapshot();d=deepcopy(data['publications'][p['source']]['definition']);current=data['drafts'].get(d['mission_id'])
            if current is not None and current['state']!='Published':raise ValueError('an editable draft already exists; finish or export it before restoring another version')
            if d['mission_id']+'@'+p['new_version'] in data['publications']:raise ValueError('select an unpublished semantic version')
            d['version']=p['new_version'];return self.library.save(d,p['expected_revision'])
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
            if d.get('schema_version')==1:d=migrate(d,registry=self.service.registry,drivers=self.service.drivers)
            d.update(mission_id=p['new_mission_id'],revision=0)
            if p['new_mission_id'] in self.library.snapshot()['drafts']:raise ValueError('import requires a new Mission ID')
            return self.library.save(d,0)
        if op=='template.save':
            if set(p)-{'mission_id','template_id','expected_hash'}:raise ValueError('strict template request required')
            d=self.library.snapshot()['drafts'][p['mission_id']]['definition'];unresolved=[]
            for n in d['nodes']:
                for name,b in list(n.get('input_bindings',{}).items()):
                    if b.get('source')=='external':del n['input_bindings'][name];unresolved.append(n['node_id']+'.'+name)
            if unresolved:d['metadata']['unresolved_tool_inputs']=unresolved
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
            from vehicle_autonomy.world.model.mission_inputs import usable
            now=self.service.clock()
            for n in item['compiled']['nodes']:
                values=list(n.get('input_bindings',{}).values())+[v['$binding'] for v in n.get('parameters',{}).values() if type(v) is dict and set(v)=={'$binding'}]
                for binding in values:
                    if binding.get('source')=='external':
                        data=self.service.visualization_goals.read_input(item['compiled']['target'],binding,now)
                        if not usable(data,now,frame=binding.get('frame'),max_age_s=binding.get('max_age_s')):raise ValueError('external input stale or invalid before Run')
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
            if p['operation']=='takeover':raise ValueError('explicit confirmed takeover endpoint required')
            if p['operation']=='resume':
                run=self.service.missions.view(p['id'])
                if run['state']=='SUSPENDED':
                    if run['target'] in self.service.operator_controls.records:raise ValueError('Vehicle Control must release its reservation before Mission resume')
                    self.service._idle(run['target'])
            return self.service.missions.debug(p['id'],p['operation'],node_id=p.get('node_id'),parameters=p.get('parameters'))
        if op=='run.takeover':
            if set(p)!={'id','confirmed'} or p['confirmed'] is not True:raise ValueError('explicit takeover confirmation required')
            self.service._require_operational();return self.service.missions.debug(p['id'],'takeover')
        raise ValueError('unknown Mission Studio operation')

    def close(self):self.library.close()
