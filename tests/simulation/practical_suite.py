"""Failure-preserving serial regression of all practical yard scenarios."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

from tests.simulation.harness import StageRunner
from tests.simulation.launch import ROOT,output
from tests.simulation.practical_evidence import audit

CASES=('admission','calibration','courier','patrol','circle','rotation','cancel','restart')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-send',action='store_true');parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--llm-config',type=Path,required=True)
    args=parser.parse_args()
    if not args.allow_send:parser.error('explicit owned localhost simulation SEND required')
    directory=args.run_dir.resolve();directory.mkdir(parents=True,exist_ok=False)
    if len(str(directory/'06/app.sock').encode())>=108:parser.error('shorter evidence path required')
    runner=StageRunner(directory,total_timeout=5400)
    report={'passed':False,'started_at':datetime.now(timezone.utc).isoformat(),
        'source_commit':output(['git','rev-parse','HEAD']),
        'source_dirty':bool(output(['git','status','--porcelain'])),
        'expected_cases':len(CASES),'core_skipped':0,'cases':[],
        'scope':'known static yard; parameterized LLM missions; not P26 or hardware acceptance'}
    def save():(directory/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    unit=runner.run_stage('unit',[sys.executable,'-m','tests.simulation.harness','--unit-report',str(directory/'unit.json')],timeout=120)
    report['unit']=json.loads((directory/'unit.json').read_text()) if (directory/'unit.json').exists() else {'passed':False}
    save()
    for index,case in enumerate(CASES):
        print('['+case+'] starting',flush=True)
        if not unit['passed']:
            report['cases'].append({'name':case,'status':'BLOCKED','reason':'unit failed'});save();continue
        path=directory/f'{index:02d}'
        stage=runner.run_stage(case,[sys.executable,'-m','tests.simulation.practical_scenarios','--allow-send',
            '--llm-config',str(args.llm_config.resolve()),'--case',case,'--run-dir',str(path)],timeout=760,stage_dir=path)
        result=json.loads((path/'summary.json').read_text()) if (path/'summary.json').exists() else {'passed':False,'error':'missing scenario result'}
        report['cases'].append({'name':case,'status':'PASS' if stage['passed'] and result['passed'] else 'FAIL',
            'evidence':str(path),'error':result.get('error'),'duration_s':result.get('duration_s')})
        save()
    report['passed']=report['unit']['passed'] and all(c['status']=='PASS' for c in report['cases']) and len(report['cases'])==len(CASES)
    report['finished_at']=datetime.now(timezone.utc).isoformat();save()
    independent=audit(directory)
    report['independent_truth_passed']=independent['passed']
    report['passed']=report['passed'] and independent['passed'];save()
    independent['summary_sha256']=hashlib.sha256((directory/'summary.json').read_bytes()).hexdigest()
    (directory/'independent-truth-audit.json').write_text(json.dumps(independent,indent=2)+'\n')
    print(json.dumps(report));return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
