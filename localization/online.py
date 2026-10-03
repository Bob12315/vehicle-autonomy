"""Telemetry-only localization and bounded transform publication cut."""
from uuid import uuid4
from contracts.core.geometry import Transform3
from contracts.core.quality import QualityState
from contracts.world.models import ResourceDependency
from core.transform import TransformTree
from .reported import ReportedPoseLocalization


class OnlineLocalization:
    def __init__(self, max_age_ns):
        self.max_age_ns = max_age_ns
        self.projector = ReportedPoseLocalization()
        self.tree = self._new_tree()
        self.epoch = uuid4().hex
        self.last = None
        self.source_version = None

    def _new_tree(self):
        return TransformTree(max_interpolation_gap_ns=self.max_age_ns)

    def update(self, state, now):
        estimate = self.projector.estimate(state)
        self.source_version = None
        if estimate is None or estimate.quality is not QualityState.VALID or estimate.pose.frame_id != "odom":
            return None, None
        stamps = [estimate.published_at, estimate.pose.captured_at]
        if estimate.twist is not None:
            if estimate.twist.frame_id != "odom":
                return None, None
            stamps.append(estimate.twist.captured_at)
        try:
            if any(not 0 <= now.elapsed_ns_since(stamp) <= self.max_age_ns for stamp in stamps):
                return None, None
        except ValueError:
            return None, None
        pose = estimate.pose
        value = Transform3(pose.value.position, pose.value.orientation)
        if self.last is not None:
            previous_time, previous_value = self.last
            if pose.captured_at.clock_domain_id != previous_time.clock_domain_id or pose.captured_at < previous_time:
                raise ValueError("transform source time regressed or changed domain")
            if pose.captured_at == previous_time and value != previous_value:
                # Composite telemetry may update orientation under the conservative
                # position/attitude timestamp. Start a new cut, never rewrite history.
                self.tree = self._new_tree()
                self.epoch = uuid4().hex
                self.last = None
        if self.last is None or pose.captured_at != self.last[0]:
            # A reported pose maps a base_link point INTO odom. Inverse queries
            # provide odom -> base_link; the names alone imply no identity map edge.
            self.tree.add_dynamic("base_link", "odom", pose.captured_at, value)
            self.last = pose.captured_at, value
        self.source_version = state.version
        dependency = ResourceDependency("Transform", f"reported:{self.epoch}", state.version)
        return estimate, dependency
