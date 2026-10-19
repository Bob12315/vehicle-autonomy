# Native boundary overlay notices

The optional overlay is built against the operator's installed SLAM Toolbox **2.8.5**, upstream revision `ec8f7635dea317b531c419f798f87d90a336f32e`.

- [Upstream package](https://github.com/SteveMacenski/slam_toolbox/tree/ec8f7635dea317b531c419f798f87d90a336f32e) declares LGPL. Its root license is preserved in `SLAM_TOOLBOX_LICENSE` (LGPL 2.1).
- Karto SDK headers retain their copyright **2010 SRI International** and **LGPL 3 or later** notices. Its license is preserved in `KARTO_SDK_LICENSE`; `GPL-3` supplies the incorporated GPL terms.
- Upstream `src/slam_mapper.cpp` credits Simbe Robotics / Steve Macenski (2018) and Samsung Research America (2019); it also carries a generic Creative Commons notice. Preserve those upstream notices when redistributing their source. This repository's overlay defines only the exported method that invokes the existing SDK API, with a one-time execution marker.
- Installed headers are copied to a local build directory with their notices intact. The only SDK modification changes the two dimension expressions in `OccupancyGrid::ComputeDimensions` from rounded extents to inclusive `ceil(extent / resolution) + 1`. Build manifests record the original/patched header hashes, overlay sources and runtime library hashes. No installed ROS files are replaced.

Rebuildable source is provided; no precompiled overlay or copied SDK header is committed here. The counterexample and builder are under `integrations/ros2/`. This overlay is optional and applies only to an explicitly selected SLAM subprocess.
