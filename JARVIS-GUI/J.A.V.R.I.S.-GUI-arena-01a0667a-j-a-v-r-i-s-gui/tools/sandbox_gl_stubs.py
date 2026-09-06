#!/usr/bin/env python3
"""Generate no-op stub libraries so Qt can be *imported* in a minimal container.

WHY THIS EXISTS
---------------
Qt links against ``libGL.so.1``, ``libEGL.so.1``, ``libdbus-1.so.3`` and
``libxkbcommon.so.0``. Minimal CI images (and this project's development
sandbox) often lack them and have no package manager access to install them.
Without them ``import PySide6.QtGui`` fails at load time, so *no* test can run,
including tests that never touch a display.

This script emits stub shared objects exporting exactly the symbols Qt
references, with matching symbol versions (the dynamic loader checks versions,
not just sonames, so naive one-symbol stubs are rejected).

WHAT THIS IS NOT
----------------
This is **not** a graphics implementation and is **not** part of the product.
The stubs return nothing and do nothing. They make ``-platform offscreen`` with
the software rasteriser possible; any code path that actually calls GL will
misbehave. Never place the output directory on ``LD_LIBRARY_PATH`` on a real
desktop, and never ship it.

Usage:
    python tools/sandbox_gl_stubs.py --output build/glstubs
    LD_LIBRARY_PATH=build/glstubs python -m pytest
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

#: Symbol prefix -> stub library filename.
LIBRARIES: dict[str, str] = {
    "gl": "libGL.so.1",
    "egl": "libEGL.so.1",
    "dbus_": "libdbus-1.so.3",
    "xkb_": "libxkbcommon.so.0",
}


def _qt_library_root() -> Path:
    """Locate the Qt shared libraries inside the installed PySide6 wheel."""
    try:
        import PySide6
    except ImportError:  # pragma: no cover - developer-facing tool
        sys.exit("PySide6 is not installed; nothing to generate stubs for.")
    return Path(PySide6.__file__).parent / "Qt" / "lib"


def _classify(symbol: str) -> str | None:
    """Return the stub library a symbol belongs to, or None if not ours."""
    if symbol.startswith("gl") and len(symbol) > 2 and symbol[2].isupper():
        return LIBRARIES["gl"]
    for prefix in ("egl", "dbus_", "xkb_"):
        if symbol.startswith(prefix):
            return LIBRARIES[prefix]
    return None


def collect_symbols(root: Path) -> dict[str, dict[str | None, set[str]]]:
    """Map stub library -> symbol version -> symbol names, via ``nm``."""
    if shutil.which("nm") is None:
        sys.exit("'nm' (binutils) is required.")

    wanted: dict[str, dict[str | None, set[str]]] = defaultdict(lambda: defaultdict(set))
    candidates = [*root.glob("*.so.6"), *root.parent.glob("plugins/*/*.so")]
    for library in candidates:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["nm", "-D", "--undefined-only", "--with-symbol-versions", str(library)],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            fields = line.split()
            if not fields:
                continue
            token = fields[-1]
            name, _, version = token.partition("@@")
            if not version:
                name, _, version = token.partition("@")
            target = _classify(name)
            if target is not None:
                wanted[target][version or None].add(name)
    return wanted


def build(output: Path) -> list[Path]:
    """Compile the stub libraries into ``output``. Returns the paths written."""
    compiler = shutil.which("gcc") or shutil.which("cc")
    if compiler is None:
        sys.exit("A C compiler (gcc or cc) is required.")

    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for filename, versions in sorted(collect_symbols(_qt_library_root()).items()):
        stem = filename.split(".")[0]
        source = output / f"{stem}.c"
        version_script = output / f"{stem}.map"

        all_names = sorted({name for names in versions.values() for name in names})
        source.write_text("".join(f"void {name}(void) {{}}\n" for name in all_names))
        version_script.write_text(
            "".join(
                f"{version or 'STUB_BASE'} {{ global: "
                + "; ".join(sorted(names))
                + "; local: *; };\n"
                for version, names in versions.items()
            )
        )

        target = output / filename
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                compiler,
                "-shared",
                "-fPIC",
                f"-Wl,--version-script={version_script}",
                "-o",
                str(target),
                str(source),
            ],
            check=True,
        )
        written.append(target)
        print(f"  {filename}: {len(all_names)} symbols")

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/glstubs"),
        help="Directory to write the stub libraries into.",
    )
    args = parser.parse_args()

    print("Generating SANDBOX-ONLY stub libraries (not for production use):")
    written = build(args.output)
    if not written:
        print("Nothing generated: Qt reported no missing symbols of interest.")
        return 1
    print(f"\nDone. Run tests with:\n  LD_LIBRARY_PATH={args.output} python -m pytest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
