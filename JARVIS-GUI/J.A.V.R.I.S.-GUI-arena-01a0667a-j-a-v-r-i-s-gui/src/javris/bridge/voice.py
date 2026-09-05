"""Push-to-talk voice input: speech becomes console text, nothing more.

The kernel ships a voice stack (ADR-0019) whose ``jarvis voice ask`` records,
transcribes, **runs the request**, and speaks the outcome. The GUI deliberately
does not use that command, and the reason is a security one.

``voice ask`` executes autonomously: the transcript goes straight into the
orchestrator. If the GUI shelled out to it, a misheard sentence would reach the
kernel without ever passing the GUI's own gates -- the reversibility check
(gate 2) and the consent prompt (gate 1) would both be bypassed, and the owner
would never have seen the words that were acted upon.

So this module uses only the *first half* of the pipeline:

    record -> transcribe -> **put the text in the console input**

The transcript is placed in the command line for the owner to read and submit.
Speech is treated as a keyboard that can mishear, which is exactly what it is.
Every downstream gate then applies unchanged, and the ADR's own rule -- "speech
misrecognition must never be able to manufacture per-call consent" (D3) --
holds a fortiori: voice here cannot even *initiate* an action, let alone
consent to one.

Capability detection is read-only and reports absence honestly. A machine with
no microphone or no STT binary is a normal machine, not a broken one; the UI
hides the control and says why when asked.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

#: Recorder binaries, in the kernel's probe order (ADR-0019 D2).
RECORDER_CANDIDATES = ("arecord", "pw-record")

#: Speech-to-text binaries, in the kernel's probe order.
STT_CANDIDATES = ("whisper-cli", "whisper.cpp", "whisper")

#: Recording length bounds. The kernel accepts 1..15 seconds; a push-to-talk
#: utterance that runs longer than this is not a command.
MIN_SECONDS = 1
MAX_SECONDS = 15
DEFAULT_SECONDS = 5

#: A transcript longer than this is not a spoken command; it is a runaway
#: transcription, and it must not be pasted into the console unbounded.
MAX_TRANSCRIPT_CHARS = 500


@dataclass(frozen=True, slots=True)
class VoiceCapabilities:
    """What this machine can actually do, probed without side effects."""

    recorder: str = ""
    stt: str = ""
    stt_model: str = ""

    @property
    def can_listen(self) -> bool:
        """True when a spoken phrase can be turned into text.

        Requires all three: something to record with, something to transcribe
        with, and a model for it. Two out of three is not a degraded mode, it
        is an absence, and it is reported as one.
        """
        return bool(self.recorder and self.stt and self.stt_model)

    @property
    def missing(self) -> tuple[str, ...]:
        """Human-readable list of what is absent, for an honest explanation."""
        gaps: list[str] = []
        if not self.recorder:
            gaps.append("a recorder (" + " or ".join(RECORDER_CANDIDATES) + ")")
        if not self.stt:
            gaps.append("a speech-to-text binary (" + ", ".join(STT_CANDIDATES) + ")")
        if not self.stt_model:
            gaps.append("a model path in $JARVIS_STT_MODEL")
        return tuple(gaps)


def _first_on_path(candidates: tuple[str, ...]) -> str:
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    return ""


def detect(env: dict[str, str] | None = None) -> VoiceCapabilities:
    """Probe voice capability. Read-only and side-effect free.

    Mirrors the kernel's own detection so the GUI and ``jarvis voice doctor``
    agree about what the machine can do. The model path counts only when the
    file actually exists -- a stale environment variable is not a capability.
    """
    source = os.environ if env is None else env
    model = source.get("JARVIS_STT_MODEL", "")
    if model:
        try:
            if not Path(model).is_file():
                model = ""
        except OSError:
            model = ""
    return VoiceCapabilities(
        recorder=_first_on_path(RECORDER_CANDIDATES),
        stt=_first_on_path(STT_CANDIDATES),
        stt_model=model,
    )


def clamp_seconds(seconds: int) -> int:
    """Clamp a recording length into the kernel's accepted range."""
    return max(MIN_SECONDS, min(MAX_SECONDS, seconds))


def record_argv(recorder: str, wav: Path, seconds: int) -> tuple[str, ...]:
    """Fixed argv for a recording, matching the kernel's own invocation.

    No shell, and the only variable tokens are a clamped integer and a path the
    GUI itself chose. Nothing derived from speech or from the network reaches
    an argument list.
    """
    duration = str(clamp_seconds(seconds))
    name = Path(recorder).name
    if name == "pw-record":
        return (recorder, "--rate", "16000", "--channels", "1", str(wav))
    return (recorder, "-r", "16000", "-f", "S16_LE", "-c", "1", "-d", duration, str(wav))


def transcribe_argv(stt: str, model: str, wav: Path) -> tuple[str, ...]:
    """Fixed argv for transcription, matching the kernel's invocation."""
    return (stt, "-m", model, "-f", str(wav), "-nt")


def clean_transcript(raw: str) -> str:
    """Reduce STT output to a single bounded line of command text.

    Whisper-class binaries emit timestamps, bracketed annotations such as
    ``[BLANK_AUDIO]`` or ``(wind blowing)``, and multi-line output. None of
    that is command text. The result is collapsed to one line and capped,
    because this string is about to be shown as something the owner might run.
    """
    lines: list[str] = []
    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue
        # Drop lines that are entirely an annotation.
        if text.startswith(("[", "(")) and text.endswith(("]", ")")):
            continue
        lines.append(text)

    joined = " ".join(lines).strip()

    # Remove inline annotations that survived alongside real words.
    for opener, closer in (("[", "]"), ("(", ")")):
        while opener in joined and closer in joined[joined.index(opener) :]:
            start = joined.index(opener)
            end = joined.index(closer, start)
            joined = (joined[:start] + " " + joined[end + 1 :]).strip()

    joined = " ".join(joined.split())
    return joined[:MAX_TRANSCRIPT_CHARS]
