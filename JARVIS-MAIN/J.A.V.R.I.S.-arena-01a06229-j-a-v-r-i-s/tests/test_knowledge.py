"""Knowledge system: store schema, verifiers, cite-or-abstain answers, fetch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.knowledge.answers import answer
from jarvis.knowledge.fetch import OnlineRefused, online_enabled, verify_url
from jarvis.knowledge.grounding import verify_fact
from jarvis.knowledge.store import KnowledgeError, load_kb, match_fact


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return load_kb()


# -- store -------------------------------------------------------------------


def test_kb_loads_with_all_facts(kb) -> None:  # type: ignore[no-untyped-def]
    assert kb.version == 1
    ids = {f.id for f in kb.facts}
    assert {
        "kernel.ostype",
        "procfs.meminfo",
        "kernel.release.uname",
        "os-release.identity",
        "distro.pkg.apt",
        "distro.pkg.dnf",
        "distro.pkg.pacman",
        "distro.pkg.apk",
        "pitfall.arch.partial-upgrade",
        "pitfall.debian.noninteractive",
        "pitfall.apt-vs-apt-get",
        "systemctl.is-active.exit",
    } <= ids
    assert len(kb.facts) == 12


def test_every_fact_has_sources(kb) -> None:  # type: ignore[no-untyped-def]
    for fact in kb.facts:
        assert fact.sources, fact.id
        assert fact.claim, fact.id


def test_kernel_facts_cite_torvalds_linux(kb) -> None:  # type: ignore[no-untyped-def]
    ostype = next(f for f in kb.facts if f.id == "kernel.ostype")
    kernel_docs = [s for s in ostype.sources if s.kind == "kernel-doc"]
    assert kernel_docs and kernel_docs[0].repo == "torvalds/linux"
    assert kernel_docs[0].ref.startswith("Documentation/")


def test_duplicate_fact_id_refused(tmp_path: Path) -> None:
    body = {
        "kb_version": 1,
        "facts": [
            {
                "id": "x.dup",
                "topic": "t",
                "claim": "c",
                "patterns": ["p"],
                "sources": [{"kind": "docs", "ref": "r"}],
            },
        ],
    }
    (tmp_path / "a.json").write_text(json.dumps(body), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="duplicate"):
        load_kb(tmp_path)


def test_uncited_fact_refused(tmp_path: Path) -> None:
    body = {
        "kb_version": 1,
        "facts": [{"id": "x.nosrc", "topic": "t", "claim": "c", "patterns": ["p"], "sources": []}],
    }
    (tmp_path / "a.json").write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="at least one source"):
        load_kb(tmp_path)


def test_unknown_verifier_kind_refused(tmp_path: Path) -> None:
    body = {
        "kb_version": 1,
        "facts": [
            {
                "id": "x.bad",
                "topic": "t",
                "claim": "c",
                "patterns": ["p"],
                "sources": [{"kind": "docs", "ref": "r"}],
                "verify": {"kind": " psychic"},
            }
        ],
    }
    (tmp_path / "a.json").write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(KnowledgeError, match=r"verify\.kind"):
        load_kb(tmp_path)


def test_version_mismatch_refused(tmp_path: Path) -> None:
    base = {
        "kb_version": 1,
        "facts": [
            {
                "id": "x.a",
                "topic": "t",
                "claim": "c",
                "patterns": ["p"],
                "sources": [{"kind": "docs", "ref": "r"}],
            }
        ],
    }
    (tmp_path / "a.json").write_text(json.dumps(base), encoding="utf-8")
    other = dict(base)
    other["kb_version"] = 2
    other["facts"] = [dict(base["facts"][0], id="x.b")]
    (tmp_path / "b.json").write_text(json.dumps(other), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="kb_version"):
        load_kb(tmp_path)


# -- matching ------------------------------------------------------------------


def test_match_prefers_longest_pattern(kb) -> None:  # type: ignore[no-untyped-def]
    fact = match_fact("what is the debian package manager", kb)
    assert fact is not None and fact.id == "distro.pkg.apt"
    assert match_fact("completely unrelated nonsense", kb) is None


# -- verifiers (real host) ------------------------------------------------------


def test_verify_file_equals_ostype() -> None:
    status, detail = verify_fact(
        {"kind": "file_equals", "path": "/proc/sys/kernel/ostype", "value": "Linux"}
    )
    assert status == "verified", detail


def test_verify_file_exists_meminfo() -> None:
    status, _ = verify_fact({"kind": "file_exists", "path": "/proc/meminfo"})
    assert status == "verified"


def test_verify_os_release_field() -> None:
    status, _ = verify_fact({"kind": "os_release_field", "field": "ID"})
    assert status == "verified"


def test_verify_binary_present_and_absent() -> None:
    verified, _ = verify_fact({"kind": "binary_present", "name": "sh"})
    assert verified == "verified"
    contradicted, detail = verify_fact({"kind": "binary_present", "name": "definitely-not-here"})
    assert contradicted == "contradicted"
    assert "not on PATH" in detail


def test_verify_command_ok() -> None:
    status, _ = verify_fact({"kind": "command_ok", "argv": ["uname", "-r"]})
    assert status == "verified"


def test_verify_none_is_doc_sourced() -> None:
    status, detail = verify_fact(None)
    assert status == "unverifiable-here"
    assert "documentation-sourced" in detail


# -- answers -----------------------------------------------------------------


def test_answer_verified_with_citations(kb) -> None:  # type: ignore[no-untyped-def]
    result = answer("what is the kernel type", kb)
    assert result.status == "answered"
    assert result.fact_id == "kernel.ostype"
    assert result.machine_status == "verified"
    assert result.sources  # citation always present


def test_answer_unverified_here_is_honest(kb) -> None:  # type: ignore[no-untyped-def]
    result = answer("alpine package manager", kb)
    assert result.status == "answered-unverified-here"
    assert result.machine_status in ("contradicted", "unverifiable-here")
    assert "not applicable here" in result.note or "documentation-sourced" in result.note
    assert result.sources  # still cited


def test_answer_refusal_never_guesses(kb) -> None:  # type: ignore[no-untyped-def]
    result = answer("who is the president of france", kb)
    assert result.status == "refused"
    assert result.claim == ""
    assert result.sources == ()
    assert "will not guess" in result.note


def test_answer_arch_pitfall_doc_sourced(kb) -> None:  # type: ignore[no-untyped-def]
    result = answer("tell me about pacman -Sy partial upgrades", kb)
    assert result.fact_id == "pitfall.arch.partial-upgrade"
    assert result.sources[0]["kind"] == "docs"


# -- fetch allowlist (no network in these tests) -------------------------------


def test_online_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_ONLINE_DOCS", raising=False)
    assert online_enabled() is False
    monkeypatch.setenv("JARVIS_ONLINE_DOCS", "1")
    assert online_enabled() is True


def test_allowlist_refuses_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_a: object, **_k: object) -> None:
        raise AssertionError("network request must never happen")

    monkeypatch.setattr(urllib_request_module(), "urlopen", explode)
    with pytest.raises(OnlineRefused):
        verify_url("https://evil.example.com/payload")


def urllib_request_module():  # type: ignore[no-untyped-def]
    from jarvis.knowledge import fetch

    return fetch.urllib.request


# -- CLI surface ---------------------------------------------------------------


def test_cli_explain_verified(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["--json", "explain", "what", "is", "the", "kernel", "type"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["fact_id"] == "kernel.ostype"
    assert data["machine"]["status"] == "verified"
    assert data["sources"]


def test_cli_explain_refused_exit_code(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["--json", "explain", "stock", "prices", "of", "acme"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "refused"


def test_cli_facts_json(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.cli.app import main

    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    assert main(["--json", "facts", "pitfalls"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 4
    assert all(entry["sources"] >= 1 for entry in data)


# -- redirect guard (audit hardening) ------------------------------------------


def test_safe_redirect_handler_refuses_off_allowlist_redirects() -> None:
    import urllib.request

    from jarvis.knowledge.fetch import OnlineRefused, SafeRedirectHandler

    handler = SafeRedirectHandler()
    request = urllib.request.Request("https://man7.org/linux/man-pages/man1/uname.1.html")
    with pytest.raises(OnlineRefused):
        handler.redirect_request(
            request,
            fp=None,
            code=302,
            msg="Found",
            headers=None,
            newurl="https://evil.example.com/payload",
        )


def test_all_fetch_requests_use_the_safe_opener() -> None:
    import inspect

    from jarvis.knowledge import fetch

    source = inspect.getsource(fetch)
    assert "urllib.request.urlopen" not in source, (
        "raw urlopen bypasses the redirect-validating opener"
    )
    assert source.count("_opener().open(") >= 3
