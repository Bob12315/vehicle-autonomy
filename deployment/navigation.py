"""Explicit path admission and live-map fences for the localhost Rover App.

This coordinator has no command port. Its injected final guard only rejects;
all writes still belong to the original Execution/Authority/Safety/writer.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tomllib

from actions.basic import yaw
from actions.path_following import TrackingParameters
from contracts.core.primitives import ResourceVersion
from contracts.vehicle.command import TwistTargetCommand
from contracts.world.models import ResourceReference
from guidance.path_following import (BODY_RADIUS_FROM_DRIVE_M, CROSS_TRACK_M, DRIVE_OFFSET_M,
                                    PATH_CLEARANCE_M, PlanarBinding, PolylineTracker, drive_reference)
from mapping.grid import pose_from_json
from planning.collision import CollisionGrid
from planning.models import MapContext, Pose2D, PlanningError


@dataclass(frozen=True, slots=True)
class NavigationConfig:
    plan_path: Path
    timeout_ns: int
    goals_path: Path | None = None
    tracking_mode: str = 'smooth'

    @classmethod
    def load(cls, path):
        data = tomllib.loads(Path(path).read_text())
        if set(data)-{"schema", "model", "plan_path", "timeout_ns", "goals_path", "tracking_mode"} or not {"schema", "model", "plan_path", "timeout_ns"} <= set(data) or type(data["schema"]) is not int or data["schema"] != 1:
            raise ValueError("invalid navigation configuration")
        if data["model"] != "target_rover_front_axle_v1":
            raise ValueError("only the audited front-drive Rover model is supported")
        if type(data["plan_path"]) is not str or not Path(data["plan_path"]).is_absolute():
            raise ValueError("navigation plan path must be explicit and absolute")
        if type(data["timeout_ns"]) is not int or not 1_000_000_000 <= data["timeout_ns"] <= 70_000_000_000:
            raise ValueError("navigation timeout must be within 1..70 seconds")
        goals = data.get("goals_path")
        if goals is not None and (type(goals) is not str or not Path(goals).is_absolute()):
            raise ValueError("navigation goals path must be explicit and absolute")
        mode=data.get('tracking_mode','smooth')
        if mode not in ('smooth','stop_turn'):raise ValueError('unregistered tracking strategy')
        return cls(Path(data["plan_path"]), data["timeout_ns"],None if goals is None else Path(goals),mode)


@dataclass(frozen=True, slots=True)
class NavigationView:
    request_id: str | None
    error: str | None


class NavigationReader:
    __slots__ = ("_read",)

    def __init__(self, read):
        self._read = read

    def snapshot(self):
        return self._read()


def read_plan(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 2_000_000:
            raise ValueError("plan must be a bounded regular file")
        payload = stream.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("plan is too large")
    return payload, hashlib.sha256(payload).hexdigest()


class NavigationSupervisor:
    def __init__(self, config, safety, event_sink=None, source_store=None):
        self.config, self.safety = config, safety
        self.source_store = source_store
        self.emit = event_sink or (lambda *args, **kwargs: None)
        self.context = self.binding = self.body_grid = self.route_grid = None
        self.parameters = None
        self.view = NavigationView(None, "navigation_not_admitted")
        self.reader = NavigationReader(lambda: self.view)
        self.consumed = set()
        self.tracker = None
        self.last_drift_m = None
        self.revalidations = 0
        self.last_error = None

    def fail(self, reason):
        if self.parameters is not None and self.view.error is None:
            self.view = NavigationView(self.parameters.request_id, reason)
            self.last_error = reason
            self.emit("navigation_invalidated", reason=reason)

    def update_map(self, mapped, health, now, frame_epoch):
        try:
            if mapped is None:
                if self.parameters is not None and self.view.error is None:
                    self.emit("navigation_source_fault",health=dict(health))
                raise ValueError("navigation_map_unavailable")
            context = MapContext(mapped.reference, mapped.sha256, frame_epoch, mapped.grid,
                                 "live_map", mapped.captured_at, 2_500_000_000)
            context.check_fresh(now)
            transform = pose_from_json(health["odom_in_map"])
            if abs(transform.orientation.x) > .01 or abs(transform.orientation.y) > .01:
                raise ValueError("navigation_nonplanar_alignment")
            binding = PlanarBinding(transform.position.x, transform.position.y, yaw(transform))
            p = self.parameters
            if p is not None and self.view.error is None:
                if (frame_epoch, str(context.reference.version.generation_id)) != (p.frame_epoch, p.source_generation):
                    raise ValueError("navigation_map_epoch_changed")
                drift = max(math.hypot(binding.to_map(point).x-p.binding.to_map(point).x,
                                       binding.to_map(point).y-p.binding.to_map(point).y) for point in p.poses)
                self.last_drift_m = drift
                if drift > .1:
                    raise ValueError("navigation_alignment_changed")
                _, digest = read_plan(self.config.plan_path)
                if digest != p.file_sha256:
                    raise ValueError("navigation_plan_file_changed")
                if self.context is None or self.context.sha256 != context.sha256 or self.binding != binding:
                    # A changing SLAM map is accepted only after checking every
                    # segment again in that map's explicitly observed alignment.
                    self.route_grid = CollisionGrid(context, PATH_CLEARANCE_M)
                    try:
                        self.route_grid.validate(tuple(binding.to_map(point) for point in p.poses))
                    except PlanningError as exc:
                        raise ValueError("navigation_path_blocked: "+str(exc)) from exc
                    self.body_grid = CollisionGrid(context, BODY_RADIUS_FROM_DRIVE_M+.04)
                    self.revalidations += 1
                    self.emit("navigation_map_revalidated", sha256=context.sha256,
                              revision=context.reference.version.revision, drift_m=drift)
            self.context, self.binding = context, binding
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            self.context = None
            self.fail(str(exc))

    def admit(self, world, now):
        context, binding = self.context, self.binding
        if context is None or binding is None or world.map != context.reference:
            raise ValueError("fresh adopted navigation map required")
        context.check_fresh(now)
        raw, digest = read_plan(self.config.plan_path)
        response = json.loads(raw)
        if type(response) is not dict or response.get("ok") is not True or type(response.get("result")) is not dict:
            raise ValueError("successful app.plan output required")
        d = response["result"]
        fields = {"schema", "request_id", "executable", "kind", "backend", "frame_id", "frame_epoch", "map", "clock_domain_id",
                  "requested_ns", "validated_ns", "valid_until_ns", "clearance_m", "length_m", "start", "goal", "poses"}
        if set(d) != fields or type(d["schema"]) is not int or d["schema"] != 1 or d["executable"] is not False or d["kind"] != "geometric_path":
            raise ValueError("unsupported geometric path document")
        if d["backend"] != "nav2.SmacPlanner2D.jazzy" or d["frame_id"] != "map" or d["frame_epoch"] != context.frame_epoch:
            raise ValueError("plan backend or frame epoch mismatch")
        if type(d["request_id"]) is not str or not 1 <= len(d["request_id"]) <= 128 or d["request_id"] in self.consumed:
            raise ValueError("invalid or already consumed plan identity")
        if len(self.consumed) >= 128:
            raise ValueError("navigation admission limit reached; restart required")
        if d["clock_domain_id"] != str(now.clock_domain_id):
            raise ValueError("plan clock domain mismatch")
        if any(type(d[k]) is not int for k in ("requested_ns", "validated_ns", "valid_until_ns")) or not (
                0 <= d["requested_ns"] <= d["validated_ns"] <= now.monotonic_ns < d["valid_until_ns"] <= d["requested_ns"]+20_000_000_000):
            raise ValueError("plan admission deadline invalid or expired")
        m = d["map"]
        if type(m) is not dict or set(m) != {"resource_id", "generation", "revision", "sha256", "source_kind", "captured_ns"}:
            raise ValueError("invalid plan map dependency")
        if (m["source_kind"], m["resource_id"], m["generation"]) != ("live_map", str(context.reference.resource_id), str(context.reference.version.generation_id)):
            raise ValueError("live map source identity required; recordings cannot authorize motion")
        if type(m["revision"]) is not int or not 0 <= m["revision"] <= context.reference.version.revision:
            raise ValueError("plan map revision is invalid")
        if type(m["captured_ns"]) is not int or not 0 <= d["requested_ns"]-m["captured_ns"] <= 10_000_000_000:
            raise ValueError("plan source capture is invalid")
        if type(m["sha256"]) is not str or len(m["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in m["sha256"]):
            raise ValueError("invalid source content identity")
        if m["revision"] == context.reference.version.revision and (m["sha256"] != context.sha256 or m["captured_ns"] != context.captured_at.monotonic_ns):
            raise ValueError("plan reuses a map revision with different source facts")
        if type(d["clearance_m"]) not in (int, float) or not math.isfinite(d["clearance_m"]) or not PATH_CLEARANCE_M <= d["clearance_m"] <= 2:
            raise ValueError("motion requires at least 0.95 metre planned clearance about the drive axle")
        if type(d["poses"]) is not list or not 2 <= len(d["poses"]) <= 8192:
            raise ValueError("bounded path required")
        def pose(value):
            if type(value) is not list or len(value) != 3:
                raise ValueError("planar triple required")
            return Pose2D(*value)
        poses = tuple(pose(v) for v in d["poses"])
        start, goal = pose(d["start"]), pose(d["goal"])
        if any(math.hypot(a.x-b.x, a.y-b.y) > .1 for a, b in ((start, poses[0]), (goal, poses[-1]))):
            raise ValueError("plan endpoint mismatch")
        route = CollisionGrid(context, d["clearance_m"])
        length = route.validate(poses)
        if self.source_store is not None:
            original_grid = self.source_store.load(m["sha256"])
            # This is stored content validation, not a freshness assertion.
            # Preserve its old version; never retime it with the current map.
            original_context = MapContext(ResourceReference(m["resource_id"], ResourceVersion(m["generation"],m["revision"])),
                m["sha256"], context.frame_epoch, original_grid, "recorded_map")
            CollisionGrid(original_context, d["clearance_m"]).validate(poses)
        if type(d["length_m"]) not in (int, float) or not math.isfinite(d["length_m"]) or abs(length-d["length_m"]) > 1e-6:
            raise ValueError("plan length mismatch")
        odom = tuple(binding.to_odom(p) for p in poses)
        loc = world.localization
        if loc is None or loc.pose.frame_id != "odom" or not 0 <= now.elapsed_ns_since(loc.pose.captured_at) <= 500_000_000:
            raise ValueError("fresh odom localization required")
        current_pose = loc.pose.value
        current = drive_reference(Pose2D(current_pose.position.x,current_pose.position.y,yaw(current_pose)))
        if math.hypot(current.x-odom[0].x, current.y-odom[0].y) > .2:
            raise ValueError("plan start is too far from current vehicle")
        for point in odom:
            if not (self.safety.min_x_m+BODY_RADIUS_FROM_DRIVE_M <= point.x <= self.safety.max_x_m-BODY_RADIUS_FROM_DRIVE_M
                    and self.safety.min_y_m+BODY_RADIUS_FROM_DRIVE_M <= point.y <= self.safety.max_y_m-BODY_RADIUS_FROM_DRIVE_M):
                raise ValueError("bound path footprint exceeds vehicle geofence")
        parameters = TrackingParameters(world.environment, d["request_id"], str(context.frame_epoch),
            str(context.reference.version.generation_id), digest, binding, odom, self.config.timeout_ns,
            self.config.tracking_mode=='stop_turn')
        self.parameters = parameters
        self.view = NavigationView(parameters.request_id, None)
        self.tracker = PolylineTracker(odom)
        self.route_grid, self.body_grid = route, CollisionGrid(context, BODY_RADIUS_FROM_DRIVE_M+.04)
        self.last_drift_m, self.revalidations = 0., 0
        self.last_error = None
        self.emit("navigation_admitted", request_id=parameters.request_id, plan_sha256=digest,
                  source_map_sha256=m["sha256"], adopted_map_sha256=context.sha256,
                  binding={"x": binding.x, "y": binding.y, "yaw": binding.yaw},
                  reference_point="front_drive_axle", base_to_reference_x_m=DRIVE_OFFSET_M,
                  footprint_radius_m=BODY_RADIUS_FROM_DRIVE_M,
                  odom_poses=[[p.x, p.y, p.yaw] for p in odom], length_m=length)
        return parameters

    def consume(self):
        self.consumed.add(self.parameters.request_id)

    def finish(self):
        self.parameters = None
        self.view = NavigationView(None, "navigation_not_admitted")

    def write_guard(self, command, state, now):
        if self.parameters is None:
            return None
        if self.view.error:
            return self.view.error
        try:
            if not isinstance(command.command, TwistTargetCommand) or command.command.frame_id != "base_link":
                raise ValueError("navigation_requires_body_twist")
            if self.context is None:
                raise ValueError("navigation_map_unavailable")
            self.context.check_fresh(now)
            if read_plan(self.config.plan_path)[1] != self.parameters.file_sha256:
                raise ValueError("navigation_plan_file_changed")
            for value in (state.reported_pose, state.reported_twist):
                if value is None or not 0 <= now.elapsed_ns_since(value.captured_at) <= 500_000_000:
                    raise ValueError("navigation_state_stale")
            p = state.reported_pose.value
            current = drive_reference(Pose2D(p.position.x, p.position.y, yaw(p)))
            distance, progress = self.tracker.project(current)
            self.tracker.progress = progress
            if distance > CROSS_TRACK_M:
                raise ValueError("navigation_cross_track_exceeded")
            twist = command.command.target_twist
            if not 0 <= twist.linear.x <= .18 or abs(twist.angular.z) > .25:
                raise ValueError("navigation_velocity_bound_exceeded")
            # Check a one-second swept prediction including turning. Unknown
            # cells block it too. StopMotion is exempt in the common writer.
            predicted = []
            for i in range(9):
                t, v, w = i/8, twist.linear.x, twist.angular.z
                if abs(w) < 1e-8:
                    x, y = current.x+v*t*math.cos(current.yaw), current.y+v*t*math.sin(current.yaw)
                else:
                    x = current.x+v/w*(math.sin(current.yaw+w*t)-math.sin(current.yaw))
                    y = current.y-v/w*(math.cos(current.yaw+w*t)-math.cos(current.yaw))
                predicted.append(self.binding.to_map(Pose2D(x, y)))
            self.body_grid.validate(tuple(predicted))
            return None
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.fail(str(exc))
            return str(exc)

    def status(self, world=None, now=None):
        start = None
        if world is not None and now is not None and self.context is not None and self.binding is not None:
            try:
                self.context.check_fresh(now)
                loc = world.localization
                if (world.map == self.context.reference and loc is not None and loc.pose.frame_id == "odom"
                        and 0 <= now.elapsed_ns_since(loc.pose.captured_at) <= 500_000_000):
                    p = loc.pose.value
                    point = self.binding.to_map(drive_reference(Pose2D(p.position.x,p.position.y,yaw(p))))
                    start = {"frame": "map", "frame_epoch": self.context.frame_epoch,
                             "reference_point": "front_drive_axle", "position": [point.x,point.y],
                             "captured_ns": loc.pose.captured_at.monotonic_ns}
            except ValueError:
                pass
        return {"configured": True, "active": self.parameters is not None,
                "request_id": self.view.request_id, "error": self.view.error,
                "last_error": self.last_error,
                "alignment_drift_m": self.last_drift_m, "map_revalidations": self.revalidations,
                "model": "target_rover_front_axle_v1", "base_to_reference_x_m": DRIVE_OFFSET_M,
                "required_clearance_m": PATH_CLEARANCE_M, "planning_start": start,
                "progress_m": None if self.tracker is None else self.tracker.progress}
