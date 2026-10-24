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


class ExternalActionDriver:
    def __init__(self,target='external'):self.target=target
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


def register_external(registry,name,create_job,*,continuous=False,parameters_type=WaitParameters):
    registry.register_typed(ActionSpec(name,parameters_type,frozenset({'external'}),kind=ActionKind.CONTINUOUS if continuous else ActionKind.GOAL,
        vehicle_types=frozenset({'external'}),resources=(ActionResource('ai.inference'),),
        description='Explicit external job endpoint; no vehicle authority',default_timeout_ns=10_000_000_000,
        success_semantics='External terminal result; lost response retains UNKNOWN and its resource.'),ExternalFactory(create_job))


def ros_job(name,parameters,*,service=False,domain_id=172,result_timeout=40):
    if not 0<=domain_id<=232:raise ValueError('bounded explicit ROS domain required')
    from vehicle_autonomy.actions.external import ros_worker
    env=dict(os.environ,ROS_DOMAIN_ID=str(domain_id),ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
    return ProcessJob([str(resource_root()/'scripts/with_ros2.sh'),'/usr/bin/python3',str(Path(ros_worker.__file__)),
        '--name',name,'--duration',str(getattr(parameters,'duration_s',.5)),'--result-timeout',str(result_timeout),*(['--service'] if service else [])],env=env)
