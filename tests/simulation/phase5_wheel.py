"""Independent Phase 4 wheel smoke plus installed Phase 5 native resources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile
from tests.simulation.mission_wheel import run as mission_wheel


def run(root):
    root=root.resolve();base=mission_wheel(root);result={'passed':False,'phase4_wheel':base}
    try:
        assert base['passed'],'existing installed-wheel regression failed'
        checkout=Path(__file__).resolve().parents[2];wheel,=(root/'dist').glob('*.whl');verified=[]
        with ZipFile(wheel) as archive:
            for relative in ('world/navigation/native/source_receiver.cpp','world/navigation/native/CMakeLists.txt'):
                name='vehicle_autonomy/'+relative;source=checkout/'src'/name
                assert archive.read(name)==source.read_bytes(),'installed native source mismatch'
                verified.append(dict(path=name,sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        env=dict(os.environ);env.pop('PYTHONPATH',None);env.pop('VAF_RESOURCE_ROOT',None)
        python=root/'venv/bin/python'
        code="""import json,sys
from pathlib import Path
import vehicle_autonomy
from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.actions.navigation.native_rover import NativeRoverNavigationFactory
from vehicle_autonomy.app.bootstrap.native_navigation_processes import NativeNavigationProcesses
from vehicle_autonomy.world.navigation.source_ipc import NativeSourceSocket
assert Path(vehicle_autonomy.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert 'rclpy' not in sys.modules and 'gz.transport13' not in sys.modules
r=resource_root()
for p in ('simulation/phase5/nav2_rover.yaml','simulation/phase5/navigate_rover.xml','simulation/phase5/slam_mapping.yaml'):
 assert (r/p).is_file()
print(json.dumps(dict(resource_root=str(r),optional_ros_imported=False)))
"""
        probe=subprocess.run([str(python),'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=20)
        (root/'phase5-import.log').write_text(probe.stdout+probe.stderr)
        assert probe.returncode==0,'independent Phase 5 imports failed'
        result['installed']=json.loads(probe.stdout)
        wrapper=Path(result['installed']['resource_root'])/'scripts/with_ros2.sh'
        with (root/'phase5-native-build.log').open('x') as log:
            built=subprocess.run([str(wrapper),str(python),'-m','vehicle_autonomy.world.navigation.build_source_receiver','--directory',str(root/'native-build')],cwd=root,env=env,stdout=log,stderr=log,timeout=180)
        assert built.returncode==0,'building installed native source failed'
        manifest=json.loads((root/'native-build/manifest.json').read_text())
        assert manifest['sources']['source_receiver.cpp']==verified[0]['sha256']
        result.update(passed=True,verified_native_sources=verified,native_build=manifest,vehicle_connections=0)
    except BaseException as exc:result.update(passed=False,error=type(exc).__name__+': '+str(exc))
    finally:(root/'phase5-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();r=run(a.run_dir);print(json.dumps(dict(passed=r['passed'],error=r.get('error'))));raise SystemExit(0 if r['passed'] else 1)
