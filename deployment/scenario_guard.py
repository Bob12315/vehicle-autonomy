"""Rejected-only maneuver binding at the original sole simulation writer."""
import math
from actions.basic import yaw
from contracts.vehicle.command import TwistTargetCommand
from guidance.path_following import drive_reference
from planning.models import Pose2D


def distance_to_path(p,path):
    best=float('inf')
    for a,b in zip(path,path[1:]):
        dx,dy=b.x-a.x,b.y-a.y
        f=max(0.,min(1.,((p.x-a.x)*dx+(p.y-a.y)*dy)/max(1e-12,dx*dx+dy*dy)))
        best=min(best,math.hypot(p.x-a.x-f*dx,p.y-a.y-f*dy))
    return best


class ScenarioGuard:
    def __init__(self,scene,environment,previous=None):
        self.scene,self.environment,self.previous=scene,environment,previous;self.parameters=None

    def __call__(self,envelope,state,now):
        if self.previous:
            reason=self.previous(envelope,state,now)
            if reason:return reason
        if self.parameters is None:return None
        try:
            self.scene.check()
            if any(s is None or not 0<=now.elapsed_ns_since(s.captured_at)<=500_000_000 for s in (state.reported_pose,state.reported_twist)):
                raise ValueError('scenario_state_stale')
            c=envelope.command
            if not isinstance(c,TwistTargetCommand) or c.frame_id!='base_link':raise ValueError('scenario_requires_body_twist')
            t=c.target_twist;v,w=t.linear.x,t.angular.z
            raw=state.reported_pose.value;p=drive_reference(Pose2D(raw.position.x,raw.position.y,yaw(raw)))
            centering=(self.parameters.kind=='turn' or self.parameters.kind in ('drive','visit')
                       and math.hypot(p.x-self.parameters.end.x,p.y-self.parameters.end.y)<=.15)
            minimum=-.05 if centering else 0
            maximum=.05 if self.parameters.kind=='turn' else .18
            if (any(x!=0 for x in (t.linear.y,t.linear.z,t.angular.x,t.angular.y)) or not minimum<=v<=maximum or abs(w)>.25):
                raise ValueError('scenario_velocity_bound_exceeded')
            if distance_to_path(p,self.parameters.path)>.15:raise ValueError('scenario_cross_track_exceeded')
            for i in range(11):
                dt=i/10
                dx=v*dt*math.cos(p.yaw) if abs(w)<1e-6 else v/w*(math.sin(p.yaw+w*dt)-math.sin(p.yaw))
                dy=v*dt*math.sin(p.yaw) if abs(w)<1e-6 else v/w*(-math.cos(p.yaw+w*dt)+math.cos(p.yaw))
                self.scene.clearance(Pose2D(p.x+dx,p.y+dy),self.environment)
        except (OSError,ValueError) as exc:return str(exc)
        return None
