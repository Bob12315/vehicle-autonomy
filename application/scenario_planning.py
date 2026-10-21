"""Deterministic finite simulation itinerary and known-scene collision admission.

This is a configured static scene, not sensor perception or live obstacle avoidance.
"""
import hashlib
import json
import math
from pathlib import Path

from actions.rover_maneuver import ManeuverParameters
from planning.models import Pose2D

FOOTPRINT=.72
MARGIN=.15


def catalog(environment):
    number=lambda a,b:{'type':'number','min':a,'max':b}
    descriptions={
      'motion:drive':('Drive forward relative to current heading, then stop and disarm.',{'distance_m':number(.2,10),'speed_mps':number(.08,.18)}),
      'motion:turn':('Rotate in place by signed degrees; positive is left/CCW; stop and disarm.',{'angle_deg':number(-1080,1080)}),
      'motion:circle':('Drive finite full circles from current pose; stop and disarm.',{'radius_m':number(1.5,3),'laps':{'type':'integer','min':1,'max':3},'direction':{'enum':['left','right']},'speed_mps':number(.08,.18)}),
      'motion:wait':('Stay stopped for a finite duration; not a camera or object detection.',{'duration_s':number(1,30)}),
      'motion:visit':('Drive a straight clear corridor to a named station, stop and disarm.',{'waypoint':{'enum':[p.name for p in environment.points]},'speed_mps':number(.08,.18)})}
    return {k:{'description':d,'parameters':p} for k,(d,p) in descriptions.items()}


class StaticScene:
    def __init__(self,path,environment):
        self.path=Path(path);raw=self.path.read_bytes()
        if len(raw)>65536:raise ValueError('scene exceeds bound')
        self.sha256=hashlib.sha256(raw).hexdigest();d=json.loads(raw)
        if (type(d) is not dict or set(d)!={'schema','environment_id','obstacles'} or type(d['schema']) is not int
                or d['schema']!=1 or d['environment_id']!=environment.resource_id or type(d['obstacles']) is not list
                or len(d['obstacles'])>64):raise ValueError('explicit matching static scene required')
        self.obstacles=[]
        for box in d['obstacles']:
            if (type(box) is not dict or set(box)!={'name','x','y','width','depth','height'}
                    or type(box['name']) is not str or not box['name'] or len(box['name'])>48
                    or any(type(box[k]) not in (int,float) or not math.isfinite(box[k]) or abs(box[k])>100 for k in ('x','y','width','depth','height'))
                    or any(box[k]<=0 for k in ('width','depth','height'))):raise ValueError('invalid bounded scene box')
            self.obstacles.append(dict(box))
        self.obstacles=tuple(self.obstacles)

    def check(self):
        try:raw=self.path.read_bytes()
        except OSError as exc:raise ValueError('static_scene_unavailable') from exc
        if hashlib.sha256(raw).hexdigest()!=self.sha256:raise ValueError('static_scene_changed')

    def clearance(self,point,environment,*,margin=MARGIN):
        fence=environment.geofence;r=FOOTPRINT+margin
        if not fence.min_x+r<=point.x<=fence.max_x-r or not fence.min_y+r<=point.y<=fence.max_y-r:
            raise ValueError('maneuver_footprint_outside_geofence')
        for b in self.obstacles:
            dx=max(abs(point.x-b['x'])-b['width']/2,0)
            dy=max(abs(point.y-b['y'])-b['depth']/2,0)
            if math.hypot(dx,dy)<=r:raise ValueError('maneuver_known_obstacle:'+b['name'])


