from pathlib import Path
import sys
import time
from uuid import uuid4

CTX = dict(vehicle_id='rover', vehicle_type='rover', environment='simulation', ros_namespace='/rover', ros_domain_id=91, mavlink_profile='monitor')


def tool(name='fixture', *, code=None, ready=True):
    return dict(schema=1, id=name, name=name, type='service', version='test', supported_os=['linux'], dependencies=[],
        install_detection=[dict(kind='executable', value=sys.executable)], stop_strategy='owned_process_group',
        integrations=[], agent_requirements=[], permissions=[], profiles={'default':dict(
            argv=[sys.executable, '-u', '-c', code or 'import time; print("started", flush=True); time.sleep(120) # fixture '+uuid4().hex],
            env={}, health=dict(argv=[sys.executable, '-c', 'print("ok")'], contains=['ok']),
            ready=dict(argv=[sys.executable, '-c', 'print("ready")'], contains=['ready']) if ready else None,
            connection=dict(kind='test', description='process fixture, not ROS or SITL'), startup_timeout_s=2, stop_timeout_s=.2)})


def wait(predicate, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = predicate()
        if result: return result
        time.sleep(.04)
    raise AssertionError('condition timed out')
