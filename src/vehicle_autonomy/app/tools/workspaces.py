"""Bounded dependency orchestration and shared ownership, outside Mission runtime."""
from copy import deepcopy
from threading import Event, Thread
import time
from uuid import uuid4

from .schema import compatibility, context, fingerprint, identifier, number, object_fields, string


def validate(value):
    object_fields(value,('schema','id','name','context','components'))
    if value['schema']!=1:raise ValueError('Workspace schema 1 required')
    identifier(value['id']);string(value['name'],128);context(value['context'])
    if type(value['components']) is not list or not 1<=len(value['components'])<=24:raise ValueError('1..24 components required')
    nodes={};assignments=set()
    for c in value['components']:
        object_fields(c,('id','agent_id','tool_id','profile_id','depends_on','optional','wait_for','timeout_s'))
        for k in ('id','agent_id','tool_id','profile_id'):identifier(c[k])
        if c['id'] in nodes:raise ValueError('duplicate component ID')
        key=(c['agent_id'],c['tool_id'])
        if key in assignments:raise ValueError('one Tool instance per Agent per Workspace')
        assignments.add(key);nodes[c['id']]=c
        if type(c['depends_on']) is not list or len(c['depends_on'])>24 or len(set(c['depends_on']))!=len(c['depends_on']):raise ValueError('bounded unique dependencies required')
        for dep in c['depends_on']:identifier(dep)
        if type(c['optional']) is not bool or c['wait_for'] not in ('running','ready'):raise ValueError('explicit optional/readiness policy required')
        number(c['timeout_s'],1,180)
    visited=set();visiting=set();order=[]
    def visit(key):
        if key not in nodes:raise ValueError('unknown Workspace dependency')
        if key in visiting:raise ValueError('Workspace dependency cycle')
        if key in visited:return
        visiting.add(key)
        for dep in nodes[key]['depends_on']:visit(dep)
        visiting.remove(key);visited.add(key);order.append(key)
    for key in nodes:visit(key)
    result=deepcopy(value);result['components']=[deepcopy(nodes[k]) for k in order];return result


TEMPLATES=(dict(id='rover-navigation',name='Rover Navigation',description='ROS 2 → Nav2 + RViz2; requires configured map/TF/sensor inputs'),
    dict(id='uav-ground-station',name='UAV Ground Station',description='Copter/Plane context + existing telemetry-only MAVLink relay + QGC'),
    dict(id='uav-visualization',name='UAV Visualization',description='Existing Copter/Plane → Visualization Bridge → desktop RViz2; optional telemetry-only QGC'),
    dict(id='simulation-visualization',name='Simulation Visualization',description='Observe existing matching Framework-owned Gazebo/SITL → Bridge → RViz2; vehicle lifecycle remains with trusted launcher'),
    dict(id='simulation-lab',name='Simulation Lab',description='Gazebo + native SITL + QGC, optional RViz2; select matching coupled profiles for vehicle physics'))


