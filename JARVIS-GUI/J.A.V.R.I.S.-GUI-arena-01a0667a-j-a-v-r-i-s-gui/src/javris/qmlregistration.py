"""Registration of Python types into the QML type system.

A registered singleton is used in preference to a context property. Context
properties are invisible to the QML tooling, so every reference to one is
reported as an unqualified access by ``qmllint`` and cannot be type-checked; a
registered singleton is a first-class QML type that the linter understands.
"""

from __future__ import annotations

from PySide6.QtQml import QQmlEngine, qmlRegisterSingletonInstance

from .controller import HudController

#: QML module under which Python-side types are exposed.
QML_MODULE = "javris.core"
QML_MAJOR_VERSION = 1
QML_MINOR_VERSION = 0

#: QML type name of the controller singleton.
CONTROLLER_TYPE = "Hud"

#: QML module and singleton name of the design-token Theme object.
QML_MODULE_UI = "javris.ui"
THEME_TYPE = "Theme"


def register_controller(controller: HudController) -> None:
    """Expose ``controller`` to QML as ``javris.core.Hud``.

    Must be called before any QML that imports ``javris.core`` is loaded.

    Args:
        controller: The instance to expose. Ownership stays with the caller,
            so it must outlive the QML engine.
    """
    # PySide6 6.11's type stub declares the name parameter as bytes, but the
    # runtime rejects bytes and requires str. The stub is wrong; verified
    # against PySide6 6.11.2.
    qmlRegisterSingletonInstance(
        HudController,
        QML_MODULE,
        QML_MAJOR_VERSION,
        QML_MINOR_VERSION,
        CONTROLLER_TYPE,  # type: ignore[arg-type]
        controller,
    )


def configure_engine(engine: QQmlEngine, import_path: str) -> None:
    """Point ``engine`` at the project's QML modules.

    Args:
        engine: The engine to configure.
        import_path: Directory containing the ``javris`` QML module tree.
    """
    engine.addImportPath(import_path)


def set_ambient_motion(engine: QQmlEngine, *, enabled: bool) -> bool:
    """Switch decorative animation on or off on the ``Theme`` singleton.

    Ambient motion is purely decorative: drifting motes, the scanline, ring
    rotation and pointer parallax. Motion that carries information - alert
    escalation, gauge transitions, state colour - is deliberately unaffected,
    because suppressing that would hide data rather than reduce distraction
    (docs/RESEARCH.md, D19).

    Args:
        engine: A configured engine whose QML modules have been loaded.
        enabled: False to stop all decorative animation.

    Returns:
        True if the setting was applied. False when the ``Theme`` singleton
        could not be resolved, which is not fatal - the HUD simply keeps its
        default motion rather than failing to start over a cosmetic option.
    """
    theme = engine.singletonInstance(QML_MODULE_UI, THEME_TYPE)
    if theme is None:
        return False
    theme.setProperty("ambientMotion", enabled)
    return True
