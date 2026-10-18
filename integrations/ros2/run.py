"""Exec an installed ROS executable without leaving a ros2-run parent process."""
import os
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 3 or any(Path(v).name != v for v in sys.argv[1:3]):
        raise SystemExit("usage: python -m integrations.ros2.run PACKAGE EXECUTABLE [ARGS...]")
    from ament_index_python.packages import get_package_prefix
    package, executable = sys.argv[1:3]
    path = Path(get_package_prefix(package)) / "lib" / package / executable
    os.execv(path, [str(path), *sys.argv[3:]])


if __name__ == "__main__":
    main()
