"""Explicit external World utility; no software is fetched at import or startup."""
from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from vehicle_autonomy.app.bootstrap.paths import RuntimePaths

def main():
    """Fetch pinned source entry files. Existing files are never overwritten."""
    from pathlib import Path
    import urllib.request
    ROOT=HostEnvironment().path('legacy_assets')
    SOURCES=[
     ('ArduPilot/ardupilot_gazebo','3ec51428fd43deb7b71137192ba16394b450d78e','worlds/iris_runway.sdf','iris_runway.sdf'),
     ('ArduPilot/ardupilot_gazebo','3ec51428fd43deb7b71137192ba16394b450d78e','worlds/zephyr_runway.sdf','zephyr_runway.sdf'),
     ('ArduPilot/ardupilot_gazebo','3ec51428fd43deb7b71137192ba16394b450d78e','LICENSE.md','ardupilot_gazebo_LICENSE.md'),
     ('ArduPilot/ardupilot_gz','8df4dc1726e37504e6fc8b952d02e554cfa3176f','ardupilot_gz_gazebo/worlds/playpen.sdf','playpen.sdf'),
     ('ArduPilot/ardupilot_gz','8df4dc1726e37504e6fc8b952d02e554cfa3176f','ardupilot_gz_bringup/launch/multiagent.launch.py','multiagent.launch.py'),
     ('ArduPilot/ardupilot_gz','8df4dc1726e37504e6fc8b952d02e554cfa3176f','LICENSE','ardupilot_gz_LICENSE'),
     ('clearpathrobotics/clearpath_simulator','a7c5cf377027cbbb6cb64e4eae9c786750b5b276','clearpath_gz/worlds/warehouse.sdf','warehouse.sdf'),
     ('clearpathrobotics/clearpath_simulator','a7c5cf377027cbbb6cb64e4eae9c786750b5b276','clearpath_gz/worlds/orchard.sdf','orchard.sdf'),
     ('clearpathrobotics/clearpath_simulator','a7c5cf377027cbbb6cb64e4eae9c786750b5b276','LICENSE','clearpath_LICENSE'),
     ('PX4/PX4-gazebo-models','e5997f455e33ec071c7c677fc59a65781de496a4','worlds/windy.sdf','windy.sdf'),
     ('PX4/PX4-gazebo-models','e5997f455e33ec071c7c677fc59a65781de496a4','LICENSE','px4_LICENSE'),
     ('mertgulerx/world-collection','a0c262a497da1b0b9fd9970add6ff346e09afaeb','worlds/F5_urban_w06_b15/F5_urban_w06_b15.sdf','urban.sdf'),
     ('mertgulerx/world-collection','a0c262a497da1b0b9fd9970add6ff346e09afaeb','worlds/F5_urban_w06_b15/LICENSE','urban_LICENSE'),
    ]
    for filename in ('orchard_world.dae','orchard_trunks.dae','orchard_leaves.dae','Ground.png','GroundForest003_COL_VAR1_3K.jpg.001.jpg','GroundMoss001_COL_1K.jpg.001.jpg','GroundTireTracks001_COL_3K.jpg.001.jpg','RustPlain007_COL_VAR1_3K.jpg.001.jpg'):
        SOURCES.append(('clearpathrobotics/clearpath_simulator','a7c5cf377027cbbb6cb64e4eae9c786750b5b276','clearpath_gz/meshes/orchard/'+filename,'orchard/'+filename))
    for filename in ('base_station_with_tripod.dae','base_station_with_tripod.stl'):
        SOURCES.append(('clearpathrobotics/clearpath_simulator','a7c5cf377027cbbb6cb64e4eae9c786750b5b276','clearpath_gz/meshes/accessories/'+filename,'accessories/'+filename))
    for filename in ('model.config','model.sdf'):
        SOURCES.append(('ArduPilot/SITL_Models','25bc38ed8c6c0345840159a8cbc0b02781d52f3c','Gazebo/models/rover_playpen/'+filename,'rover_playpen/'+filename))
    for path in (resource_root()/'simulation/world_registry/sitl_models_files.txt').read_text().splitlines():
        SOURCES.append(('ArduPilot/SITL_Models','25bc38ed8c6c0345840159a8cbc0b02781d52f3c',path,path.removeprefix('Gazebo/models/')))
    ROOT.mkdir(parents=True,exist_ok=True)
    failed=[]
    for repo,commit,path,name in SOURCES:
        dst=ROOT/name
        if dst.exists(): print('exists',dst); continue
        dst.parent.mkdir(parents=True,exist_ok=True)
        url=f'https://raw.githubusercontent.com/{repo}/{commit}/{path}'
        try:
            with urllib.request.urlopen(url, timeout=40) as response: data=response.read()
            with dst.open('xb') as f: f.write(data)
            print('downloaded',dst,len(data))
        except Exception as exc: failed.append(name); print('FAILED',name,exc)
    if failed: raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
