"""Explicit deployment registration of external endpoints (no auto-discovery)."""
from concurrent.futures import Future
from datetime import datetime,timezone
import os
from pathlib import Path
from uuid import uuid4

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.actions.external.clients import ProcessJob,ApiJob
from vehicle_autonomy.actions.external.job import ExternalFactory,WaitParameters
from vehicle_autonomy.contracts.action import ActionContext,ActionKind,ActionResource,ActionSafety
from vehicle_autonomy.contracts.core.primitives import ResourceVersion,SchemaVersion
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.contracts.world.models import WorldSnapshot
from vehicle_autonomy.engine.action.resources import PersistentResources


class ExternalActionDriver:
    def __init__(self,target='external',*,state_dir=None,resource_scope='external'):
        self.target=target
        base=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))
        self.resource_store=PersistentResources(state_dir or os.environ.get('VAF_ACTION_RESOURCE_DIR') or
            base/'vehicle-autonomy/action-resources',resource_scope)
    def context(self):return ActionContext(self.target,'external',frozenset({'external'}))
    def snapshot(self):
        return WorldSnapshot(SchemaVersion(1,0),'external:world',ResourceVersion('external',1),
            TimePoint(__import__('time').monotonic_ns(),datetime.now(timezone.utc),'host-monotonic-simulation'))
    def info(self):return dict(target=self.target,kind='external',connected=True,owned_simulation=False,
        system_send=False,action_send=False,deployment_send=False,capabilities=['external'])
    def effect_results(self,identifier):return ()
    def begin_exit(self,identifier):pass
    def finish_scope(self,identifier,**kw):f=Future();f.set_result(ActionSafety(True));return f
    def guard_status(self,identifier):return None
    def close(self):pass


def reconcile_api_resource(record,*,token=None):
    """Read the existing job only; never create/cancel/resubmit during recovery.

    Call from trusted deployment recovery with the stable resource scope and
    the same provider credentials. A missing ID cannot be resolved this way.
    """
    descriptor=record['descriptor']
    identity=ApiJob.identity(descriptor['endpoint'],token=token)
    if any(identity[k]!=record['provider'][k] for k in ('provider_id','provider_epoch','resource_id')):
        return ActionSafety(False,False,'recovery provider identity/epoch mismatch')
    value=ApiJob.query_existing(descriptor,token=token)
    terminal=value.get('state') in ('SUCCEEDED','FAILED','CANCELLED')
    return ActionSafety(terminal,False,None if terminal else 'external job still unresolved',
        {'owner':record['owner'],'scope':record['scope'],'terminal':terminal,
         'job_id':descriptor.get('job_id'),'state':value.get('state'),'verification':'read_existing_provider_job'})


def register_external(registry,name,create_job,*,continuous=False,parameters_type=WaitParameters,output_schema=None,resource_store=None):
    registry.register_typed(ActionSpec(name,parameters_type,frozenset({'external'}),kind=ActionKind.CONTINUOUS if continuous else ActionKind.GOAL,
        vehicle_types=frozenset({'external'}),resources=(ActionResource('ai.inference'),),
        description='Explicit external job endpoint; no vehicle authority',default_timeout_ns=10_000_000_000,
        output_schema=output_schema or {'type':'object','description':'Provider-specific JSON result; deployments may supply a stricter schema'},
        success_semantics='External terminal result; lost response retains UNKNOWN and its resource.',external_lifecycle='managed'),ExternalFactory(create_job,resource_store=resource_store))


def ros_job(name,parameters,*,service=False,domain_id=172,result_timeout=40):
    if not 0<=domain_id<=232:raise ValueError('bounded explicit ROS domain required')
    from vehicle_autonomy.actions.external import ros_worker
    env=dict(os.environ,ROS_DOMAIN_ID=str(domain_id),ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
    return ProcessJob([str(resource_root()/'scripts/with_ros2.sh'),'/usr/bin/python3',str(Path(ros_worker.__file__)),
        '--name',name,'--duration',str(getattr(parameters,'duration_s',.5)),'--result-timeout',str(result_timeout),*(['--service'] if service else [])],env=env)


def initialize_http_resources(directory,endpoint,verify_inventory,*,scope='external',token=None):
    """Trusted local deployment bootstrap using the actual public identity."""
    identity=ApiJob.identity(endpoint,token=token)
    def verify():
        assessment=verify_inventory()
        if not isinstance(assessment,ActionSafety):raise TypeError('trusted provider inventory proof required')
        from vehicle_autonomy.contracts.core.serialization import to_json_value
        evidence=to_json_value(assessment.evidence) or {}
        evidence.update(identity,protocol='http_job',locator=endpoint.rstrip('/'))
        return ActionSafety(assessment.release_safe,assessment.continuation_allowed,assessment.reason,evidence)
    return PersistentResources.initialize(directory,verify,scope=scope)
