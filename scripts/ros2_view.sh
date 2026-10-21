#!/usr/bin/env bash
# Display only: no Nav2 lifecycle changes, goal publication, TF invention or vehicle I/O.
set -euo pipefail
cd "$(dirname "$0")/.."
view_mode="${1:-lidar}"
case "$view_mode" in
  lidar) view_config=config/rviz/rs16-readonly.rviz ;;
  navigation) view_config=config/rviz/navigation-readonly.rviz ;;
  *) echo 'Usage: ros2_view.sh [lidar|navigation] [--check]' >&2; exit 2 ;;
esac
if [[ $# -gt 2 || ( $# -eq 2 && "$2" != --check ) ]]; then
  echo 'Only --check is accepted after the view name.' >&2; exit 2
fi
case "$(uname -m)" in
  aarch64)
    view_wrapper=./scripts/with_ros2_humble.sh
    view_qt_prefix="${VAF_ROS2_HUMBLE_ROOT:-$HOME/vehicle-autonomy/ros2-humble/root}/usr/lib/aarch64-linux-gnu/qt5/plugins" ;;
  x86_64)
    view_wrapper=./scripts/with_ros2.sh
    view_qt_prefix="${VAF_ROS2_ROOT:-$HOME/.local/share/vehicle-autonomy/ros2-jazzy/root}/usr/lib/x86_64-linux-gnu/qt5/plugins" ;;
  *) echo 'No reviewed ROS wrapper for this architecture.' >&2; exit 2 ;;
esac
if [[ -d "$view_qt_prefix/platforms" ]]; then
  export QT_PLUGIN_PATH="$view_qt_prefix${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
  export QT_QPA_PLATFORM_PLUGIN_PATH="$view_qt_prefix/platforms"
fi
if [[ "${2:-}" == --check ]]; then
  export QT_QPA_PLATFORM=offscreen
  exec "$view_wrapper" ros2 run rviz2 rviz2 --help
fi
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo 'RViz2 requires a graphical session. Use a ROS desktop or explicit SSH X11 forwarding.' >&2
  exit 2
fi
exec "$view_wrapper" ros2 run rviz2 rviz2 -d "$view_config"