def template(template_id, ctx, agents):
    identifier(template_id);ctx=context(ctx)
    def host(tool):
        candidates=[a for a in agents if any(t['manifest']['id']==tool for t in a['tools'])]
        return next((a['id'] for a in candidates if a['role']=='desktop' and tool in ('rviz2','qgroundcontrol')),candidates[0]['id'] if candidates else 'select-agent')
    def component(tool,depends=(),optional=False,wait_for='ready',profile='default'):
        return dict(id=tool,agent_id=host(tool),tool_id=tool,profile_id=profile,depends_on=list(depends),optional=optional,wait_for=wait_for,timeout_s=120)
    paired=sorted([a for a in agents if all(any(t['manifest']['id']==tool and ctx['vehicle_type'] in t['manifest']['profiles'] for t in a['tools']) for tool in ('visualization-bridge','rviz2'))],key=lambda a:(a['role']!='desktop',a['id']))
    def visual(depends=()):
        result=[component('visualization-bridge',depends,profile=ctx['vehicle_type']),component('rviz2',['visualization-bridge'],profile=ctx['vehicle_type'])]
        if paired:
            for c in result:c['agent_id']=paired[0]['id']
        return result
    if template_id=='rover-navigation':
        if ctx['vehicle_type']!='rover':raise ValueError('Rover Navigation requires Rover context')
        if paired:
            components=[component('ros2'),*visual(['ros2']),component('nav2',['ros2'],True),component('slam',['ros2'],True)]
            components[0]['agent_id']=paired[0]['id']
        else:components=[component('ros2'),component('nav2',['ros2']),component('rviz2',['ros2'],True)]
    elif template_id=='uav-visualization':
        if ctx['vehicle_type'] not in ('copter','plane'):raise ValueError('UAV Visualization requires Copter/Plane context')
        components=[*visual(),component('qgroundcontrol',optional=True,wait_for='running',profile='monitor')]
    elif template_id=='simulation-visualization':
        if ctx['environment']!='simulation':raise ValueError('Simulation Visualization requires simulation context')
        components=[component('gazebo',profile='framework-owned'),component('sitl',['gazebo'],profile='framework-owned'),*visual(['sitl'])]
        for c in components[:2]:
            qualified=next((a for a in agents if any(t['manifest']['id']==c['tool_id'] and 'framework-owned' in t['manifest']['profiles'] for t in a['tools'])),None)
            if qualified:c['agent_id']=qualified['id']
    elif template_id=='uav-ground-station':
        if ctx['vehicle_type'] not in ('copter','plane'):raise ValueError('UAV Ground Station requires Copter/Plane context')
        components=[component('qgroundcontrol',wait_for='running',profile='monitor')]
    elif template_id=='simulation-lab':
        if ctx['environment']!='simulation':raise ValueError('Simulation Lab requires simulation context')
        components=[component('gazebo',profile='headless'),component('sitl',['gazebo'],profile=ctx['vehicle_type']),component('qgroundcontrol',['sitl'],wait_for='running',profile='monitor'),component('rviz2',['sitl'],True)]
        if ctx['vehicle_type']=='rover':
            pair=next((a for a in agents if all(any(t['manifest']['id']==tool and 'rover-coupled' in t['manifest']['profiles'] for t in a['tools']) for tool in ('gazebo','sitl'))),None)
            if pair:
                for c in components[:2]:c.update(agent_id=pair['id'],profile_id='rover-coupled')
                components[0]['wait_for']='running'  # JSON FDM starts after Gazebo process, then stats qualify readiness.
    else:raise ValueError('unknown Workspace template')
    return validate(dict(schema=1,id=template_id,name=next(t['name'] for t in TEMPLATES if t['id']==template_id),context=ctx,components=components))


