"""ADR-0019 voice front-end: honest detection, fixed-argv adapters, kernel parity.

Stubs on a fake PATH stand in for arecord/whisper/piper/paplay, so the whole
round trip is exercised without audio hardware. The request path is the real
orchestrator (harmless T0 commands), proving voice is presentation only.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from jarvis.safety.tiers import SafetyRefusal
from jarvis.voice.detect import detect
from jarvis.voice.pipeline import MAX_RECORD_SECONDS, VoicePipeline, _clean_text

_STUB = """#!/bin/bash
echo "$0|$*" >> "{sidecar}"
cat >> "{stdin_sidecar}"
case "$(basename "$0")" in
  arecord) : > "${{!#}}";;
  whisper-cli) echo "{transcript}";;
  piper) : > "{reply_wav}";;
esac
exit 0
"""


@pytest.fixture()
def voice_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Stub binaries + model files + state dir; returns the sandbox root."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sidecar = tmp_path / "argv.log"
    stdin_sidecar = tmp_path / "stdin.log"
    script = _STUB.format(
        sidecar=sidecar,
        stdin_sidecar=stdin_sidecar,
        transcript="show memory usage",
        reply_wav=tmp_path / "state" / "voice" / "reply.wav",
    )
    for name in ("arecord", "whisper-cli", "piper", "paplay"):
        stub = bin_dir / name
        stub.write_text(script, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    model = tmp_path / "model.bin"
    model.write_text("stub", encoding="utf-8")
    state = tmp_path / "state"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("JARVIS_STT_MODEL", str(model))
    monkeypatch.setenv("JARVIS_TTS_MODEL", str(model))
    monkeypatch.setenv("JARVIS_STATE_DIR", str(state))
    return {"root": tmp_path, "sidecar": sidecar, "stdin": stdin_sidecar, "bin": bin_dir}


def _pipeline(voice_env: dict[str, Path]) -> VoicePipeline:
    return VoicePipeline(detect())


# --------------------------------------------------------------------------
# detection honesty
# --------------------------------------------------------------------------


def test_detect_finds_stubbed_stack(voice_env: dict[str, Path]) -> None:
    caps = detect()
    assert caps.recorder == "arecord"
    assert caps.stt == "whisper-cli"
    assert caps.tts == "piper"
    assert caps.player == "paplay"
    assert caps.can_transcribe and caps.can_speak
    assert caps.missing_for_full_loop() == []


def test_detect_headless_is_honest_not_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent-voice-bin")
    monkeypatch.delenv("JARVIS_STT_MODEL", raising=False)
    monkeypatch.delenv("JARVIS_TTS_MODEL", raising=False)
    caps = detect()
    assert caps.recorder is None and caps.stt is None and caps.tts is None
    assert not caps.can_transcribe and not caps.can_speak
    missing = caps.missing_for_full_loop()
    assert any("recorder" in m for m in missing) and any("piper" in m for m in missing)


def test_detect_ignores_missing_model_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setenv("JARVIS_STT_MODEL", str(tmp_path / "nope.bin"))
    caps = detect()
    assert caps.stt_model is None  # set but nonexistent → honestly None


# --------------------------------------------------------------------------
# argv templates: fixed, no shell, validated
# --------------------------------------------------------------------------


def test_record_uses_fixed_argv_and_creates_wav(voice_env: dict[str, Path]) -> None:
    pipeline = _pipeline(voice_env)
    wav = pipeline.record(5)
    assert wav.exists()
    argv = voice_env["sidecar"].read_text(encoding="utf-8").strip().splitlines()[0]
    argv = argv.split("|", 1)[1].split()
    assert argv[:8] == ["-r", "16000", "-f", "S16_LE", "-c", "1", "-d", "5"]
    assert str(wav) == argv[-1]


def test_transcribe_uses_model_path_and_returns_text(voice_env: dict[str, Path]) -> None:
    pipeline = _pipeline(voice_env)
    text = pipeline.transcribe(voice_env["root"] / "state" / "voice" / "request.wav")
    assert text == "show memory usage"
    argv = voice_env["sidecar"].read_text(encoding="utf-8").strip().splitlines()[-1]
    model = os.environ["JARVIS_STT_MODEL"]
    assert f"-m|{model}|".replace("|", " ") in argv.replace("|", " ")
    assert "-nt" in argv and "-f" in argv


def test_speak_pipes_text_via_stdin_not_argv(voice_env: dict[str, Path]) -> None:
    pipeline = _pipeline(voice_env)
    assert pipeline.speak("done. sys memory completed.") is True
    piped = voice_env["stdin"].read_text(encoding="utf-8").strip()
    assert piped == "done. sys memory completed."


def test_speak_is_false_without_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("JARVIS_TTS_MODEL", raising=False)
    pipeline = _pipeline({})
    assert pipeline.speak("hello") is False  # honest degrade, never raises


def test_record_refusals_are_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    pipeline = _pipeline({})
    with pytest.raises(SafetyRefusal):
        pipeline.record(5)  # no recorder
    with pytest.raises(SafetyRefusal):
        pipeline.record(MAX_RECORD_SECONDS + 1)  # out of range
    with pytest.raises(SafetyRefusal):
        pipeline.record(0)


def test_pw_record_has_no_timed_mode_honestly(tmp_path: Path) -> None:
    """pw-record records until killed — this release says so instead of guessing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "pw-record"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    caps = detect(which=lambda n: str(stub) if n == "pw-record" else None, env={})
    pipeline = VoicePipeline(caps)
    with pytest.raises(SafetyRefusal, match="--wav"):
        pipeline.record(3)