def resolve(design,environment,start,scene):
    """Anchor all relative commands once. Future steps never silently rebase."""
    scene.check();prepared={};pose=start;total_s=0.
    for i,mission in enumerate(design.missions):
        if not mission.startswith('motion:'):
            if mission!='disarmed_mode':raise ValueError('parameterized designs cannot mix opaque legacy routes')
            total_s+=20;continue
        a=dict(design.arguments[i]);kind=mission.split(':')[1];end=pose
        speed=a.get('speed_mps',.15);turn=radius=duration=0.
        if kind=='drive':
            distance=a['distance_m'];end=Pose2D(pose.x+distance*math.cos(pose.yaw),pose.y+distance*math.sin(pose.yaw),pose.yaw)
            eta=distance/speed
        elif kind=='visit':
            point=environment.resolve(a['waypoint']).position;distance=math.hypot(point.x-pose.x,point.y-pose.y)
            heading=math.atan2(point.y-pose.y,point.x-pose.x) if distance>.01 else pose.yaw
            end=Pose2D(point.x,point.y,heading);eta=distance/speed+math.pi/.2
        elif kind=='turn':
            turn=math.radians(a['angle_deg'])
            if abs(turn)<math.radians(5):raise ValueError('turn must be at least five degrees')
            end=Pose2D(pose.x,pose.y,math.atan2(math.sin(pose.yaw+turn),math.cos(pose.yaw+turn)));eta=abs(turn)/.2
        elif kind=='circle':
            radius=a['radius_m'];turn=2*math.pi*a['laps']*(1 if a['direction']=='left' else -1)
            eta=abs(turn)*radius/speed
        elif kind=='wait':duration=a['duration_s'];eta=duration
        else:raise ValueError('unknown registered scenario maneuver')
        if kind=='circle':
            sign=1 if turn>0 else -1
            cx=pose.x-sign*radius*math.sin(pose.yaw);cy=pose.y+sign*radius*math.cos(pose.yaw)
            polar=pose.yaw-sign*math.pi/2;n=math.ceil(abs(turn)*radius/.04)
            path=tuple(Pose2D(cx+radius*math.cos(polar+turn*j/n),cy+radius*math.sin(polar+turn*j/n)) for j in range(n+1))
        else:
            n=max(1,math.ceil(math.hypot(end.x-pose.x,end.y-pose.y)/.04))
            path=tuple(Pose2D(pose.x+(end.x-pose.x)*j/n,pose.y+(end.y-pose.y)*j/n) for j in range(n+1))
        for point in path:scene.clearance(point,environment)
        timeout_s=math.ceil(eta*1.8+20)
        if timeout_s>300:raise ValueError('maneuver exceeds 300 second step budget')
        total_s+=timeout_s+30
        if total_s>600:raise ValueError('itinerary exceeds 600 second total budget')
        prepared[i]=ManeuverParameters(environment.reference,kind,pose,end,path,speed,turn,radius,duration,timeout_s*1_000_000_000)
        pose=end
    return prepared,{'estimated_deadline_s':round(total_s,1),'frame':'odom','reference_point':'front_drive_axle',
        'footprint_radius_m':FOOTPRINT,'clearance_margin_m':MARGIN,'static_scene_sha256':scene.sha256,
        'start':[start.x,start.y,start.yaw],'end':[pose.x,pose.y,pose.yaw],
        'path_preview':[[p.x,p.y] for step in prepared.values() for p in step.path[::max(1,len(step.path)//80)]],
        'obstacle_source':'configured static scene; not live sensor avoidance'}


def build(parameters,mode_id):
    from actions.basic import BasicParameters
    from actions.rover_maneuver import SPEC
    from contracts.decision import MissionPlan,MissionStep
    from core.sitl_mode_action import SITL_MODE_SPEC,SitlModeParameters
    e=parameters.environment
    return MissionPlan('scenario:'+parameters.kind,(
        MissionStep('mode',SITL_MODE_SPEC.name,SitlModeParameters('GUIDED',mode_id)),
        MissionStep('arm','basic.arm',BasicParameters('rover',e)),
        MissionStep('maneuver',SPEC.name,parameters),
        MissionStep('stop','basic.stop',BasicParameters('rover',e,timeout_ns=8_000_000_000)),
        MissionStep('disarm','basic.disarm',BasicParameters('rover',e))))
