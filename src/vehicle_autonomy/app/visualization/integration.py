"""Compose the existing Tool/Workspace use cases; never own a vehicle port."""
from hashlib import sha256
import json

from vehicle_autonomy.app.tools.schema import compatibility,context
from .state import snapshot


def open_rviz(service,target):
    source=snapshot(service,target);tools=getattr(service,'tool_service',None)
    if tools is None:raise ValueError('Tool Manager is not configured')
    with tools.lock:
        saved=tools.settings['context']
        ctx=dict(vehicle_id=target,vehicle_type=source['kind'],environment=source['environment'],
            ros_namespace=saved['ros_namespace'] if saved['vehicle_id']==target else '/'+''.join(c if c.isalnum() or c=='_' else '_' for c in target),
            ros_domain_id=saved['ros_domain_id'],mavlink_profile=saved['mavlink_profile'])
        ctx=context(ctx);kind=source['kind'];agents=tools.registry.snapshot()['agents'];candidates=[]
        for agent in agents:
            if not agent['connected']:continue
            manifests={t['manifest']['id']:t for t in agent['tools']}
            if all(tool in manifests and kind in manifests[tool]['manifest']['profiles'] and manifests[tool]['checks'][kind]['installed']
                   for tool in ('visualization-bridge','rviz2')):
                if manifests['rviz2']['checks'][kind]['desktop']:candidates.append(agent)
        if not candidates:raise ValueError('No online Agent with configured Visualization Bridge, matching RViz profile and desktop; provision its trusted registry first')
        agent=sorted(candidates,key=lambda a:(a['role']!='desktop',a['id']))[0]
        for previous in tools.workspaces.data['runs'].values():
            if previous['state'] in ('STOPPED','ABANDONED') or compatibility(previous['spec']['context'])==compatibility(ctx):continue
            conflicting=[c for c in previous['components'] if c['agent_id']==agent['id'] and c['tool_id'] in ('visualization-bridge','rviz2') and c['state'] not in ('STOPPED','RELEASED')]
            if not conflicting:continue
            if not previous['spec']['id'].startswith('visualization-') or {c['tool_id'] for c in previous['components']}!={'visualization-bridge','rviz2'}:
                raise ValueError('selected Agent is used by another Workspace/context; explicitly release that Workspace first')
            for c in conflicting:
                lease=tools.workspaces.data['leases'].get(tools.workspaces.key(c))
                if lease and (lease['baseline'] or set(lease['owners'])!={previous['id']}):raise ValueError('visualization process is shared or manually owned; no automatic context switch')
            if previous['state']!='STOPPING':tools.handle('workspace.stop',dict(run_id=previous['id']))
            return dict(state='SWITCHING',previous_run_id=previous['id'],agent_id=agent['id'],context=ctx,
                error='waiting for prior visualization-only Workspace to exit; vehicle/Mission unaffected')
        digest=sha256(json.dumps(dict(context=compatibility(ctx),agent=agent['id']),sort_keys=True).encode()).hexdigest()[:16]
        identity='visualization-'+digest
        for run in tools.workspaces.data['runs'].values():
            if run['spec']['id']==identity and run['state'] not in ('STOPPED','FAILED','ABANDONED'):
                return dict(workspace_id=identity,run_id=run['id'],state=run['state'],reused=True,agent_id=agent['id'],context=ctx,error=run['error'])
        components=[dict(id=tool,agent_id=agent['id'],tool_id=tool,profile_id=kind,depends_on=[] if tool=='visualization-bridge' else ['visualization-bridge'],optional=False,wait_for='ready',timeout_s=90) for tool in ('visualization-bridge','rviz2')]
        spec=dict(schema=1,id=identity,name=kind.title()+' RViz2 Visualization',context=ctx,components=components)
        tools.handle('workspace.save',dict(spec=spec));run=tools.handle('workspace.launch',dict(id=identity))
        return dict(workspace_id=identity,run_id=run['id'],state=run['state'],reused=False,agent_id=agent['id'],context=ctx,error=run['error'])
