#!/usr/bin/env python3
"""Create a URI-only local adaptation using individually pinned Fuel models."""
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree as ET
import shutil
R=Path(__file__).resolve().parent; A=R/'assets'; root=A/'fuel/fuel.gazebosim.org'; dest=A/'adapter_models'; dest.mkdir(parents=True,exist_ok=True)
versions={('movai','shelf'):'1',('movai','shelf_big'):'2',('openrobotics','chair'):'3',('openrobotics','jersey%20barrier'):'6',('openrobotics','malevisitoronphone'):'2',('openrobotics','table'):'4',('openrobotics','warehouse'):'5',('openrobotics','foldable_chair'):'3',('plateau','casual%20female'):'1'}
tree=ET.parse(A/'warehouse.sdf')
for uri in tree.findall('.//include/uri'):
    url=(uri.text or '').strip(); parts=urlsplit(url).path.strip('/').split('/')
    if len(parts)!=4 or parts[2]!='models': raise SystemExit('Unexpected Fuel URI: '+url)
    owner=parts[1].lower(); name=quote(parts[3].lower(),safe=''); version=versions.get((owner,name))
    if version is None: raise SystemExit('Unpinned Fuel resource: '+url)
    src=root/owner/'models'/name/version
    if not (src/'model.sdf').is_file(): raise SystemExit('Missing: '+str(src))
    local='vaf_'+owner+'_'+name.replace('%20','_'); shutil.copytree(src,dest/local,dirs_exist_ok=True);uri.text='model://'+local
# Fuel table v4 duplicates visual/collision names under a link; Harmonic rejects it.
table=dest/'vaf_openrobotics_table/model.sdf'; model=ET.parse(table)
for link in model.findall('.//link'):
    collisions={x.get('name') for x in link.findall('collision')}
    for visual in link.findall('visual'):
        if visual.get('name') in collisions: visual.set('name','visual_'+visual.get('name'))
for node in model.findall('.//albedo_map'):
    if (node.text or '').endswith('/Table_Diffuse.jpg'): node.text='model://vaf_openrobotics_table/Table_Diffuse.jpg'
model.write(table,encoding='unicode',xml_declaration=True)
world=tree.find('world'); physics=world.find('physics'); gravity=physics.find('gravity')
if gravity is not None: physics.remove(gravity); world.append(gravity)
tree.write(A/'warehouse_adapted.sdf',encoding='unicode',xml_declaration=True)
print(A/'warehouse_adapted.sdf')
