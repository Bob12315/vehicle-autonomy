# Standard Action contract

Generated from the same ActionRegistry used by API and Web. Physical confirmation is separate from command/mode adoption. The adjacent `action-catalog.json` exports per-vehicle schemas, TTLs, timeouts, resource and capability requirements.

| Action | Type | Vehicles | Success |
|---|---|---|---|
| Arm | OneShot | copter, plane, rover | Command COMPLETED plus authenticated post-request target state; mode adoption is not arrival. |
| AutoLand | Goal | plane | AutoLand: actual ground <0.25 m, speed <1 m/s settled 3 s and authenticated disarm. Other operations confirm configuration only; flight remains reserved. |
| Disarm | OneShot | copter, plane, rover | Command COMPLETED plus authenticated post-request target state; mode adoption is not arrival. |
| Drive | Continuous | rover | Continuous body setpoints until explicit cancel. Exit zeros the old stream, requests native HOLD and requires the existing observed stop barrier. New movement requires GUIDED again. |
| GetVehicleState | Query | copter, plane, rover | Read immutable world, including freshness; grants no authority. |
| Goto | Goal | copter, rover | Existing spatial arrival, stability and stop barriers; ACK is not arrival. |
| Hold | Continuous | copter | SetYaw: observed yaw within 0.1 rad settled 1 s; continuous operations require explicit cancellation. |
| Land | Goal | copter | Observed ground, disarm and stability; native ACK is insufficient. |
| Loiter | OneShot | plane | AutoLand: actual ground <0.25 m, speed <1 m/s settled 3 s and authenticated disarm. Other operations confirm configuration only; flight remains reserved. |
| RTL | Goal | copter, plane, rover | Plane: native RTL mode adoption, not arrival or landing. Rover/Copter: physical ReturnHome goal. |
| ReturnHome | Goal | copter, rover | Rover: actual home <=0.75 m, <=0.1 m/s settled 2 s, native HOLD exit. Copter: observed touchdown and disarmed. |
| SetGuidedTarget | OneShot | plane | AutoLand: actual ground <0.25 m, speed <1 m/s settled 3 s and authenticated disarm. Other operations confirm configuration only; flight remains reserved. |
| SetMode | OneShot | copter, plane, rover | Command COMPLETED plus authenticated post-request target state; mode adoption is not arrival. |
| SetVelocity | Continuous | copter | SetYaw: observed yaw within 0.1 rad settled 1 s; continuous operations require explicit cancellation. |
| SetYaw | Goal | copter | SetYaw: observed yaw within 0.1 rad settled 1 s; continuous operations require explicit cancellation. |
| Stop | Goal | rover | Observed stationary state plus completed stream stop barrier. |
| Takeoff | Goal | copter, plane | Copter: measured climb +/-0.35 m, settled 2 s. Plane: 50 +/-5 m and 8..28 m/s, settled 2 s; flight remains reserved. |
| Turn | Continuous | rover | Continuous body setpoints until explicit cancel. Exit zeros the old stream, requests native HOLD and requires the existing observed stop barrier. New movement requires GUIDED again. |

All writing Actions share target-scoped `vehicle.control` exclusivity. Queries use shared `vehicle.state`. Default SEND is false. Every write additionally requires an explicit live owned SITL proof, Action SEND, existing Authority/Lease, TTL, session/generation and Safety validation.

SetMode cannot invoke Rover RTL or Copter RTL/LAND: their native motion must use the corresponding Goal Action. Plane TAKEOFF/AUTOLAND also require their Goal wrappers. Plane Loiter/RTL/Guided configuration retains the physical flight reservation. Disarm requires a signed stationary ground reference.

A successful airborne Plane native Action retains its safety reservation. A new Action requires explicit `continuation_of` and a new SEND authorization. Existing Execution performs LOITER recovery, fences old queued work, revokes authority and closes the old link; only completed authenticated recovery, fresh read-only airborne state with global fix, and explicit new grant permit continuation. Cancelled, failed or UNKNOWN actions cannot use this path. Plane cancellation remains UNCONFIRMED; no zero velocity or airborne Disarm is used.

Copter/Rover motion Actions compose the existing basic Action spatial and stop barriers. Rover continuous exit additionally requests the audited native HOLD after its stream stop; the next move requires GUIDED. Continuous operations cannot silently succeed when a provider ends. The independent owner thread cycles safety without HTTP clients. Timed-out or exceptional exits do not release hazardous claims. Cleanup ingress permits only stopping/recovery effects.

Metadata JSON and parameter/output schemas are served by `/api/actions?target=TARGET`. The final round report records actual per-Action test results; this generated catalog alone is not execution evidence.
