"""Phase-one only: two independent real Rover/Copter A-F acceptance runs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
from uuid import uuid4

from tests.simulation.harness import StageRunner, stamp, unit_suite
from tests.simulation.launch import ROOT, output


def source_hash():
    digest=hashlib.sha256()
    for directory in ('src','tests','scripts','configs','simulation'):
        for path in sorted((ROOT/directory).rglob('*')):
            if path.is_file() and path.suffix in ('.py','.sh','.json','.toml','.parm','.sdf','.cpp','.h'):
                digest.update(str(path.relative_to(ROOT)).encode()+b'\0'+path.read_bytes()+b'\0')
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--allow-send',action='store_true')
    parser.add_argument('--unit-report',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.unit_report:
        return unit_suite(args.unit_report)
    if not args.allow_send:
        parser.error('--allow-send required; targets are exclusively newly owned loopback SITL fixtures')
    path=(args.run_dir or ROOT/'artifacts/phase1-control'/('suite-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])).resolve()
    path.mkdir(parents=True,exist_ok=False)
    runner=StageRunner(path,total_timeout=5400)
    summary=dict(passed=False,run_id=path.name,started_at=stamp(),run_dir=str(path),
        framework_sha=output(['git','rev-parse','HEAD']),working_tree_dirty=bool(output(['git','status','--porcelain'])),
        source_sha256=source_hash(),python=sys.version,rounds=[],scope='phase1; owned loopback SITL/Gazebo only')
    def interrupted(signum,frame):
        raise InterruptedError(f'phase1 signal {signum}')
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    try:
        for name,command,timeout in (
            ('preflight',[sys.executable,str(ROOT/'scripts/preflight_simulation.py'),'--isolated'],30),
            ('unit',[sys.executable,'-m','tests.simulation.phase1_harness','--unit-report',str(path/'unit.json')],90),
        ):
            print(f'[{name}] starting',flush=True)
            result=runner.run_stage(name,command,timeout=timeout)
            if not result['passed']:
                raise RuntimeError(f'{name} failed')
            print(f'[{name}] PASS',flush=True)
        for index in (1,2):
            round_dir=path/f'run-{index}-{uuid4().hex[:8]}'
            round_dir.mkdir()
            record=dict(run_id=round_dir.name,started_at=stamp(),vehicles={},passed=False)
            summary['rounds'].append(record)
            for kind in ('rover','copter'):
                vehicle=dict(passed=False,stages={},groups={})
                record['vehicles'][kind]=vehicle
                specifications=(
                    ('probe','tests.simulation.phase1_probe',['--kind',kind]),
                    ('physical','tests.simulation.rover_protocol' if kind=='rover' else 'tests.simulation.copter_scenario',['--full']),
                    ('faults','tests.simulation.fault_scenario',['--kind',kind]),
                )
                for case,module,extra in specifications:
                    name=f'{index}_{kind}_{case}'
                    stage_dir=round_dir/f'{kind}-{case}'
                    print(f'[{name}] starting',flush=True)
                    status=runner.run_stage(name,[sys.executable,'-m',module,'--allow-send',*extra,'--run-dir',str(stage_dir)],
                                            timeout=420,stage_dir=stage_dir)
                    result=json.loads((stage_dir/'summary.json').read_text()) if (stage_dir/'summary.json').exists() else {}
                    manifest=json.loads((stage_dir/'manifest.json').read_text()) if (stage_dir/'manifest.json').exists() else {}
                    cleanup=(manifest.get('ports_released') is True and manifest.get('remaining_process_groups')==[]
                             and bool(manifest.get('ended_at')) and bool(manifest.get('processes'))
                             and all(p.get('stopped') and p.get('exit_code') is not None for p in manifest['processes']))
                    passed=(status['passed'] and result.get('passed') is True and cleanup
                            and not any(key.endswith('_error') for key in result))
                    vehicle['stages'][case]=dict(passed=passed,summary=str(stage_dir/'summary.json'),
                        manifest=str(stage_dir/'manifest.json'),log=status['log'],cleanup=cleanup)
                    print(f'[{name}] {"PASS" if passed else "FAIL"}',flush=True)
                probe=json.loads(Path(vehicle['stages']['probe']['summary']).read_text()) if Path(vehicle['stages']['probe']['summary']).exists() else {}
                faults=json.loads(Path(vehicle['stages']['faults']['summary']).read_text()) if Path(vehicle['stages']['faults']['summary']).exists() else {}
                required_faults={'unauthorized','duplicate','deadman','cancel','shutdown_during_motion','signal_shutdown',
                                 'runtime_process_restart','runtime_restart','state_timeout','temporary_disconnect',
                                 'long_disconnect','delayed_telemetry','old_replay','ack_timeout','sitl_restart'}
                for group in 'ABDEF':
                    passed=(vehicle['stages']['probe']['passed'] and probe.get('groups',{}).get(group,{}).get('passed') is True)
                    if group=='E':
                        passed=passed and vehicle['stages']['faults']['passed'] and all(faults.get('faults',{}).get(f,{}).get('passed') is True for f in required_faults)
                    if group=='F':
                        passed=passed and all(s['cleanup'] for s in vehicle['stages'].values())
                    vehicle['groups'][group]='PASS' if passed else 'FAIL'
                vehicle['groups']['C']='PASS' if vehicle['stages']['physical']['passed'] else 'FAIL'
                vehicle['passed']=all(value=='PASS' for value in vehicle['groups'].values())
            record['passed']=all(v['passed'] for v in record['vehicles'].values())
            record['ended_at']=stamp()
            (round_dir/'summary.json').write_text(json.dumps(record,indent=2))
            (path/'summary.json').write_text(json.dumps(summary,indent=2))
        summary['final_source_sha256']=source_hash()
        summary['passed']=all(r['passed'] for r in summary['rounds']) and summary['source_sha256']==summary['final_source_sha256']
    except BaseException as exc:
        summary['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if runner.current is not None:
            runner.stop(runner.current)
        summary['ended_at']=stamp()
        (path/'summary.json').write_text(json.dumps(summary,indent=2))
        print(json.dumps(summary,indent=2),flush=True)
    return 0 if summary['passed'] else 1

if __name__=='__main__':
    raise SystemExit(main())
