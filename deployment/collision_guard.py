"""Optional rejection-only scan fence for the existing sole simulation writer.

Requires already transformed/admitted base_link observations. No source is
automatically installed and the hardware-read-only composition never uses a
command port. This is a conservative straight-forward qualification adapter,
not a replacement for footprint-aware turning or a hardware safety controller.
"""
from __future__ import annotations

from contracts.vehicle.command import StopMotionCommand, TwistTargetCommand
from perception.obstacles import CollisionMonitor


class ScanWriteGuard:
    def __init__(self, scan_reader, *, max_speed_mps=.15, previous=None):
        if type(max_speed_mps) not in (int,float) or not 0 < max_speed_mps <= .15:
            raise ValueError('explicit conservative speed ceiling required')
        self.reader, self.previous = scan_reader, previous
        self.max_speed_mps = max_speed_mps
        self.monitor = CollisionMonitor(frame='base_link')
        self.last_result = None

    def __call__(self, envelope, state, now):
        command = envelope.command
        if isinstance(command, StopMotionCommand):
            return None
        if self.previous is not None:
            reason = self.previous(envelope,state,now)
            if reason is not None:
                return reason
        if not isinstance(command,TwistTargetCommand) or command.frame_id!='base_link':
            return 'collision_guard_requires_body_twist'
        twist=command.target_twist
        if (twist.linear.x<0 or any(v!=0 for v in (twist.linear.y,twist.linear.z,
                                                 twist.angular.x,twist.angular.y,twist.angular.z))):
            return 'collision_guard_unqualified_reverse_or_turning'
        try:
            observation=self.reader()
            valid=state.reported_pose is not None and 0<=now.elapsed_ns_since(state.reported_pose.captured_at)<=300_000_000
            result=self.monitor.evaluate(observation,now,localization_valid=valid)
        except Exception as exc:
            return 'collision_guard_source_failure:'+type(exc).__name__
        self.last_result=result
        if not result['motion_allowed']:
            return 'collision_guard:'+result['reason']
        if twist.linear.x>self.max_speed_mps*result['speed_scale']:
            return 'collision_guard_speed_reduction_required'
        return None