class Workspaces:
    def __init__(self,service):
        self.service=service;self.registry=service.registry;self.store=service.store
        self.data=self.store.load('workspaces.json',dict(schema=1,definitions={},runs={},leases={}))
        object_fields(self.data,('schema','definitions','runs','leases'))
        if self.data['schema']!=1:raise ValueError('unsupported Workspace store')
        for spec in self.data['definitions'].values():validate(spec)
        for run in self.data['runs'].values():
            if run['state'] not in ('STOPPED','ABANDONED') and any(run['id'] in l['owners'] for l in self.data['leases'].values()):
                run.update(state='UNKNOWN',recovering=True,error='backend restarted; explicit instance reconciliation required')
                for c in run['components']:
                    if c['state'] not in ('STOPPED','RELEASED'):c.update(state='UNKNOWN',observed_ready=False)
        self.fault=None;self.closed=Event();self.thread=Thread(target=self._monitor,name='workspace-manager',daemon=True);self.thread.start()

    @staticmethod
    def key(c):return c['agent_id']+'/'+c['tool_id']

    def _persist(self):self.store.save('workspaces.json',self.data)

    def _find(self,c):
        a,t=self.service.selected(c['agent_id'],c['tool_id'],c['profile_id'])
        if not self.registry.online(a):raise ValueError('Agent disconnected: '+c['agent_id'])
        return a,t

    def assert_unshared(self,agent,tool):
        lease=self.data['leases'].get(agent+'/'+tool)
        if lease and lease['owners']:raise ValueError('Workspace owns/shares this service; stop the Workspace first')

    def assert_compatible(self,c,ctx):
        lease=self.data['leases'].get(self.key(c))
        if lease and lease['owners'] and (lease['profile_id']!=c['profile_id'] or lease['context']!=compatibility(ctx)):
            raise ValueError('incompatible shared service profile/context')

    def manual_operation(self,payload,job):
        key=self.key(payload)
        if payload['operation'] in ('launch','open','restart'):
            lease=self.data['leases'].get(key)
            if lease is None or not lease['owners']:
                lease=dict(profile_id=payload['profile_id'],context=compatibility(payload['context']),boot_id=job['boot_id'],instance_id=None,owners=[],baseline=True,launch_job_id=job['id'])
                self.data['leases'][key]=lease
            else:lease['baseline']=True
            self._persist()
        elif payload['operation']=='stop' and key in self.data['leases']:
            self.data['leases'].pop(key);self._persist()

    def _preflight(self,c,ctx):
        a,t=self._find(c);self.assert_compatible(c,ctx)
        instance=t['instance']
        if instance and (instance.get('process_running') or instance.get('state') in ('STARTING','STOPPING')):
            if not instance['owned'] or instance['context']!=compatibility(ctx) or instance['profile_id']!=c['profile_id']:
                raise ValueError('existing service has incompatible/unknown ownership or context')
        elif t['external_pids']:raise ValueError('external process is observation-only; context/ownership unknown')
        elif not t['checks'][c['profile_id']]['launchable']:
            raise ValueError('Missing Dependency: '+'; '.join(t['checks'][c['profile_id']]['missing']))
        if c['wait_for']=='ready' and not t['manifest']['profiles'][c['profile_id']]['readiness_probe']:
            raise ValueError('profile has no functional readiness probe; choose explicit running threshold')
        return a,t

    def handle(self,operation,payload):
        if self.fault:raise ValueError('Workspace persistence fenced: '+self.fault)
        if operation=='workspace.template':
            object_fields(payload,('template_id','context'))
            return template(payload['template_id'],payload['context'],self.registry.snapshot()['agents'])
        if operation=='workspace.save':
            object_fields(payload,('spec',));spec=validate(payload['spec'])
            if spec['id'] not in self.data['definitions'] and len(self.data['definitions'])>=64:raise ValueError('Workspace definition budget exhausted')
            self.store.audit(operation,workspace=spec['id']);self.data['definitions'][spec['id']]=spec;self._persist();return spec
        if operation=='workspace.launch':
            object_fields(payload,('id',));identifier(payload['id']);spec=deepcopy(self.data['definitions'][payload['id']])
            if any(r['spec']['id']==spec['id'] and r['state'] not in ('STOPPED','ABANDONED','FAILED') for r in self.data['runs'].values()):raise ValueError('Workspace already active; use retry or stop')
            if len(self.data['runs'])>=128:raise ValueError('Workspace run history budget exhausted')
            # Preflight ALL required components before the first launch.
            components=[];failed=False
            for c in spec['components']:
                component=deepcopy(c)|dict(state='PENDING',error=None,job_id=None,stop_job_id=None,instance_id=None,deadline=0.,observed_ready=False)
                try:self._preflight(c,spec['context'])
                except Exception as exc:
                    component.update(state='SKIPPED' if c['optional'] else 'FAILED',error=str(exc)[:500]);failed|=not c['optional']
                components.append(component)
            run=dict(id=uuid4().hex,spec=spec,state='FAILED' if failed else 'PREPARING',components=components,
                     error='required preflight failed; nothing launched' if failed else None,recovering=False,started_at=time.time())
            self.store.audit(operation,workspace=spec['id'],run=run['id'],preflight_passed=not failed)
            self.data['runs'][run['id']]=run;self._persist();return deepcopy(run)
        if operation in ('workspace.stop','workspace.retry'):
            object_fields(payload,('run_id',));run=self.data['runs'][identifier(payload['run_id'])]
            if run.get('recovering'):raise ValueError('reconcile backend restart before stop/retry')
            self.store.audit(operation,run=run['id'])
            if operation=='workspace.stop':
                run.update(state='STOPPING',stop_deadline=time.monotonic()+25)
                for c in run['components']:
                    stop=self.registry.jobs.get(c.get('stop_job_id'))
                    if stop and stop['state'] in ('FAILED','EXPIRED','UNKNOWN'):c['stop_job_id']=None
            else:
                if run['state'] not in ('FAILED','DEGRADED','PREPARED'):raise ValueError('only failed/degraded components can retry')
                for c in run['components']:
                    if c['state'] in ('FAILED','SKIPPED','BLOCKED'):
                        c.update(state='PENDING',error=None,job_id=None,stop_job_id=None,deadline=0.)
                run.update(state='PREPARING',error=None)
            self._persist();return deepcopy(run)
        if operation=='workspace.reconcile':return self._reconcile(payload)
        raise ValueError('unsupported Workspace operation')

    def _reconcile(self,payload):
        object_fields(payload,('run_id','decision','instances'));run=self.data['runs'][identifier(payload['run_id'])]
        if not run.get('recovering') or payload['decision'] not in ('resume','release') or type(payload['instances']) is not dict:raise ValueError('explicit restarted-run reconciliation required')
        if payload['decision']=='release':
            for lease in self.data['leases'].values():
                if run['id'] in lease['owners']:lease['owners'].remove(run['id']);lease['baseline']=True
            run.update(state='ABANDONED',recovering=False,error='operator released records without asserting process cleanup')
            for c in run['components']:c.update(state='RELEASED',observed_ready=False)
        else:
            claims=[]
            for c in run['components']:
                lease=self.data['leases'].get(self.key(c))
                if not lease or run['id'] not in lease['owners']:continue
                a,t=self._find(c);i=t['instance'];expected=payload['instances'].get(c['id'])
                if not i or expected!=i['instance_id'] or a['boot_id']!=lease['boot_id'] or i['context']!=lease['context'] or i['profile_id']!=lease['profile_id']:
                    raise ValueError('current Agent boot/context/instance does not match operator reconciliation')
                if lease['instance_id'] is not None and lease['instance_id']!=expected:raise ValueError('pinned service instance changed')
                claims.append((c,lease,expected))
            for c,lease,expected in claims:
                c.update(instance_id=expected,state='WAITING',error=None,deadline=time.monotonic()+c['timeout_s']);lease['instance_id']=expected
            for c in run['components']:
                if c['state']=='UNKNOWN':c.update(state='PENDING',job_id=None,error=None)
            run.update(state='PREPARING',recovering=False,error=None)
        self.store.audit('workspace.reconcile',run=run['id'],decision=payload['decision']);self._persist();return deepcopy(run)

    def _start(self,run,c):
        a,t=self._preflight(c,run['spec']['context']);key=self.key(c);lease=self.data['leases'].get(key);i=t['instance']
        c['visualization']='ros2.visualization' in t['manifest']['integrations']
        live=i and (i['process_running'] or i['state']=='STARTING')
        if lease is None or not lease['owners'] and (lease['boot_id']!=a['boot_id'] or lease['context']!=compatibility(run['spec']['context']) or lease['profile_id']!=c['profile_id']):
            lease=dict(profile_id=c['profile_id'],context=compatibility(run['spec']['context']),boot_id=a['boot_id'],
                       instance_id=i['instance_id'] if live else None,owners=[],baseline=bool(live))
            self.data['leases'][key]=lease
        if run['id'] not in lease['owners']:lease['owners'].append(run['id'])
        if a['boot_id']!=lease['boot_id']:raise ValueError('service Agent boot changed; reconciliation required')
        if live and lease['instance_id'] is None:lease['instance_id']=i['instance_id']
        if not live and i and i['cleanup_confirmed']:lease['instance_id']=None
        c.update(state='WAITING',deadline=time.monotonic()+c['timeout_s'],instance_id=lease['instance_id'],
                 before_instance_id=None if i is None else i['instance_id'])
        self._persist()  # claim/intent durable BEFORE mailbox side effect
        if not live:
            previous=self.registry.jobs.get(lease.get('launch_job_id'))
            if previous and previous['state'] in ('QUEUED','DELIVERED'):
                c['job_id']=previous['id']
            else:
                job=self.registry.submit(c['agent_id'],'launch',c['tool_id'],c['profile_id'],run['spec']['context'])
                c['job_id']=job['id'];lease['launch_job_id']=job['id']
            self._persist()

    def _observe(self,run,c):
        a,t=self._find(c);lease=self.data['leases'][self.key(c)];i=t['instance']
        if a['boot_id']!=lease['boot_id']:raise ValueError('Agent boot changed; prior service outcome unknown')
        job=self.registry.jobs.get(c['job_id'])
        if job and job['state'] in ('FAILED','EXPIRED','CANCELLED'):raise ValueError(job['error'] or 'launch rejected')
        if i and (c['instance_id'] is not None or i['instance_id']!=c.get('before_instance_id')):
            if not i['owned'] or i['profile_id']!=c['profile_id'] or i['context']!=lease['context']:raise ValueError('service identity/context changed')
            if lease['instance_id'] is not None and lease['instance_id']!=i['instance_id']:raise ValueError('pinned service instance changed')
            c['instance_id']=i['instance_id'];lease['instance_id']=i['instance_id'];c['observed_ready']=i['ready']
            if i['state'] in ('FAILED','UNKNOWN') or i['process_running'] is False and i['state']!='STARTING':raise ValueError(i['error'] or 'service exited')
            if i['ready']:c['state']='READY';c['qualified_once']=True
            elif i['process_running'] and c['wait_for']=='running':c['state']='RUNNING'
            elif i['process_running'] and c.get('qualified_once') and 'ros2.visualization' in t['manifest']['integrations']:c['state']='DEGRADED'
            else:c['state']='WAITING'
        if c['state']=='WAITING' and time.monotonic()>c['deadline']:raise TimeoutError('Workspace component readiness timeout')

    def _stop_component(self,run,c):
        c['observed_ready']=False
        key=self.key(c);lease=self.data['leases'].get(key)
        if lease is None or run['id'] not in lease['owners']:c['state']='RELEASED';return
        if len(lease['owners'])>1 or lease['baseline']:
            lease['owners'].remove(run['id']);c['state']='RELEASED';return
        job=self.registry.jobs.get(c['job_id'])
        if job and job['state']=='QUEUED':
            job.update(state='CANCELLED',error='Workspace stopped before delivery')
        a,t=self._find(c);i=t['instance']
        if a['boot_id']!=lease['boot_id']:raise ValueError('Agent boot changed; cannot prove old process exit')
        if c['instance_id'] is None:
            if i and i['instance_id']!=c.get('before_instance_id') and i['profile_id']==c['profile_id'] and i['context']==lease['context']:
                c['instance_id']=i['instance_id'];lease['instance_id']=i['instance_id']
            elif job and job['state'] in ('FAILED','EXPIRED','CANCELLED'):
                lease['owners'].remove(run['id']);self.data['leases'].pop(key);c['state']='STOPPED';return
            else:raise ValueError('launch/instance outcome not yet confirmed')
        if i is None or i['instance_id']!=c['instance_id']:raise ValueError('owned instance identity lost')
        if i['process_running'] is False and i['cleanup_confirmed']:
            lease['owners'].remove(run['id']);self.data['leases'].pop(key);c['state']='STOPPED';return
        if c['stop_job_id'] is None:
            self._persist()
            stop=self.registry.submit(c['agent_id'],'stop',c['tool_id'],c['profile_id'],run['spec']['context']);c['stop_job_id']=stop['id'];self._persist()
        stop=self.registry.jobs.get(c['stop_job_id'])
        if stop and stop['state'] in ('FAILED','EXPIRED'):raise ValueError(stop['error'] or 'stop failed')
        c['state']='STOPPING'

    def _tick(self,run):
        if run.get('recovering') or run['state'] in ('STOPPED','ABANDONED','FAILED','UNKNOWN'):return
        if run['state']=='STOPPING':
            for c in reversed(run['components']):
                if c['state'] in ('STOPPED','RELEASED'):continue
                if any(c['id'] in d['depends_on'] and d['state'] not in ('STOPPED','RELEASED') for d in run['components']):continue
                try:self._stop_component(run,c)
                except Exception as exc:c.update(state='UNKNOWN',error=str(exc)[:500])
            if all(c['state'] in ('STOPPED','RELEASED') for c in run['components']):run['state']='STOPPED'
            elif time.monotonic()>run.get('stop_deadline',float('inf')):run.update(state='UNKNOWN',error='Workspace cleanup unconfirmed; ownership retained, inspect and explicitly retry stop')
            return
        by_id={c['id']:c for c in run['components']}
        for c in run['components']:
            try:
                if c['state']=='PENDING':
                    deps=[by_id[key] for key in c['depends_on']]
                    if any(d['state'] in ('FAILED','SKIPPED','BLOCKED','UNKNOWN') for d in deps):c.update(state='SKIPPED' if c['optional'] else 'BLOCKED',error='dependency failed');continue
                    if any(d['state'] not in ('READY','RUNNING') for d in deps):continue
                    self._start(run,c)
                if c['state'] in ('WAITING','RUNNING','READY','DEGRADED'):self._observe(run,c)
            except Exception as exc:
                agent=self.registry.agents.get(c['agent_id']);lease=self.data['leases'].get(self.key(c))
                if c.get('visualization') and (not agent or not self.registry.online(agent) or lease and agent['boot_id']!=lease['boot_id']):
                    c.update(state='UNKNOWN',observed_ready=False,error='visualization Agent disconnected or changed boot')
                    run.update(state='UNKNOWN',recovering=True,error='visualization ownership unknown; explicitly reconcile current instances after Agent recovery')
                    return
                c.update(state='SKIPPED' if c['optional'] else 'FAILED',observed_ready=False,error=type(exc).__name__+': '+str(exc)[:500])
        required=[c for c in run['components'] if not c['optional']]
        if any(c['state'] in ('FAILED','BLOCKED') for c in required):run.update(state='FAILED',error='required component failed; stop explicitly to release owned services')
        elif all(c['state'] in ('READY','RUNNING','SKIPPED','DEGRADED') for c in run['components']):
            run['state']='DEGRADED' if any(c['state'] in ('SKIPPED','DEGRADED') for c in run['components']) else 'READY' if all(c['observed_ready'] for c in run['components']) else 'PREPARED'
        else:run['state']='PREPARING'

    def _monitor(self):
        while not self.closed.wait(.1):
            with self.service.lock:
                try:
                    before=fingerprint(self.data)
                    self.registry.snapshot()  # expire jobs even without browser polling
                    for run in self.data['runs'].values():self._tick(run)
                    if fingerprint(self.data)!=before:self._persist()
                except Exception as exc:
                    self.fault=type(exc).__name__;self.closed.set()

    def snapshot(self):
        runs=deepcopy(list(self.data['runs'].values()))
        with self.registry.lock:
            agents={key:dict(online=self.registry.online(a),tools={t['manifest']['id']:t['instance'] for t in a['tools']}) for key,a in self.registry.agents.items()}
            for run in runs:
                for c in run['components']:
                    a=agents.get(c['agent_id']);i=None if a is None else a['tools'].get(c['tool_id'])
                    ended=c['state'] in ('STOPPED','RELEASED')
                    c['observed_ready']=bool(not ended and a and a['online'] and i and i['instance_id']==c['instance_id'] and i['ready'])
                    if not ended and (not a or not a['online']) and c['instance_id']:
                        c['state']='DISCONNECTED'
                        if run['state'] in ('READY','PREPARED','DEGRADED'):
                            run['state']='UNKNOWN'
                            if c.get('visualization'):run.update(recovering=True,error='visualization Agent offline; explicitly reconcile current instances after recovery')
        return dict(definitions=deepcopy(list(self.data['definitions'].values())),runs=runs,
            leases=deepcopy(self.data['leases']),templates=deepcopy(TEMPLATES),fault=self.fault)

    def close(self):
        self.closed.set();self.thread.join(12)
        if self.thread.is_alive():raise RuntimeError('Workspace worker did not exit')
