"""Application entry point.

Wires the controller to the QML engine and shows the HUD. Kept deliberately
thin: everything testable lives in the modules it imports.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from .controller import HudController
from .qmlregistration import configure_engine, register_controller, set_ambient_motion
from .telemetry.service import MIN_INTERVAL_MS

#: QML modules are named javris.ui.*, so the *parent of the package* is
#: what must be on the import path.
SRC_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = SRC_ROOT / "javris" / "ui"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="javris",
        description="J.A.V.R.I.S. — a Linux heads-up display driven by real system telemetry.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=1000,
        metavar="MS",
        help=f"Telemetry polling interval in milliseconds (minimum {MIN_INTERVAL_MS}).",
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Start in a normal window instead of full screen.",
    )
    parser.add_argument(
        "--no-ambient",
        action="store_true",
        help="Disable decorative motion (drifting motes, scanline, ring "
        "rotation, parallax). Telemetry and alerts are unaffected.",
    )
    return parser.parse_args(argv)


def build_window_source() -> QUrl:
    """Return the URL of the top-level QML window."""
    return QUrl.fromLocalFile(str(UI_ROOT / "Main.qml"))


def main(argv: list[str] | None = None) -> int:
    """Run the application. Returns the process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # 4x multisampling, requested before the application exists because the
    # format is read when the first window is created.
    #
    # Scope of this, honestly stated: it improves the *hardware* path, where
    # Rectangle borders and rotated edges would otherwise show stair-stepping.
    # It does nothing under QT_QUICK_BACKEND=software, and Shape elements using
    # CurveRenderer already antialias themselves regardless. Requesting samples
    # is a hint -- drivers that cannot honour it fall back silently rather than
    # failing to start, so this is safe to ask for unconditionally.
    surface_format = QSurfaceFormat.defaultFormat()
    surface_format.setSamples(4)
    QSurfaceFormat.setDefaultFormat(surface_format)

    app = QGuiApplication(sys.argv)
    app.setApplicationName("J.A.V.R.I.S.")
    app.setOrganizationName("javris")

    controller = HudController(interval_ms=args.interval)

    controller.set_windowed(args.windowed)
    register_controller(controller)

    engine = QQmlApplicationEngine()
    configure_engine(engine, str(SRC_ROOT))
    engine.load(build_window_source())

    if not engine.rootObjects():
        print("Fatal: the QML interface failed to load.", file=sys.stderr)
        return 1

    if args.no_ambient:
        set_ambient_motion(engine, enabled=False)

    root = engine.rootObjects()[0]
    if isinstance(root, QQuickWindow):
        controller.shutdownRequested.connect(root.close)
    controller.shutdownRequested.connect(app.quit)
    app.aboutToQuit.connect(controller.stop)

    controller.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
