#!/usr/bin/env bash
# Build the JARVIS .deb from a prebuilt wheel (ADR-0011).
#
# Layout: the pure-Python wheel is unpacked into /usr/share/jarvis/lib and a
# /usr/bin/jarvis shim runs it with PYTHONPATH set — fully self-contained,
# depends only on python3 >= 3.10. No pip in postinst.
#
# Usage: packaging/deb/build-deb.sh <path-to-wheel> [output-dir]
set -euo pipefail

WHEEL="${1:?usage: build-deb.sh <wheel> [outdir]}"
OUTDIR="${2:-dist}"
VERSION="$(python3 -c "import sys; sys.path.insert(0, 'src'); import jarvis; print(jarvis.__version__)")"

command -v dpkg-deb >/dev/null || { echo "dpkg-deb not found" >&2; exit 1; }
[ -f "$WHEEL" ] || { echo "wheel not found: $WHEEL" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/jarvis-agent"
LIB="$PKG/usr/share/jarvis/lib"
BIN="$PKG/usr/bin"
DEBIAN="$PKG/DEBIAN"
mkdir -p "$LIB" "$BIN" "$DEBIAN"

python3 - "$WHEEL" "$LIB" <<'PYEOF'
import sys
import zipfile

wheel, dest = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(wheel) as zf:
    zf.extractall(dest)
PYEOF

cat > "$BIN/jarvis" <<'SH'
#!/bin/sh
# JARVIS launcher (deb layout, ADR-0011)
exec env PYTHONPATH="/usr/share/jarvis/lib${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m jarvis "$@"
SH
chmod 755 "$BIN/jarvis"

cat > "$DEBIAN/control" <<CTRL
Package: jarvis-agent
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10)
Installed-Size: $(du -sk "$PKG/usr" | cut -f1)
Maintainer: JARVIS owners <thecyberexpert123-stack@users.noreply.github.com>
Homepage: https://github.com/thecyberexpert123-stack/J.A.V.R.I.S.
Description: JARVIS (Just A Rather Very Intelligent System) — verified automation agent for Linux
 Safety-kernelled task engine with LLM planning behind deterministic guards,
 cited knowledge (cite-or-abstain), capability-matrix GUI control, journaling
 and undo. This package is self-contained: it ships its own library copy and
 only requires python3.
CTRL

mkdir -p "$OUTDIR"
dpkg-deb --root-owner-group --build "$PKG" \
    "$OUTDIR/jarvis-agent_${VERSION}_all.deb" >/dev/null
echo "built $OUTDIR/jarvis-agent_${VERSION}_all.deb"
