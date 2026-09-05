"""Voice capability detection (ADR-0019 D2): read-only, honest, side-effect free.

Mirrors gui/detect.py: a machine without audio hardware or voice binaries is a
normal, honestly-reported state — never an error.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

_Which = Callable[[str], str | None]

_RECORDER_CANDIDATES = ("arecord", "pw-record")
_STT_CANDIDATES = ("whisper-cli", "whisper.cpp", "whisper")
_PLAYER_CANDIDATES = ("paplay", "aplay", "ffplay")
_TTS = "piper"


@dataclass(frozen=True)
class VoiceCapabilities:
    """What this machine can do for voice I/O right now (truthfully)."""

    recorder: str | None  # binary name, or None
    stt: str | None
    tts: str | None
    player: str | None
    stt_model: str | None  # $JARVIS_STT_MODEL if set AND the file exists
    tts_model: str | None  # $JARVIS_TTS_MODEL if set AND the file exists

    def to_json_dict(self) -> dict[str, object]:
        return {
            "recorder": self.recorder,
            "stt": self.stt,
            "tts": self.tts,
            "player": self.player,
            "stt_model": self.stt_model,
            "tts_model": self.tts_model,
        }

    @property
    def can_transcribe(self) -> bool:
        return self.stt is not None and self.stt_model is not None

    @property
    def can_speak(self) -> bool:
        return self.tts is not None and self.tts_model is not None and self.player is not None

    def missing_for_full_loop(self) -> list[str]:
        """Human-readable list of what a full spoken round-trip still needs."""
        missing: list[str] = []
        if self.recorder is None:
            missing.append("a recorder (arecord or pw-record)")
        if self.stt is None:
            missing.append(f"an STT binary (one of: {', '.join(_STT_CANDIDATES)})")
        elif self.stt_model is None:
            missing.append("a whisper model file ($JARVIS_STT_MODEL)")
        if self.tts is None:
            missing.append("piper (TTS)")
        elif self.tts_model is None:
            missing.append("a piper voice model ($JARVIS_TTS_MODEL)")
        if self.player is None:
            missing.append("an audio player (paplay, aplay, or ffplay)")
        return missing


def _model(env: Mapping[str, str], key: str) -> str | None:
    raw = env.get(key, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return raw if path.is_file() else None


def detect(which: _Which = shutil.which, env: Mapping[str, str] | None = None) -> VoiceCapabilities:
    """Probe PATH for each adapter role; honor explicit model paths when valid."""
    env_map: Mapping[str, str] = os.environ if env is None else env
    recorder = next((b for b in _RECORDER_CANDIDATES if which(b)), None)
    stt = next((b for b in _STT_CANDIDATES if which(b)), None)
    player = next((b for b in _PLAYER_CANDIDATES if which(b)), None)
    tts = _TTS if which(_TTS) else None
    return VoiceCapabilities(
        recorder=recorder,
        stt=stt,
        tts=tts,
        player=player,
        stt_model=_model(env_map, "JARVIS_STT_MODEL"),
        tts_model=_model(env_map, "JARVIS_TTS_MODEL"),
    )
