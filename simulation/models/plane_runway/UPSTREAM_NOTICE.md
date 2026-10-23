# Upstream model attribution

The Zephyr and ArduPilot plugin SDF portions derive from
https://github.com/ArduPilot/ardupilot_gazebo at
3ec51428fd43deb7b71137192ba16394b450d78e.
Upstream Zephyr authors: Cole Biesemeyer and Nate Koenig (model.config).
The upstream project supplies GNU LGPL v3 (LICENSE.md); the license is retained
as LGPL-3.0.txt. Meshes are referenced from the installed, unchanged upstream
Gazebo resource path and are not copied here.

Local modifications: flatten the two SDF wrappers into one portable fixture,
add three free-rolling physical wheels and wheel axle damping. Aerodynamic and
ArduPilot actuator plugins retain the upstream model's coefficients/mappings.
The accompanying world starts level on wheels on a marked flat runway; no
throw, artificial launch force, pose teleport or built-in SITL physics replaces
Gazebo. This is a simulation fixture, not a validated real airframe model.
