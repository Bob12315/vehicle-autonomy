"""Download authenticated Jazzy packages into a user prefix (Ubuntu 24.04 amd64).

This does not install packages in the system or run maintainer scripts.
Normal /opt/ros/jazzy installations can be used instead; see docs/ros2_mapping.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


PACKAGES = ["ros-jazzy-slam-toolbox", "ros-jazzy-rclpy", "ros-jazzy-tf2-ros-py",
            "ros-jazzy-ros2cli", "ros-jazzy-ros2run", "ros-jazzy-ros2service",
            "ros-jazzy-ros2lifecycle", "ros-jazzy-ros-gz-bridge"]
ROS_KEY = "C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path.home()/".local/share/vehicle-autonomy/ros2-jazzy")
    parser.add_argument("--navigation", action="store_true", help="also extract the read-only Nav2 planner dependencies")
    args = parser.parse_args()
    if subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip() != "amd64" or 'VERSION_ID="24.04"' not in Path("/etc/os-release").read_text():
        parser.error("the audited local extraction requires Ubuntu 24.04 amd64")
    directory = args.directory.resolve()
    if (directory / "root/opt/ros/jazzy/local_setup.bash").exists() and not args.navigation:
        print(f"Existing local Jazzy tree retained: {directory}/root")
        return 0
    apt = directory / "apt"
    for relative in ("lists/partial", "archives/partial", "gnupg"):
        (apt / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
    key = apt / "ros.gpg"
    subprocess.run(["curl", "--connect-timeout", "10", "--max-time", "60", "-fsSL",
        "https://raw.githubusercontent.com/ros/rosdistro/master/ros.key", "-o", str(key)], check=True)
    keys = subprocess.check_output(["gpg", "--homedir", str(apt / "gnupg"), "--show-keys", "--with-colons", str(key)], text=True)
    fingerprints = [line.split(":")[9] for line in keys.splitlines() if line.startswith("fpr:")]
    if ROS_KEY not in fingerprints:
        raise RuntimeError("ROS signing key changed; inspect the official key rotation before continuing")
    sources = apt / "sources.list"
    sources.write_text(f"deb [signed-by={key}] https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu noble main\n" +
        "\n".join(f"deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] https://mirrors.tuna.tsinghua.edu.cn/ubuntu {suite} main universe restricted multiverse"
                    for suite in ("noble", "noble-updates", "noble-security")) + "\n")
    config = apt / "apt.conf"
    config.write_text(f'''Dir::Etc::sourcelist "{sources}";
Dir::Etc::sourceparts "-";
Dir::Etc::parts "-";
Dir::State::lists "{apt/'lists'}";
Dir::State::status "/var/lib/dpkg/status";
Dir::Cache::archives "{apt/'archives'}";
Dir::Cache::pkgcache "{apt/'pkgcache.bin'}";
Dir::Cache::srcpkgcache "{apt/'srcpkgcache.bin'}";
Debug::NoLocking "true";
APT::Sandbox::User "{os.environ['USER']}";
Acquire::Retries "2";
Acquire::https::Timeout "30";
Acquire::Languages "none";
''')
    subprocess.run(["apt-get", "-c", str(config), "update"], check=True)
    requested = PACKAGES + (["ros-jazzy-nav2-planner", "ros-jazzy-nav2-smac-planner", "ros-jazzy-nav2-msgs"] if args.navigation else [])
    subprocess.run(["apt-get", "-c", str(config), "--download-only", "--assume-yes",
                    "--no-install-recommends", "install", *requested], check=True)
    packages = []
    for archive in sorted((apt / "archives").glob("*.deb")):
        subprocess.run(["dpkg-deb", "--extract", str(archive), str(directory / "root")], check=True)
        packages.append({"file": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()})
    (directory / "manifest.json").write_text(json.dumps({"distribution": "jazzy", "key": ROS_KEY,
        "requested": requested, "packages": packages, "system_status": "/var/lib/dpkg/status"}, indent=2))
    print(f"Local ROS 2 environment prepared: {directory}/root")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
