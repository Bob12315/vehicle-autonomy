"""Independent collision/axle measurements from the SDF used by Gazebo.

Never imported by production guidance. Covers the two explicitly audited wheel
and free-swiveling-caster SDF layouts, with conservative full-yaw bounds.
"""
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class RoverGeometry:
    axle_x: float
    track_m: float
    radius_from_axle_m: float
    body_size: tuple[float,...]
    body_mass_kg: float
    source_sha256: str


def measure(path):
    path=Path(path);tree=ET.parse(path);model=tree.find('model')
    def pose(node):return tuple(map(float,node.findtext('pose','0 0 0 0 0 0').split()))
    body=model.find("link[@name='base_link']");base=pose(body)
    if any(abs(v)>1e-8 for v in (*base[:2],*base[3:])):raise ValueError('geometry audit requires planar zero-XY base frame')
    plugin=model.find("plugin[@name='ArduPilotPlugin']")
    wheels=[]
    for control in plugin.findall('control'):
        joint=model.find(f"joint[@name='{control.findtext('jointName')}']")
        wheels.append(model.find(f"link[@name='{joint.findtext('child')}']"))
    if len(wheels)!=2:raise ValueError('two independently driven wheels required')
    positions=[pose(w) for w in wheels]
    if abs(positions[0][0]-positions[1][0])>1e-8:raise ValueError('common drive axle required')
    axle=sum(p[0] for p in positions)/2
    size=tuple(map(float,body.findtext('collision/geometry/box/size').split()))
    bound=math.hypot(size[0]/2+abs(axle),size[1]/2)
    for wheel in wheels:
        p=pose(wheel);shape=wheel.find('collision/geometry/cylinder')
        r=float(shape.findtext('radius'));half=float(shape.findtext('length'))/2
        bound=max(bound,math.hypot(abs(p[0]-axle)+r,abs(p[1])+half))
    for swivel in model.findall('joint'):
        if swivel.findtext('axis/xyz')!='0 0 1':continue
        pivot=model.find(f"link[@name='{swivel.findtext('child')}']");pp=pose(pivot)
        roll=next(j for j in model.findall('joint') if j.findtext('parent')==pivot.attrib['name'])
        caster=model.find(f"link[@name='{roll.findtext('child')}']");cp=pose(caster)
        cylinder=caster.find('collision/geometry/cylinder')
        wheel_bound=math.hypot(float(cylinder.findtext('radius')),float(cylinder.findtext('length'))/2)
        bound=max(bound,math.hypot(pp[0]-axle,pp[1])+math.hypot(cp[0]-pp[0],cp[1]-pp[1])+wheel_bound)
    return RoverGeometry(axle,abs(positions[0][1]-positions[1][1]),bound,size,
        float(body.findtext('inertial/mass')),hashlib.sha256(path.read_bytes()).hexdigest())
