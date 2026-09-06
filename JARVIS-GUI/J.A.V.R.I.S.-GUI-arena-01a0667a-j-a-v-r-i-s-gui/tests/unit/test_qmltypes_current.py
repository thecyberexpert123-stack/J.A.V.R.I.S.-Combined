"""The committed QML type description must match the live controller.

``src/javris/core/javris.core.qmltypes`` is what qmllint and IDE tooling know
about the Python-side singleton. It is generated, and it drifted once: the
bridge, consent, voice and plan surfaces were added to the controller without
regenerating it, so for a while every one of those properties was invisible
to the QML tooling. Nothing failed, because nothing compared the file to the
meta-object it describes. This does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = PROJECT_ROOT / "tools" / "generate_qmltypes.py"
COMMITTED = PROJECT_ROOT / "src" / "javris" / "core" / "javris.core.qmltypes"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_qmltypes", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("generate_qmltypes", module)
    spec.loader.exec_module(module)
    return module


def test_committed_qmltypes_match_the_live_meta_object() -> None:
    generator = _load_generator()
    expected = generator.render()
    actual = COMMITTED.read_text(encoding="utf-8")
    assert actual == expected, (
        "javris.core.qmltypes is out of date with HudController; "
        "run `python tools/generate_qmltypes.py` and commit the result."
    )


def test_qmltypes_describes_the_agent_surface() -> None:
    # The properties the HUD's agent link binds to must be visible to
    # qmllint, or the binding is an unqualified access it cannot check.
    text = COMMITTED.read_text(encoding="utf-8")
    for name in ("agentConnected", "agentAvailable", "agentVersion", "agentTransport"):
        assert f'name: "{name}"' in text
    assert 'name: "connectAgent"' in text
