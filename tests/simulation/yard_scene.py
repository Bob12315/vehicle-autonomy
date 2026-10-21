"""Build visible/collidable known-yard fixtures from the exact admitted scene file."""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from application.scenario_planning import StaticScene
from environments.resources import Environment
from tests.simulation.launch import ROOT


def add_yard(owned):
    scene=StaticScene(ROOT/'simulation/scenes/yard.json',Environment.load(ROOT/'simulation/environments/yard.toml'))
    tree=ET.parse(owned.world_path);world=tree.find('world')
    for b in scene.obstacles:
        model=ET.SubElement(world,'model',name=b['name']);ET.SubElement(model,'static').text='true'
        ET.SubElement(model,'pose').text=f"{b['x']} {b['y']} {b['height']/2} 0 0 0"
        link=ET.SubElement(model,'link',name='box')
        for kind in ('collision','visual'):
            item=ET.SubElement(link,kind,name=kind);size=ET.SubElement(ET.SubElement(ET.SubElement(item,'geometry'),'box'),'size')
            size.text=f"{b['width']} {b['depth']} {b['height']}"
            if kind=='visual':ET.SubElement(ET.SubElement(item,'material'),'diffuse').text='0.8 0.45 0.16 1'
    environment=Environment.load(ROOT/'simulation/environments/yard.toml')
    for point in environment.points:
        model=ET.SubElement(world,'model',name='station_'+point.name);ET.SubElement(model,'static').text='true'
        ET.SubElement(model,'pose').text=f'{point.position.x} {point.position.y} 0.015 0 0 0'
        visual=ET.SubElement(ET.SubElement(model,'link',name='marker'),'visual',name='marker')
        cylinder=ET.SubElement(ET.SubElement(visual,'geometry'),'cylinder')
        ET.SubElement(cylinder,'radius').text='.35';ET.SubElement(cylinder,'length').text='.02'
        ET.SubElement(ET.SubElement(visual,'material'),'diffuse').text='0.15 0.7 0.5 1'
    # Visible boundary is separate from the strict software footprint/geofence gate.
    for x,y,w,d in [(0,-15,30,.1),(0,15,30,.1),(-15,0,.1,30),(15,0,.1,30)]:
        model=ET.SubElement(world,'model',name=f'fence_{x}_{y}');ET.SubElement(model,'static').text='true'
        ET.SubElement(model,'pose').text=f'{x} {y} .2 0 0 0';link=ET.SubElement(model,'link',name='fence')
        for k in ('visual','collision'):ET.SubElement(ET.SubElement(ET.SubElement(ET.SubElement(link,k,name=k),'geometry'),'box'),'size').text=f'{w} {d} .4'
    tree.write(owned.world_path)
    owned.params.append(ROOT/'simulation/params/rover_navigation.parm')
    owned.manifest['parameters']=[str(p) for p in owned.params]
    owned.manifest['parameter_files_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in owned.params}
    owned.manifest['scenario']={'source':str(scene.path),'sha256':scene.sha256,'description':'known static yard; no live obstacle avoidance'}
    owned._save()
