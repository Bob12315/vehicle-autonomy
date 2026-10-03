"""Owned object fixtures and services; these are test stimuli, never Mission APIs."""
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

def add_objects(owned):
    tree=ET.parse(owned.world_path);world=tree.find('world')
    if not any(p.attrib.get('name')=='gz::sim::systems::UserCommands' for p in world.findall('plugin')):
        ET.SubElement(world,'plugin',filename='gz-sim-user-commands-system',name='gz::sim::systems::UserCommands')
    for index,(x,y) in enumerate(((2,1),(1,1.7),(2.6,.5)),1):
        model=ET.SubElement(world,'model',name=f'target_{index}');ET.SubElement(model,'static').text='true';ET.SubElement(model,'pose').text=f'{x} {y} 0.05 0 0 0'
        link=ET.SubElement(model,'link',name='marker');visual=ET.SubElement(link,'visual',name='visual');geometry=ET.SubElement(visual,'geometry');cylinder=ET.SubElement(geometry,'cylinder');ET.SubElement(cylinder,'radius').text='.15';ET.SubElement(cylinder,'length').text='.1'
    tree.write(owned.world_path)
    calibration=owned.run_dir/'sensor.toml'
    calibration.write_text(f'''schema = 1
world = "{owned.world}"
frame = "odom"
translation = [0.0, 0.0, 0.0]
rotation = [0.0, 0.0, 0.0, 1.0]
source = "owned runway fixture ENU axes; SITL configured origin and spawn XY zero; object plane 0.05 m; not an inferred transform"
models = ["target_1", "target_2", "target_3"]
''')
    return calibration

def service(owned,name,request_type,body):
    command=['gz','service','-s',f'/world/{owned.world}/{name}','--reqtype',request_type,'--reptype','gz.msgs.Boolean','--timeout','2000','--req',body]
    result=subprocess.run(command,capture_output=True,text=True,timeout=5)
    if result.returncode or 'true' not in result.stdout:raise RuntimeError(f'fixture service {name} failed: {result.stdout} {result.stderr}')
    with (owned.run_dir/'fixture-services.log').open('a') as stream:stream.write(str(command)+'\n'+result.stdout+'\n')
