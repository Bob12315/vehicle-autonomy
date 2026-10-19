"""P23 actual native boundary overlay and independent stationary map/pose checks."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from uuid import uuid4
from tests.simulation.launch import ROOT,install_signal_cleanup
from tests.simulation import ros2_mapping


def run(directory,yaw,library):
    old=os.environ.get('VAF_SLAM_BOUNDARY_LIBRARY')
    os.environ['VAF_SLAM_BOUNDARY_LIBRARY']=str(library)
    ros2_mapping.ROOM_YAW=yaw
    try:
        report=ros2_mapping.run(directory,smoke=True)
        if not report['passed']:return report
        manifest=json.loads(library.with_name('manifest.json').read_text())
        if 'VAF_BOUNDARY_OVERLAY_ACTIVE' not in (directory/'slam.log').read_text():
            raise AssertionError('patched native occupancy method was not invoked')
        if manifest['native_probes']['upstream']['dropped_endpoints']!=2 or manifest['native_probes']['fixed']['dropped_endpoints']!=0:
            raise AssertionError('native boundary counterexample/fix regression missing')
        cuts=[json.loads(l) for l in (directory/'application-status.jsonl').read_text().splitlines()]
        cuts=[c for c in cuts if c['truth'] is not None and c['status'].get('slam_localization_candidate',{}).get('candidate')]
        if not cuts:raise AssertionError('no actual SLAM pose candidate')
        errors=[]
        for cut in cuts:
            audit=cut['status']['slam_localization_candidate'];pose=audit['candidate']['position']
            if audit['control_eligible'] or audit['active_source']!='vehicle_reported_odom':raise AssertionError('unapproved source switch')
            errors.append(math.hypot(pose[0]-cut['truth'][0],pose[1]-cut['truth'][1]))
        if max(errors)>.15:raise AssertionError('stationary SLAM pose differs from independent truth')
        report.update(boundary_overlay={'method_invoked':True,'manifest_sha256':hashlib.sha256(library.with_name('manifest.json').read_bytes()).hexdigest(),
            'library_sha256':manifest['library_sha256'],'native_probes':manifest['native_probes']},
            slam_candidate_truth_max_error_m=max(errors),active_localization='vehicle_reported_odom')
    except Exception as exc:report={**locals().get('report',{}),'passed':False,'error':f'{type(exc).__name__}: {exc}'}
    finally:
        if old is None:os.environ.pop('VAF_SLAM_BOUNDARY_LIBRARY',None)
        else:os.environ['VAF_SLAM_BOUNDARY_LIBRARY']=old
    (directory/'summary.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--yaw',type=float,choices=(0.,.15),required=True)
    p.add_argument('--boundary-library',type=Path,required=True)
    p.add_argument('--run-dir',type=Path)
    a=p.parse_args();install_signal_cleanup()
    directory=(a.run_dir or ROOT/'artifacts/simulation'/f'map-reliability-{a.yaw}-{uuid4().hex[:8]}').resolve()
    report=run(directory,a.yaw,a.boundary_library.resolve())
    print(json.dumps({'directory':str(directory),**report}));return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
