"""LLM planner validation: every refusal branch and the happy path.

These tests ARE the schema gate: plans that reach execution have, by
construction, passed the same matchers the deterministic engine uses.
"""

from __future__ import annotations

import pytest

from conftest import FakeProvider
from jarvis.planner.llm import PlanRefused, build_plan
from jarvis.providers.base import ProviderError

VALID = '{"explanation": "install monitoring", "steps": ["install htop", "system info"]}'


def test_valid_plan_builds_parts() -> None:
    provider = FakeProvider([VALID])
    plan = build_plan("set up quick monitoring", provider)
    assert [pb.id for pb, _params in plan.parts] == ["pkg.install", "sys.info"]
    assert plan.step_texts == ("install htop", "system info")
    assert plan.explanation == "install monitoring"
    assert plan.provider_name == "fake"
    # the request was forwarded (truncation only applies to very long inputs)
    assert provider.calls and provider.calls[0][1] == "set up quick monitoring"


def test_invalid_json_refused() -> None:
    with pytest.raises(PlanRefused, match="not valid JSON"):
        build_plan("x", FakeProvider(["here is your plan: install htop"]))  # type: ignore[list-item]


def test_non_object_refused() -> None:
    with pytest.raises(PlanRefused, match="not a JSON object"):
        build_plan("x", FakeProvider(['["install htop"]']))  # type: ignore[list-item]


def test_missing_steps_refused() -> None:
    with pytest.raises(PlanRefused, match='"steps"'):
        build_plan("x", FakeProvider(['{"explanation": "hi"}']))  # type: ignore[list-item]


def test_empty_steps_refused_honestly() -> None:
    with pytest.raises(PlanRefused, match="no steps"):
        build_plan("x", FakeProvider(['{"explanation": "cannot", "steps": []}']))  # type: ignore[list-item]


def test_unknown_intent_refused() -> None:
    with pytest.raises(PlanRefused, match="does not map"):
        build_plan("x", FakeProvider(['{"steps": ["flurb the frobnicator"]}']))  # type: ignore[list-item]


def test_injection_shaped_step_refused() -> None:
    # The matcher must reject option/flag/path injection inside intent text.
    with pytest.raises(PlanRefused, match="failed validation"):
        build_plan("x", FakeProvider(['{"steps": ["install htop; rm -rf /"]}']))  # type: ignore[list-item]


def test_flag_injection_step_refused() -> None:
    with pytest.raises(PlanRefused, match="failed validation"):
        build_plan("x", FakeProvider(['{"steps": ["install -oApt::Proxy evil"]}']))  # type: ignore[list-item]


def test_too_many_steps_refused() -> None:
    steps = ",".join('"system info"' for _ in range(7))
    with pytest.raises(PlanRefused, match="maximum is 6"):
        build_plan("x", FakeProvider([f'{{"steps": [{steps}]}}']))  # type: ignore[list-item]


def test_non_string_step_refused() -> None:
    with pytest.raises(PlanRefused, match="not a string"):
        build_plan("x", FakeProvider(['{"steps": [42]}']))  # type: ignore[list-item]


def test_empty_step_refused() -> None:
    with pytest.raises(PlanRefused, match="not a string"):
        build_plan("x", FakeProvider(['{"steps": ["   "]}']))  # type: ignore[list-item]


def test_overlong_step_refused() -> None:
    long = "install " + "a" * 200
    with pytest.raises(PlanRefused, match="implausibly long"):
        build_plan("x", FakeProvider([f'{{"steps": ["{long}"]}}']))  # type: ignore[list-item]


def test_provider_error_propagates() -> None:
    with pytest.raises(ProviderError, match="backend down"):
        build_plan("x", FakeProvider(raise_on_complete=ProviderError("backend down")))  # type: ignore[arg-type]


def test_non_string_explanation_tolerated() -> None:
    plan = build_plan("x", FakeProvider(['{"explanation": 5, "steps": ["system info"]}']))  # type: ignore[list-item]
    assert plan.explanation == ""
