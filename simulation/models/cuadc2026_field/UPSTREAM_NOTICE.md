# CUADC scene/model provenance

The CUADC2026 field, fixed-down Iris/gimbal recipe and water-bottle model were
supplied by the user from their existing CUADC Gazebo workspace. Only SDF,
model metadata and the source mission recipe were migrated; no old Python
control, MAVLink bridge or application implementation is imported.

The Iris and gimbal mesh dependencies remain in the separately configured
ArduPilot Gazebo installation. The copied fixed-down gimbal SDF references
that installation's `gimbal_small_3d/meshes`; the byte-identical mesh copies
were intentionally not redistributed in this checkout. Their source hashes
are recorded by the vehicle registry and migration manifest. Consult the
external project's individual license notices; this migration does not grant
additional redistribution rights or infer ownership of the supplied assets.

The standalone source world is retained verbatim. The registered scene uses
a separate vehicle-free derivative: the original field markings, target
links and collisions are preserved, while the infinite collision plane is
replaced with a reviewed finite 160 x 160 m flat ground, and the embedded
vehicle and reference axes are removed. Vehicle instances are separately
owned by the existing simulation runtime.
