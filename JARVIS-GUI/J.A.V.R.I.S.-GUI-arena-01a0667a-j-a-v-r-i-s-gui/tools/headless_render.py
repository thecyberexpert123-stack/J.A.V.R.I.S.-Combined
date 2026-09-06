#!/usr/bin/env python3
"""Render the HUD offscreen to a PNG for review, and verify it loads cleanly.

This is a smoke test and a review aid, not a pass/fail visual assertion. Qt's
own testing guidance warns against bitmap comparison as a gate, because
resolution, fonts and themes make it flaky; the image produced here is for a
human to look at. The *assertion* is that the QML graph loads without errors
and produces a non-empty frame.

Usage:
    python tools/headless_render.py --output build/hud.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSize, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
UI_ROOT = SRC_ROOT / "javris" / "ui"

# Allow running from a source checkout without an editable install.
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from javris.attention import RAISE_SAMPLES  # noqa: E402
from javris.controller import HudController  # noqa: E402
from javris.qmlregistration import register_controller  # noqa: E402
from javris.telemetry.models import MemorySnapshot, TelemetrySnapshot  # noqa: E402
from javris.telemetry.service import TelemetrySampler  # noqa: E402


class _SaturatedSampler:
    """A review-only sampler reporting memory at 96%.

    This exists solely so the attention-escalation overlay can be photographed
    for the documentation on a machine that is not actually under load. It is
    a developer tool and is never reachable from the application: the shipped
    HUD only ever renders real readings from :class:`TelemetrySampler`.
    """

    def sample(self) -> TelemetrySnapshot:
        total = 8 * 1024**3
        return TelemetrySnapshot(
            monotonic_time=0.0,
            cpu_total_percent=12.0,
            cpu_core_percents=(9.0, 15.0),
            memory=MemorySnapshot(
                total=total,
                available=int(total * 0.04),
                swap_total=0,
                swap_free=0,
            ),
            uptime_seconds=7_320.0,
        )


def render(
    output: Path,
    width: int,
    height: int,
    settle_ms: int,
    mode: str | None = None,
    state: str | None = None,
    simulate_alert: bool = False,
    boot_progress: float | None = None,
) -> int:
    """Load the HUD offscreen and save a frame. Returns a process exit code."""
    QCoreApplication.setAttribute(  # Software rasteriser: no GPU in CI.
        getattr(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt, "AA_UseSoftwareOpenGL", None) or 0
    )
    app = QGuiApplication(sys.argv)

    sampler = _SaturatedSampler() if simulate_alert else TelemetrySampler()
    controller = HudController(sampler=sampler, interval_ms=200)
    controller.set_windowed(True)
    register_controller(controller)

    view = QQuickView()
    view.engine().addImportPath(str(SRC_ROOT))
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(QSize(width, height))
    view.setSource(QUrl.fromLocalFile(str(UI_ROOT / "HudSurface.qml")))

    if view.status() != QQuickView.Status.Ready:
        for error in view.errors():
            print(f"QML error: {error.toString()}", file=sys.stderr)
        return 1

    if view.rootObject() is None:
        print("QML loaded but produced no root object.", file=sys.stderr)
        return 1

    controller.start()

    if mode is not None:
        # cycleMode advances one step, and there are now three modes.
        for _ in range(4):
            if controller.mode == mode:
                break
            controller.cycleMode()
    if state is not None:
        # Walk a *legal* path to the target: the transition table rejects
        # illegal jumps (correctly), so e.g. STANDBY -> SPEAKING must go via
        # LISTENING and PROCESSING. Trying to jump straight there just logged a
        # refusal and rendered the wrong state.
        routes = {
            "STANDBY": ["STANDBY"],
            "LISTENING": ["STANDBY", "LISTENING"],
            "PROCESSING": ["STANDBY", "PROCESSING"],
            "EXECUTING": ["STANDBY", "PROCESSING", "EXECUTING"],
            "SPEAKING": ["STANDBY", "PROCESSING", "SPEAKING"],
            "ERROR": ["ERROR"],
            "OFFLINE": ["OFFLINE"],
            "BOOTING": [],
        }
        for step in routes.get(state.upper(), ["STANDBY", state]):
            if not controller.requestState(step):
                print(f"Refused transition to {step}.", file=sys.stderr)
                return 1
        if controller.state != state.upper():
            print(
                f"Wanted state {state.upper()}, ended in {controller.state}.",
                file=sys.stderr,
            )
            return 1

    if boot_progress is not None:
        # Freeze the boot choreography for inspection.
        #
        # bootProgress carries a Behavior, so assigning it *retargets an
        # animation* rather than setting a value. The assignment is therefore
        # repeated just before the grab, and the value actually captured is
        # read back and reported - an earlier version of this tool silently
        # rendered a different frame than the one requested.
        root = view.rootObject()
        if root is not None:
            root.setProperty("bootProgress", boot_progress)

    if simulate_alert:
        # Escalation requires a sustained condition by design, so drive enough
        # polls for the policy to raise rather than waiting out real time.
        for _ in range(RAISE_SAMPLES):
            controller._poll()  # Private on purpose: review tool, not app code.

    exit_code = 0

    def capture() -> None:
        nonlocal exit_code
        root = view.rootObject()
        if boot_progress is not None and root is not None:
            root.setProperty("bootProgress", boot_progress)
            actual = root.property("bootProgress")
            print(f"bootProgress requested={boot_progress} captured={actual}")
        image = view.grabWindow()
        if image.isNull() or image.width() == 0:
            print("Frame grab produced an empty image.", file=sys.stderr)
            exit_code = 1
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(output))
            print(f"Wrote {output} ({image.width()}x{image.height()})")
        controller.stop()
        app.quit()

    # Let the boot animation and the first telemetry poll settle first.
    QTimer.singleShot(settle_ms, capture)
    app.exec()

    # Tear the view down explicitly. Otherwise it is destroyed during
    # interpreter shutdown, after the context properties have gone, and every
    # binding re-evaluates against a null controller - producing a wall of
    # harmless but alarming TypeError output.
    view.setSource(QUrl())
    view.deleteLater()
    QCoreApplication.processEvents()
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/hud.png"))
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument(
        "--mode",
        choices=["DIAGNOSTICS", "MONITOR", "ASSISTANT"],
        default=None,
        help="Render a specific HUD mode instead of the default.",
    )
    parser.add_argument("--state", default=None, help="Force an assistant state, e.g. PROCESSING.")
    parser.add_argument(
        "--simulate-alert",
        action="store_true",
        help="Review only: feed a synthetic saturated reading so the "
        "attention-escalation overlay can be captured. Never used by the app.",
    )
    parser.add_argument(
        "--boot-progress",
        type=float,
        default=None,
        help="Review only: freeze the boot sequence at this 0.0-1.0 progress.",
    )
    parser.add_argument(
        "--settle",
        type=int,
        default=2500,
        help="Milliseconds to wait before capturing, so animations settle.",
    )
    args = parser.parse_args()
    return render(
        args.output,
        args.width,
        args.height,
        args.settle,
        args.mode,
        args.state,
        args.simulate_alert,
        args.boot_progress,
    )


if __name__ == "__main__":
    raise SystemExit(main())
