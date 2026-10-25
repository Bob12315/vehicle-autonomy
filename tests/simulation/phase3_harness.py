"""Two frozen-code A--G rounds, genuine Action HTTP/Chrome and AP/Gazebo."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
from uuid import uuid4

from tests.simulation.harness import StageRunner,stamp
from tests.simulation.launch import ROOT,output


def source_hash():
    digest=hashlib.sha256()
    for name in ('src','tests','scripts','simulation','configs'):
        for path in sorted((ROOT/name).rglob('*')):
            if path.is_file() and path.suffix in ('.py','.sh','.toml','.json','.parm','.sdf','.cpp','.h','.js','.html','.css','.yaml'):
                digest.update(str(path.relative_to(ROOT)).encode()+b'\0'+path.read_bytes()+b'\0')
    digest.update((ROOT/'pyproject.toml').read_bytes())
    return digest.hexdigest()


def cleaned(path):
    m=json.loads((path/'manifest.json').read_text())
    return bool(m.get('credentials_removed') and m.get('ports_released') and m.get('remaining_process_groups')==[]
        and not list(path.glob('sitl_state*')) and not list(path.glob('*.private')))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--allow-send',action='store_true')
    parser.add_argument('--sitl-bin-dir',type=Path,required=True);parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args()
    if not args.allow_send:parser.error('--allow-send only authorizes newly created own simulations')
    if output(['git','status','--porcelain']):parser.error('freeze and commit code before formal acceptance')
    binary=args.sitl_bin_dir.resolve()
    if not all((binary/name).is_file() for name in ('ardurover','arducopter','arduplane')):parser.error('explicit isolated three-vehicle binaries required')
    root=args.run_dir.resolve();root.mkdir(parents=True,exist_ok=False)
    runner=StageRunner(root,total_timeout=10800,env=dict(os.environ,VAF_SIMULATION_SITL_BIN_DIR=str(binary)))
    report={'passed':False,'status':'FAIL','started_at':stamp(),'framework_sha':output(['git','rev-parse','HEAD']),
        'source_sha256':source_hash(),'rounds':[],'stages':{}}
    def save():
        (root/'summary.json').write_text(json.dumps(report,indent=2))
    def interrupted(*_):raise InterruptedError('Phase 3 interrupted')
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    def stage(name,module,path,extra=(),timeout=720):
        print(name+' starting',flush=True)
        status=runner.run_stage(name,[sys.executable,'-m',module,*extra,'--run-dir',str(path)],timeout=timeout,stage_dir=path)
        result=json.loads((path/'summary.json').read_text()) if (path/'summary.json').exists() else {}
        entry={'passed':bool(status['passed'] and result.get('passed') is True),'summary':str(path/'summary.json')}
        if (path/'manifest.json').exists():entry['cleanup']=cleaned(path);entry['passed']&=entry['cleanup']
        report['stages'][name]=entry;save();print(name+(' PASS' if entry['passed'] else ' FAIL'),flush=True)
        if not entry['passed']:raise RuntimeError(name+' failed; original evidence retained')
        return result
    try:
        unit=runner.run_stage('unit',[sys.executable,'-m','tests.simulation.harness','--unit-report',str(root/'unit.json')],timeout=180)
        if not unit['passed']:raise RuntimeError('full unit regression failed')
        stage('independent_remediation_boundaries','tests.simulation.remediation_external',
            root/'independent-remediation-boundaries',timeout=120)
        for number in (1,2):
            run=root/f'round-{number}-{uuid4().hex[:8]}';run.mkdir()
            record={'number':number,'passed':False,'vehicles':{},'groups':{}};report['rounds'].append(record)
            for kind in ('rover','copter','plane'):
                normal=stage(f'{number}_{kind}_actions','tests.simulation.action_scenario',run/(kind+'-actions'),
                    ['--allow-send','--kind',kind,'--return-action','ReturnHome' if number==1 else 'RTL',*(['--browser'] if kind=='rover' else [])])
                faults=stage(f'{number}_{kind}_faults','tests.simulation.action_scenario',run/(kind+'-faults'),
                    ['--allow-send','--kind',kind,'--faults'],timeout=180)
                record['vehicles'][kind]={'normal':normal['passed'],'faults':faults['passed'],
                    'actions':[{'name':a['name'],'state':a.get('final',{}).get('state')} for a in normal['actions']]}
                if kind=='rover':record['groups']['F']=normal.get('web_browser',{}).get('passed') is True
            external=stage(f'{number}_external','tests.simulation.external_actions',run/'external',timeout=100)
            record['groups'].update(A=True,B=True,C=True,D=True,E=external['passed'])
            save()
        # The unchanged Phase 2 harness itself runs two complete three-vehicle
        # A--F suites, including every Phase 1 safety and writer regression.
        regression=stage('phase1_phase2_regression','tests.simulation.phase2_harness',root/'phase2-regression',
            ['--allow-send','--sitl-bin-dir',str(binary)],timeout=7200)
        for record,old in zip(report['rounds'],regression['rounds'],strict=True):
            record['groups']['G']=old['passed'];record['regression_round']=old['run_id']
            record['passed']=all(record['groups'].get(letter) is True for letter in 'ABCDEFG')
        report['final_source_sha256']=source_hash()
        report['passed']=all(r['passed'] for r in report['rounds']) and report['source_sha256']==report['final_source_sha256']
    except BaseException as exc:report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if runner.current is not None:runner.stop(runner.current)
        report['ended_at']=stamp();report['status']='READY FOR RE-AUDIT' if report['passed'] else 'FAIL';save()
        print(report['status'],flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
