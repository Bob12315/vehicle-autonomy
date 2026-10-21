#!/usr/bin/env bash
# Explicit RK3588/Jammy sidecar environment; never sources x86 Jazzy libraries.
set -eo pipefail
vaf_humble_root="${VAF_ROS2_HUMBLE_ROOT:-$HOME/vehicle-autonomy/ros2-humble/root}"
if [[ $(uname -m) != aarch64 ]]; then
    echo 'This isolated Humble wrapper requires the ARM64 board.' >&2
    exit 2
fi
source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 22.04 ]]; then
    echo 'This isolated Humble prefix requires Ubuntu 22.04.' >&2
    exit 2
fi
if [[ ! -f "$vaf_humble_root/opt/ros/humble/local_setup.bash" ]]; then
    echo 'Isolated ARM64 Humble prefix missing.' >&2
    exit 2
fi
export COLCON_CURRENT_PREFIX="$vaf_humble_root/opt/ros/humble"
source "$COLCON_CURRENT_PREFIX/local_setup.bash"
export LD_LIBRARY_PATH="$vaf_humble_root/usr/lib:$vaf_humble_root/usr/lib/aarch64-linux-gnu:$vaf_humble_root/usr/lib/aarch64-linux-gnu/blas:$vaf_humble_root/usr/lib/aarch64-linux-gnu/lapack:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$vaf_humble_root/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID="${VAF_ROS_DOMAIN_ID:-85}"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
exec "$@"
