"""Repeatable world smoke tests; level promotion requires actual evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from .catalog import SceneRegistry
from .manager import SimulationManager, TERMINAL
from .results import compare_reports


def smoke(manager, identifier, *, seconds, timeout, vehicle='none', seed=0):
    record=manager.create(dict(scene_id=identifier,vehicle=vehicle,seed=seed))
    key=record['id']
    manager.start(key)
    deadline=time.monotonic()+timeout
    try:
        while time.monotonic()<deadline:
            record=manager.sample(key)
            if record['state'] in TERMINAL:
                break
            if (record['metrics'].get('sim_seconds') or 0)>=seconds and record['levels']['L2']=='PASS':
                break
            time.sleep(.1)
    finally:
        manager.stop(key)
        thread=manager.threads.get(key)
        if thread:thread.join(manager.startup_timeout+40)
    record=manager.sample(key)
    complete=(record['state']=='FINISHED' and not record.get('error') and
              record['levels']['L1']=='PASS' and record['levels']['L2']=='PASS' and record['cleanup']=='COMPLETE')
    if not complete and not record.get('error'):
        record['error']='requested simulated duration/readiness was not reached before timeout'
    record['smoke_status']='PASS' if complete and (record['metrics'].get('sim_seconds') or 0)>=seconds else 'BLOCKED' if 'BLOCKED:' in (record.get('error') or '') else 'FAIL'
    # This is a smoke-test result in addition to the durable session report.
    (manager.directory/key/'smoke-result.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
    return record


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='operation',required=True)
    sub.add_parser('list')
    check=sub.add_parser('check');check.add_argument('scene_id')
    for name in ('smoke','batch'):
        p=sub.add_parser(name)
        p.add_argument('--data-dir',type=Path,required=True)
        p.add_argument('--seconds',type=float,default=5)
        p.add_argument('--timeout',type=float,default=90)
        p.add_argument('--seed',type=int,default=0)
        p.add_argument('--vehicle',choices=('none','rover','copter','plane'),default='none')
        if name=='smoke':p.add_argument('--scene',required=True)
        else:p.add_argument('--scene',action='append',default=[])
    comparison=sub.add_parser('compare')
    comparison.add_argument('baseline',type=Path);comparison.add_argument('candidate',type=Path)
    args=parser.parse_args(argv)
    if args.operation=='compare':
        print(json.dumps(compare_reports(json.loads(args.baseline.read_text()),json.loads(args.candidate.read_text())),ensure_ascii=False,indent=2))
        return 0
    registry=SceneRegistry()
    if args.operation=='list':
        print(json.dumps(registry.list_scenes(),ensure_ascii=False,indent=2))
        return 0
    if args.operation=='check':
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            world=registry.generate(args.scene_id,Path(temp)/'world.sdf')
            result=subprocess.run([registry.host.executable('gazebo') or 'gz','sdf','-k',str(world)],timeout=30,capture_output=True,text=True)
            print(result.stdout+result.stderr)
            return result.returncode
    if not 0<args.seconds<=3600 or not 1<=args.timeout<=3600:
        parser.error('seconds and timeout must be finite positive values within 3600 seconds')
    manager=SimulationManager(args.data_dir,registry)
    try:
        identifiers=([args.scene] if args.operation=='smoke' else args.scene or
                     [entry['id'] for entry in registry.list_scenes() if entry['id'][:1] in 'RCF'])
        results=[]
        for identifier in identifiers:
            try:
                record=smoke(manager,identifier,seconds=args.seconds,timeout=args.timeout,
                             vehicle=args.vehicle,seed=args.seed)
            except Exception as exc:
                record=dict(scene_id=identifier,smoke_status='BLOCKED' if 'BLOCKED:' in str(exc) else 'FAIL',error=str(exc))
            results.append(record)
            print(json.dumps(dict(scene_id=identifier,id=record.get('id'),status=record['smoke_status'],
                levels=record.get('levels'),metrics=record.get('metrics'),error=record.get('error')),ensure_ascii=False),flush=True)
        summary=dict(results=results,passed=all(r['smoke_status']=='PASS' for r in results))
        (manager.directory/'batch-results.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
        return 0 if summary['passed'] else 1
    finally:
        manager.close()


if __name__=='__main__':
    raise SystemExit(main())
