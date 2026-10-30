#!/usr/bin/env bash
# Explicit RK3588/Jammy sidecar environment; never sources x86 Jazzy libraries.
set -eo pipefail
if [[ $(uname -m) != aarch64 ]]; then
    echo 'This isolated Humble wrapper requires the ARM64 board.' >&2
    exit 2
fi
source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 22.04 ]]; then
    echo 'This isolated Humble prefix requires Ubuntu 22.04.' >&2
    exit 2
fi
vaf_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
vaf_python="${VAF_PYTHON:-$vaf_root/.venv/bin/python}"
if [[ ! -x "$vaf_python" && -z "${VAF_PYTHON:-}" ]]; then vaf_python=python3; fi
export ROS_LOCALHOST_ONLY=1
export ROS_DOMAIN_ID="${VAF_ROS_DOMAIN_ID:-85}"
exec "$vaf_python" -m vehicle_autonomy.app.bootstrap.host_environment ros --distribution humble -- "$@"
