"""Bounded planar polyline guidance. No ROS, effects, or device access."""
from __future__ import annotations

from dataclasses import dataclass
import math

from planning.models import Pose2D


def angle(value):
    return math.atan2(math.sin(value), math.cos(value))


# The audited two-front-drive-wheel / two-rear-caster model. Its drive
# reference is NOT base_link: pivoting translates the body origin.
DRIVE_OFFSET_M = .25
BODY_RADIUS_FROM_DRIVE_M = .72
PATH_CLEARANCE_M = .95
CROSS_TRACK_M = .15


def drive_reference(body):
    return Pose2D(body.x+DRIVE_OFFSET_M*math.cos(body.yaw),
                  body.y+DRIVE_OFFSET_M*math.sin(body.yaw), body.yaw)


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
    def __init__(self, poses, *, stop_turn=False):
        if type(stop_turn) is not bool:raise ValueError('explicit tracking strategy required')
        self.stop_turn=stop_turn
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
        error = angle(math.atan2(target.y-pose.y, target.x-pose.x)-pose.yaw)
        rate = max(-.2, min(.2, .25*error-.75*measured_yaw_rate))
        speed = min(.15, max(.04, .5*(remaining-.12))) * max(0., math.cos(error))**3
        # Caster stiction makes tiny steering corrections ineffective on the
        # audited physical Rover. Align at the drive axle before advancing;
        # hysteresis prevents noisy heading cuts from toggling every cycle.
        if self.stop_turn:
            if abs(error) > .3 or (distance > .06 and abs(error) > .15):
                self.turning = True
            if abs(error) < .08 and abs(measured_yaw_rate) < .1:
                self.turning = False
            if self.turning:
                speed = 0.
                rate = math.copysign(.2,error) if abs(error) >= .08 else 0.
        elif abs(error) > .45:
            speed = 0.
        return GuidanceOutput(0. if arrived else speed, 0. if arrived else rate,
                              self.progress, distance, arrived)
