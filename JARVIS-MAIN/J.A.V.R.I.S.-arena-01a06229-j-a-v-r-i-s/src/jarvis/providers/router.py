"""Provider routing (ADR-0003: hybrid, local-first).

Precedence for *planning* (execution safety is independent of this choice —
every plan still passes the tier gate):
1. deterministic engine (decided by the caller via playbook match),
2. local Ollama when reachable,
3. remote OpenAI-compatible endpoint when configured AND not disabled,
4. none → the agent refuses honestly instead of guessing.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from jarvis.providers.base import Provider, ProviderError
from jarvis.providers.ollama import OllamaProvider
from jarvis.providers.openai_compatible import DEFAULT_BASE_URL, KEY_ENV, OpenAICompatibleProvider

REMOTE_DISABLE_ENV = "JARVIS_REMOTE_LLM"
NO_AI_ENV = "JARVIS_NO_AI"
_TRANSIENT_KINDS = frozenset({"unreachable", "timeout"})


@dataclass(frozen=True)
class Routing:
    """Outcome of the planning-backend decision."""

    mode: str  # "local" | "remote" | "none"
    provider: Provider | None
    note: str


def remote_allowed(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else dict(os.environ)
    return source.get(REMOTE_DISABLE_ENV, "1") != "0"


def plan_routing(env: dict[str, str] | None = None, *, enabled: bool = True) -> Routing:
    """Decide which planning backend to use (cheap availability probes only).

    ``enabled=False`` (CLI ``--no-ai`` / ``JARVIS_NO_AI=1`` — ADR-0014 D7)
    returns a "none" routing without probing anything: the no-AI contract is
    a declared operator mode, not an accident of a missing backend.
    """
    env_map = env or {}
    if not enabled:
        return Routing("none", None, f"AI disabled by operator (--no-ai or {NO_AI_ENV}=1)")
    local = OllamaProvider(host=env_map.get("OLLAMA_HOST"), model=env_map.get("JARVIS_LOCAL_MODEL"))
    if local.available():
        return Routing("local", local, "local-first policy (ADR-0003)")

    if not remote_allowed(env):
        return Routing(
            "none",
            None,
            "no local model detected and remote planning disabled (JARVIS_REMOTE_LLM=0)",
        )

    remote = OpenAICompatibleProvider()
    if remote.available():
        return Routing("remote", remote, "no local model detected; remote endpoint configured")
    return Routing(
        "none",
        None,
        f"no local Ollama detected and no remote key configured ({KEY_ENV}); "
        f"remote base URL would be {DEFAULT_BASE_URL}",
    )


# -- ADR-0025 D3: dual-path reliability with mandatory disclosure -------------


def ordered_candidates(
    env: dict[str, str] | None = None,
    *,
    enabled: bool = True,
    extra: Sequence[Provider] = (),
) -> list[Provider]:
    """Probed AI backends in ADR-0003 precedence (local → remote, then extras).

    ``extra`` exists for tests (stub providers); production callers pass
    nothing. Remote appears only when allowed (JARVIS_REMOTE_LLM) and
    configured (key present).
    """
    env_map = env or {}
    out: list[Provider] = []
    if not enabled:
        return out
    local = OllamaProvider(host=env_map.get("OLLAMA_HOST"), model=env_map.get("JARVIS_LOCAL_MODEL"))
    if local.available():
        out.append(local)
    if remote_allowed(env_map):
        remote = OpenAICompatibleProvider()
        if remote.available():
            out.append(remote)
    for provider in extra:
        if not any(p.name == provider.name and p.model == provider.model for p in out):
            out.append(provider)
    return out


def complete_with_failover(
    system: str,
    user: str,
    *,
    schema: dict[str, object] | None = None,
    timeout_s: float = 90.0,
    env: dict[str, str] | None = None,
    enabled: bool = True,
    breaker: object | None = None,  # ProviderBreaker | None (avoids an import cycle)
    primary: Provider | None = None,
    extra: Sequence[Provider] = (),
) -> tuple[str, Provider]:
    """One AI completion across BOTH paths — local and API, both reliable.

    Order: *primary* (the router's pick, when the caller already made one)
    then the remaining probed candidates. Each candidate is attempted behind
    the breaker; the primary additionally gets ONE bounded retry on transient
    failures (unreachable/timeout) — the breaker, not the retry loop, remains
    the storm guard. On a candidate's final failure, failover moves to the
    next candidate. All candidates exhausted → ProviderError summarizing
    every path. The winner is returned so callers can DISCLOSE it
    (`served_by`) — failover is never silent (ADR-0025 D3).
    """
    order: list[Provider] = []
    for provider in ([primary] if primary is not None else []) + list(
        ordered_candidates(env, enabled=enabled, extra=extra)
    ):
        if not any(p.name == provider.name and p.model == provider.model for p in order):
            order.append(provider)
    if not order:
        raise ProviderError(
            "no AI backend is configured or reachable (local endpoint down; "
            f"remote requires {KEY_ENV} and JARVIS_REMOTE_LLM!=0)",
            kind="unreachable",
        )
    failures: list[str] = []
    last: ProviderError | None = None
    for index, provider in enumerate(order):
        attempts = 2 if index == 0 else 1
        for attempt in range(attempts):
            allow_note = ""
            if breaker is not None:
                allowed, allow_note = breaker.allow(provider.name)  # type: ignore[attr-defined]
                if not allowed:
                    failures.append(f"{provider.name}: breaker open")
                    last = ProviderError(allow_note, kind="breaker-open")
                    break
            try:
                text = provider.complete(system, user, timeout_s=timeout_s, schema=schema)
            except ProviderError as exc:
                failures.append(f"{provider.name}: {exc.kind}")
                last = exc
                # FailureKind is a str-Enum: compare by value, never str()
                # (str(FailureKind.TIMEOUT) is "FailureKind.TIMEOUT", not "timeout")
                if attempt + 1 < attempts and exc.kind in _TRANSIENT_KINDS:
                    continue
                break
            except Exception as exc:  # defensive: never let a backend bug escape as a crash
                failures.append(f"{provider.name}: error")
                last = ProviderError(f"{provider.name} failed unexpectedly: {exc}")
                break
            else:
                return text, provider
    detail = "; ".join(failures) if failures else "no candidate attempted"
    kind = last.kind if last is not None else "unreachable"
    raise ProviderError(f"all AI paths failed ({detail})", kind=kind)
