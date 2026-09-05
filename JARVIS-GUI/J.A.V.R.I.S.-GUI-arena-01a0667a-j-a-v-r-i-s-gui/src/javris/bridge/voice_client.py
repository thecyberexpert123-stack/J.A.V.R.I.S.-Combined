"""Qt driver for push-to-talk capture: record, transcribe, hand back text.

Never executes the transcript. The result is emitted as a string for the
console input field, where the owner reads it and decides whether to submit.
See :mod:`javris.bridge.voice` for why the kernel's own ``voice ask`` (which
would run the transcript directly) is deliberately not used.

Both subprocesses are spawned with fixed argv and no shell, and both are bounded
by timers: a recorder that never exits must not leave the UI stuck in LISTENING
forever.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from . import voice

#: Grace beyond the requested duration before a recorder is considered hung.
RECORD_GRACE_MS = 5_000

#: Transcription budget. Whisper on CPU is slow, but a minute of wall clock for
#: a five-second clip means something is wrong.
TRANSCRIBE_TIMEOUT_MS = 60_000


class VoiceClient(QObject):
    """Records a short phrase and transcribes it to text."""

    #: Recording has begun; the UI should show that it is listening.
    listening = Signal()
    #: Recording finished, transcription running.
    transcribing = Signal()
    #: Transcription succeeded. Carries the cleaned text, never executed.
    transcribed = Signal(str)
    #: Capture failed or was cancelled. Carries a human-readable reason.
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._caps = voice.detect()
        self._process: QProcess | None = None
        self._wav: Path | None = None
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self._stage = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    # -- capability --------------------------------------------------------

    @property
    def capabilities(self) -> voice.VoiceCapabilities:
        """The probe result from construction time."""
        return self._caps

    def refresh(self) -> None:
        """Re-probe. Cheap, and lets a newly-installed binary be noticed."""
        self._caps = voice.detect()

    def available(self) -> bool:
        """True when this machine can turn speech into text."""
        return self._caps.can_listen

    def explain_unavailable(self) -> str:
        """Why voice is unavailable, in the operator's terms."""
        gaps = self._caps.missing
        if not gaps:
            return "Voice input is available."
        return "Voice input needs " + ", ".join(gaps) + "."

    @property
    def busy(self) -> bool:
        """True while a capture is in flight."""
        return self._process is not None

    # -- capture -----------------------------------------------------------

    def start(self, seconds: int = voice.DEFAULT_SECONDS) -> bool:
        """Begin recording. Returns False when unavailable or already busy."""
        if self.busy:
            return False
        if not self.available():
            self.failed.emit(self.explain_unavailable())
            return False

        try:
            self._tmpdir = tempfile.TemporaryDirectory(prefix="javris-voice-")
        except OSError as exc:
            self.failed.emit(f"Could not create a temporary directory: {exc}")
            return False

        self._wav = Path(self._tmpdir.name) / "capture.wav"
        duration = voice.clamp_seconds(seconds)
        argv = voice.record_argv(self._caps.recorder, self._wav, duration)

        self._stage = "record"
        if not self._spawn(argv, duration * 1000 + RECORD_GRACE_MS):
            return False
        self.listening.emit()
        return True

    def cancel(self) -> None:
        """Abandon a capture in progress. Nothing is transcribed or returned."""
        if self._process is None:
            return
        self._stage = "cancelled"
        self._timer.stop()
        process = self._process
        self._process = None
        process.kill()
        process.waitForFinished(2000)
        self._cleanup()
        self.failed.emit("Voice capture cancelled.")

    # -- internals ---------------------------------------------------------

    def _spawn(self, argv: tuple[str, ...], timeout_ms: int) -> bool:
        program, *arguments = argv
        process = QProcess(self)
        # Program and arguments are set separately: no shell is involved.
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.finished.connect(lambda code, status: self._on_finished(code, status))
        process.errorOccurred.connect(self._on_error)

        self._process = process
        process.start()
        if not process.waitForStarted(3000):
            self._process = None
            self._cleanup()
            self.failed.emit(f"Could not start {Path(program).name}.")
            return False

        self._timer.start(timeout_ms)
        return True

    def _on_timeout(self) -> None:
        if self._process is None:
            return
        stage = self._stage
        process = self._process
        self._process = None
        process.kill()
        process.waitForFinished(2000)
        self._cleanup()
        self.failed.emit(f"Voice {stage} timed out and was stopped.")

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if self._process is None:
            return
        self._timer.stop()
        self._process = None
        self._cleanup()
        self.failed.emit(f"Voice capture failed ({error.name}).")

    def _on_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        process = self._process
        if process is None:
            return
        self._timer.stop()
        self._process = None

        if status is not QProcess.ExitStatus.NormalExit:
            self._cleanup()
            self.failed.emit("Voice capture ended abnormally.")
            return

        if self._stage == "record":
            self._after_record(process, exit_code)
        else:
            self._after_transcribe(process, exit_code)

    def _after_record(self, process: QProcess, exit_code: int) -> None:
        wav = self._wav
        # A recorder that exits non-zero, or writes nothing, has not produced
        # audio. Transcribing an empty file would yield a confident-looking
        # empty transcript, which is worse than an honest failure.
        if exit_code != 0 or wav is None or not wav.is_file() or wav.stat().st_size == 0:
            detail = bytes(process.readAllStandardError().data()).decode("utf-8", errors="replace")
            self._cleanup()
            first_line = detail.strip().splitlines()[0] if detail.strip() else ""
            suffix = f" ({first_line})" if first_line else ""
            self.failed.emit(f"No audio was recorded{suffix}.")
            return

        self._stage = "transcribe"
        argv = voice.transcribe_argv(self._caps.stt, self._caps.stt_model, wav)
        if self._spawn(argv, TRANSCRIBE_TIMEOUT_MS):
            self.transcribing.emit()

    def _after_transcribe(self, process: QProcess, exit_code: int) -> None:
        raw = bytes(process.readAllStandardOutput().data()).decode("utf-8", errors="replace")
        self._cleanup()

        if exit_code != 0:
            self.failed.emit("Transcription failed.")
            return

        text = voice.clean_transcript(raw)
        if not text:
            # Silence is a normal outcome of pressing the button by accident.
            self.failed.emit("Nothing was heard.")
            return
        self.transcribed.emit(text)

    def _cleanup(self) -> None:
        """Remove the recorded audio.

        Captured speech is deleted as soon as it has been transcribed. The GUI
        keeps no audio: a HUD is not a recording device, and a stray WAV of
        whatever was said near the microphone is not something to leave behind.
        """
        self._wav = None
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None
