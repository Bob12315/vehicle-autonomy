"""Read-only Gazebo pose truth for simulation acceptance tests only."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from threading import Condition
import time

from gz.msgs10.pose_v_pb2 import Pose_V
from gz.transport13 import Node


@dataclass(frozen=True, slots=True)
class TruthSample:
    model: str
    host_received_ns: int
    simulation_ns: int
    x_m: float
    y_m: float
    z_m: float
    yaw_rad: float


class GazeboTruthOracle:
    """Subscribe to pose telemetry; never publish or call Gazebo services."""

    def __init__(self, world: str, model: str, *, history_size: int = 1000) -> None:
        if not world or not model or history_size < 2:
            raise ValueError("world, model and history size are required")
        self.world = world
        self.model = model
        self.topic = f"/world/{world}/pose/info"
        self._condition = Condition()
        self._samples: deque[TruthSample] = deque(maxlen=history_size)
        self._error: str | None = None
        self._node = Node()
        if not self._node.subscribe(Pose_V, self.topic, self._ingest):
            raise RuntimeError(f"Gazebo pose subscription failed: {self.topic}")

    def _ingest(self, message: Pose_V) -> None:
        received = time.monotonic_ns()
        stamp = message.header.stamp
        sim_ns = stamp.sec * 1_000_000_000 + stamp.nsec
        target = next((pose for pose in message.pose if pose.name == self.model), None)
        if target is None:
            with self._condition:
                self._error = f"model {self.model} missing from {self.topic}"
                self._condition.notify_all()
            return
        q = target.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y),
                         1 - 2 * (q.y * q.y + q.z * q.z))
        sample = TruthSample(self.model, received, sim_ns,
                             target.position.x, target.position.y, target.position.z, yaw)
        with self._condition:
            if self._samples and sim_ns < self._samples[-1].simulation_ns:
                self._error = "Gazebo simulation time regressed"
            else:
                self._samples.append(sample)
            self._condition.notify_all()

    def latest(self) -> TruthSample | None:
        with self._condition:
            if self._error:
                raise RuntimeError(self._error)
            return None if not self._samples else self._samples[-1]

    def wait_new(self, *, after_host_ns: int, timeout_s: float) -> TruthSample:
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while True:
                if self._error:
                    raise RuntimeError(self._error)
                if self._samples and self._samples[-1].host_received_ns > after_host_ns:
                    return self._samples[-1]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"new Gazebo truth unavailable on {self.topic}")
                self._condition.wait(remaining)

    def recent_speed_mps(self, *, window_sim_s: float = 0.5) -> float | None:
        if window_sim_s <= 0:
            raise ValueError("speed window must be positive")
        with self._condition:
            if self._error:
                raise RuntimeError(self._error)
            if len(self._samples) < 2:
                return None
            newest = self._samples[-1]
            older = next((sample for sample in reversed(self._samples)
                          if newest.simulation_ns - sample.simulation_ns >= window_sim_s * 1e9), None)
            if older is None:
                return None
            elapsed = (newest.simulation_ns - older.simulation_ns) / 1e9
            return math.hypot(newest.x_m - older.x_m, newest.y_m - older.y_m) / elapsed

    def recent_vertical_speed_mps(self, *, window_sim_s: float = 0.5) -> float | None:
        if window_sim_s <= 0:
            raise ValueError("speed window must be positive")
        with self._condition:
            if self._error:
                raise RuntimeError(self._error)
            if len(self._samples) < 2:
                return None
            newest = self._samples[-1]
            older = next((sample for sample in reversed(self._samples)
                          if newest.simulation_ns - sample.simulation_ns >= window_sim_s * 1e9), None)
            if older is None:
                return None
            elapsed = (newest.simulation_ns - older.simulation_ns) / 1e9
            return (newest.z_m - older.z_m) / elapsed

    def recent_velocity_enu(self, *, window_sim_s: float = 0.5) -> tuple[float, float, float] | None:
        if window_sim_s <= 0:
            raise ValueError("speed window must be positive")
        with self._condition:
            if self._error:
                raise RuntimeError(self._error)
            if len(self._samples) < 2:
                return None
            newest = self._samples[-1]
            older = next((sample for sample in reversed(self._samples)
                          if newest.simulation_ns - sample.simulation_ns >= window_sim_s * 1e9), None)
            if older is None:
                return None
            elapsed = (newest.simulation_ns - older.simulation_ns) / 1e9
            return ((newest.x_m - older.x_m) / elapsed,
                    (newest.y_m - older.y_m) / elapsed,
                    (newest.z_m - older.z_m) / elapsed)

    def recent_yaw_rate_rad_s(self, *, window_sim_s: float = 0.5) -> float | None:
        if window_sim_s <= 0:
            raise ValueError("yaw window must be positive")
        with self._condition:
            if self._error:
                raise RuntimeError(self._error)
            if len(self._samples) < 2:
                return None
            newest = self._samples[-1]
            older = next((sample for sample in reversed(self._samples)
                          if newest.simulation_ns - sample.simulation_ns >= window_sim_s * 1e9), None)
            if older is None:
                return None
            delta = math.atan2(math.sin(newest.yaw_rad - older.yaw_rad),
                               math.cos(newest.yaw_rad - older.yaw_rad))
            return delta / ((newest.simulation_ns - older.simulation_ns) / 1e9)
