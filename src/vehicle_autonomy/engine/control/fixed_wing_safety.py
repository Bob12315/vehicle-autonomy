"""Conventional fixed-wing simulation admission and final-write conditions."""
import math
from dataclasses import replace
from vehicle_autonomy.contracts.effects.vehicle import (ArmEffect, DisarmEffect, ModeEffect, FixedWingTargetEffect,
    PoseTargetEffect, TwistTargetEffect, StopMotionEffect, TakeoffEffect, LandEffect)
from vehicle_autonomy.engine.control.vehicle_safety import VehicleSafetyPolicy


class PlaneSimulationSafetyPolicy(VehicleSafetyPolicy):
    def state_reason(self, vehicle, now):
        if vehicle is None or vehicle.reported_pose is None or vehicle.reported_twist is None:
            return 'plane_motion_state_unavailable'
        for sample in (vehicle.reported_pose, vehicle.reported_twist):
            try:
                if not 0 <= now.elapsed_ns_since(sample.captured_at) <= self.limits.max_snapshot_age_ns:
                    return 'plane_motion_state_stale'
            except ValueError:
                return 'plane_motion_clock_domain_mismatch'
        p = vehicle.reported_pose.value.position
        v = vehicle.reported_twist.value.linear
        speed = math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)
        if not (self.limits.min_x_m <= p.x <= self.limits.max_x_m
                and self.limits.min_y_m <= p.y <= self.limits.max_y_m
                and self.limits.min_altitude_m <= p.z <= self.limits.max_altitude_m and speed <= self.limits.max_linear_mps
                and math.hypot(p.x,p.y) <= min(self.limits.max_x_m,self.limits.max_y_m)):
            return 'plane_state_outside_envelope'
        return None

    def evaluate(self, envelope, world, now):
        effect = envelope.effect
        selected = replace(envelope, effect=ModeEffect("GUIDED")) if isinstance(effect, FixedWingTargetEffect) else envelope
        reason = super().evaluate(selected, world, now)
        if reason is not None:
            return reason
        if isinstance(effect, (PoseTargetEffect, TwistTargetEffect, StopMotionEffect, TakeoffEffect, LandEffect)):
            return 'plane_requires_native_modes_not_hover_or_zero_velocity'
        vehicle = world.vehicle
        reason = self.state_reason(vehicle, now)
        if reason is not None:
            return reason
        p = vehicle.reported_pose.value.position
        v = vehicle.reported_twist.value.linear
        speed = math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)
        ground = abs(p.z) <= 1.5 and speed <= 1.0
        if isinstance(effect, (ArmEffect, DisarmEffect)) and not ground:
            return 'plane_arm_disarm_requires_stationary_ground'
        if isinstance(effect, FixedWingTargetEffect):
            if not vehicle.operation.armed or p.z < 10:
                return 'plane_navigation_requires_airborne'
            sample = vehicle.global_position
            if sample is None:
                return 'plane_global_fix_unavailable'
            try:
                if not 0 <= now.elapsed_ns_since(sample.captured_at) <= self.limits.max_snapshot_age_ns:
                    return 'plane_global_fix_stale'
            except ValueError:
                return 'plane_global_clock_domain_mismatch'
            current = sample.value; target = effect.center
            north = math.radians(target.latitude_deg-current.latitude_deg)*6378137.
            east = math.radians(target.longitude_deg-current.longitude_deg)*6378137.*math.cos(math.radians(current.latitude_deg))
            altitude = p.z+target.altitude_m-current.altitude_m
            if not (self.limits.min_x_m+200 <= p.x+east <= self.limits.max_x_m-200
                    and self.limits.min_y_m+200 <= p.y+north <= self.limits.max_y_m-200
                    and 20 <= altitude <= self.limits.max_altitude_m-10
                    and math.hypot(p.x+east,p.y+north) <= min(self.limits.max_x_m,self.limits.max_y_m)-200):
                return 'plane_native_target_outside_geofence'
        if isinstance(effect, ModeEffect):
            if effect.native_mode == 'MANUAL' and (not ground or vehicle.operation.armed):
                return 'plane_manual_requires_disarmed_ground'
            if effect.native_mode == 'TAKEOFF' and (not ground or not vehicle.operation.armed):
                return 'plane_takeoff_requires_armed_ground'
            if effect.native_mode in ('AUTOLAND', 'LOITER', 'RTL', 'GUIDED') and (
                    not vehicle.operation.armed or p.z < 10):
                return 'plane_navigation_requires_airborne'
        return None
