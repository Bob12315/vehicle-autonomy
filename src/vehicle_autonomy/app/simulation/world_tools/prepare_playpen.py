"""Explicit external World utility; no software is fetched at import or startup."""
from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from vehicle_autonomy.app.bootstrap.paths import RuntimePaths

def main():
    """Build local URI adaptations; never modify downloaded upstream files."""
    from pathlib import Path
    import shutil
    R=resource_root()/'simulation/world_registry'
    A=HostEnvironment().path('legacy_assets'); dest=A/'adapter_models'; dest.mkdir(parents=True,exist_ok=True)
    for name,source in [('vaf_ground_plane', A/'fuel/fuel.gazebosim.org/openrobotics/models/ground%20plane/5'),('vaf_jersey_barrier',A/'fuel/fuel.gazebosim.org/openrobotics/models/jersey%20barrier/6')]:
        if not source.is_dir(): raise SystemExit(f'Missing pinned Fuel resource: {source}')
        shutil.copytree(source,dest/name,dirs_exist_ok=True)
    source=(A/'rover_playpen/model.sdf').read_text()
    source=source.replace('https://fuel.gazebosim.org/1.0/OpenRobotics/models/ground plane','model://vaf_ground_plane').replace('https://fuel.gazebosim.org/1.0/OpenRobotics/models/jersey barrier','model://vaf_jersey_barrier')
    model=dest/'vaf_rover_playpen';model.mkdir(exist_ok=True); (model/'model.sdf').write_text(source);shutil.copy2(A/'rover_playpen/model.config',model/'model.config')
    world=(A/'playpen.sdf').read_text().replace('model://rover_playpen','model://vaf_rover_playpen')
    (A/'playpen_adapted.sdf').write_text(world)
    print(A/'playpen_adapted.sdf')


if __name__ == "__main__":
    raise SystemExit(main())
