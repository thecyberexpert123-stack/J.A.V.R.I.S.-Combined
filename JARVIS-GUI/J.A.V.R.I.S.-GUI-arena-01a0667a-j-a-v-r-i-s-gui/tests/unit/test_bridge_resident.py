"""Tests for the resident-mode doorway client.

The security properties asserted here were each verified against a running
``jarvis serve`` at kernel 1.18.0: 401 without a token, 421 for a foreign Host
header, a 0600 token file, and a ``{"result": ..., "isError": ...}`` envelope
whose ``result`` is already decoded (unlike stdio, where it is a JSON string).
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from javris.bridge import protocol, resident
from javris.bridge.protocol import OutcomeKind
from javris.bridge.resident import ResidentError


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "token"
    path.write_text("s3cret-token", encoding="utf-8")
    path.chmod(0o600)
    return path


# -- endpoint safety -------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_endpoints_are_accepted(host: str) -> None:
    resident.validate_endpoint(host, resident.DEFAULT_PORT)


@pytest.mark.parametrize(
    "host",
    # "0.0.0.0" is deliberately in this list: binding-to-all is exactly the
    # misconfiguration this guard exists to refuse.
    ["10.0.0.5", "example.com", "0.0.0.0", "192.168.1.1"],  # noqa: S104
)
def test_non_loopback_endpoints_are_refused(host: str) -> None:
    # The bearer token must never leave the machine.
    with pytest.raises(ResidentError, match="loopback"):
        resident.validate_endpoint(host, resident.DEFAULT_PORT)


@pytest.mark.parametrize("port", [0, -1, 70000])
def test_out_of_range_ports_are_refused(port: int) -> None:
    with pytest.raises(ResidentError):
        resident.validate_endpoint("127.0.0.1", port)


def test_urls_never_contain_the_token() -> None:
    url = resident.tool_url("127.0.0.1", 8777, "jarvis_status")
    assert url == "http://127.0.0.1:8777/v1/tools/jarvis_status"
    assert "token" not in url.lower()


def test_tool_url_rejects_an_unknown_tool() -> None:
    with pytest.raises(ValueError):
        resident.tool_url("127.0.0.1", 8777, "jarvis_rm_rf")


# -- token handling --------------------------------------------------------


def test_a_correctly_permissioned_token_is_read(token_file: Path) -> None:
    assert resident.read_token(token_file) == "s3cret-token"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666])
def test_a_token_readable_by_others_is_refused(token_file: Path, mode: int) -> None:
    # If another account can read it, that account can already act as the
    # owner. Using it anyway would paper over a real compromise.
    token_file.chmod(mode)
    with pytest.raises(ResidentError, match="readable by other accounts"):
        resident.read_token(token_file)


def test_a_missing_token_is_an_honest_absence(tmp_path: Path) -> None:
    with pytest.raises(ResidentError, match="jarvis serve install"):
        resident.read_token(tmp_path / "nope")


def test_an_empty_token_is_refused(token_file: Path) -> None:
    token_file.write_text("   \n", encoding="utf-8")
    token_file.chmod(0o600)
    with pytest.raises(ResidentError, match="empty"):
        resident.read_token(token_file)


def test_an_implausibly_large_token_is_not_read(token_file: Path) -> None:
    token_file.write_text("x" * (resident.MAX_TOKEN_BYTES + 1), encoding="utf-8")
    token_file.chmod(0o600)
    with pytest.raises(ResidentError, match="implausibly large"):
        resident.read_token(token_file)


def test_a_directory_is_not_a_token(tmp_path: Path) -> None:
    directory = tmp_path / "serve"
    directory.mkdir(mode=0o700)
    with pytest.raises(ResidentError):
        resident.read_token(directory)


def test_token_path_follows_the_kernels_state_dir_rules() -> None:
    explicit = resident.default_token_path({"JARVIS_STATE_DIR": "/custom"})
    assert explicit == Path("/custom/serve/token")

    xdg = resident.default_token_path({"XDG_STATE_HOME": "/xdg"})
    assert xdg == Path("/xdg/jarvis/serve/token")

    fallback = resident.default_token_path({})
    assert fallback.parts[-5:] == (".local", "state", "jarvis", "serve", "token")


def test_token_file_mode_helper_matches_what_the_kernel_writes(token_file: Path) -> None:
    # Documents the expectation rather than the implementation: the kernel
    # writes 0600, and read_token accepts exactly that.
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert resident.read_token(token_file)


# -- request bodies --------------------------------------------------------


def test_allow_is_absent_unless_asked_for() -> None:
    body = json.loads(resident.build_body("jarvis_do", {"request": "install htop"}))
    assert "allow" not in body


def test_allow_is_present_only_when_asked_for() -> None:
    body = json.loads(resident.build_body("jarvis_do", {"request": "upgrade"}, allow=True))
    assert body["allow"] is True


def test_consent_cannot_be_attached_to_a_read_only_tool() -> None:
    with pytest.raises(ValueError):
        resident.build_body("jarvis_explain", {"question": "x"}, allow=True)


def test_unknown_tools_are_refused_before_the_wire() -> None:
    with pytest.raises(ValueError):
        resident.build_body("jarvis_rm_rf", {})


# -- envelope normalisation ------------------------------------------------


def test_http_envelope_is_normalised_into_the_stdio_shape() -> None:
    # Reusing one classifier is the point: the refusal-versus-failure
    # distinction must not have two implementations that can drift.
    envelope = {
        "result": {
            "outcome": {
                "status": "refused",
                "tier": 2,
                "hint": "review the plan with jarvis_preview",
            }
        },
        "isError": True,
    }
    outcome = protocol.classify_outcome(resident.envelope_to_message(envelope))
    assert outcome.kind is OutcomeKind.REFUSED
    assert outcome.tier == 2
    assert outcome.consent_required is True


def test_http_success_classifies_as_ok() -> None:
    envelope = {"result": {"claim": "The kernel is Linux."}, "isError": False}
    outcome = protocol.classify_outcome(resident.envelope_to_message(envelope))
    assert outcome.kind is OutcomeKind.OK
    assert "Linux" in outcome.text


def test_tier_three_over_http_is_not_offered_for_approval() -> None:
    envelope = {"result": {"outcome": {"status": "refused", "tier": 3}}, "isError": True}
    outcome = protocol.classify_outcome(resident.envelope_to_message(envelope))
    assert outcome.consent_required is False


def test_a_malformed_envelope_is_reported_not_raised() -> None:
    with pytest.raises(ResidentError):
        resident.parse_envelope(b"not json")
    with pytest.raises(ResidentError):
        resident.parse_envelope(b"[1,2,3]")


def test_a_valid_envelope_parses() -> None:
    assert resident.parse_envelope(b'{"isError": false}') == {"isError": False}


# -- server header ---------------------------------------------------------


def test_kernel_version_is_read_from_the_server_header() -> None:
    # Captured verbatim from a running doorway.
    header = "jarvis-serve/1.18.0 Python/3.11.2"
    assert resident.parse_server_header(header) == "1.18.0"


@pytest.mark.parametrize("header", ["", "nginx/1.2", "Python/3.11.2", "jarvis-serve/"])
def test_an_unrecognised_server_header_yields_no_version(header: str) -> None:
    # Unknown is reported as unknown rather than guessed.
    assert resident.parse_server_header(header) == ""


# -- status explanations ---------------------------------------------------


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (401, "token"),
        (421, "Host header"),
        (413, "64 KiB"),
        (404, "tool"),
        (500, "internal error"),
    ],
)
def test_observed_statuses_are_explained_in_operator_terms(status: int, needle: str) -> None:
    assert needle in resident.describe_http_status(status)
