#!/usr/bin/env bash
# No install, no privileged writes. Caller supplies a reviewed official checkout.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -ne 2 ]]; then
  echo 'Usage: build_rs16_adapter.sh /official/rs_driver /new/output-directory' >&2
  exit 2
fi
sdk_root=$(realpath "$1")
adapter_output=$(realpath -m "$2")
sdk_sha=$(git -C "$sdk_root" rev-parse HEAD)
if [[ "$sdk_sha" != 897b14d3bdb6186a75df27ba51b65b5bd5557723 ]]; then
  echo 'Unsupported rs_driver source revision; review before updating the pin' >&2
  exit 2
fi
mkdir -m 700 -p "$adapter_output"
rs16_flags=(-DDISABLE_PCAP_PARSE)
rs16_libs=()
if [[ -n "${VAF_RS16_PCAP_PREFIX:-}" ]]; then
  rs16_flags=(-I "$VAF_RS16_PCAP_PREFIX/usr/include")
  rs16_libs=(-L "$VAF_RS16_PCAP_PREFIX/usr/lib/aarch64-linux-gnu" -lpcap)
elif command -v pkg-config >/dev/null && pkg-config --exists libpcap; then
  rs16_flags=()
  rs16_libs=(-lpcap)
fi
g++ -std=c++14 -O2 -pthread "${rs16_flags[@]}" -I "$sdk_root/src" \
  integrations/robosense/rs16_capture.cpp "${rs16_libs[@]}" -o "$adapter_output/rs16_capture"
cp "$sdk_root/LICENSE" "$adapter_output/RS_DRIVER_LICENSE"
printf '%s\n' "$sdk_sha" > "$adapter_output/sdk-commit.txt"
sha256sum "$adapter_output/rs16_capture" > "$adapter_output/binary.sha256"
