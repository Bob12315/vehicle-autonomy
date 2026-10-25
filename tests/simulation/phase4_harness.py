"""Two frozen Phase 4 A--J rounds, followed by unchanged full Phase 1/2/3."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from uuid import uuid4
from tests.simulation.harness import StageRunner,stamp
from tests.simulation.launch import output
from tests.simulation.phase3_harness import source_hash,cleaned


def tracked_inputs():
    """Include binary meshes, CI and all tracked baselines, not suffix guesses."""
    names=subprocess.check_output(['git','ls-files','-z']).decode().split('\0')
    return {name:hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in names if name and Path(name).is_file()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-send',action='store_true');parser.add_argument('--sitl-bin-dir',type=Path,required=True);parser.add_argument('--run-dir',type=Path,required=True)
    a=parser.parse_args()
    if not a.allow_send:parser.error('explicit SEND for newly owned local simulations required')
    if output(['git','status','--porcelain']):parser.error('commit/freeze all source and tests before formal acceptance')
    binary=a.sitl_bin_dir.resolve()
    if not all((binary/n).is_file() for n in ('ardurover','arducopter','arduplane')):parser.error('project-owned three-vehicle SITL binaries required')
    root=a.run_dir.resolve();root.mkdir(parents=True,exist_ok=False)
    runner=StageRunner(root,total_timeout=21600,env=dict(os.environ,VAF_SIMULATION_SITL_BIN_DIR=str(binary)))
    report=dict(passed=False,status='FAIL',started_at=stamp(),framework_sha=output(['git','rev-parse','HEAD']),source_sha256=source_hash(),rounds=[],stages={})
    inputs=tracked_inputs()
    (root/'frozen-inputs.json').write_text(json.dumps(dict(tracked=inputs,sitl_binaries={
        n:hashlib.sha256((binary/n).read_bytes()).hexdigest() for n in ('ardurover','arducopter','arduplane')}),indent=2)+'\n')
    def save():(root/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    def interrupted(*args):raise InterruptedError('Phase 4 formal acceptance interrupted')
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    def stage(name,module,path,extra=(),timeout=900):
        print(name+' starting',flush=True)
        try:
            status=runner.run_stage(name,[sys.executable,'-m',module,*extra,'--run-dir',str(path)],timeout=timeout,stage_dir=path)
        finally:
            # Nested scenarios own separate manifests. A killed parent must not
            # strand their explicitly registered credentials or process groups.
            for manifest in path.rglob('manifest.json'):
                if not cleaned(manifest.parent):runner.cleanup_manifest(manifest.parent)
        summary=json.loads((path/'summary.json').read_text()) if (path/'summary.json').is_file() else {}
        manifests=list(path.rglob('manifest.json'))
        valid=all(cleaned(p.parent) for p in manifests)
        entry=dict(passed=bool(status['passed'] and summary.get('passed') is True and valid),summary=str(path/'summary.json'),owned_fixture_count=len(manifests),cleanup=valid)
        report['stages'][name]=entry;save();print(name+(' PASS' if entry['passed'] else ' FAIL'),flush=True)
        if not entry['passed']:raise RuntimeError(name+' failed; evidence retained, no later stage substituted')
        return summary
    try:
        unit=runner.run_stage('unit',[sys.executable,'-m','tests.simulation.harness','--unit-report',str(root/'unit.json')],timeout=180)
        report['unit']=json.loads((root/'unit.json').read_text())
        if not unit['passed'] or not report['unit']['passed'] or report['unit']['skipped']:raise RuntimeError('full unit regression failed/skipped')
        for number in (1,2):
            folder=root/f'round-{number}-{uuid4().hex[:8]}';folder.mkdir()
            record=dict(number=number,passed=False,groups={});report['rounds'].append(record)
            vehicles={}
            for kind in ('rover','copter','plane'):
                vehicles[kind]=stage(f'{number}_{kind}_web_mission_manual','tests.simulation.mission_web_scenario',folder/(kind+'-web'),['--kind',kind],timeout=1500 if kind=='plane' else 600)
            rover=stage(f'{number}_rover_ownership_faults','tests.simulation.phase4_faults',folder/'rover-faults',['--kind','rover'],timeout=360)
            copter=stage(f'{number}_copter_ownership_faults','tests.simulation.phase4_faults',folder/'copter-faults',['--kind','copter'],timeout=420)
            plane=stage(f'{number}_plane_continuation_unknown','tests.simulation.phase4_plane',folder/'plane-boundaries',timeout=900)
            mixed=stage(f'{number}_mixed_external','tests.simulation.mission_external_boundary',folder/'mixed-external',timeout=240)
            record['groups']=dict(A=True,B=rover['logic']['passed'] and copter['logic']['passed'],
                C=vehicles['rover']['passed'],D=vehicles['copter']['passed'],E=vehicles['plane']['passed'],
                F=all(v['passed'] for v in vehicles.values()),G=all(v['mission']['state']=='SUCCEEDED' for v in vehicles.values()),
                H=rover['passed'] and copter['passed'] and plane['passed'] and mixed['passed'],
                I=rover['logic']['expired_and_duplicate_events_rejected'] and copter['logic']['expired_and_duplicate_events_rejected'])
            save()
        # Original entry itself runs two three-vehicle Action/Chrome/API/ROS
        # rounds and two entire Phase 1/2 physical/safety regressions.
        prior=stage('phase1_phase2_phase3_complete','tests.simulation.phase3_harness',root/'prior-regression',
            ['--allow-send','--sitl-bin-dir',str(binary)],timeout=10800)
        for record in report['rounds']:
            record['groups']['J']=prior['passed'];record['passed']=all(record['groups'].get(g) is True for g in 'ABCDEFGHIJ')
        wheel=stage('wheel_independent_install','tests.simulation.mission_wheel',root/'wheel',timeout=180)
        audit=stage('history_credentials_cleanup','tests.simulation.mission_audit',root/'audit',timeout=180)
        report['final_source_sha256']=source_hash()
        report['tracked_inputs_unchanged']=inputs==tracked_inputs()
        report['passed']=all(r['passed'] for r in report['rounds']) and wheel['passed'] and audit['passed'] and report['tracked_inputs_unchanged'] and report['source_sha256']==report['final_source_sha256']
    except BaseException as exc:report['error']=type(exc).__name__+': '+str(exc)
    finally:
        if runner.current is not None:runner.stop(runner.current)
        report.update(ended_at=stamp(),status='READY FOR RE-AUDIT' if report['passed'] else 'FAIL');save();print(report['status'],flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
