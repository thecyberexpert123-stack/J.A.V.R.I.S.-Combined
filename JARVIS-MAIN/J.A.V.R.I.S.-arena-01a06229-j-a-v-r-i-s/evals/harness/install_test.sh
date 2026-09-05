#!/bin/sh
# Install-test harness: runs INSIDE a Tier-1 distro container (ADR-0011).
# Installs the packaging artifact native to the distro from /repo/dist,
# smoke-tests the CLI, prints an eval-annotation-compatible PASS/FAIL line.
#
# Usage: install_test.sh <distro-name>   (debian-12|ubuntu-24.04|fedora|arch|alpine)
set -u

DISTRO="${1:?usage: install_test.sh <distro-name>}"
DIST="/repo/dist"
STATE_DIR="${JARVIS_STATE_DIR:-/tmp/jarvis-install-state}"

fail() {
    FLAT="$(printf %s "$1" | tr '\n' ' ' | tail -c 300)"
    echo "::error title=install-test::$DISTRO: $FLAT"
    echo "install-test :: FAIL $DISTRO: $FLAT"
    exit 1
}

smoke() {
    export JARVIS_STATE_DIR="$STATE_DIR"
    command -v jarvis >/dev/null || fail "jarvis not on PATH after install"
    VERSION="$(jarvis --version 2>&1)" || fail "jarvis --version failed: $VERSION"
    case "$VERSION" in
        jarvis\ *) : ;;
        *) fail "unexpected version output: $VERSION" ;;
    esac
    ANSWER="$(jarvis --json explain "what is the kernel type" 2>&1)" \
        || fail "explain failed: $(printf %s "$ANSWER" | tail -c 200)"
    printf %s "$ANSWER" > "$STATE_DIR/answer.json"
    grep -q '"fact_id": "kernel.ostype"' "$STATE_DIR/answer.json" \
        || fail "knowledge base missing from install (packaging bug): $ANSWER"
    grep -q '"fact_id": "kernel.ostype"' "$STATE_DIR/answer.json" \
        || fail "knowledge base missing from install (packaging bug)"
    echo "install-test :: PASS $DISTRO ($VERSION; KB shipped in package)"
}

mkdir -p "$STATE_DIR"

case "$DISTRO" in
    debian-12|ubuntu-24.04)
        apt-get update -qq || fail "apt-get update"
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$DIST"/jarvis-agent_*_all.deb \
            >/dev/null || fail "apt install of .deb"
        smoke
        ;;
    fedora)
        dnf install -y rpm-build unzip >/dev/null || fail "rpm-build install"
        RPMB="$(mktemp -d)"
        mkdir -p "$RPMB/SOURCES" "$RPMB/SPECS" "$RPMB/RPMS"
        WHEEL_FILE="$(basename "$DIST"/jarvis_agent-*.whl)" || fail "wheel glob"
        RPMVER="${WHEEL_FILE#jarvis_agent-}"
        RPMVER="${RPMVER%%-*}"
        cp "$DIST/$WHEEL_FILE" "$RPMB/SOURCES/jarvis-agent-$RPMVER-py3-none-any.whl" \
            || fail "wheel copy"
        sed "s/^Version:.*/Version: $RPMVER/" /repo/packaging/rpm/jarvis-agent.spec \
            > "$RPMB/SPECS/jarvis-agent.spec"
        rpmbuild -bb --define "_topdir $RPMB" "$RPMB/SPECS/jarvis-agent.spec" \
            > "$RPMB/build.log" 2>&1 || { tail -20 "$RPMB/build.log"; fail "rpmbuild"; }
        dnf install -y "$RPMB"/RPMS/noarch/jarvis-agent-*.rpm >/dev/null \
            || fail "dnf install of .rpm"
        rpm -q jarvis-agent | grep -q "$RPMVER" || fail "rpm version mismatch: $(rpm -q jarvis-agent)"
        smoke
        ;;
    arch)
        pacman -Syu --noconfirm --needed base-devel unzip >/dev/null 2>&1 \
            || fail "base-devel install"
        WORK="$(mktemp -d)"
        cp /repo/packaging/arch/PKGBUILD "$WORK/PKGBUILD"
        # local-file source so makepkg needs no published release yet
        WHEEL_FILE="$(basename "$DIST"/jarvis_agent-*.whl)" || fail "wheel glob"
        PKGVER="${WHEEL_FILE#jarvis_agent-}"
        PKGVER="${PKGVER%%-*}"
        sed -i "s#^source=.*#source=(\"$WHEEL_FILE\")#" "$WORK/PKGBUILD"
        sed -i "s#^pkgver=.*#pkgver=$PKGVER#" "$WORK/PKGBUILD"
        cp "$DIST"/jarvis_agent-*.whl "$WORK/" || fail "wheel copy"
        useradd -m builder 2>/dev/null || true
        chown -R builder:builder "$WORK"
        chmod -R a+rX "$WORK"
        # makepkg refuses to run as root (and 'nobody' is expired) — build as builder
        su -s /bin/sh builder -c "cd $WORK && makepkg -f --noconfirm >build.log 2>&1" >su.log 2>&1 \
            || fail "makepkg: $(cat su.log "$WORK/build.log" 2>/dev/null)"
        pacman -U --noconfirm "$WORK"/jarvis-agent-*-any.pkg.tar.zst >/dev/null \
            || fail "pacman -U"
        smoke
        ;;
    alpine)
        apk add --no-cache python3 py3-pip >/dev/null || fail "python3/pip install"
        PIP_BREAK_SYSTEM_PACKAGES=1 pip install --quiet --break-system-packages \
            "$DIST"/jarvis_agent-*.whl || fail "pip install of wheel"
        smoke
        ;;
    *)
        fail "unknown distro: $DISTRO"
        ;;
esac
