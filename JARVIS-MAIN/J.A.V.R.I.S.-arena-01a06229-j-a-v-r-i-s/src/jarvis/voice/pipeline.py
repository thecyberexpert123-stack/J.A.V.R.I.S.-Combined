"""The voice pipeline (ADR-0019): three fixed-argv adapters and kernel parity.

Every external call is a frozen argv over a probed binary with validated
inputs (model paths, integer seconds, state-dir WAV paths) — no shell, no
string interpolation into commands. The request itself goes through the SAME
orchestrator construction the MCP surface uses without ``allow``, so T2 is
deterministically refused (consent parity; see ADR-0019 D3).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from jarvis.cli.mcp_server import _build_orchestrator
from jarvis.core.orchestrator import Orchestrator, TaskOutcome
from jarvis.execution.runner import ExecResult, LocalRunner, Runner
from jarvis.journal.sqlite import state_dir
from jarvis.safety.tiers import SafetyRefusal
from jarvis.voice.detect import VoiceCapabilities

MAX_VOICE_TEXT_CHARS = 500
MAX_RECORD_SECONDS = 15
_SAMPLE_RATE = "16000"
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+(?:\s+|$)|[^.!?!.?]+$")


def split_sentences(text: str) -> list[str]:
    """Split on sentence boundaries, keeping punctuation (ADR-0025 D4)."""
    parts = [match.group(0).strip() for match in _SENTENCE_RE.finditer(text)]
    return [part for part in parts if part]


def _clean_text(text: str, what: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        raise SafetyRefusal(f"empty {what}")
    if len(cleaned) > MAX_VOICE_TEXT_CHARS:
        raise SafetyRefusal(f"{what} too long for the voice surface ({len(cleaned)} chars)")
    if any(ord(ch) < 0x20 for ch in cleaned):
        raise SafetyRefusal(f"control characters are not allowed in {what}")
    return cleaned


class VoicePipeline:
    """Spoken round-trip: record → transcribe → kernel → summarize → speak."""

    def __init__(
        self,
        caps: VoiceCapabilities,
        runner: Runner | None = None,
        orchestrator: Orchestrator | None = None,
    ) -> None:
        self.caps = caps
        self.runner = runner if runner is not None else LocalRunner()
        # MCP-parity construction without allow: T2 refuses deterministically.
        self.orchestrator = (
            orchestrator if orchestrator is not None else _build_orchestrator(allow=False)
        )

    # -- adapters ----------------------------------------------------------

    def record(self, seconds: int) -> Path:
        """Record a request WAV via the probed recorder; returns the path."""
        if self.caps.recorder is None:
            raise SafetyRefusal("no recorder available (install arecord, or pass --wav)")
        if self.caps.recorder != "arecord":
            raise SafetyRefusal(
                f"{self.caps.recorder} has no timed mode in this release; pass --wav instead"
            )
        if not isinstance(seconds, int) or not 1 <= seconds <= MAX_RECORD_SECONDS:
            raise SafetyRefusal(f"seconds must be an integer in 1..{MAX_RECORD_SECONDS}")
        wav = self._workdir() / "request.wav"
        argv: tuple[str, ...] = (
            "arecord",
            "-r",
            _SAMPLE_RATE,
            "-f",
            "S16_LE",
            "-c",
            "1",
            "-d",
            str(seconds),
            "-q",
            str(wav),
        )
        result = self._run(argv, timeout_s=seconds + 10.0)
        if result.exit_code != 0 or not wav.exists():
            raise SafetyRefusal(
                f"recording failed (exit {result.exit_code}): {result.stderr_tail[:120]}"
            )
        return wav

    def transcribe(self, wav: Path) -> str:
        """WAV → text via the probed STT binary and the configured model."""
        if not self.caps.can_transcribe:
            raise SafetyRefusal(
                "transcription unavailable: need an STT binary and $JARVIS_STT_MODEL"
            )
        assert self.caps.stt is not None and self.caps.stt_model is not None
        argv: tuple[str, ...] = (
            self.caps.stt,
            "-m",
            self.caps.stt_model,
            "-nt",
            "-f",
            str(wav),
        )
        result = self._run(argv, timeout_s=120.0)
        if result.exit_code != 0:
            raise SafetyRefusal(
                f"transcription failed (exit {result.exit_code}): {result.stderr_tail[:120]}"
            )
        return _clean_text(result.stdout_tail, "transcript")

    def speak(self, text: str) -> bool:
        """Speak text via piper + the probed player. Returns True if spoken."""
        if not self.caps.can_speak:
            return False
        assert self.caps.tts is not None and self.caps.tts_model is not None
        assert self.caps.player is not None
        payload = _clean_text(text, "response")
        wav = self._workdir() / "reply.wav"
        synth = self._run(
            (self.caps.tts, "-m", self.caps.tts_model, "-f", str(wav)),
            stdin_text=payload + "\n",
            timeout_s=60.0,
        )
        if synth.exit_code != 0 or not wav.exists():
            return False
        played = self._run(self._player_argv(str(wav)), timeout_s=60.0)
        return played.exit_code == 0

    def speak_sentences(self, text: str) -> bool:
        """Speak sentence-by-sentence (ADR-0025 D4): first audio sooner.

        Each sentence is synthesized and played in order, so playback of the
        first sentence begins after ONE sentence's synthesis instead of the
        whole reply's — the honest form of the research's voice-latency win
        for a pipeline whose TTS, not its LLM, dominates latency. Returns
        True if any sentence was spoken (same honesty contract as speak).
        """
        sentences = split_sentences(_clean_text(text, "response"))
        if len(sentences) <= 1:
            return self.speak(text)
        spoken = False
        for sentence in sentences:
            if self.speak(sentence):
                spoken = True
        return spoken

    def _player_argv(self, wav: str) -> tuple[str, ...]:
        assert self.caps.player is not None
        if self.caps.player == "paplay":
            return ("paplay", wav)
        if self.caps.player == "aplay":
            return ("aplay", "-q", wav)
        return ("ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", wav)

    # -- the round trip ----------------------------------------------------

    def ask(self, request_text: str) -> tuple[str, object, bool]:
        """Text → kernel (T0/T1 only) → (summary, outcome, spoken).

        The outcome object is the standard TaskOutcome; the summary is the
        terse spoken/printed form. T2/T3 refusals are outcomes, not exceptions
        — the kernel decided, the voice layer reports.
        """
        request = _clean_text(request_text, "request")
        outcome = self.orchestrator.run_intent(request)
        summary = self._summarize(outcome)
        spoken = self.speak_sentences(summary)
        return summary, outcome, spoken

    def _summarize(self, outcome: TaskOutcome) -> str:
        playbook = outcome.playbook_id or "?"
        name = outcome.status.value
        if name in {"success", "succeeded"}:
            return f"done. {playbook.replace('.', ' ')} completed."
        lines = str(outcome.error or "").splitlines()
        error = (lines[0] if lines else "").strip()[:200]
        if name == "refused":
            hint = "system-level actions need typed confirmation with yes."
            return f"refused. {error} {hint}" if "approval" in error else f"refused. {error}"
        return f"{name}. {error}" if error else f"{name}."

    # -- plumbing ----------------------------------------------------------

    def _workdir(self) -> Path:
        d = state_dir() / "voice"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _run(
        self,
        argv: Sequence[str],
        *,
        stdin_text: str = "",
        timeout_s: float = 60.0,
    ) -> ExecResult:
        return self.runner.run(
            tuple(argv),
            requires_root=False,
            timeout_s=timeout_s,
            stdin_text=stdin_text,
            echo=False,
        )
