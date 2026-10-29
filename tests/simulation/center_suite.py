"""Bounded scene regressions; native failures are retained and do not stop peers."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

from tests.simulation.harness import StageRunner
from tests.simulation.launch import ROOT,install_signal_cleanup
from vehicle_autonomy.app.simulation.catalog import SceneRegistry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--scene',action='append',default=[])
    parser.add_argument('--kind',choices=('rover','copter','plane'),action='append',default=[])
    parser.add_argument('--allow-send',action='store_true')
    parser.add_argument('--seconds',type=float,default=8)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--physics',action='store_true')
    parser.add_argument('--faults',action='store_true',help='run actual disarmed SEND-off receive fault isolation')
    args=parser.parse_args()
    if args.kind and not args.allow_send:parser.error('--kind motion acceptance requires explicit --allow-send')
    if not 1<=args.seconds<=3600:parser.error('seconds must be in [1,3600]')
    root=args.run_dir.resolve();root.mkdir(parents=True,exist_ok=False)
    install_signal_cleanup()
    runner=StageRunner(root,total_timeout=7200,env=os.environ)
    summary=dict(started_at=datetime.now(timezone.utc).isoformat(),seed=args.seed,cases=[])
    scenes=args.scene or [s['id'] for s in SceneRegistry().list_scenes() if s.get('layout')]
    def stage(name,module,arguments,timeout):
        path=root/name
        record=runner.run_stage(name,[sys.executable,'-m',module,*arguments,'--run-dir',str(path)],timeout=timeout,stage_dir=None)
        status='PASS' if record['passed'] else 'FAIL'
        if not record['passed'] and path.exists():
            for manifest in path.rglob('manifest.json'):
                runner.cleanup_manifest(manifest.parent)
        result_path=path/'result.json'
        if result_path.exists():
            value=json.loads(result_path.read_text())
            if 'BLOCKED:' in value.get('error',''):status='BLOCKED'
        summary['cases'].append(dict(name=name,status=status,log=record['log'],result=str(result_path)))
        (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    # CLI manager already records per-scene PASS/FAIL/BLOCKED with process cleanup.
    command=[sys.executable,'-m','vehicle_autonomy.app.simulation.cli','batch',
        '--data-dir',str(root/'worlds'),'--seconds',str(args.seconds),'--seed',str(args.seed)]
    for scene in scenes:command+=['--scene',scene]
    native=runner.run_stage('worlds',command,timeout=max(120,len(scenes)*70))
    if (root/'worlds/batch-results.json').exists():
        world_report=json.loads((root/'worlds/batch-results.json').read_text())
        summary['cases'].extend(dict(name='world-'+r['scene_id'],status=r['smoke_status'],result=str(root/'worlds'/r.get('id','')/'smoke-result.json')) for r in world_report['results'])
    else:summary['cases'].append(dict(name='worlds',status='FAIL',log=native['log']))
    if args.physics:
        for scene in ('R01','R05','C06'):
            stage('physics-'+scene,'tests.simulation.center_physics',['--scene',scene],70)
    if args.faults:
        stage('mission-lifecycle','tests.simulation.center_missions',[],180)
        stage('software-faults','tests.simulation.center_faults',[],240)
    for kind in args.kind:
        stage('vehicle-'+kind,'tests.simulation.center_vehicle',['--kind',kind,'--allow-send'],1000 if kind=='plane' else 420)
    summary.update(ended_at=datetime.now(timezone.utc).isoformat(),passed=all(r['status']=='PASS' for r in summary['cases']))
    (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return int(not summary['passed'])


if __name__=='__main__':raise SystemExit(main())
