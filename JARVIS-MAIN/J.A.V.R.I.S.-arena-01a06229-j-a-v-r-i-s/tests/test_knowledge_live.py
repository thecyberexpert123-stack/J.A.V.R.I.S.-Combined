"""Live knowledge tests: real upstream verification against torvalds/linux.

Runs with RUN_LIVE=1. Uses api.github.com (Contents API), which reaches
torvalds/linux even where raw hosts are blocked (see ADR-0009).
"""

from __future__ import annotations

import pytest

from jarvis.knowledge.fetch import verify_kernel_doc
from jarvis.knowledge.store import load_kb

pytestmark = pytest.mark.live


def test_cited_kernel_docs_exist_upstream() -> None:
    kb = load_kb()
    kernel_sources = [s for f in kb.facts for s in f.sources if s.kind == "kernel-doc"]
    assert kernel_sources, "KB must contain kernel-doc citations"
    for source in kernel_sources:
        check = verify_kernel_doc(source.repo, source.ref)
        assert check.reachable, f"{source.repo}:{source.ref} -> {check.detail}"


def test_kernel_doc_missing_path_reports_honestly() -> None:
    check = verify_kernel_doc("torvalds/linux", "Documentation/does/not/exist.rst")
    assert check.reachable is False
    assert check.http_status == 404
