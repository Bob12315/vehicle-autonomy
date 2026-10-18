"""Read-only planning use case. No vehicle command port or Effect is produced."""
from __future__ import annotations

import math
from uuid import uuid4

from planning.collision import CollisionGrid
from planning.models import PathCandidate, PlanRequest, PlanningError, VerifiedPath


class ReadOnlyPlanningService:
    def __init__(self, context_provider, backend, clock):
        self.context_provider, self.backend, self.clock = context_provider, backend, clock

    def plan(self, start, goal, *, timeout_s=15., clearance_m=.55):
        if type(timeout_s) not in (int,float) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 20:
            raise ValueError("planning timeout must be within twenty seconds")
        context = self.context_provider()
        now = self.clock()
        context.check_fresh(now)
        request = PlanRequest(uuid4().hex, context, start, goal, now,
                              now.monotonic_ns+int(timeout_s*1e9), clearance_m)
        collision = CollisionGrid(context, clearance_m)
        for label, pose in (("START",start),("GOAL",goal)):
            try:collision.validate((pose,))
            except PlanningError as exc:
                raise PlanningError("INVALID_"+label,str(exc)) from exc
        candidate = self.backend.compute(request, collision.configuration_grid())
        if not isinstance(candidate, PathCandidate):
            raise PlanningError("INVALID_PATH", "planner returned an untyped path")
        validated_at = self.clock()
        if validated_at.clock_domain_id != now.clock_domain_id or not now.monotonic_ns <= validated_at.monotonic_ns < request.deadline_ns:
            raise PlanningError("TIMEOUT", "planning result arrived after its deadline or in another clock domain")
        context.check_fresh(validated_at)
        if (candidate.request_id,candidate.map_sha256,candidate.frame_epoch,candidate.frame_id) != (
            request.request_id,context.sha256,context.frame_epoch,context.grid.frame_id):
            raise PlanningError("INVALID_PATH", "planner response does not match request/map/frame")
        for expected, actual in ((start,candidate.poses[0]),(goal,candidate.poses[-1])):
            if math.hypot(actual.x-expected.x,actual.y-expected.y) > .10:
                raise PlanningError("INVALID_PATH", "path endpoint differs from the requested position by more than 0.10 m")
        length = collision.validate(candidate.poses)
        current = self.context_provider()
        validated_at = self.clock()
        if validated_at.clock_domain_id != now.clock_domain_id or not now.monotonic_ns <= validated_at.monotonic_ns < request.deadline_ns:
            raise PlanningError("TIMEOUT", "path validation exceeded the planning deadline")
        context.check_fresh(validated_at)
        current.check_fresh(validated_at)
        if (current.sha256, current.frame_epoch, current.reference, current.source_kind) != (
            context.sha256, context.frame_epoch, context.reference, context.source_kind):
            # A new publication revision with identical content/source remains
            # geometrically equivalent; retain the ORIGINAL dependency/time.
            if (current.sha256, current.frame_epoch, current.reference.resource_id, current.reference.version.generation_id, current.source_kind) != (
                context.sha256, context.frame_epoch, context.reference.resource_id, context.reference.version.generation_id, context.source_kind):
                raise PlanningError("MAP_CHANGED", "planning map content/source/frame epoch changed during computation")
        until = request.deadline_ns if context.captured_at is None else min(request.deadline_ns,context.captured_at.monotonic_ns+context.max_age_ns)
        return VerifiedPath(request,candidate,validated_at,until,length,self.backend.name)
