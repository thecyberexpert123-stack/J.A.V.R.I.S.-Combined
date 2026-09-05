"""Tests for voice capability detection and transcript cleaning.

The governing rule, from ADR-0019 D3 and reinforced here: speech must never be
able to manufacture consent. In this GUI voice cannot even *initiate* an
action -- a transcript becomes text in the input field and nothing more -- so
every downstream gate applies unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from javris.bridge import voice
from javris.bridge.voice import VoiceCapabilities, clean_transcript

# -- capability reporting --------------------------------------------------


def test_all_three_pieces_are_required_to_listen() -> None:
    caps = VoiceCapabilities(
        recorder="/usr/bin/arecord", stt="/usr/bin/whisper-cli", stt_model="/m"
    )
    assert caps.can_listen is True


@pytest.mark.parametrize(
    ("recorder", "stt", "model"),
    [
        ("", "/usr/bin/whisper-cli", "/m"),
        ("/usr/bin/arecord", "", "/m"),
        ("/usr/bin/arecord", "/usr/bin/whisper-cli", ""),
        ("", "", ""),
    ],
)
def test_a_partial_stack_is_an_absence_not_a_degraded_mode(
    recorder: str, stt: str, model: str
) -> None:
    caps = VoiceCapabilities(recorder=recorder, stt=stt, stt_model=model)
    assert caps.can_listen is False
    assert caps.missing, "an unavailable stack must be able to explain itself"


def test_missing_pieces_are_named_specifically() -> None:
    caps = VoiceCapabilities()
    text = " ".join(caps.missing)
    assert "arecord" in text
    assert "whisper-cli" in text
    assert "JARVIS_STT_MODEL" in text


def test_a_complete_stack_reports_nothing_missing() -> None:
    caps = VoiceCapabilities(recorder="a", stt="b", stt_model="c")
    assert caps.missing == ()


def test_a_model_path_that_does_not_exist_is_not_a_capability(tmp_path: Path) -> None:
    # A stale environment variable must not be mistaken for a working model.
    caps = voice.detect({"JARVIS_STT_MODEL": str(tmp_path / "absent.bin")})
    assert caps.stt_model == ""


def test_an_existing_model_path_is_accepted(tmp_path: Path) -> None:
    model = tmp_path / "model.bin"
    model.write_bytes(b"weights")
    assert voice.detect({"JARVIS_STT_MODEL": str(model)}).stt_model == str(model)


def test_detection_is_side_effect_free(tmp_path: Path) -> None:
    before = sorted(tmp_path.iterdir())
    voice.detect({"JARVIS_STT_MODEL": str(tmp_path / "x")})
    assert sorted(tmp_path.iterdir()) == before


# -- argv construction -----------------------------------------------------


def test_recording_argv_matches_the_kernels_invocation(tmp_path: Path) -> None:
    wav = tmp_path / "a.wav"
    argv = voice.record_argv("/usr/bin/arecord", wav, 5)
    assert argv == (
        "/usr/bin/arecord",
        "-r",
        "16000",
        "-f",
        "S16_LE",
        "-c",
        "1",
        "-d",
        "5",
        str(wav),
    )


def test_pw_record_gets_its_own_flags(tmp_path: Path) -> None:
    argv = voice.record_argv("/usr/bin/pw-record", tmp_path / "a.wav", 5)
    assert argv[0] == "/usr/bin/pw-record"
    assert "--rate" in argv


@pytest.mark.parametrize(("given", "expected"), [(0, 1), (-5, 1), (99, 15), (5, 5), (15, 15)])
def test_recording_length_is_clamped(given: int, expected: int) -> None:
    assert voice.clamp_seconds(given) == expected


def test_argv_carries_no_shell_metacharacters(tmp_path: Path) -> None:
    # No shell is involved, and the only variable tokens are a clamped integer
    # and a path the GUI chose itself.
    wav = tmp_path / "a.wav"
    argv = voice.record_argv("/usr/bin/arecord", wav, 5)
    argv += voice.transcribe_argv("/usr/bin/whisper-cli", "/m.bin", wav)
    for token in argv:
        assert not any(char in token for char in ";|&$`><\n")


# -- transcript cleaning ---------------------------------------------------


def test_whisper_timestamps_and_annotations_are_stripped() -> None:
    raw = "[00:00.000 --> 00:02.000]\n[BLANK_AUDIO]\n  restart the ssh service  \n(wind blowing)\n"
    assert clean_transcript(raw) == "restart the ssh service"


def test_multiple_lines_collapse_into_one_command() -> None:
    cleaned = clean_transcript("remove the file\nreport.log\n")
    assert cleaned == "remove the file report.log"


def test_inline_annotations_are_removed() -> None:
    assert clean_transcript("upgrade (coughs) the system") == "upgrade the system"


def test_silence_yields_an_empty_string() -> None:
    # An empty transcript is a normal outcome and must not become a command.
    for raw in ("", "   \n\n", "[BLANK_AUDIO]", "[ Silence ]"):
        assert clean_transcript(raw) == ""


def test_whitespace_is_normalised() -> None:
    assert clean_transcript("  install    htop  ") == "install htop"


def test_a_runaway_transcript_is_capped() -> None:
    # This string is about to be shown as something the owner might run.
    text = clean_transcript("word " * 5000)
    assert len(text) <= voice.MAX_TRANSCRIPT_CHARS
