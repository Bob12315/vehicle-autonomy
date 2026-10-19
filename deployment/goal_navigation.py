"""Application-owned goal lifecycle above the existing typed path Mission."""
from __future__ import annotations

import math
from pathlib import Path
from uuid import uuid4

from actions.basic import yaw
from guidance.path_following import PATH_CLEARANCE_M, drive_reference
from mapping.grid import atomic_json
from planning.models import Pose2D
from .navigation_job import PlanningJob

TERMINAL = ("SUCCEEDED","FAILED","CANCELLED")


class GoalNavigation:
    def __init__(self, app, name, *, job_factory=PlanningJob):
        self.catalog = app.navigation_goals
        self.catalog.check(app.environment)
        if name not in self.catalog.goals:
            raise ValueError("unregistered navigation goal")
        self.goal = self.catalog.goals[name]
        self.destination = self.goal.resolve(app.environment)
        self.environment = app.environment.reference
        self.frame_epoch = app.vehicle.world_epoch
        self.source_generation = str(app.navigation.context.reference.version.generation_id)
        self.task_id = "navigation:"+uuid4().hex
        self.status = "PLANNING"
        self.error = None
        self.started_ns = app.vehicle.clock().monotonic_ns
        self.deadline_ns = self.started_ns+int(self.catalog.policy.total_timeout_s*1e9)
        self.child_id = None
        self.child_history = []
        self.job = None
        self.job_factory = job_factory
        self.pending_terminal = None
        self.attempt = 0
        self.retry_at_ns = None
        self.last_backend_directory = None
        self._start_plan(app)

    @property
    def active(self):
        return self.status not in TERMINAL

    def _check(self, app):
        self.catalog.check(app.environment)
        world, now = app.vehicle.world_snapshot(),app.vehicle.clock()
        nav = app.navigation
        if app.environment_fault or world is None or world.environment != self.environment or app.vehicle.world_epoch != self.frame_epoch:
            raise ValueError("navigation_environment_or_epoch_changed")
        if self.status == "RUNNING" and nav.view.error is not None:
            return world,now  # The child owns the observed Stop exit barrier.
        if nav.context is None or world.map != nav.context.reference or nav.binding is None:
            raise ValueError("navigation_map_unavailable")
        nav.context.check_fresh(now)
        if str(nav.context.reference.version.generation_id) != self.source_generation:
            raise ValueError("navigation_map_source_changed")
        loc = world.localization
        if loc is None or loc.twist is None or loc.pose.frame_id != "odom":
            raise ValueError("navigation_localization_unavailable")
        if any(not 0 <= now.elapsed_ns_since(value.captured_at) <= 500_000_000 for value in (loc.pose,loc.twist)):
            raise ValueError("navigation_localization_stale")
        return world,now

    def _start_plan(self, app):
        world,now = self._check(app)
        if world.vehicle.operation.armed or app.vehicle.authority.system_send or app.vehicle.authority.action_send:
            raise ValueError("planning requires a stopped disarmed vehicle and disabled SEND")
        twist = world.localization.twist.value
        if math.hypot(twist.linear.x,twist.linear.y) > .1 or abs(twist.angular.z) > .15:
            raise ValueError("planning requires observed stationary state")
        pose = world.localization.pose.value
        nav = app.navigation
        start = nav.binding.to_map(drive_reference(Pose2D(pose.position.x,pose.position.y,yaw(pose))))
        goal = nav.binding.to_map(self.destination)
        self.attempt += 1
        directory = nav.config.plan_path.parent/"navigation-jobs"/self.task_id.split(":")[1]/str(self.attempt)
        directory.mkdir(parents=True,exist_ok=False)
        self.job = self.job_factory(nav.context,start,goal,self.catalog.policy,PATH_CLEARANCE_M+self.catalog.policy.planning_reserve_m,directory)
        self.status = "PLANNING"
        app._emit("goal_planning_started",task_id=self.task_id,goal=self.goal.name,attempt=self.attempt,
                  directory=str(directory),source_sha256=nav.context.sha256)

    def _child(self, app):
        child = app._mission_status()
        return child if child is not None and child["task_id"] == self.child_id else None

    def cancel(self, app, *, error=None):
        if not self.active:return
        self.pending_terminal = "FAILED" if error else "CANCELLED"
        self.error = error
        self.status = "CANCELLING"
        if self.job:self.job.cancel()
        child = self._child(app)
        if child and child["status"] not in TERMINAL:
            app._cancel_child()

    def fail(self, app, reason):
        self.cancel(app,error=reason)

    def _finish(self, app, status, error=None):
        self.status,self.error = status,error
        app._emit("goal_navigation_finished",**self.view(app))

    def tick(self, app):
        if not self.active:return
        child = self._child(app)
        if self.status == "RUNNING" and child is not None and child["status"] in TERMINAL and self.pending_terminal is None:
            self.child_history.append({"task_id":child["task_id"],"status":child["status"],"error":child["error"]})
            recoverable = child["status"] == "FAILED" and str(child["error"]).startswith("navigation_path_blocked:")
            if recoverable and self.attempt <= self.catalog.policy.max_replans:
                try:
                    self._check(app)
                    if app.vehicle.clock().monotonic_ns >= self.deadline_ns:
                        raise ValueError("navigation_total_deadline_exceeded")
                    # The failed child has already completed its exit barrier
                    # and end_run. A separate typed recovery Mission must now
                    # observe Stop and Disarm before any new read-only job.
                    recovery = app.start_mission("safe_recovery",_navigation_child=True)
                    self.child_id = recovery["task_id"]
                    self.status = "RECOVERING"
                    app._emit("goal_recovery_started",task_id=self.task_id,child_id=self.child_id,attempt=self.attempt)
                except (OSError,ValueError,TypeError,RuntimeError) as exc:
                    self._finish(app,"FAILED",str(exc))
            else:
                self._finish(app,child["status"],child["error"])
            return
        if self.pending_terminal is None:
            try:
                self._check(app)
                if app.vehicle.clock().monotonic_ns > self.deadline_ns:
                    raise ValueError("navigation_total_deadline_exceeded")
            except (OSError,ValueError,TypeError) as exc:
                self.fail(app,str(exc))
        if self.pending_terminal is not None:
            child = self._child(app)
            if (self.job is None or self.job.done) and (child is None or child["status"] in TERMINAL):
                if self.job:self.job.close();self.job=None
                self._finish(app,self.pending_terminal,self.error)
            return
        if self.status == "RECOVERING":
            child = self._child(app)
            if child is None:
                self._finish(app,"FAILED","navigation_recovery_scope_missing")
            elif child["status"] in TERMINAL:
                self.child_history.append({"task_id":child["task_id"],"status":child["status"],"error":child["error"]})
                if child["status"] != "SUCCEEDED":
                    self._finish(app,"FAILED",child["error"] or "navigation_recovery_failed")
                else:
                    self.retry_at_ns = app.vehicle.clock().monotonic_ns+int(self.catalog.policy.retry_delay_s*1e9)
                    self.status = "RETRY_WAIT"
        elif self.status == "RETRY_WAIT":
            if app.vehicle.clock().monotonic_ns >= self.retry_at_ns:
                try:self._start_plan(app)
                except (OSError,ValueError,TypeError,RuntimeError) as exc:self._finish(app,"FAILED",str(exc))
        elif self.status == "PLANNING":
            if not self.job.done:return
            job,self.job = self.job,None
            try:
                result = job.result()
                self.last_backend_directory = None if job.backend.last_directory is None else str(job.backend.last_directory)
                job.close()
                self._check(app)
                expected = app.navigation.binding.to_map(self.destination)
                if math.hypot(result.request.goal.x-expected.x,result.request.goal.y-expected.y) > .1:
                    raise ValueError("navigation_goal_alignment_changed")
                atomic_json(app.navigation.config.plan_path,{"ok":True,"result":result.document(),
                    "evidence_directory":self.last_backend_directory})
                child = app.start_mission("follow_path",_navigation_child=True)
                self.child_id = child["task_id"]
                self.status = "RUNNING"
                app._emit("goal_path_started",task_id=self.task_id,child_id=self.child_id,
                          request_id=result.request.request_id,attempt=self.attempt)
            except (OSError,ValueError,TypeError,RuntimeError) as exc:
                job.close()
                self._finish(app,"FAILED",str(exc))
        elif self.status == "RUNNING":
            child = self._child(app)
            if child is None:
                self._finish(app,"FAILED","navigation_child_scope_missing")
            elif child["status"] in TERMINAL:
                self.child_history.append({"task_id":child["task_id"],"status":child["status"],"error":child["error"]})
                self._finish(app,child["status"],child["error"])

    def close(self, app):
        if self.job:
            self.job.close()
            self.job = None
        if self.active:self._finish(app,"CANCELLED","application_shutdown")

    def view(self, app):
        child = self._child(app)
        # Expose request/result history once. Duplicating it inside `child`
        # can exceed a Unix socket send window and starve the ROS TF probe.
        child_view = None if child is None else {k:v for k,v in child.items() if k not in ("effects","requests","stops")}
        return {"task_id":self.task_id,"mission":"navigate:"+self.goal.name,"status":self.status,
            "step": self.status.lower() if child is None else child["step"],"error":self.error,
            "goal":self.goal.name,"reference_point":self.goal.reference_point,
            "destination_odom":[self.destination.x,self.destination.y],"catalog_sha256":self.catalog.sha256,
            "frame_epoch":str(self.frame_epoch),"attempt":self.attempt,"deadline_ns":self.deadline_ns,
            "steps":[] if child is None else child["steps"],"child":child_view,"history":self.child_history,
            "configuration_sha256":self.catalog.sha256,"effects":{} if child is None else child["effects"],
            "requests":{} if child is None else child["requests"],"stops":{} if child is None else child["stops"],
            "backend_directory":self.last_backend_directory}
