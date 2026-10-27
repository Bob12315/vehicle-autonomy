"""Owned physical obstacles. Scene truth is never a navigation data input."""
import xml.etree.ElementTree as ET


def block(world,name,x,y,sx,sy):
    model=ET.SubElement(world,'model',name=name);ET.SubElement(model,'static').text='true';ET.SubElement(model,'pose').text=f'{x} {y} .5 0 0 0'
    link=ET.SubElement(model,'link',name='body')
    for tag in ('collision','visual'):
        part=ET.SubElement(link,tag,name=name+'_'+tag);geometry=ET.SubElement(part,'geometry');box=ET.SubElement(geometry,'box');ET.SubElement(box,'size').text=f'{sx} {sy} 1'


def no_path(owned):
    tree=ET.parse(owned.world_path);world=tree.find('world')
    # Real 0.8 m opening: laser rays see the goal-side map, but the qualified
    # Rover footprint cannot pass. No truth map is supplied to SLAM/Nav2.
    block(world,'phase5_upper_partition',1.5,2.2,.2,3.6)
    block(world,'phase5_lower_partition',1.5,-2.2,.2,3.6)
    tree.write(owned.world_path)
    return dict(type='physical_narrow_passage',gap_m=.8,x_m=1.5,goal_x_m=3.)


def static_obstacle(owned):
    tree=ET.parse(owned.world_path);world=tree.find('world')
    block(world,'phase5_static_obstacle',1.6,0.,.4,.5)
    tree.write(owned.world_path)
    return dict(type='physical_box',x_m=1.6,y_m=0.,size_x_m=.4,size_y_m=.5,goal_x_m=3.)
