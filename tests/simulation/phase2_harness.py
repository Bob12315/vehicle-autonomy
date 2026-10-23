"""Two independent three-vehicle SITL/Gazebo control regression runs."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
from uuid import uuid4
from tests.simulation.harness import StageRunner, stamp
from tests.simulation.launch import ROOT, output
from tests.simulation.phase1_harness import source_hash


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-send',action='store_true');p.add_argument('--run-dir',type=Path)
    p.add_argument('--sitl-bin-dir',type=Path,required=True)
    args=p.parse_args()
    if not args.allow_send:p.error('--allow-send required; exclusively newly owned loopback simulations')
    binary=args.sitl_bin_dir.resolve()
    if not all((binary/name).is_file() for name in ('ardurover','arducopter','arduplane')):
        p.error('all three SITL binaries must exist in the explicit isolated directory')
    root=(args.run_dir or ROOT/'artifacts/phase2-control'/('acceptance-'+uuid4().hex[:8])).resolve()
    root.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,VAF_SIMULATION_SITL_BIN_DIR=str(binary))
    runner=StageRunner(root,total_timeout=7200,env=env)
    result=dict(passed=False,status='FAIL',started_at=stamp(),framework_sha=output(['git','rev-parse','HEAD']),
        source_sha256=source_hash(),binary_sha256={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in binary.iterdir() if f.is_file()},rounds=[])
    def interrupted(signum,frame):raise InterruptedError(f'phase2 signal {signum}')
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    try:
        stage=runner.run_stage('unit',[sys.executable,'-m','tests.simulation.harness','--unit-report',str(root/'unit.json')],timeout=100)
        if not stage['passed']:raise RuntimeError('unit suite failed')
        for index in (1,2):
            run=root/f'run-{index}-{uuid4().hex[:8]}';run.mkdir()
            record=dict(passed=False,run_id=run.name,vehicles={});result['rounds'].append(record)
            for kind in ('rover','copter','plane'):
                vehicle=dict(passed=False,stages={});record['vehicles'][kind]=vehicle
                cases=([('control','tests.simulation.plane_scenario',[])] if kind=='plane' else [
                    ('probe','tests.simulation.phase1_probe',['--kind',kind,'--review-remediation']),
                    ('physical','tests.simulation.rover_protocol' if kind=='rover' else 'tests.simulation.copter_scenario',['--full',*(['--native-rtl'] if kind=='rover' else [])]),
                    ('faults','tests.simulation.fault_scenario',['--kind',kind])])
                if kind=='rover':cases.insert(1,('legacy_physical','tests.simulation.rover_protocol',['--full']))
                for case,module,extra in cases:
                    name=f'{index}_{kind}_{case}';path=run/f'{kind}-{case}'
                    print(name+' starting',flush=True)
                    status=runner.run_stage(name,[sys.executable,'-m',module,'--allow-send',*extra,'--run-dir',str(path)],timeout=780 if kind=='plane' else 420,stage_dir=path)
                    summary=json.loads((path/'summary.json').read_text()) if (path/'summary.json').exists() else {}
                    manifest=json.loads((path/'manifest.json').read_text()) if (path/'manifest.json').exists() else {}
                    cleanup=bool(manifest.get('credentials_removed') and manifest.get('ports_released')
                        and manifest.get('remaining_process_groups')==[] and not list(path.glob('sitl_state*'))
                        and not list(path.glob('*.private')))
                    passed=bool(status['passed'] and summary.get('passed') is True and cleanup and not any(k.endswith('_error') for k in summary))
                    if kind=='plane':
                        passed=passed and all(summary.get(key,{}).get('passed') for key in ('takeoff','native_target','landing','cancel','link_loss'))
                        passed=passed and all(summary.get('regressions',{}).get(key,{}).get('passed') for key in ('lock_expiry','guard_expiry','lease_expiry','valid_after_rejections','wrap_replay','normal_arm_disarm'))
                    vehicle['stages'][case]=dict(passed=passed,summary=str(path/'summary.json'),manifest=str(path/'manifest.json'),cleanup=cleanup)
                    print(name+(' PASS' if passed else ' FAIL'),flush=True)
                    (root/'summary.json').write_text(json.dumps(result,indent=2))
                if kind != 'plane':
                    probe=json.loads(Path(vehicle['stages']['probe']['summary']).read_text())
                    faults=json.loads(Path(vehicle['stages']['faults']['summary']).read_text())
                    required_faults={'unauthorized','duplicate','deadman','cancel','shutdown_during_motion','signal_shutdown',
                        'runtime_process_restart','runtime_restart','state_timeout','temporary_disconnect','long_disconnect',
                        'delayed_telemetry','old_replay','ack_timeout','sitl_restart'}
                    required_review={'old_ack_heartbeat_replay','normal_continuous_arm_disarm','lock_expiry','guard_expiry',
                        'valid_after_rejections','wire_order','wraparound_replay'}
                    vehicle['groups']={group: bool(vehicle['stages']['probe']['passed'] and
                        probe.get('groups',{}).get(group,{}).get('passed')) for group in 'ABDEF'}
                    vehicle['groups']['C']=vehicle['stages']['physical']['passed']
                    if kind=='rover':
                        physical=json.loads(Path(vehicle['stages']['physical']['summary']).read_text())
                        vehicle['groups']['C'] &= physical.get('native_rtl',{}).get('passed') is True and vehicle['stages']['legacy_physical']['passed']
                        physical_manifest=json.loads(Path(vehicle['stages']['physical']['manifest']).read_text())
                        vehicle['groups']['C'] &= len(physical_manifest.get('rover_parameter_readback',{}))==5
                    vehicle['groups']['D'] &= all(probe.get('remediation',{}).get(k,{}).get('passed') for k in required_review)
                    vehicle['groups']['E'] &= vehicle['stages']['faults']['passed'] and all(faults.get('faults',{}).get(k,{}).get('passed') for k in required_faults)
                    if kind=='rover':vehicle['groups']['E'] &= physical.get('native_rtl_cancel',{}).get('passed') is True
                    vehicle['groups']['F'] &= all(stage['cleanup'] for stage in vehicle['stages'].values())
                else:
                    control=json.loads(Path(vehicle['stages']['control']['summary']).read_text())
                    m=json.loads(Path(vehicle['stages']['control']['manifest']).read_text())
                    vehicle['groups']=dict(A=bool(len(m.get('plane_parameter_readback',{}))==12 and m.get('signing_epochs')),
                        B=bool(control.get('native_target',{}).get('passed')),
                        C=bool(control.get('takeoff',{}).get('passed') and control.get('landing',{}).get('passed')),
                        D=all(control.get('regressions',{}).get(k,{}).get('passed') for k in ('lock_expiry','guard_expiry','lease_expiry','valid_after_rejections')),
                        E=bool(control.get('cancel',{}).get('passed') and control.get('link_loss',{}).get('passed')
                            and control.get('regressions',{}).get('wrap_replay',{}).get('passed')),
                        F=vehicle['stages']['control']['cleanup'])
                vehicle['passed']=all(s['passed'] for s in vehicle['stages'].values()) and all(vehicle['groups'].values())
            record['passed']=all(v['passed'] for v in record['vehicles'].values())
        result['final_source_sha256']=source_hash()
        result['passed']=all(r['passed'] for r in result['rounds']) and result['final_source_sha256']==result['source_sha256']
    except BaseException as exc:result['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if runner.current is not None:runner.stop(runner.current)
        result['status']='READY FOR INDEPENDENT REVIEW' if result['passed'] else 'FAIL'
        result['ended_at']=stamp();(root/'summary.json').write_text(json.dumps(result,indent=2))
        print(result['status'],flush=True)
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
