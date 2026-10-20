"""Bounded planar polyline guidance. No ROS, effects, or device access."""
from __future__ import annotations

from dataclasses import dataclass
import math

from planning.models import Pose2D
from .navigation_model import FRONT_AXLE,VehicleNavigationModel


def angle(value):
    return math.atan2(math.sin(value), math.cos(value))


# The audited two-front-drive-wheel / two-rear-caster model. Its drive
# reference is NOT base_link: pivoting translates the body origin.
DRIVE_OFFSET_M = FRONT_AXLE.base_to_reference_x_m
BODY_RADIUS_FROM_DRIVE_M = FRONT_AXLE.footprint_radius_m
PATH_CLEARANCE_M = FRONT_AXLE.path_clearance_m
CROSS_TRACK_M = FRONT_AXLE.cross_track_m


def drive_reference(body, model=FRONT_AXLE):
    return Pose2D(body.x+model.base_to_reference_x_m*math.cos(body.yaw),
                  body.y+model.base_to_reference_x_m*math.sin(body.yaw), body.yaw)


@dataclass(frozen=True, slots=True)
class PlanarBinding:
    """Explicit map <- odom alignment, pinned for one admitted run."""
    x: float
    y: float
    yaw: float

    def __post_init__(self):
        Pose2D(self.x, self.y, self.yaw)

    def to_map(self, p):
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return Pose2D(self.x+c*p.x-s*p.y, self.y+s*p.x+c*p.y, angle(self.yaw+p.yaw))

    def to_odom(self, p):
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        x, y = p.x-self.x, p.y-self.y
        return Pose2D(c*x+s*y, -s*x+c*y, angle(p.yaw-self.yaw))


@dataclass(frozen=True, slots=True)
class GuidanceOutput:
    speed_mps: float
    yaw_rate_rps: float
    progress_m: float
    cross_track_m: float
    arrived: bool


class PolylineTracker:
    def __init__(self, poses, *, stop_turn=False, model=FRONT_AXLE, allow_reverse=False):
        if not isinstance(model,VehicleNavigationModel):raise TypeError("typed navigation model required")
        self.model=model
        if type(stop_turn) is not bool:raise ValueError('explicit tracking strategy required')
        self.stop_turn=stop_turn
        if type(allow_reverse) is not bool:raise ValueError('explicit reverse permission required')
        self.allow_reverse=allow_reverse;self.direction=None
        if not isinstance(poses, tuple) or not 2 <= len(poses) <= 8192 or not all(isinstance(p, Pose2D) for p in poses):
            raise ValueError("tracking needs 2..8192 immutable poses")
        self.poses = poses
        self.distances = [0.]
        for a, b in zip(poses, poses[1:]):
            self.distances.append(self.distances[-1]+math.hypot(b.x-a.x, b.y-a.y))
        if not .1 <= self.distances[-1] <= 20:
            raise ValueError("initial Rover tracking supports paths of 0.1..20 metres")
        self.progress = 0.
        self.turning = False

    def sample(self, distance):
        for i, end in enumerate(self.distances[1:]):
            if end >= distance:
                a, b = self.poses[i:i+2]
                f = max(0., min(1., (distance-self.distances[i])/max(1e-12, end-self.distances[i])))
                return Pose2D(a.x+f*(b.x-a.x), a.y+f*(b.y-a.y))
        return self.poses[-1]

    def project(self, p):
        best = (float("inf"), self.progress)
        # Restrict projection to a local arc window: crossings must not skip a
        # whole loop or a distant leg. Progress can never regress.
        for i, (a, b) in enumerate(zip(self.poses, self.poses[1:])):
            start, end = self.distances[i:i+2]
            if end < self.progress-.2 or start > self.progress+.8:
                continue
            dx, dy = b.x-a.x, b.y-a.y
            f = max(0., min(1., ((p.x-a.x)*dx+(p.y-a.y)*dy)/max(1e-12, dx*dx+dy*dy)))
            projected = start+f*(end-start)
            if projected > self.progress+.8:
                continue
            distance = math.hypot(p.x-a.x-f*dx, p.y-a.y-f*dy)
            if distance < best[0]:
                best = distance, max(self.progress, projected)
        return best

    def update(self, pose, measured_yaw_rate=0.):
        distance, self.progress = self.project(pose)
        goal = self.poses[-1]
        remaining = math.hypot(goal.x-pose.x, goal.y-pose.y)
        arrived = self.progress >= self.distances[-1]-.3 and remaining <= .18
        # A longer straight-line preview avoids chasing centimetre-scale
        # localization noise. Shorten it at bends rather than cutting corners.
        preview = .75
        anchor = self.sample(self.progress)
        while True:
            target = self.sample(min(self.distances[-1], self.progress+preview))
            chord = (Pose2D(anchor.x+(target.x-anchor.x)*i/8,
                            anchor.y+(target.y-anchor.y)*i/8) for i in range(1,8))
            if preview <= .25 or all(self.project(p)[0] <= .07 for p in chord):
                break
            preview = max(.25,preview-.1)
        bearing=math.atan2(target.y-pose.y, target.x-pose.x)
        if self.direction is None:
            self.direction=-1 if self.allow_reverse and abs(angle(bearing-pose.yaw))>2*math.pi/3 else 1
        error = angle(bearing-pose.yaw-(math.pi if self.direction<0 else 0))
        rate_limit=min(.2,self.model.max_yaw_rate_rps)
        rate = max(-rate_limit, min(rate_limit, .25*error-.75*measured_yaw_rate))
        speed = min(.15, self.model.max_speed_mps, max(.04, .5*(remaining-.12))) * max(0., math.cos(error))**3
        # The explicit caster strategy uses stronger moving feedback and a
        # damped pivot for large heading errors; the default stays unchanged.
        if self.stop_turn:
            # Stronger heading feedback overcomes the owned caster chassis'
            # small-command deadband. Only large turns require a full stop;
            # repeatedly stopping for small corrections winds up its steering
            # loop and prevents bounded paths finishing within their deadline.
            rate=max(-rate_limit,min(rate_limit,1.2*error-.75*measured_yaw_rate))
            if abs(measured_yaw_rate)<.05 and abs(error)>.12 and abs(rate)<rate_limit:
                rate=math.copysign(rate_limit,error)
            speed=min(speed,.12 if distance<=.08 and abs(error)<=.2 else .06)
            self.turning=abs(error)>.45
            if self.turning:
                speed = 0.
        elif abs(error) > .45:
            speed = 0.
        if self.direction<0:speed=-min(speed,.1,self.model.max_speed_mps)
        return GuidanceOutput(0. if arrived else speed, 0. if arrived else rate,
                              self.progress, distance, arrived)
