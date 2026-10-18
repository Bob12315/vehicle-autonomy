#!/usr/bin/env bash
# Optional ROS environment for an external process; the framework stays ROS-free.
set -eo pipefail
vaf_local_root="${VAF_ROS2_ROOT:-$HOME/.local/share/vehicle-autonomy/ros2-jazzy/root}"
if [[ -f /opt/ros/jazzy/setup.bash && -z "${VAF_ROS2_ROOT:-}" ]]; then
    source /opt/ros/jazzy/setup.bash
elif [[ -f "$vaf_local_root/opt/ros/jazzy/local_setup.bash" ]]; then
    export COLCON_CURRENT_PREFIX="$vaf_local_root/opt/ros/jazzy"
    source "$COLCON_CURRENT_PREFIX/local_setup.bash"
    export LD_LIBRARY_PATH="$vaf_local_root/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
    export PYTHONPATH="$vaf_local_root/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
else
    echo 'ROS 2 Jazzy was not found; install the optional mapping dependencies.' >&2
    exit 2
fi
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-LOCALHOST}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
exec "$@"
