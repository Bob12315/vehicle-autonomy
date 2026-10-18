"""Read-only Rover Application -> actual SLAM map -> actual Nav2 path; no SEND."""
import argparse
import json
from pathlib import Path
import time
from uuid import uuid4

from app.control import request
from app.plan import LiveMapProvider
from application.planning import ReadOnlyPlanningService
from integrations.ros2.nav2_planner import Nav2Planner
from mapping.exchange import MappingConfig
from mapping.grid import atomic_json
from planning.models import Pose2D
from tests.simulation.launch import ROOT,install_signal_cleanup
from tests.simulation.nav2_planning import oracle
from tests.simulation.ros2_mapping import run


def probe(endpoint,config,directory):
    provider=LiveMapProvider(MappingConfig.load(config,'host-monotonic-simulation'),endpoint)
    # Initial transport/SLAM startup can precede Application READY by a cycle.
    until=time.monotonic()+10
    while time.monotonic()<until:
        before=request(endpoint,'status')['result']
        if before['state']=='READY' and before['mapping']['adopted']:break
        time.sleep(.1)
    else:raise RuntimeError('read-only Application did not become ready')
    if before['system_send'] or before['action_send'] or before['vehicle']['armed'] or before['task'] is not None:
        raise RuntimeError('planning test requires untouched disarmed read-only application')
    backend=Nav2Planner(directory/'planning')
    context=provider()
    path=ReadOnlyPlanningService(provider,backend,provider.clock).plan(Pose2D(0,0),Pose2D(1.,0))
    document=path.document()
    independent=oracle(context.grid,document['poses'],.55)
    after=request(endpoint,'status')['result']
    if after['system_send'] or after['action_send'] or after['vehicle']['armed'] or after['task'] is not None:
        raise RuntimeError('read-only planning changed Application authority/task')
    if document['map']['source_kind']!='live_map' or document['executable']:
        raise RuntimeError('live map provenance or non-executable result missing')
    atomic_json(directory/'live-path.json',document)
    atomic_json(directory/'planning-app-status.json',{'before':before,'after':after})
    # Confirm planning never created a vehicle command request or motion Effect.
    events=[json.loads(line) for line in (directory/'application.log').read_text().splitlines() if line.startswith('{')]
    if any(event.get('event') in ('task_started','effect_requested','effect_dispatched') for event in events):
        raise RuntimeError('unexpected task/effect during planning')
    return {'passed':True,'points':len(path.candidate.poses),'length_m':path.length_m,
            'source_kind':document['map']['source_kind'],'source_map_sha256':document['map']['sha256'],
            'executable':False,'system_send':after['system_send'],'action_send':after['action_send'],
            'vehicle_armed':after['vehicle']['armed'],'task':after['task'],
            'backend_directory':str(backend.last_directory),**independent}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',type=Path)
    args=parser.parse_args();install_signal_cleanup()
    directory=(args.run_dir or ROOT/'artifacts/simulation'/('nav2-live-'+uuid4().hex[:8])).resolve()
    report=run(directory,smoke=True,planning_probe=probe)
    print(json.dumps({'directory':str(directory),**report}));return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
