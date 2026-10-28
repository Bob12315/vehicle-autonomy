"""Operator use cases for external tools; never receives a vehicle driver."""
from copy import deepcopy
from threading import RLock

from .broker import AgentRegistry
from .schema import context, identifier, object_fields
from .storage import Store


DEFAULT_CONTEXT = dict(vehicle_id='rover', vehicle_type='rover', environment='simulation',
    ros_namespace='/rover', ros_domain_id=91, mavlink_profile='monitor')


class ToolService:
    def __init__(self, directory):
        self.store=Store(directory);self.lock=RLock();self.registry=AgentRegistry(self.store)
        self.settings=self.store.load('settings.json',dict(context=DEFAULT_CONTEXT,profiles={}))
        context(self.settings['context'])
        from .workspaces import Workspaces
        self.workspaces=Workspaces(self)

    def selected(self, agent_id, tool_id, profile_id):
        identifier(agent_id);identifier(tool_id);identifier(profile_id)
        with self.registry.lock:
            agent=self.registry.agents[agent_id]
            tool=next(t for t in agent['tools'] if t['manifest']['id']==tool_id)
            if profile_id not in tool['manifest']['profiles']:raise ValueError('unknown registered profile')
            return agent,tool

    def handle(self, operation, payload):
        with self.lock:
            if operation=='settings.context':
                ctx=context(payload);value=deepcopy(self.settings);value['context']=ctx
                self.store.audit('settings.context',context=ctx);self.store.save('settings.json',value);self.settings=value
                return ctx
            if operation=='tools.configure':
                object_fields(payload,('agent_id','tool_id','profile_id','context'))
                self.selected(payload['agent_id'],payload['tool_id'],payload['profile_id']);ctx=context(payload['context'])
                value=deepcopy(self.settings);key=payload['agent_id']+':'+payload['tool_id']
                value['profiles'][key]=dict(profile_id=payload['profile_id'],context=ctx)
                self.store.audit('tool.configure',agent=payload['agent_id'],tool=payload['tool_id'],profile=payload['profile_id'])
                self.store.save('settings.json',value);self.settings=value;return value['profiles'][key]
            if operation=='tools.operation':
                object_fields(payload,('agent_id','tool_id','profile_id','operation','context'))
                if self.workspaces and payload['operation'] in ('stop','restart'):
                    self.workspaces.assert_unshared(payload['agent_id'],payload['tool_id'])
                if self.workspaces and payload['operation'] in ('launch','open'):
                    self.workspaces.assert_compatible(payload,payload['context'])
                result=self.registry.submit(payload['agent_id'],payload['operation'],payload['tool_id'],payload['profile_id'],payload['context'])
                if self.workspaces:self.workspaces.manual_operation(payload,result)
                return result
            if operation.startswith('workspace.') and self.workspaces:
                return self.workspaces.handle(operation,payload)
            raise ValueError('unsupported Tool service operation')

    def snapshot(self):
        with self.lock:
            return dict(**self.registry.snapshot(),settings=deepcopy(self.settings),events=list(self.store.events)[-100:],
                        workspaces=None if self.workspaces is None else self.workspaces.snapshot())

    def close(self):
        if self.workspaces:self.workspaces.close()
        self.store.close()
