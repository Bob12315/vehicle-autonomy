"""Actual Nav2 read-only acceptance: detour, no path, unknown, rotation and P18 map."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from application.planning import ReadOnlyPlanningService
from contracts.core.geometry import Pose3,Quaternion,Vector3
from contracts.core.primitives import ResourceVersion
from contracts.core.time import TimePoint
from contracts.world.models import ResourceReference
from integrations.ros2.nav2_planner import Nav2Planner
from mapping.grid import MapStore,OccupancyGrid,atomic_json
from planning.models import MapContext,Pose2D,PlanningError

ROOT = Path(__file__).resolve().parents[2]
IDENTITY = Pose3(Vector3(0,0,0),Quaternion(0,0,0,1))


def oracle(grid, points, radius):
    """Independent dense sampling + circle/AABB distance over ORIGINAL cells.

    Does not call the production validator or inspect its inflated grid.
    Sampling at <= resolution/5 complements the exact unit segment tests.
    """
    q=grid.origin.orientation;angle=2*math.atan2(q.z,q.w)
    samples=0
    for a,b in zip(points,points[1:] or points):
        distance=math.hypot(b[0]-a[0],b[1]-a[1]);count=max(1,math.ceil(distance/(grid.resolution_m/5)))
        for i in range(count+1):
            t=i/count
            x=a[0]+(b[0]-a[0])*t-grid.origin.position.x
            y=a[1]+(b[1]-a[1])*t-grid.origin.position.y
            x,y=math.cos(angle)*x+math.sin(angle)*y,-math.sin(angle)*x+math.cos(angle)*y
            edge=min(x,y,grid.width*grid.resolution_m-x,grid.height*grid.resolution_m-y)
            if edge <= radius:raise AssertionError('independent oracle: map-edge footprint collision')
            for row in range(max(0,math.floor((y-radius)/grid.resolution_m)-1),min(grid.height,math.floor((y+radius)/grid.resolution_m)+2)):
                for col in range(max(0,math.floor((x-radius)/grid.resolution_m)-1),min(grid.width,math.floor((x+radius)/grid.resolution_m)+2)):
                    if 0<=grid.cells[row*grid.width+col]<=19:continue
                    dx=max(col*grid.resolution_m-x,0,x-(col+1)*grid.resolution_m)
                    dy=max(row*grid.resolution_m-y,0,y-(row+1)*grid.resolution_m)
                    clearance=math.hypot(dx,dy)
                    if clearance <= radius:raise AssertionError('independent oracle: obstacle/unknown footprint collision')
            samples+=1
    return {'samples':samples,'verified_clearance_m':radius}


def clock():return TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),'host-monotonic-planning')


def run(directory):
    directory.mkdir(parents=True,exist_ok=False)
    report={'passed':False,'cases':{}}
    try:
        cells=[0]*6400
        for y in range(12,65):cells[y*80+40]=100
        detour=OccupancyGrid('map',.1,80,80,IDENTITY,tuple(cells))
        sealed=list(cells)
        for y in range(80):sealed[y*80+40]=100
        unknown=list(sealed)
        for y in range(80):unknown[y*80+40]=-1
        narrow=list(sealed)
        for y in range(36,44):narrow[y*80+40]=0
        rotated=OccupancyGrid('map',.1,80,80,Pose3(Vector3(-3,2,0),Quaternion(0,0,math.sin(.3),math.cos(.3))),tuple(cells))
        fixture=json.loads((ROOT/'simulation/planning/recorded_map.json').read_text())
        actual=MapStore(ROOT/'simulation/planning/maps').load(fixture['sha256'])
        cases=[('wall_detour',detour,Pose2D(2,4),Pose2D(6,4),None),
               ('sealed_wall',OccupancyGrid('map',.1,80,80,IDENTITY,tuple(sealed)),Pose2D(2,4),Pose2D(6,4),'NO_PATH'),
               ('unknown_barrier',OccupancyGrid('map',.1,80,80,IDENTITY,tuple(unknown)),Pose2D(2,4),Pose2D(6,4),'NO_PATH'),
               ('narrow_gate',OccupancyGrid('map',.1,80,80,IDENTITY,tuple(narrow)),Pose2D(2,4),Pose2D(6,4),'NO_PATH'),
               ('rotated_origin',rotated,Pose2D(2,4),Pose2D(6,4),None),
               ('recorded_p18',actual,Pose2D(*fixture['start']),Pose2D(*fixture['goal']),None),
               ('recorded_invalid_goal',actual,Pose2D(0,0),Pose2D(2.3,3.3),'INVALID_GOAL'),
               ('recorded_conservative_goal',actual,Pose2D(0,0),Pose2D(2,3.5),'NO_PATH')]
        for name,grid,start,goal,expected in cases:
            case=directory/name;case.mkdir()
            digest=MapStore(case/'maps').save(grid)
            context=MapContext(ResourceReference('recorded.map',ResourceVersion('recording:'+digest,0)),digest,'recording:'+digest,grid,'recorded_map')
            if name=='rotated_origin':start,goal=context.to_world(start),context.to_world(goal)
            backend=Nav2Planner(case/'backend')
            try:
                path=ReadOnlyPlanningService(lambda:context,backend,clock).plan(start,goal)
                if expected:raise AssertionError(f'{name} unexpectedly returned a path')
                document=path.document();assert not document['executable']
                independent=oracle(grid,document['poses'],.55)
                if name=='wall_detour' and path.length_m<=5:raise AssertionError('wall detour was not represented')
                atomic_json(case/'path.json',document)
                report['cases'][name]={'passed':True,'length_m':path.length_m,'points':len(path.candidate.poses),**independent}
            except PlanningError as exc:
                if exc.code!=expected:raise
                report['cases'][name]={'passed':True,'expected_rejection':exc.code,'message':str(exc)}
            if expected=='INVALID_GOAL':
                if backend.last_directory is not None:raise AssertionError('invalid goal reached Nav2')
                continue
            if backend.last_directory is None:raise AssertionError('actual Nav2 was not called')
            manifest=json.loads((backend.last_directory/'manifest.json').read_text())
            response=json.loads((backend.last_directory/'response.json').read_text())
            if not manifest['process_group_released'] or not response.get('costmap_verified'):
                raise AssertionError('missing native costmap/cleanup evidence')
            report['cases'][name]['backend_directory']=str(backend.last_directory)
            report['cases'][name]['nav2_version']=response['nav2_version']

        # Test the public CLI independently of the Python application use case.
        command=[sys.executable,'-m','app.plan','--map-store',str(ROOT/'simulation/planning/maps'),
            '--map-sha256',fixture['sha256'],'--start','0','0','--goal','1.9','3.5',
            '--evidence-directory',str(directory/'cli-backend'),'--output',str(directory/'cli.json')]
        cli=subprocess.run(command,capture_output=True,text=True,timeout=22)
        (directory/'cli.log').write_text(cli.stdout+cli.stderr)
        if cli.returncode:raise AssertionError('public CLI failed')
        value=json.loads(cli.stdout)
        if not value['ok'] or value['result']['map']['source_kind']!='recorded_map':raise AssertionError('CLI provenance missing')
        report['public_cli']=True
        report['cases']['public_cli_oracle']=oracle(actual,value['result']['poses'],.55)

        context=MapContext(ResourceReference('recorded.map',ResourceVersion('timeout',0)),hashlib.sha256(detour.encoded()).hexdigest(),'timeout',detour,'recorded_map')
        backend=Nav2Planner(directory/'timeout-backend')
        try:ReadOnlyPlanningService(lambda:context,backend,clock).plan(Pose2D(2,4),Pose2D(6,4),timeout_s=.7)
        except PlanningError as exc:
            if exc.code!='TIMEOUT':raise
            report['deadline_rejection']=exc.code
        else:raise AssertionError('late planner unexpectedly accepted')
        if not json.loads((backend.last_directory/'manifest.json').read_text())['process_group_released']:
            raise AssertionError('timeout left an owned process group')
        if not (backend.last_directory/'native-process.json').is_file():
            raise AssertionError('timeout did not exercise an actual native planner process')
        report['passed']=True
    except Exception as exc:
        report['error']=f'{type(exc).__name__}: {exc}'
    atomic_json(directory/'summary.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',type=Path)
    args=parser.parse_args();directory=(args.run_dir or ROOT/'artifacts/simulation'/('nav2-readonly-'+uuid4().hex[:8])).resolve()
    report=run(directory);print(json.dumps({'directory':str(directory),**report}));return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
