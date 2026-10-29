"""Deterministic, vehicle-independent Harmonic world construction.

Geometry and physical disturbances are real SDF. This module makes no control,
perception, GPS-denial or fixed-wing capability claims.
"""
from __future__ import annotations

import math
import random
from pathlib import Path
import xml.etree.ElementTree as ET


def child(parent, tag, text=None, **attributes):
    element = ET.SubElement(parent, tag, attributes)
    if text is not None:
        element.text = str(text)
    return element


def geometry(parent, size, shape='box'):
    geo = child(parent, 'geometry')
    item = child(geo, shape)
    if shape == 'box':
        child(item, 'size', ' '.join(map(str, size)))
    elif shape == 'cylinder':
        child(item, 'radius', size[0]); child(item, 'length', size[1])
    else:
        child(item, 'radius', size[0])


def box(world, name, pose, size, *, static=True, color='.55 .6 .65 1', shape='box', friction=1):
    model = child(world, 'model', name=name)
    child(model, 'static', str(static).lower())
    child(model, 'pose', ' '.join(map(str, pose)))
    link = child(model, 'link', name='body')
    if not static:
        inertia = child(link, 'inertial'); child(inertia, 'mass', 1)
        matrix = child(inertia, 'inertia')
        for axis in ('ixx', 'iyy', 'izz'): child(matrix, axis, .166667)
    collision = child(link, 'collision', name='collision'); geometry(collision, size, shape)
    ode = child(child(child(collision, 'surface'), 'friction'), 'ode')
    child(ode, 'mu', friction); child(ode, 'mu2', friction)
    visual = child(link, 'visual', name='visual'); geometry(visual, size, shape)
    material = child(visual, 'material')
    child(material, 'ambient', color); child(material, 'diffuse', color)
    return model


def moving_target(world, name, x, y):
    model = box(world, name, (x,y,.55,0,0,0), (1,1,1), static=False, color='.9 .15 .05 1', friction=.02)
    plugin = child(model, 'plugin', filename='gz-sim-trajectory-follower-system', name='gz::sim::systems::TrajectoryFollower')
    child(plugin, 'link_name', 'body'); child(plugin, 'loop', 'true')
    child(plugin, 'force', 4); child(plugin, 'torque', 4)
    points = child(plugin, 'waypoints')
    child(points, 'waypoint', f'{x} {y}'); child(points, 'waypoint', f'{x+8} {y}')


def validate_parameters(scene, parameters):
    if parameters is None: parameters = {}
    if not isinstance(parameters, dict): raise ValueError('parameters must be an object')
    schema = scene['parameter_schema']
    if parameters.keys() - schema.keys(): raise ValueError('unsupported environment parameters: '+', '.join(sorted(parameters.keys()-schema.keys())))
    result = {}
    for key, spec in schema.items():
        value = parameters.get(key, spec['default'])
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(key+' requires a finite number')
        if spec['type']=='integer' and not isinstance(value,int): raise ValueError(key+' requires an integer')
        if not spec['minimum'] <= value <= spec['maximum']: raise ValueError(key+' outside supported bounds')
        result[key] = value
    return result


