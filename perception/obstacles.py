"""Rejection-only near-field recommendation; never claims physical stopping."""
from __future__ import annotations

import math

from contracts.core.quality import QualityState
from sensors.lidar.scan import PlanarScan


class CollisionMonitor:
    def __init__(self, *, frame='base_link', stop_m=.6, slowdown_m=1.5, max_age_ns=300_000_000):
        if not 0 < stop_m < slowdown_m or max_age_ns <= 0:
            raise ValueError('invalid collision monitor thresholds')
        self.frame, self.stop_m, self.slowdown_m, self.max_age_ns = frame, stop_m, slowdown_m, max_age_ns

    def evaluate(self, observation, now, *, localization_valid):
        reason, scale, nearest = None, 1., None
        if not localization_valid:
            reason = 'localization_unavailable'
        elif observation is None:
            reason = 'scan_unavailable'
        elif observation.frame_id != self.frame or observation.quality is not QualityState.VALID:
            reason = 'scan_frame_or_quality'
        elif not isinstance(observation.data, PlanarScan):
            reason = 'scan_type'
        else:
            try:
                age = now.elapsed_ns_since(observation.captured_at)
                if not 0 <= age <= self.max_age_ns:
                    reason = 'scan_stale_or_future'
            except ValueError:
                reason = 'scan_clock_domain'
            if reason is None:
                scan = observation.data
                forward = [r for i, r in enumerate(scan.ranges)
                           if abs(scan.angle_min + i * scan.angle_increment) <= math.pi / 4]
                if not forward or any(r is None for r in forward):
                    reason = 'forward_coverage_unknown'
                elif any(not math.isfinite(r) or r < scan.range_min or r > scan.range_max for r in forward):
                    reason = 'invalid_forward_range'
                else:
                    nearest = min(forward)
                    if nearest <= self.stop_m:
                        reason = 'near_obstacle'
                    elif nearest < self.slowdown_m:
                        scale = (nearest - self.stop_m) / (self.slowdown_m - self.stop_m)
        return {'motion_allowed': reason is None, 'speed_scale': 0. if reason else scale,
                'reason': reason, 'nearest_m': nearest, 'physical_stop': 'UNCONFIRMED',
                'scope': 'diagnostic recommendation; requires admitted Execution guard integration'}
