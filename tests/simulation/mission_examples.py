"""Example graphs on the Control Center's owned World/isolated Driver assembly."""
import argparse
import json
import math
import os
from pathlib import Path
from threading import Thread
import time
from urllib.request import Request, urlopen
from uuid import uuid4

from vehicle_autonomy.app.mission_designer.mission_examples import examples
from vehicle_autonomy.app.web.mission_control import MissionControl, MissionControlServer
from vehicle_autonomy.app.web.server import load_token
from tests.simulation.oracle import GazeboTruthOracle


def run(path, kind):
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    token = load_token(path/'web-token.private')
    app = MissionControl({}, path/'application', simulation_allow_send=True)
    server = MissionControlServer(('127.0.0.1', 0), app, token, path/'http.jsonl')
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:'+str(server.server_address[1])
    report = dict(passed=False, kind=kind, missions=[], assembly='Control Center isolated signed Driver')
    identifier = None

    def api(route, payload=None):
        headers = {'Authorization': 'Bearer '+token}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers.update({'Content-Type': 'application/json', 'X-VAF-CSRF': token, 'X-VAF-Request-ID': uuid4().hex})
        with urlopen(Request(base+route, data, headers), timeout=15) as response:
            value = json.load(response)
        if not value['ok']:
            raise AssertionError(value)
        return value['result']

    try:
        scene = {'rover': 'R01', 'copter': 'C01', 'plane': 'F01'}[kind]
        record = api('/api/simulation/create', dict(scene_id=scene, vehicle=kind, parameters={'obstacle_count': 0}))
        identifier = record['id']
        api('/api/simulation/start', {'id': identifier})
        app.simulation_manager.wait_ready(identifier, 150)
        owner = app.simulation_manager.owners[identifier]
        child = next(iter(owner.vehicles.values()))
        target, driver = child.target, child.driver
        os.environ.update(GZ_IP='127.0.0.1', GZ_PARTITION=owner.partition)
        oracle = GazeboTruthOracle(owner.world, child.model.name)
        until = time.monotonic()+45
        while time.monotonic() < until:
            time.sleep(.15)
        initial = oracle.latest()
        assert initial is not None
        templates = api('/api/studio-b/library')['templates']
        for definition in examples(target, kind):
            mission_id = definition['mission_id']
            assert mission_id in templates, 'late-attached simulation template missing'
            saved = api('/api/studio-b/draft/save', dict(definition=definition, expected_revision=0))
            revision = saved['definition']['revision']
            api('/api/studio-b/draft/validate', dict(mission_id=mission_id, revision=revision))
            publication = api('/api/studio-b/draft/publish', dict(mission_id=mission_id, revision=revision))
            motion = definition['metadata']['requires_send']
            mission = api('/api/studio-b/run/start', dict(publication=publication['key'], allow_send=motion, debug=False))
            deadline = time.monotonic()+definition['execution_policy']['timeout_s']+30
            checkpoints = {}
            while time.monotonic() < deadline:
                truth = oracle.latest()
                assert truth is not None and time.monotonic_ns()-truth.host_received_ns < 500_000_000
                view = app.missions.view(mission['id'])
                for action_id in view['action_ids']:
                    action = app.runtime.view(action_id)
                    if action['state'] == 'SUCCEEDED' and action_id not in checkpoints:
                        checkpoints[action_id] = dict(name=action['name'], position=[truth.x_m, truth.y_m, truth.z_m])
                if view['state'] in ('SUCCEEDED', 'FAILED', 'UNKNOWN', 'TIMED_OUT', 'CANCELLED', 'REJECTED'):
                    break
                time.sleep(.1)
            else:
                raise TimeoutError(mission_id)
            commands = [command for aid in view['action_ids'] for command in driver.command_feedback(aid)]
            result = dict(mission_id=mission_id, state=view['state'], error=view['error'], release_safe=view['release_safe'],
                          command_evidence_count=len(commands), checkpoints=list(checkpoints.values()), run_id=mission['id'])
            report['missions'].append(result)
            print(kind, mission_id, view['state'], view['error'], flush=True)
            if view['state'] != 'SUCCEEDED':
                result['actions'] = [app.runtime.view(aid) for aid in view['action_ids']]
            assert view['state'] == 'SUCCEEDED' and view['release_safe'], result
            if not motion:
                assert not commands
                info = driver.info()
                assert not info['system_send'] and not info['action_send'] and not info['lease_active']
                continue
            state = driver.snapshot().vehicle
            speed = oracle.recent_speed_mps()
            home_error = math.hypot(truth.x_m-initial.x_m, truth.y_m-initial.y_m)
            assert not state.operation.armed
            assert speed is not None and speed <= (1 if kind == 'plane' else .1 if kind == 'rover' else .15)
            if kind != 'rover':
                assert home_error <= (80 if kind == 'plane' else .75)
            result['physical'] = dict(home_error_m=home_error, speed_mps=speed, height_m=truth.z_m-initial.z_m)
            if kind == 'copter':
                takeoff = next(c for c in checkpoints.values() if c['name'] == 'Takeoff')
                assert takeoff['position'][2]-initial.z_m >= 1.15
                assert truth.z_m-initial.z_m < .25
                if mission_id == 'Example_Air_SurveyReturn':
                    goals = [c for c in checkpoints.values() if c['name'] == 'Goto']
                    assert len(goals) == 2
                    for goal, point in zip(goals, ((1, 0), (1, 1))):
                        assert math.dist(goal['position'][:2], [initial.x_m+point[0], initial.y_m+point[1]]) < .75
            if kind == 'rover':
                goals = [c for c in checkpoints.values() if c['name'] == 'Goto']
                assert len(goals) == 3
                for goal, point in zip(goals, ((1, 0), (2, 0), (3, 0))):
                    assert math.dist(goal['position'][:2], [initial.x_m+point[0], initial.y_m+point[1]]) < .75
                assert math.dist([truth.x_m, truth.y_m], [initial.x_m+3, initial.y_m]) < .75
            if kind == 'plane':
                takeoff = next(c for c in checkpoints.values() if c['name'] == 'Takeoff')
                assert takeoff['position'][2]-initial.z_m >= 45
                assert truth.z_m-initial.z_m < .25 and abs(truth.y_m-initial.y_m) < 15
        api('/api/simulation/stop', {'id': identifier})
        app.simulation_manager.threads[identifier].join(70)
        final = app.simulation_manager.sample(identifier)
        assert final['state'] == 'FINISHED' and final['cleanup'] == 'COMPLETE', final.get('error')
        report.update(passed=True, cleanup=final['cleanup'])
    finally:
        server.shutdown()
        server.server_close()
        app.close()
        (path/'examples-summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', required=True, choices=('rover', 'copter', 'plane'))
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--allow-send', action='store_true')
    args = parser.parse_args()
    if not args.allow_send:
        parser.error('explicit --allow-send required for owned simulation motion acceptance')
    run(args.run_dir.resolve(), args.kind)