def generate_world(scene, output_path, *, seed=0, parameters=None):
    if type(seed) is not int or not 0 <= seed <= 2**32-1: raise ValueError('seed must be an unsigned 32-bit integer')
    p = validate_parameters(scene,parameters)
    rng = random.Random(seed)
    sdf = ET.Element('sdf', version='1.9')
    world = child(sdf, 'world', name='vaf_'+scene['id'].lower())
    physics = child(world,'physics',name='1ms',type='ignored')
    child(physics,'max_step_size',.001); child(physics,'real_time_factor',1)
    for name, filename in [('Physics','physics'),('UserCommands','user-commands'),('SceneBroadcaster','scene-broadcaster'),('Imu','imu'),('NavSat','navsat'),('Contact','contact')]:
        child(world,'plugin',filename=f'gz-sim-{filename}-system',name='gz::sim::systems::'+name)
    child(world,'gravity','0 0 -9.81')
    spherical = child(world,'spherical_coordinates')
    for key,val in [('surface_model','EARTH_WGS84'),('latitude_deg',-35.363262),('longitude_deg',149.165237),('elevation',584),('heading_deg',0)]: child(spherical,key,val)
    light = child(world,'light',type='directional',name='sun')
    child(light,'pose','0 0 100 0 0 0'); child(light,'direction','-.5 .1 -.9')
    child(light,'diffuse',f"{p['light_intensity']} {p['light_intensity']} {p['light_intensity']} 1")
    child(light,'cast_shadows','true')
    wind = child(world,'wind'); angle=math.radians(p['wind_direction'])
    child(wind,'linear_velocity',f"{p['wind_speed']*math.cos(angle)} {p['wind_speed']*math.sin(angle)} 0")
    child(world,'plugin',filename='gz-sim-wind-effects-system',name='gz::sim::systems::WindEffects')
    # Ground remains a finite collision box; spawn and all fixtures are inside it.
    sx,sy=scene['extent_m']
    box(world,'ground',(0,0,-.25,0,0,0),(sx,sy,.5),color='.3 .4 .3 1',friction=p['friction'])
    layout=scene['layout']
    if layout in ('driving','gps'):
        for x in range(8,40,8):
            for y in (-5,5): box(world,f'cone_{x}_{y}',(x,y,.5,0,0,0),(.4,1),shape='cylinder',color='1 .45 .05 1')
    elif layout in ('warehouse','indoor'):
        for i,x in enumerate((-18,-10,10,18)):
            for j,y in enumerate((-16,0,16)): box(world,f'rack_{i}_{j}',(x,y,2,0,0,0),(2,10,4),color='.2 .35 .7 1')
        box(world,'roof',(0,0,12,0,0,0),(50,50,.2))
        for i,y in enumerate((-25,25)):box(world,'wall_'+str(i),(0,y,6,0,0,0),(50,.3,12))
    elif layout in ('urban','village'):
        for i,x in enumerate((-35,-20,20,35)):
            for j,y in enumerate((-30,-12,12,30)):
                height=rng.uniform(4,20) if layout=='urban' else rng.uniform(3,6)
                box(world,f'building_{i}_{j}',(x,y,height/2,0,0,0),(9,9,height))
        box(world,'road',(0,0,.015,0,0,0),(100,12,.03),color='.1 .1 .1 1')
    elif layout in ('forest','valley'):
        for i in range(40):
            x=rng.choice((-1,1))*rng.uniform(8,48);y=rng.uniform(-45,45)
            box(world,f'trunk_{i}',(x,y,3,0,0,0),(.5,6),shape='cylinder',color='.3 .15 .05 1')
            box(world,f'canopy_{i}',(x,y,7,0,0,0),(2,),shape='sphere',color='.1 .45 .1 1')
        if layout=='valley':
            for side in (-1,1):box(world,'ridge_'+str(side),(side*43,0,8,0,side*.3,0),(25,100,16))
    elif layout in ('slope','hills'):
        for i in range(5):box(world,'ramp_'+str(i),(12+i*9,(-1)**i*12,1.5+i*.4,0,.15*(i%3+1),0),(12,9,1.5),color='.5 .35 .2 1')
    elif layout=='multilevel':
        box(world,'upper_floor',(20,15,4,0,0,0),(25,25,.3))
        box(world,'connecting_ramp',(2,15,2,0,-math.atan2(4,20),0),(20.4,4,.2))
        for i,x in enumerate((10,30)):
            for j,y in enumerate((5,25)):box(world,f'pillar_{i}_{j}',(x,y,2,0,0,0),(.4,.4,4))
    elif layout in ('traffic','moving'):
        for i,y in enumerate((-12,0,12)):moving_target(world,'moving_target_'+str(i),12,y)
    elif layout=='obstacles3d':
        for i in range(8):box(world,'aerial_barrier_'+str(i),(10+(i%4)*10,(-1)**i*8,2+(i//4)*6,0,0,0),(2,8,4))
    elif layout in ('landing','vtol'):
        box(world,'landing_platform',(15,0,.2,0,0,0),(8,8,.4),color='.9 .9 .9 1')
        for i in range(4):
            for j in range(4):
                if (i+j)%2==0:box(world,f'landing_checker_{i}_{j}',(12+i*2,-3+j*2,.411,0,0,0),(1.9,1.9,.02),color='.05 .05 .05 1')
    elif layout=='river':
        box(world,'river_visual',(25,0,.02,0,0,0),(12,300,.04),color='.05 .3 .7 1')
        box(world,'bridge_deck',(25,0,2,0,0,0),(18,8,.5),color='.45 .45 .45 1')
        for i,x in enumerate((18,32)):box(world,'bridge_support_'+str(i),(x,0,1,0,0,0),(1,8,2))
    if scene['category']=='plane':
        box(world,'runway',(150,0,.015,0,0,0),(500,25,.03),color='.1 .1 .12 1')
        for i in range(15):box(world,'runway_mark_'+str(i),(-50+i*28,0,.037,0,0,0),(12,.5,.01),color='1 1 1 1')
    if layout in ('search','cooperative'):
        for i in range(6):
            x,y=20+(i%3)*12,-15+(i//3)*30
            box(world,'target_'+str(i),(x,y,.6,0,0,0),(1.2,1.2,1.2),color=f'{.2+i*.12} .1 .8 1')
    # Random obstacle region excludes the spawn/runway; reproducible by seed.
    for i in range(p['obstacle_count']):
        x=rng.uniform(-45,45);y=rng.choice((-1,1))*rng.uniform(28,48)
        h=rng.uniform(.5,2.5)
        box(world,'random_obstacle_'+str(i),(x,y,h/2,0,0,0),(1,1,h),friction=p['friction'])
    destination=Path(output_path)
    destination.parent.mkdir(parents=True,exist_ok=True)
    ET.indent(sdf)
    ET.ElementTree(sdf).write(destination,encoding='utf-8',xml_declaration=True)
    return destination
