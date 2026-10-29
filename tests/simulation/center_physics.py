"""Native gravity/contact and dynamic-target checks for generated worlds.

This bounded subset does not certify vehicle traversal or sensor perception.
It runs one unique partition and only stops the process group it creates.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

from vehicle_autonomy.app.simulation.catalog import SceneRegistry
from vehicle_autonomy.app.simulation.scenarios import box


def run(directory, scene_id, *, seconds=8):
    directory=directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    path=SceneRegistry().generate(scene_id,directory/'world.sdf',seed=42)
    tree=ET.parse(path);world=tree.getroot().find('world')
    name='physics_'+uuid4().hex[:12];world.set('name',name)
    box(world,'drop_probe',(0,0,3,0,0,0),(1,1,1),static=False)
    tree.write(path,encoding='utf-8',xml_declaration=True)
    env=dict(os.environ,GZ_IP='127.0.0.1',GZ_PARTITION=name)
    os.environ.update(GZ_IP='127.0.0.1',GZ_PARTITION=name)
    # Optional native bindings are confined to the explicitly launched worker.
    from tests.simulation.oracle import GazeboTruthOracle
    probe=GazeboTruthOracle(name,'drop_probe')
    moving=GazeboTruthOracle(name,'moving_target_0') if scene_id in ('R05','C06') else None
    report=dict(scene_id=scene_id,status='FAIL',scope='gravity/ground contact and registered dynamic target only',samples=[])
    process=None
    try:
        with (directory/'gazebo.log').open('w') as log:
            process=subprocess.Popen(['gz','sim','-s','-r','-v3',str(path)],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            deadline=time.monotonic()+seconds+30;first_motion=None;last_motion=None
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Gazebo exited')
                sample=probe.latest()
                if sample:
                    item=dict(probe=asdict(sample))
                    if moving:
                        target=moving.latest()
                        if target:
                            assert abs(target.x_m)<55 and abs(target.y_m)<55 and .4<target.z_m<.65,('target escaped physical test region',target)
                            first_motion=first_motion or target;last_motion=target
                            item['dynamic_target']=asdict(target)
                    report['samples'].append(item)
                    if sample.simulation_ns>=seconds*1e9:break
                time.sleep(.1)
            else:raise TimeoutError('native physics truth unavailable')
            final=probe.latest()
            assert final and abs(final.z_m-.5)<.06,('gravity/contact failed',final)
            recent=[item['probe']['z_m'] for item in report['samples'][-10:]]
            assert len(recent)>=5 and max(recent)-min(recent)<.02,'probe did not settle'
            report['ground_contact_height_m']=final.z_m
            if moving:
                assert first_motion and last_motion,'dynamic model truth absent'
                distance=math.hypot(last_motion.x_m-first_motion.x_m,last_motion.y_m-first_motion.y_m)
                excursion=max(math.hypot(item['dynamic_target']['x_m']-first_motion.x_m,item['dynamic_target']['y_m']-first_motion.y_m) for item in report['samples'] if 'dynamic_target' in item)
                assert excursion>1.,('dynamic target did not move',excursion)
                report['dynamic_displacement_m']=distance
                report['dynamic_max_excursion_m']=excursion
            report['status']='PASS'
    except Exception as exc:report['error']=type(exc).__name__+': '+str(exc)
    finally:
        if process:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
            try:os.killpg(process.pid,0);os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            report['exit_code']=process.returncode
        (directory/'result.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    from tests.simulation.launch import install_signal_cleanup
    install_signal_cleanup()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene',required=True);parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=8)
    args=parser.parse_args()
    if not 1<=args.seconds<=120:parser.error('seconds must be in [1,120]')
    report=run(args.run_dir,args.scene,seconds=args.seconds)
    print(json.dumps({k:v for k,v in report.items() if k!='samples'}))
    return int(report['status']!='PASS')


if __name__=='__main__':raise SystemExit(main())
