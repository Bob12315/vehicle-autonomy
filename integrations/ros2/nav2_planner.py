"""Owned, isolated Nav2 subprocess adapter. Imports no ROS in the caller."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from contracts.core.geometry import Pose3, Quaternion, Vector3
from mapping.grid import MapStore, atomic_json
from planning.models import PathCandidate, PlanningError, Pose2D

ROOT = Path(__file__).resolve().parents[2]


class Nav2Planner:
    name = "nav2.SmacPlanner2D.jazzy"

    def __init__(self, evidence_directory=None, *, cancelled=None):
        self.evidence_directory = None if evidence_directory is None else Path(evidence_directory)
        self.last_directory = None
        self.cancelled = cancelled or (lambda: False)

    def compute(self, request, configuration_grid):
        if self.evidence_directory is None:
            with TemporaryDirectory(prefix="vaf-nav2-") as temporary:
                return self._compute(request, configuration_grid, Path(temporary))
        directory = self.evidence_directory / request.request_id
        directory.mkdir(parents=True, exist_ok=False)
        self.last_directory = directory
        return self._compute(request, configuration_grid, directory)

    def _compute(self, request, grid, directory):
        directory = directory.resolve()
        identity = Pose3(Vector3(0,0,0), Quaternion(0,0,0,1))
        grid = replace(grid, frame_id="planning_grid", origin=identity)
        digest = MapStore(directory / "maps").save(grid)
        start, goal = request.context.to_local(request.start), request.context.to_local(request.goal)
        data = {"schema": 1, "request_id": request.request_id, "map_sha256": request.context.sha256,
            "frame_epoch": request.context.frame_epoch, "grid_sha256": digest,
            "deadline_ns": request.deadline_ns, "start": [start.x,start.y,start.yaw],
            "goal": [goal.x,goal.y,goal.yaw]}
        atomic_json(directory / "request.json", data)
        env = os.environ.copy()
        env["ROS_DOMAIN_ID"] = str(100+int(request.request_id[:8],16)%100)
        env["ROS_AUTOMATIC_DISCOVERY_RANGE"] = "LOCALHOST"
        command = [str(ROOT/"scripts/with_ros2.sh"), sys.executable, "-m", "integrations.ros2.nav2_worker", str(directory)]
        started = time.monotonic_ns()
        sources = ("planning/models.py", "planning/collision.py", "application/planning.py", "app/plan.py",
                   "integrations/ros2/nav2_planner.py", "integrations/ros2/nav2_worker.py", "scripts/with_ros2.sh")
        source_hashes = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}
        timed_out = False
        cancelled = False
        with (directory / "worker.log").open("wb") as log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while process.poll() is None:
                    if self.cancelled():
                        cancelled = True
                        break
                    remaining = (request.deadline_ns-time.monotonic_ns())/1e9
                    if remaining <= 0:
                        timed_out = True
                        break
                    try:process.wait(timeout=min(.05,remaining))
                    except subprocess.TimeoutExpired:pass
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                # The worker's native planner inherits its process group.
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait(timeout=2)
                cleaned = False
                # A killed worker may exit before its native child finishes
                # ROS shutdown. Wait for the entire owned group, not just PID.
                for grace, sig in ((2.,signal.SIGTERM),(1.,signal.SIGKILL)):
                    try:os.killpg(process.pid,sig)
                    except ProcessLookupError:
                        cleaned = True
                        break
                    until = time.monotonic()+grace
                    while time.monotonic()<until:
                        try:os.killpg(process.pid,0)
                        except ProcessLookupError:
                            cleaned = True
                            break
                        time.sleep(.02)
                    if cleaned:break
        atomic_json(directory / "manifest.json", {"command":command,"pid":process.pid,"pgid":process.pid,
            "returncode":process.returncode,"process_group_released":cleaned,"timed_out":timed_out,"cancelled":cancelled,
            "ros_domain_id":env["ROS_DOMAIN_ID"],"started_ns":started,"ended_ns":time.monotonic_ns(),
            "source_map_sha256":request.context.sha256,"configuration_grid_sha256":digest,"source_files_sha256":source_hashes})
        if not cleaned:
            raise PlanningError("BACKEND_FAILURE", "owned Nav2 process group not fully released")
        if cancelled:
            raise PlanningError("CANCELLED", "Nav2 request cancelled; owned group released")
        if timed_out:
            raise PlanningError("TIMEOUT", "Nav2 subprocess exceeded the request deadline")
        path = directory / "response.json"
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise PlanningError("BACKEND_FAILURE", "Nav2 returned no bounded response; inspect worker.log")
        result = json.loads(path.read_text())
        if process.returncode or not result.get("ok"):
            raise PlanningError(result.get("code","BACKEND_FAILURE"), result.get("error","Nav2 worker failed"))
        if result.get("request_id") != request.request_id or result.get("map_sha256") != request.context.sha256 or result.get("frame_epoch") != request.context.frame_epoch:
            raise PlanningError("INVALID_PATH", "Nav2 worker response identity mismatch")
        points = result.get("poses")
        if type(points) is not list or not 1 <= len(points) <= 8192:
            raise PlanningError("INVALID_PATH", "Nav2 response exceeds path size bounds")
        poses = tuple(request.context.to_world(Pose2D(*p)) for p in points)
        return PathCandidate(request.request_id, request.context.sha256, request.context.frame_epoch, request.context.grid.frame_id, poses)
