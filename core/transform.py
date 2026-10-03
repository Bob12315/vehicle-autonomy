"""Frame graph for SI spatial values; no protocol coordinate conventions."""

from __future__ import annotations

from bisect import bisect_left
import math
from threading import RLock

from contracts.core.geometry import FrameId, Pose3, Quaternion, Transform3, Twist3, Vector3
from contracts.core.time import TimePoint


def _add(a: Vector3, b: Vector3) -> Vector3:
    return Vector3(a.x + b.x, a.y + b.y, a.z + b.z)


def _neg(a: Vector3) -> Vector3:
    return Vector3(-a.x, -a.y, -a.z)


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return Vector3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)


def _unit(x: float, y: float, z: float, w: float) -> Quaternion:
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    return Quaternion(x / norm, y / norm, z / norm, w / norm)


def _multiply(a: Quaternion, b: Quaternion) -> Quaternion:
    return _unit(
        a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
        a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
        a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
        a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
    )


def multiply_quaternions(a: Quaternion, b: Quaternion) -> Quaternion:
    """Compose unit rotations in x/y/z/w Hamilton order."""
    return _multiply(a, b)


def _rotate(q: Quaternion, v: Vector3) -> Vector3:
    axis = Vector3(q.x, q.y, q.z)
    t = _cross(axis, v)
    t = Vector3(2 * t.x, 2 * t.y, 2 * t.z)
    u = _cross(axis, t)
    return Vector3(v.x + q.w * t.x + u.x, v.y + q.w * t.y + u.y, v.z + q.w * t.z + u.z)


def rotate_vector(q: Quaternion, v: Vector3) -> Vector3:
    """Rotate a free vector without translation."""
    return _rotate(q, v)


def _inverse(value: Transform3) -> Transform3:
    inverse_rotation = Quaternion(-value.rotation.x, -value.rotation.y, -value.rotation.z, value.rotation.w)
    return Transform3(_neg(_rotate(inverse_rotation, value.translation)), inverse_rotation)


def _compose(first: Transform3, second: Transform3) -> Transform3:
    """Compose source->middle with middle->target."""
    return Transform3(
        _add(_rotate(second.rotation, first.translation), second.translation),
        _multiply(second.rotation, first.rotation),
    )


def _interpolate(first: Transform3, second: Transform3, ratio: float) -> Transform3:
    a, b = first.rotation, second.rotation
    dot = a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w
    if dot < 0:
        b = Quaternion(-b.x, -b.y, -b.z, -b.w)
        dot = -dot
    if dot > 0.9995:
        weights = (1 - ratio, ratio)
    else:
        angle = math.acos(max(-1.0, min(1.0, dot)))
        denominator = math.sin(angle)
        weights = (math.sin((1 - ratio) * angle) / denominator, math.sin(ratio * angle) / denominator)
    rotation = _unit(
        weights[0] * a.x + weights[1] * b.x,
        weights[0] * a.y + weights[1] * b.y,
        weights[0] * a.z + weights[1] * b.z,
        weights[0] * a.w + weights[1] * b.w,
    )
    translation = Vector3(
        first.translation.x + ratio * (second.translation.x - first.translation.x),
        first.translation.y + ratio * (second.translation.y - first.translation.y),
        first.translation.z + ratio * (second.translation.z - first.translation.z),
    )
    return Transform3(translation, rotation)


IDENTITY = Transform3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