# --------------------------------------------------------------------------
# text hygiene
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["", "   ", "x" * 501, "bad\x1btext"],
)
def test_clean_text_refuses(text: str) -> None:
    with pytest.raises(SafetyRefusal):
        _clean_text(text, "request")


def test_clean_text_normalizes_whitespace() -> None:
    assert _clean_text("  show   memory\tusage ", "request") == "show memory usage"


# --------------------------------------------------------------------------
# kernel parity through the voice surface
# --------------------------------------------------------------------------


def test_ask_t0_round_trip(voice_env: dict[str, Path]) -> None:
    pipeline = _pipeline(voice_env)
    summary, outcome, spoken = pipeline.ask("show memory usage")
    assert outcome.status.value == "succeeded"
    assert summary == "done. sys memory completed."
    # with the stubbed audio stack the full spoken round trip works end to end
    assert spoken is True
    piped = voice_env["stdin"].read_text(encoding="utf-8").strip()
    assert "done." in piped  # the spoken text is the agent's own summary


def test_ask_unmatched_is_refused_not_guessed(voice_env: dict[str, Path]) -> None:
    pipeline = _pipeline(voice_env)
    summary, outcome, _ = pipeline.ask("make me a sandwich")
    assert outcome.status.value == "refused"
    assert "refused" in summary


def test_ask_t2_is_refused_and_spoken_hint_points_to_typed_consent(
    voice_env: dict[str, Path],
) -> None:
    pipeline = _pipeline(voice_env)
    summary, outcome, _ = pipeline.ask("stop nginx")
    assert outcome.status.value == "refused"
    assert outcome.tier == 2
    assert "typed" in summary  # consent parity: no voice-manufactured T2 consent
    assert outcome.steps == []  # nothing executed


def test_ask_t3_style_destructive_stays_unmatchable(voice_env: dict[str, Path]) -> None:
    pipeline = _pipeline(voice_env)
    _summary, outcome, _spoken = pipeline.ask("dd if=/dev/zero of=/dev/sda")
    assert outcome.status.value == "refused"


# --------------------------------------------------------------------------
# CLI surface
# --------------------------------------------------------------------------


def test_cli_voice_doctor_reports_truth(
    voice_env: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    from jarvis.cli.app import main

    code = main(["voice", "doctor"])
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out[: out.index("}\n") + 2])
    assert payload["recorder"] == "arecord"
    assert "consent" in out and "NOT voice-consentable" in out


def test_cli_voice_say(voice_env: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    from jarvis.cli.app import main

    assert main(["voice", "say", "systems", "nominal"]) == 0
    assert "systems nominal" in capsys.readouterr().out
