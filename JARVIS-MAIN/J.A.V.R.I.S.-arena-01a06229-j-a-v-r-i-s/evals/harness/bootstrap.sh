#!/bin/sh
# Ensure python3 exists in a fresh distro container (idempotent).
set -eu
if command -v python3 >/dev/null 2>&1; then
    echo "python3 already present: $(python3 --version 2>&1)"
    exit 0
fi
echo "bootstrapping python3..."
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y --no-install-recommends python3 >/dev/null
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 >/dev/null
elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm --needed python >/dev/null
elif command -v apk >/dev/null 2>&1; then
    # htop lives in the community repo; enable it if commented out.
    sed -i 's|^#\(.*/community\)$|\1|' /etc/apk/repositories 2>/dev/null || true
    apk add --no-cache python3 >/dev/null
elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive install python3 >/dev/null
else
    echo "no supported package manager found; cannot bootstrap python3" >&2
    exit 1
fi
echo "bootstrapped: $(python3 --version 2>&1)"