class TransformTree:
    """One-path frame graph with bounded interpolation and no extrapolation."""

    def __init__(self, *, max_interpolation_gap_ns: int, max_dynamic_samples: int = 1024) -> None:
        if isinstance(max_interpolation_gap_ns, bool) or not isinstance(max_interpolation_gap_ns, int) or max_interpolation_gap_ns <= 0:
            raise ValueError("max_interpolation_gap_ns must be positive")
        if type(max_dynamic_samples) is not int or max_dynamic_samples < 2:
            raise ValueError("max_dynamic_samples must be at least two")
        self._capacity = max_dynamic_samples
        self._max_gap_ns = max_interpolation_gap_ns
        self._lock = RLock()
        self._static: dict[tuple[FrameId, FrameId], Transform3] = {}
        self._dynamic: dict[tuple[FrameId, FrameId], list[tuple[TimePoint, Transform3]]] = {}

    def _path(self, source: FrameId, target: FrameId) -> list[tuple[tuple[FrameId, FrameId], bool]] | None:
        if source == target:
            return []
        edges = set(self._static) | set(self._dynamic)
        queue: list[tuple[FrameId, list[tuple[tuple[FrameId, FrameId], bool]]]] = [(source, [])]
        seen = {source}
        for current, path in queue:
            for edge in edges:
                if edge[0] == current:
                    neighbor, forward = edge[1], True
                elif edge[1] == current:
                    neighbor, forward = edge[0], False
                else:
                    continue
                if neighbor in seen:
                    continue
                next_path = [*path, (edge, forward)]
                if neighbor == target:
                    return next_path
                seen.add(neighbor)
                queue.append((neighbor, next_path))
        return None

    @staticmethod
    def _edge(from_frame: FrameId, to_frame: FrameId) -> tuple[FrameId, FrameId]:
        source, target = FrameId(from_frame), FrameId(to_frame)
        if source == target:
            raise ValueError("transform frames must differ")
        return source, target

    def set_static(self, from_frame: FrameId, to_frame: FrameId, value: Transform3) -> None:
        edge = self._edge(from_frame, to_frame)
        if not isinstance(value, Transform3):
            raise TypeError("static transform must be Transform3")
        with self._lock:
            if self._path(*edge) is not None:
                raise ValueError("frame graph already connects these frames")
            self._static[edge] = value

    def add_dynamic(self, from_frame: FrameId, to_frame: FrameId, at_time: TimePoint, value: Transform3) -> None:
        edge = self._edge(from_frame, to_frame)
        if not isinstance(at_time, TimePoint) or not isinstance(value, Transform3):
            raise TypeError("dynamic transform requires TimePoint and Transform3")
        with self._lock:
            if edge not in self._dynamic:
                if self._path(*edge) is not None:
                    raise ValueError("frame graph already connects these frames")
                self._dynamic[edge] = []
            samples = self._dynamic[edge]
            if samples:
                if at_time.clock_domain_id != samples[0][0].clock_domain_id:
                    raise ValueError("dynamic samples must use one clock domain")
                if at_time <= samples[-1][0]:
                    raise ValueError("dynamic sample time must increase")
            samples.append((at_time, value))
            del samples[:-self._capacity]

    def _edge_at(self, edge: tuple[FrameId, FrameId], at_time: TimePoint) -> Transform3:
        static = self._static.get(edge)
        if static is not None:
            return static
        samples = self._dynamic[edge]
        if at_time.clock_domain_id != samples[0][0].clock_domain_id:
            raise ValueError("transform query uses a different clock domain")
        stamps = [stamp.monotonic_ns for stamp, _ in samples]
        index = bisect_left(stamps, at_time.monotonic_ns)
        if index < len(samples) and stamps[index] == at_time.monotonic_ns:
            return samples[index][1]
        if index == 0 or index == len(samples):
            raise LookupError("dynamic transform cannot be extrapolated")
        before, after = samples[index - 1], samples[index]
        gap = after[0].monotonic_ns - before[0].monotonic_ns
        if gap > self._max_gap_ns:
            raise LookupError("dynamic transform sample gap exceeds limit")
        return _interpolate(before[1], after[1], (at_time.monotonic_ns - before[0].monotonic_ns) / gap)

    def resolve(self, from_frame: FrameId, to_frame: FrameId, at_time: TimePoint) -> Transform3:
        if not isinstance(at_time, TimePoint):
            raise TypeError("at_time must be TimePoint")
        source, target = FrameId(from_frame), FrameId(to_frame)
        with self._lock:
            path = self._path(source, target)
            if path is None:
                raise LookupError(f"no transform from {source} to {target}")
            result = IDENTITY
            for edge, forward in path:
                step = self._edge_at(edge, at_time)
                result = _compose(result, step if forward else _inverse(step))
            return result

    def transform_point(self, value: Vector3, *, from_frame: FrameId, to_frame: FrameId, at_time: TimePoint) -> Vector3:
        if not isinstance(value, Vector3):
            raise TypeError("point must be Vector3")
        transform = self.resolve(from_frame, to_frame, at_time)
        return _add(_rotate(transform.rotation, value), transform.translation)

    def transform_vector(self, value: Vector3, *, from_frame: FrameId, to_frame: FrameId, at_time: TimePoint) -> Vector3:
        if not isinstance(value, Vector3):
            raise TypeError("vector must be Vector3")
        return _rotate(self.resolve(from_frame, to_frame, at_time).rotation, value)

    def transform_pose(self, value: Pose3, *, from_frame: FrameId, to_frame: FrameId, at_time: TimePoint) -> Pose3:
        if not isinstance(value, Pose3):
            raise TypeError("pose must be Pose3")
        transform = self.resolve(from_frame, to_frame, at_time)
        return Pose3(_add(_rotate(transform.rotation, value.position), transform.translation),
                     _multiply(transform.rotation, value.orientation))

    def transform_twist(self, value: Twist3, *, from_frame: FrameId, to_frame: FrameId, at_time: TimePoint) -> Twist3:
        if not isinstance(value, Twist3):
            raise TypeError("twist must be Twist3")
        transform = self.resolve(from_frame, to_frame, at_time)
        angular = _rotate(transform.rotation, value.angular)
        return Twist3(_add(_rotate(transform.rotation, value.linear), _cross(transform.translation, angular)), angular)

    def transform(self, value: Vector3 | Pose3 | Twist3, *, from_frame: FrameId, to_frame: FrameId, at_time: TimePoint):
        """Vector3 is a free vector here; use transform_point for a location."""
        if isinstance(value, Vector3):
            return self.transform_vector(value, from_frame=from_frame, to_frame=to_frame, at_time=at_time)
        if isinstance(value, Pose3):
            return self.transform_pose(value, from_frame=from_frame, to_frame=to_frame, at_time=at_time)
        if isinstance(value, Twist3):
            return self.transform_twist(value, from_frame=from_frame, to_frame=to_frame, at_time=at_time)
        raise TypeError("unsupported spatial value")
