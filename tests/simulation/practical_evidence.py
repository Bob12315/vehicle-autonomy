"""Independent artifact-only truth checks; never imports the runtime controller."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

PATHS={
 'calibration':[((.25,0),(1.25,0)),((1.25,0),(1.25,0)),((1.25,0),(1.25,0)),((1.25,0),(.25,0))],
 'courier':[((.25,0),(10.25,0)),((10.25,0),(10.25,0)),((10.25,0),(.25,0))],
 'patrol':[((.25,0),(3,0)),((3,0),(2,1.5)),((2,1.5),(2,1.5)),((2,1.5),(.25,3)),((.25,3),(.25,0))],
 'rotation':[((.25,0),(.25,0))],
 'cancel':[((.25,0),(4.25,0)),((4.25,0),(4.25,0)),((4.25,0),(.25,0))]}


def distance(p,a,b):
 dx,dy=b[0]-a[0],b[1]-a[1]
 f=max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(1e-12,dx*dx+dy*dy)))
 return math.hypot(p[0]-a[0]-f*dx,p[1]-a[1]-f*dy)


def audit(directory):
 summary=json.loads((directory/'summary.json').read_text())
 result={'passed':False,'scope':'independent Gazebo artifact audit; known static yard only',
         'runtime_commit':summary['source_commit'],'cases':[],
         'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
 for index,entry in enumerate(summary['cases']):
  p=directory/f'{index:02d}';out={'name':entry['name'],'passed':False}
  try:
   case=json.loads((p/'summary.json').read_text());manifest=json.loads((p/'manifest.json').read_text())
   assert case['passed'] and entry['status']=='PASS','scenario execution failed'
   assert manifest['framework_sha']==summary['source_commit'] and not manifest['working_tree_dirty'],'runtime version was not frozen clean'
   assert manifest['ports_released'] and manifest['remaining_process_groups']==[] and all(x.get('stopped') for x in manifest['processes']),'owned resource release failed'
   rows=[json.loads(line) for line in (p/'status.jsonl').read_text().splitlines() if line.strip()]
   rows=[r for r in rows if r.get('truth') is not None]
   assert rows,'no independent truth samples'
   if entry['name'] in ('admission','restart'):
    origin=rows[0]['truth'];moving=max(math.hypot(r['truth'][0]-origin[0],r['truth'][1]-origin[1]) for r in rows)
    assert moving<.02,moving
    out['max_body_displacement_m']=moving
   else:
    scene=ET.parse(p/'world.sdf').find('world');boxes=[]
    for name in ('parked_van','storage_rack','restricted_loading_zone'):
     model=scene.find(f"model[@name='{name}']");assert model is not None,name
     pose=[float(x) for x in model.find('pose').text.split()]
     size=[float(x) for x in model.find('link/collision/geometry/box/size').text.split()]
     assert pose[3:]==[0,0,0] and model.find('static').text=='true'
     boxes.append((pose[0],pose[1],size[0],size[1]))
    max_cross=0.;min_clear=float('inf');samples=0;wait_speeds=[]
    for row in rows:
     t=row['truth'];point=(t[0]+.25*math.cos(t[2]),t[1]+.25*math.sin(t[2]))
     assert max(abs(point[0]),abs(point[1]))+.72<=14.95,'footprint crosses actual yard boundary'
     for x,y,w,d in boxes:
      clear=math.hypot(max(abs(point[0]-x)-w/2,0),max(abs(point[1]-y)-d/2,0))
      min_clear=min(min_clear,clear)
      assert clear>.72,'independent truth footprint intersects static collision box'
     task=row.get('task');i=None if task is None else task.get('step_index')
     if i is None:continue
     if entry['name']=='circle':
      error=abs(math.hypot(point[0]-.25,point[1]-1.5)-1.5)
     elif i<len(PATHS[entry['name']]):
      a,b=PATHS[entry['name']][i];error=distance(point,a,b)
      if a==b and entry['name'] in ('courier','patrol') and row['speed_mps'] is not None:wait_speeds.append(row['speed_mps'])
     else:continue
     max_cross=max(max_cross,error);samples+=1
    assert samples>20,'insufficient physical trajectory observations'
    assert max_cross<=.15,('truth path deviation',max_cross)
    if wait_speeds:assert max(wait_speeds)<.05,('station dwell moved',max(wait_speeds))
    out.update(max_truth_path_error_m=max_cross,min_static_clearance_m=min_clear,trajectory_samples=samples,
               max_dwell_speed_mps=max(wait_speeds) if wait_speeds else None)
   out['passed']=True
  except (AssertionError,KeyError,ValueError,OSError) as exc:out['error']=str(exc)
  result['cases'].append(out)
 expected=['admission','calibration','courier','patrol','circle','rotation','cancel','restart']
 result['passed']=summary['passed'] and summary['expected_cases']==len(expected) and [c['name'] for c in result['cases']]==expected and all(c['passed'] for c in result['cases'])
 result['summary_sha256']=hashlib.sha256((directory/'summary.json').read_bytes()).hexdigest()
 return result


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',type=Path,required=True)
 args=parser.parse_args();r=audit(args.run_dir.resolve())
 (args.run_dir/'independent-truth-audit.json').write_text(json.dumps(r,indent=2)+'\n')
 print(json.dumps(r));return 0 if r['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
