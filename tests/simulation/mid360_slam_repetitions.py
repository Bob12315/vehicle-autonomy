"""Three fresh original-chain runs per vehicle, preserving every outcome."""
import argparse,hashlib,json,subprocess,sys,time
from pathlib import Path


def run(directory,gui=False,kind=None):
    directory=directory.resolve();directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[2]
    thresholds=root/'configs/mid360-slam-acceptance.json';original=thresholds.read_bytes()
    manifest=dict(status='RUNNING',thresholds=json.loads(original),
        thresholds_sha256=hashlib.sha256(original).hexdigest(),runs=[])
    output=directory/'repetitions.json'
    def save():output.write_text(json.dumps(manifest,indent=2)+'\n')
    save()
    kinds=(kind,) if kind else ('rover','copter');manifest['vehicle_scope']=kinds;save()
    for kind in kinds:
        for repetition in range(1,4):
            if thresholds.read_bytes()!=original:raise RuntimeError('acceptance thresholds changed during repeats')
            path=directory/(kind+'-'+str(repetition));command=[sys.executable,'-m','tests.simulation.mid360_slam_native',
                '--run-dir',str(path),'--kind',kind]
            if gui and repetition==1:command.append('--gui')
            began=time.monotonic()
            with path.with_suffix('.log').open('w') as log:
                completed=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT)
            result_path=path/'slam-result.json'
            result=json.loads(result_path.read_text()) if result_path.exists() else dict(status='FAIL',error='missing actual result')
            manifest['runs'].append(dict(kind=kind,repetition=repetition,command=command,
                returncode=completed.returncode,status=result['status'],result=str(result_path),
                host_seconds=time.monotonic()-began,metrics=result.get('metrics'),runtime=result.get('runtime')))
            save();print(kind,repetition,result['status'],flush=True)
    manifest['status']='PASS' if len(manifest['runs'])==3*len(kinds) and all(r['status']=='PASS' and r['returncode']==0 for r in manifest['runs']) else 'FAIL'
    save();return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--gui',action='store_true')
    p.add_argument('--kind',choices=['rover','copter']);a=p.parse_args()
    raise SystemExit(0 if run(a.run_dir,a.gui,a.kind)['status']=='PASS' else 1)
