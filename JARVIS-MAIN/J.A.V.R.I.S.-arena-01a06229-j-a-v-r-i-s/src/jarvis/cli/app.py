"""JARVIS command-line interface (argparse; ADR-0005 — stdlib only at M1).

Exit codes: 0 success/dry-run · 1 execution or verification failure ·
2 refused (policy, protected set, unmatched intent, invalid input) ·
130 interrupted by signal.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import cast

from jarvis import __version__
from jarvis.context.store import ContextStore, default_context_path
from jarvis.core.fingerprint import build_profile
from jarvis.core.orchestrator import Orchestrator, TaskOutcome
from jarvis.execution.runner import LocalRunner
from jarvis.gui.backends import GuiBackendError
from jarvis.gui.service import GuiPolicyError, GuiService, GuiUnavailable
from jarvis.gui.wizard import report as wizard_report
from jarvis.gui.wizard import run_checks as wizard_checks
from jarvis.intent.classifier import rank_intents, suggest_intent
from jarvis.journal.sqlite import Journal, default_db_path, state_dir
from jarvis.knowledge.ai_answer import answer_with_ai
from jarvis.knowledge.answers import answer as kb_answer
from jarvis.knowledge.store import load_kb
from jarvis.planner.llm import PlanRefused, build_plan_failover
from jarvis.planner.models import TaskStatus
from jarvis.planner.playbooks import PLAYBOOKS, match_intent, nearest_intents
from jarvis.providers.base import FailureKind, ProviderError
from jarvis.providers.breaker import ProviderBreaker, default_breaker_path
from jarvis.providers.router import NO_AI_ENV, plan_routing
from jarvis.safety.approval import ApprovalPolicy, ApprovalRefused
from jarvis.safety.disclosure import blast_radius
from jarvis.safety.integrity import issue_canary
from jarvis.safety.selftest import run_battery
from jarvis.safety.tiers import Tier
from jarvis.suggest.engine import generate_suggestions
from jarvis.system.models import InvalidInputError


def _ai_enabled(args: argparse.Namespace) -> bool:
    """The no-AI contract (ADR-0014 D7): --no-ai flag or JARVIS_NO_AI=1."""
    if getattr(args, "no_ai", False):
        return False
    return os.environ.get(NO_AI_ENV, "") != "1"


def _breaker() -> ProviderBreaker:
    return ProviderBreaker(default_breaker_path())


def _unknown_outcome(
    text: str,
    error: str,
    hint: str,
    journal: Journal | None,
    *,
    suggestion: str | None = None,
) -> TaskOutcome:
    """A processed unknown (ADR-0014 D6): disclose, suggest, record, teach.

    The journal record is growth-loop input for the owner — proactivity
    proposes, consent executes; JARVIS never turns an unknown into an action.
    Disclosure ranking prefers the learned classifier (ADR-0015, proposals
    only) and falls back to the lexical ranking when no model is available —
    both are equivalent disclosures, neither is authority.
    """
    ranked = rank_intents(text)
    if ranked:
        descriptions = {pb.id: pb.description for pb in PLAYBOOKS}
        alternatives = [
            f"{label} — {descriptions.get(label, '')}".rstrip(" -") for label, _prob in ranked
        ]
    else:
        alternatives = nearest_intents(text)
    if journal is not None:
        with contextlib.suppress(Exception):
            journal.record_unknown_request(text, error[:200], alternatives)
    parts = [hint]
    if suggestion is not None:
        parts.append(
            f"it looks like: 'jarvis do {suggestion}' — type that yourself to run it "
            "(suggestions never self-execute)."
        )
    if alternatives:
        parts.append("did you mean: " + "; ".join(alternatives) + "?")
    parts.append(
        "extend the engine: 'jarvis playbooks' lists supported intents; "
        "cited KB facts and skill packs are owner-curated (jarvis grow --help)."
    )
    return TaskOutcome(
        playbook_id="<unmatched>",
        status=TaskStatus.REFUSED,
        error=error,
        hint=" ".join(parts),
    )


def _print_outcome(outcome: TaskOutcome) -> None:
    print(f"playbook : {outcome.playbook_id}")
    print(f"task     : {outcome.task_id or '-'}")
    print(f"status   : {outcome.status.value} (exit {outcome.exit_code()})")
    for step in outcome.steps:
        exit_part = f" exit={step['exit_code']}" if step.get("exit_code") is not None else ""
        print(f"  step {step['seq']}: {step['status']}{exit_part} — {step['description']}")
    if outcome.verification is not None:
        mark = "PASS" if outcome.verification.ok else "FAIL"
        print(f"verify   : {mark} — {outcome.verification.detail}")
        for name, passed, detail in outcome.verification.checks:
            print(f"  [{'x' if passed else ' '}] {name}: {detail}")
    if outcome.undo_status is not None:
        extra = f" — {outcome.undo_reason}" if outcome.undo_reason else ""
        print(f"undo     : {outcome.undo_status.value}{extra}")
    if outcome.undo_status is None and outcome.playbook_id not in ("undo", "<unmatched>"):
        print("undo     : not applicable (read-only)")
    if outcome.snapshot_note:
        print(f"snapshot : {outcome.snapshot_note}")
    if outcome.error:
        print(f"error    : {outcome.error}", file=sys.stderr)
    if outcome.hint:
        print(f"hint     : {outcome.hint}")


def _build_orchestrator(args: argparse.Namespace) -> tuple[Orchestrator, Journal]:
    profile = build_profile()
    journal = Journal(default_db_path())
    runner = LocalRunner()
    policy = ApprovalPolicy(yes=args.yes, silent=bool(args.json))
    echo = not args.json
    return Orchestrator(
        profile,
        journal,
        runner,
        policy,
        echo=echo,
        cautious_ok=getattr(args, "cautious_ok", False),
    ), journal


def _cmd_status(args: argparse.Namespace) -> int:
    profile = build_profile()
    if args.json:
        print(json.dumps(profile.to_dict(), indent=2))
        return 0
    pm = profile.package_manager.value if profile.package_manager else "none found"
    print(
        f"distro          : {profile.distro_name} (id={profile.distro_id}"
        f"{', v' + profile.version_id if profile.version_id else ''})"
    )
    print(f"init system     : {profile.init_system}")
    print(f"package manager : {pm}")
    print(f"session type    : {profile.session_type or 'none (likely headless)'}")
    print(
        f" privileges     : {'root' if profile.is_root else 'user'}"
        f" (sudo {'available' if profile.sudo_available else 'unavailable'})"
    )
    print(f"python          : {profile.python_version}")
    try:
        routing = plan_routing()
        llm_line = f"{routing.mode} — {routing.note}"
    except Exception as exc:  # status must never crash
        llm_line = f"probe failed: {exc}"
    print(f"llm planning    : {llm_line}")
    try:
        views = _breaker().views()
        if views:
            breaker_line = "; ".join(
                f"{name}: {view['state']} ({view['failures']} fail/s, last"
                f" {view['last_reason']} {view['last_utc']})"
                for name, view in sorted(views.items())
            )
        else:
            breaker_line = "clean (no recorded provider failures)"
    except Exception as exc:  # status must never crash
        breaker_line = f"probe failed ({exc})"
    print(f"ai breaker      : {breaker_line}")
    try:
        kb = load_kb()
        print(f"knowledge base  : v{kb.version}, {len(kb.facts)} cited facts")
    except Exception as exc:  # status must never crash
        print(f"knowledge base  : unavailable ({exc})")
    try:
        from jarvis.gui.detect import probe as gui_probe

        gui_env = gui_probe()
        print(
            f"gui             : {gui_env.session_type} ({gui_env.desktop}),"
            f" {len(gui_env.tools)} GUI tool(s) on PATH"
        )
    except Exception as exc:  # status must never crash
        print(f"gui             : probe failed ({exc})")
    print(f"cautious mode   : {'ON' if _cautious_path().exists() else 'OFF'}")
    try:
        print(f"integrity       : {_integrity_line()}")
    except Exception as exc:  # status must never crash
        print(f"integrity       : probe failed ({exc})")
    context_rows = len(ContextStore(default_context_path()).feedback_rows())
    print(f"context store   : {context_rows} feedback entr{'y' if context_rows == 1 else 'ies'}")
    print(f"journal         : {default_db_path()}")
    return 0


def _cmd_do(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("error: empty request", file=sys.stderr)
        return 2
    orch, _journal = _build_orchestrator(args)
    if args.preview:
        outcome = orch.run_intent(text, dry_run=True)
        radius = blast_radius(outcome.steps)
        if args.json:
            print(json.dumps({"preview": outcome.to_json_dict(), "blast_radius": radius}, indent=2))
            return outcome.exit_code()
        print("[preview] plan (nothing executed, nothing asked):")
        for step in outcome.steps:
            step_argv = step["argv"]
            assert isinstance(step_argv, list)
            print(f"  {step['seq']}. {step['description']}")
            print(f"       $ {' '.join(str(a) for a in step_argv)}")
        print(
            f"  blast radius: tier={radius['max_tier']} root={radius['requires_root']} "
            f"network={radius['network']}"
        )
        commands = radius["commands"]
        assert isinstance(commands, list)
        print(f"  commands: {', '.join(str(c) for c in commands) or '(none)'}")
        paths_map = radius["paths"]
        assert isinstance(paths_map, dict)
        for klass, paths_ in paths_map.items():
            if paths_:
                assert isinstance(paths_, list)
                print(f"  {klass} paths: {', '.join(str(p_) for p_ in paths_)}")
        print("  execute by re-running with --yes (review the plan above first).")
        return outcome.exit_code()
    outcome = orch.run_intent(text, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(outcome.to_json_dict(), indent=2))
    else:
        _print_outcome(outcome)
    return outcome.exit_code()


def _cmd_undo(args: argparse.Namespace) -> int:
    orch, _journal = _build_orchestrator(args)
    outcome = orch.undo(args.task_id, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(outcome.to_json_dict(), indent=2))
    else:
        _print_outcome(outcome)
    return outcome.exit_code()


def _cmd_playbooks(args: argparse.Namespace) -> int:
    if args.json:
        print(
            json.dumps(
                [
                    {"id": pb.id, "description": pb.description, "tier": int(pb.tier)}
                    for pb in PLAYBOOKS
                ],
                indent=2,
            )
        )
        return 0
    print("available playbooks:")
    for pb in PLAYBOOKS:
        print(f"  {pb.id:<18} T{int(pb.tier)}  {pb.description}")
    return 0


def _cmd_tasks(args: argparse.Namespace) -> int:
    journal = Journal(default_db_path())
    tasks = journal.recent_tasks(limit=args.limit)
    if args.json:
        print(json.dumps(tasks, indent=2))
        return 0
    if not tasks:
        print("no tasks journaled yet")
        return 0
    print(f"{'id':<14}{'status':<12}{'tier':<6}{'playbook':<20}created (UTC)  intent")
    for t in tasks:
        print(
            f"{t['id']:<14}{t['status']:<12}T{t['tier']:<5}{t['playbook_id']:<20}"
            f"{t['created_utc']}  {t['intent_text']}"
        )
    return 0


def _ask_flow(
    orch: Orchestrator,
    args: argparse.Namespace,
    text: str,
    journal: Journal | None = None,
    history: list[tuple[str, str]] | None = None,
) -> TaskOutcome:
    """Engine-first routing: deterministic playbooks, LLM planner otherwise.

    ADR-0014: the AI path is breaker-tracked and classifies its failures;
    a request nothing can map becomes a *processed* unknown (nearest intents,
    journal record, teaching hint) instead of a blind refusal.
    """
    quiet = bool(args.json)
    ai_on = _ai_enabled(args)
    try:
        matched = match_intent(text)
    except InvalidInputError as exc:
        return TaskOutcome(
            playbook_id="<unmatched>",
            status=TaskStatus.REFUSED,
            error=f"invalid input: {exc}",
        )
    if matched is not None:
        if not quiet:
            print("[engine] deterministic playbook match — LLM not consulted")
        return orch.run_intent(text, dry_run=args.dry_run)

    routing = plan_routing(enabled=ai_on)
    if routing.mode == "none" or routing.provider is None:
        # ADR-0015: the learned classifier gets one proposals-only look —
        # its suggestion is TEXT the user types, never an executed plan.
        nn_suggestion = suggest_intent(text) if ai_on else None
        setup = (
            "Install Ollama (local-first, ADR-0003) or configure the remote endpoint "
            "to enable AI planning."
            if ai_on
            else "Re-run without --no-ai to enable AI planning for unmapped requests."
        )
        return _unknown_outcome(
            text,
            "unknown-request: no deterministic playbook matches and no planning backend "
            "could map this request",
            f"{routing.note}. {setup} The deterministic engine, cited KB answers and the "
            "journal still work without AI.",
            journal,
            suggestion=nn_suggestion,
        )
    provider = routing.provider
    breaker = _breaker() if ai_on else None
    if not quiet:
        print(f"[planner] asking {routing.mode}:{provider.name}/{provider.model} for a plan...")
    try:
        memory_block = ""
        try:
            from jarvis.memory.store import MemoryStore

            memory_block = MemoryStore().prompt_block()
        except OSError:
            memory_block = ""  # unreadable store → plan without memory, as before
        proposed = build_plan_failover(
            text,
            enabled=ai_on,
            breaker=breaker,
            memory_block=memory_block,
            history=history,
            primary=provider,
        )
        # ADR-0025 D3: failover is never silent — disclose the serving backend.
        print(f"[jarvis] served by {proposed.served_by}", file=sys.stderr)
    except PlanRefused as exc:
        served_name = getattr(exc, "provider_name", "") or provider.name
        if exc.kind == "unexpressible":
            if breaker is not None:
                breaker.record_success(served_name)
            return _unknown_outcome(
                text,
                f"unknown-request: {exc}",
                exc.hint or "rephrase the request, or use a supported playbook (jarvis playbooks).",
                journal,
                suggestion=suggest_intent(text),
            )
        if breaker is not None:
            breaker.record_failure(served_name, "malformed", str(exc))
        return TaskOutcome(
            playbook_id="plan",
            status=TaskStatus.REFUSED,
            error=str(exc),
            hint=exc.hint,
        )
    except ProviderError as exc:
        # all paths failed (ADR-0025 D3): account the primary honestly —
        # per-provider notes stay visible in `jarvis ai status`.
        if breaker is not None and exc.kind is not FailureKind.BREAKER_OPEN:
            breaker.record_failure(provider.name, str(exc.kind), str(exc))
        return TaskOutcome(
            playbook_id="plan",
            status=TaskStatus.FAILED,
            error=f"planning backend failed ({exc.kind}): {exc}",
            hint=(
                "degraded, not broken: the deterministic engine, cited KB answers and the "
                "journal still work; the AI path is breaker-tracked (jarvis status)."
            ),
        )
    if breaker is not None:
        breaker.record_success(provider.name)
    if not quiet:
        print(
            f"[planner] proposal ({len(proposed.parts)} step/s): "
            f"{proposed.explanation or '(no explanation)'}"
        )
        for i, (playbook, _params) in enumerate(proposed.parts, 1):
            print(f"  {i}. {playbook.id:<18} <- {proposed.step_texts[i - 1]}")
    served_label = proposed.served_by or f"{provider.name}/{provider.model}"
    return orch.run_plan(
        text,
        list(proposed.parts),
        explanation=proposed.explanation,
        provider_label=f"{routing.mode}:{served_label}",
        dry_run=args.dry_run,
    )


def _cmd_ask(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("error: empty request", file=sys.stderr)
        return 2
    orch, _journal = _build_orchestrator(args)
    outcome = _ask_flow(orch, args, text, journal=_journal)
    if args.json:
        print(json.dumps(outcome.to_json_dict(), indent=2))
    else:
        _print_outcome(outcome)
    return outcome.exit_code()


def _cmd_chat(args: argparse.Namespace) -> int:
    args.json = False  # chat is a human surface
    orch, journal = _build_orchestrator(args)
    print("JARVIS chat — deterministic engine first; local/remote planner for the rest.")
    print("commands: /status /playbooks /tasks [n] /undo <id> /help — Ctrl-D or /quit exits")
    history: list[tuple[str, str]] = []  # ADR-0025 D2: bounded conversation context
    while True:
        try:
            line = input("jarvis> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        low = line.lower()
        if low in {"q", "quit", "exit", "/quit"}:
            return 0
        if low in {"h", "help", "/help"}:
            print(
                "Type a request in plain English. /tasks lists recent task ids; "
                "/undo <id> reverses one."
            )
            continue
        if low == "/status":
            _cmd_status(args)
            continue
        if low == "/playbooks":
            _cmd_playbooks(args)
            continue
        if low.startswith("/tasks"):
            tokens = line.split()
            limit = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else 10
            tasks = journal.recent_tasks(limit=limit)
            if not tasks:
                print("no tasks journaled yet")
            for t in tasks:
                print(
                    f"  {t['id']}  {t['status']:<11} {t['playbook_id']:<20} "
                    f"{str(t['intent_text'])[:60]}"
                )
            continue
        if low.startswith("/undo"):
            tokens = line.split()
            if len(tokens) != 2:
                print("usage: /undo <task-id>")
                continue
            _print_outcome(orch.undo(tokens[1]))
            continue
        outcome = _ask_flow(orch, args, line, journal=journal, history=history)
        _print_outcome(outcome)
        history.append((line, f"{outcome.playbook_id}:{outcome.status.value}"))


def _cmd_file(args: argparse.Namespace) -> int:
    orch, _journal = _build_orchestrator(args)
    playbook = next((pb for pb in PLAYBOOKS if pb.id == "file.append"), None)
    if playbook is None:  # pragma: no cover - registry constant
        print("error: file.append playbook missing", file=sys.stderr)
        return 2
    text = " ".join(args.text)
    outcome = orch.run_plan(
        f"[file] append to {args.path}",
        [(playbook, {"path": args.path, "text": text})],
        provider_label="cli:file",
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(outcome.to_json_dict(), indent=2))
    else:
        _print_outcome(outcome)
    return outcome.exit_code()


def _cmd_explain(args: argparse.Namespace) -> int:
    question = " ".join(args.question).strip()
    if not question:
        print("error: empty question", file=sys.stderr)
        return 2
    try:
        kb = load_kb()
    except Exception as exc:
        print(f"error: knowledge base unavailable: {exc}", file=sys.stderr)
        return 1
    result = kb_answer(question, kb)
    if result.status == "refused" and _ai_enabled(args):
        result = answer_with_ai(question, kb, enabled=True)
    if args.json:
        print(json.dumps(result.to_json_dict(), indent=2))
        return 0 if result.status != "refused" else 2
    if result.status == "refused":
        print("I cannot answer this from cited knowledge and I will not guess.")
        print(f"hint     : {result.note}")
        return 2
    if result.ai_text:
        print(f"answer   : {result.ai_text}")
        print("           (ai-synthesized; every claim is one of the cited KB facts below)")
    print(f"fact     : {result.fact_id}")
    print(f"claim    : {result.claim}")
    print(f"machine  : {result.machine_status} — {result.machine_detail}")
    print(f"note     : {result.note}")
    for src in result.sources:
        label = f"{src.get('kind')}: {src.get('ref')}"
        if src.get("url"):
            label += f" ({src['url']})"
        print(f"source   : {label}")
    return 0


def _cmd_facts(args: argparse.Namespace) -> int:
    try:
        kb = load_kb()
    except Exception as exc:
        print(f"error: knowledge base unavailable: {exc}", file=sys.stderr)
        return 1
    facts = kb.facts
    if args.topic:
        wanted = args.topic.lower()
        facts = tuple(f for f in facts if f.topic == wanted)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": f.id,
                        "topic": f.topic,
                        "claim": f.claim,
                        "sources": len(f.sources),
                        "local_check": bool(f.verify),
                    }
                    for f in facts
                ],
                indent=2,
            )
        )
        return 0
    if not facts:
        print(f"no facts for topic {args.topic!r} (topics: {sorted({f.topic for f in kb.facts})})")
        return 0
    print(f"knowledge base v{kb.version} — {len(facts)} fact(s):")
    for fact in facts:
        check = "local check" if fact.verify else "doc-sourced"
        print(f"  {fact.id:<28} [{fact.topic}] {fact.claim[:70]}… ({check})")
    return 0


def _cmd_gui(args: argparse.Namespace) -> int:
    kind = args.gui_command

    if kind == "status":
        service = _build_gui(args)
        data = service.status()
        if args.json:
            print(json.dumps(data, indent=2))
            return 0
        session = data["session"]
        assert isinstance(session, dict)
        print(f"session   : {session['session_type']} ({session['desktop']})")
        print(f"tools     : {', '.join(session['tools']) or '(none)'}")
        caps = data["capabilities"]
        assert isinstance(caps, dict)
        for cap, binding in caps.items():
            assert isinstance(binding, dict)
            mark = binding.get("backend") or "unavailable"
            print(f"  {cap:<11}: {mark} [{binding.get('path')}] — {binding.get('reason')}")
        atspi = data["atspi"]
        assert isinstance(atspi, dict)
        print(f"  atspi      detail: {atspi['detail']}")
        if data.get("hint"):
            print(f"hint      : {data['hint']}")
        return 0

    if kind == "wizard":
        checks = wizard_checks()
        if args.json:
            print(
                json.dumps(
                    [
                        {"name": c.name, "ok": c.ok, "detail": c.detail, "fix": c.fix}
                        for c in checks
                    ],
                    indent=2,
                )
            )
            return 0
        print(wizard_report(checks))
        return 0

    if kind == "windows":
        service = _build_gui(args)
        try:
            windows = service.windows()
        except (GuiUnavailable, GuiPolicyError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except GuiBackendError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    [{"id": w.id, "title": w.title, "backend": w.backend} for w in windows],
                    indent=2,
                )
            )
        else:
            for w in windows:
                print(f"  {w.id:<12} {w.title}")
        return 0

    service = _build_gui(args)
    try:
        if kind == "open":
            outcome = service.open_app(args.argv)
        elif kind == "focus":
            outcome = service.focus(args.title)
        elif kind == "type":
            outcome = service.type_text(" ".join(args.text))
        elif kind == "key":
            outcome = service.key(args.combo)
        elif kind == "screenshot":
            outcome = service.screenshot(Path(args.path))
        elif kind == "close":
            outcome = service.close(args.title)
        elif kind == "describe":
            question = " ".join(args.question).strip() or (
                "Describe what is on this screen concisely."
            )
            text = service.describe(Path(args.path), question)
            if args.json:
                print(json.dumps({"description": text}, indent=2))
            else:
                print(text)
            return 0
        else:  # pragma: no cover - argparse guards this
            return 2
    except ApprovalRefused as exc:
        print(f"refused  : {exc}", file=sys.stderr)
        return 2
    except (GuiPolicyError, GuiUnavailable) as exc:
        print(f"error    : {exc}", file=sys.stderr)
        return 2
    except GuiBackendError as exc:
        print(f"error    : {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(outcome.to_json_dict(), indent=2))
    else:
        print(f"action    : {outcome.action}")
        print(f"status    : {outcome.status}")
        if outcome.target:
            print(f"target    : {outcome.target}")
        print(f"detail    : {outcome.detail}")
    return 0


def _build_gui(args: argparse.Namespace) -> GuiService:
    journal = Journal(default_db_path())
    runner = LocalRunner()
    policy = ApprovalPolicy(yes=args.yes, silent=bool(args.json))
    return GuiService(runner, policy, journal, echo=not args.json)


def _cmd_safety_check(args: argparse.Namespace) -> int:
    results = run_battery()
    if args.json:
        print(
            json.dumps(
                [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results],
                indent=2,
            )
        )
    else:
        print("JARVIS safety self-test (real components, execution-blocked runner):")
        for result in results:
            mark = "PASS" if result.ok else "FAIL"
            print(f"  [{mark}] {result.name}: {result.detail}")
    failed = sum(1 for r in results if not r.ok)
    verdict = "SAFETY CHECK PASSED" if failed == 0 else f"SAFETY CHECK FAILED ({failed})"
    if args.json:
        print(json.dumps({"verdict": verdict, "failed": failed}, indent=2))
    else:
        print(f"== {verdict} ==")
    return 0 if failed == 0 else 1


def _cautious_path() -> Path:

    return state_dir() / "cautious"


def _cmd_cautious(args: argparse.Namespace) -> int:
    marker = _cautious_path()
    if args.action in ("on", "off"):
        marker.parent.mkdir(parents=True, exist_ok=True)
        if args.action == "on":
            marker.write_text("on\n", encoding="utf-8")
        else:
            marker.unlink(missing_ok=True)
    active = marker.exists()
    if args.json:
        print(json.dumps({"cautious": active}, indent=2))
        return 0
    print(f"cautious mode : {'ON' if active else 'OFF'}")
    if not active:
        print("  (recommended while JARVIS is new on this machine: jarvis cautious on)")
    if active:
        print(
            "  T2+ actions are blocked; review plans with --preview, then run "
            "once with --cautious-ok, or disable: jarvis cautious off"
        )
    return 0


def _suggest_target() -> list[dict[str, object]]:
    from jarvis.core.fingerprint import build_profile
    from jarvis.journal.sqlite import Journal

    journal = Journal(default_db_path())
    context = ContextStore(default_context_path())
    suggestions = generate_suggestions(build_profile(), journal, context)
    return [s.to_json_dict() for s in suggestions]


def _cmd_suggest(args: argparse.Namespace) -> int:
    action = getattr(args, "suggest_command", None)

    if action in ("accept", "reject"):
        if action == "reject" and not args.reason:
            print(
                "error: rejecting without a reason wastes the calibration signal "
                '(use --reason "...")',
                file=sys.stderr,
            )
            return 2
        context = ContextStore(default_context_path())
        suggestion = _lookup_suggestion(args.suggestion_id) if action == "accept" else None
        if action == "accept" and suggestion is None:
            print(
                f"error: no current suggestion {args.suggestion_id!r} (list with: jarvis suggest)",
                file=sys.stderr,
            )
            return 2
        try:
            context.record_feedback(
                args.suggestion_id,
                "accepted" if action == "accept" else "rejected",
                reason=args.reason,
                title=str(suggestion["title"]) if suggestion else "",
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if suggestion is not None:
            print(f"accepted: {suggestion['title']}")
            print("review first, then run:")
            print(f"  {suggestion['command']}")
        else:
            print(f"rejected {args.suggestion_id} — suppressed from future suggestions")
            print(f"reason recorded: {args.reason}")
        return 0

    suggestions = _suggest_target()
    if args.json:
        print(json.dumps(suggestions, indent=2))
        return 0
    if not suggestions:
        print(
            "no suggestions right now — everything I can see is already handled "
            "or nothing matches the evidence rules."
        )
        return 0
    print("suggestions (evidence-backed; I will not run anything):")
    canary = issue_canary("cli")
    print(
        f"  canary     : {canary} — if this string ever appears outside this machine,"
        " trace it: jarvis doctor --canaries"
    )
    for suggestion in suggestions:
        assert isinstance(suggestion, dict)
        evidence_list = suggestion["evidence"]
        assert isinstance(evidence_list, list)
        print(f"  [{suggestion['id']}] {suggestion['title']}")
        print(f"      {suggestion['detail']}")
        for evidence in evidence_list:
            assert isinstance(evidence, dict)
            kind = evidence.get("kind", "")
            detail = evidence.get("detail") or evidence.get("claim", "")
            print(f"      evidence: {kind}: {detail}")
        print(f"      accept: jarvis suggest accept {suggestion['id']}")
        print(f'      reject: jarvis suggest reject {suggestion["id"]} --reason "..."')
    return 0


def _lookup_suggestion(suggestion_id: str) -> dict[str, object] | None:
    from jarvis.core.fingerprint import build_profile
    from jarvis.journal.sqlite import Journal

    journal = Journal(default_db_path())
    context = ContextStore(default_context_path())
    for suggestion in generate_suggestions(build_profile(), journal, context):
        data = suggestion.to_json_dict()
        if data["id"] == suggestion_id:
            return data
    return None


def _cmd_context(args: argparse.Namespace) -> int:
    from jarvis.context.routines import infer_routines

    context = ContextStore(default_context_path())
    action = getattr(args, "context_command", None) or "show"

    if action == "prefer":
        try:
            if args.unset:
                removed = context.unset_preference(args.key)
                print(
                    f"removed preference {args.key!r}" if removed else f"no preference {args.key!r}"
                )
                return 0 if removed else 2
            context.set_preference(args.key, args.value)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"preference set: {args.key} = {args.value}")
        print("tunes suggestions only — never authority (ADR-0012)")
        return 0

    if action == "rule":
        try:
            if args.remove_id:
                removed = context.remove_rule(args.remove_id)
                print(f"removed {args.remove_id}" if removed else f"no rule {args.remove_id!r}")
                return 0 if removed else 2
            rule_id = context.add_rule(" ".join(args.text))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"house rule added: [{rule_id}] {' '.join(args.text)}")
        print("matching suggestions are suppressed from listings")
        return 0

    if action == "routines":
        journal = Journal(default_db_path())
        routines = infer_routines(journal)
        if args.json:
            print(json.dumps(routines, indent=2))
            return 0
        if not routines:
            print("no routines yet — recurring patterns appear after repeated journaled use")
            return 0
        print("inferred routines (derived from the journal; nothing persisted):")
        for routine in routines:
            print(
                f"  {routine['playbook_id']:<22} {routine['runs_in_window']}x"
                f"/{routine['window_days']}d  {routine['cadence']:<16}"
                f" confidence={routine['confidence']}"
            )
            if routine["charter_hint"]:
                print(f"    hint: {routine['charter_hint']}")
        return 0

    if action == "forget":
        if not _charter_consent(yes=args.yes, silent=bool(args.json)):
            print(
                "refused: context forget requires explicit consent (destructive)", file=sys.stderr
            )
            return 2
        counts = context.forget_everything()
        total = sum(counts.values())
        print(f"context store forgotten: {total} row(s) removed {counts}")
        return 0

    # show
    rows = context.feedback_rows()
    prefs = context.preferences()
    rules = context.rule_rows()
    if args.json:
        print(json.dumps({"feedback": rows, "preferences": prefs, "rules": rules}, indent=2))
        return 0
    if not rows and not prefs and not rules:
        print("context store: empty (feedback, preferences, and rules all empty)")
        print("this store tunes suggestions only; it never grants authority to act (ADR-0012).")
        return 0
    if rows:
        print(f"feedback — {len(rows)} entr{'y' if len(rows) == 1 else 'ies'}:")
        for row in rows:
            print(
                f"  {row['created_utc']}  {row['decision']:<8} {row['suggestion_id']}"
                + (f" — {row['reason']}" if row["reason"] else "")
            )
    if prefs:
        print(f"preferences — {len(prefs)}:")
        for key, value in prefs.items():
            print(f"  {key} = {value}")
    if rules:
        print(f"house rules — {len(rules)}:")
        for rule in rules:
            print(f"  [{rule['id']}] {rule['rule_text']}")
    print("this store tunes suggestions only; it never grants authority to act (ADR-0012).")
    return 0


def _integrity_line() -> str:
    from jarvis.safety import integrity

    baseline = integrity.default_baseline_path()
    if not baseline.is_file():
        return "no baseline — run: jarvis doctor --write-baseline"
    report = integrity.verify(baseline)
    if report.clean:
        return f"verified ({len(report.rows)} entries, baseline {report.created_utc})"
    return f"DRIFT ({len(report.drift)} entry/ies differ) — run: jarvis doctor"


def _charter_consent(yes: bool, silent: bool) -> bool:
    """T2-grade consent for installing a standing order — the real gate."""
    policy = ApprovalPolicy(yes=yes, silent=silent)
    try:
        policy.decide(Tier.T2, [])
    except ApprovalRefused:
        return False
    return True


def _charter_install(args: argparse.Namespace) -> int:
    import shutil as _shutil

    from jarvis.journal.sqlite import _utcnow
    from jarvis.safety import charter as ch

    doc: dict[str, object] = {
        "schema": ch.CHARTER_SCHEMA,
        "id": args.charter_id,
        "request": args.request,
        "playbooks": list(args.playbook),
        "tier_ceiling": args.tier_ceiling,
        "max_steps_per_run": args.max_steps,
        "monthly_run_budget": args.monthly_runs,
        "on_calendar": args.on_calendar,
        "timeout_start_sec": args.timeout_start_sec,
        "failure_policy": ch.FAILURE_POLICY,
        "created_utc": _utcnow(),
    }
    errors = ch.validate_charter(doc)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2
    tiers = ch.playbook_tiers()
    print("charter contract (a standing order — read every line):")
    print(f"  id        : {args.charter_id}")
    print(f"  request   : {args.request}")
    allow = ", ".join(f"{p} (T{tiers[p]})" if p in tiers else p for p in args.playbook)
    print(f"  allowlist : {allow} — hard ceiling T{args.tier_ceiling} (T3 refused by the kernel)")
    print(
        f"  breakers  : failure->{ch.FAILURE_POLICY} · <={args.max_steps} steps/run ·"
        f" <={args.monthly_runs} runs/30d · TimeoutStartSec={args.timeout_start_sec}"
    )
    schedule = (
        f"systemd user timer ({args.on_calendar})" if args.on_calendar else "manual (no schedule)"
    )
    print(f"  schedule  : {schedule}")
    print("  scope     : every firing is a normal journaled task; nothing outside the allowlist")
    if not _charter_consent(yes=args.yes, silent=bool(args.json)):
        print("refused: charter not installed (no consent)", file=sys.stderr)
        return 2
    try:
        path = ch.write_charter(doc)
    except ch.CharterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"installed: {path}")
    print("policy state changed — review it, then: jarvis doctor --write-baseline")
    if args.on_calendar and not args.no_timer:
        jarvis_path = _shutil.which("jarvis")
        if jarvis_path is None:
            print("timer: jarvis executable not on PATH — schedule manually (jarvis charter run)")
        else:
            service, timer = ch.unit_documents(doc, jarvis_path)
            unit_dir = ch.user_unit_dir()
            unit_dir.mkdir(parents=True, exist_ok=True)
            (unit_dir / f"jarvis-charter-{args.charter_id}.service").write_text(service)
            (unit_dir / f"jarvis-charter-{args.charter_id}.timer").write_text(timer)
            ok_reload, detail = ch.systemctl_user(["daemon-reload"])
            ok_enable, detail2 = ch.systemctl_user(
                ["enable", "--now", f"jarvis-charter-{args.charter_id}.timer"]
            )
            if ok_reload and ok_enable:
                print(f"timer enabled (systemd user): jarvis-charter-{args.charter_id}.timer")
            else:
                print(f"timer NOT enabled ({detail or detail2}) — schedule manually:")
                print(f"  jarvis charter run {args.charter_id}")
    return 0


def _cmd_charter(args: argparse.Namespace) -> int:
    from jarvis.safety import charter as ch

    action = args.charter_command
    if action == "install":
        return _charter_install(args)
    if action == "list":
        journal = Journal(default_db_path())
        contracts = sorted(ch.charters_dir().glob("*.json"))
        if not contracts:
            print("no charters installed (install one with: jarvis charter install)")
            return 0
        print(f"{'id':<20}{'status':<10}{'ceiling':<9}{'runs':<6}{'fail':<6}request")
        for path in contracts:
            doc = json.loads(path.read_text())
            state = ch.read_state(str(doc.get("id", "?")))
            used = ch.count_recent_runs(journal, list(doc.get("playbooks", [])))
            print(
                f"{doc.get('id', '?')!s:<20}{state.get('status', '?')!s:<10}"
                f"T{doc.get('tier_ceiling', '?')!s:<8}"
                f"{used}/{doc.get('monthly_run_budget', '?')!s:<4}"
                f"{state.get('failures', 0)!s:<6}{doc.get('request', '')}"
            )
        return 0
    if action == "run":
        try:
            doc = ch.load_charter(args.charter_id)
            state = ch.read_state(args.charter_id)
        except ch.CharterError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        journal = Journal(default_db_path())
        playbook_id, reason = ch.precheck(doc, state, journal)
        if not playbook_id:
            print(f"error: {reason}", file=sys.stderr)
            return 2
        # Pre-authorized by the charter (owner consented at install); precheck
        # narrowed this firing to the allowlisted playbook at or under the ceiling.
        orch = Orchestrator(
            build_profile(),
            journal,
            LocalRunner(),
            ApprovalPolicy(yes=True, silent=bool(args.json), stdin=io.StringIO()),
            echo=False,
        )
        outcome = orch.run_intent(str(doc["request"]), dry_run=args.dry_run)
        if not args.dry_run:
            ch.record_firing(args.charter_id, outcome.status.value)
        if args.json:
            print(json.dumps(outcome.to_json_dict(), indent=2))
        else:
            _print_outcome(outcome)
        return outcome.exit_code()
    # pause / resume / revoke
    try:
        doc = ch.load_charter(args.charter_id)
    except ch.CharterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if action == "pause":
        ch.set_status(args.charter_id, "paused", reason="paused by owner")
        if doc.get("on_calendar"):
            ch.systemctl_user(["stop", f"jarvis-charter-{args.charter_id}.timer"])
        print(f"paused {args.charter_id} — runs will refuse until: jarvis charter resume")
        return 0
    if action == "resume":
        ch.set_status(args.charter_id, "active", reason="")
        if doc.get("on_calendar"):
            ch.systemctl_user(["start", f"jarvis-charter-{args.charter_id}.timer"])
        print(f"resumed {args.charter_id}")
        return 0
    ch.set_status(args.charter_id, "revoked", reason="revoked by owner")
    if doc.get("on_calendar"):
        ch.systemctl_user(["disable", "--now", f"jarvis-charter-{args.charter_id}.timer"])
    print(
        f"revoked {args.charter_id} — the contract file is kept for audit; firings refuse forever"
    )
    return 0


def _cmd_skill(args: argparse.Namespace) -> int:
    """Verified skill packs: install/list/remove (ADR-0013 M9b)."""
    from jarvis.planner.playbooks import PLAYBOOKS
    from jarvis.planner.skills import SkillError, install_skill, installed_skills, remove_skill

    if args.skill_command == "install":
        pack_file = Path(args.pack_file)
        if not pack_file.is_file():
            print(f"error: no such pack file: {pack_file}", file=sys.stderr)
            return 2
        try:
            candidate = json.loads(pack_file.read_text())
        except json.JSONDecodeError as exc:
            print(f"error: pack is not valid JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(candidate, dict):
            print("error: pack must be a JSON object", file=sys.stderr)
            return 2
        playbook = next((pb for pb in PLAYBOOKS if pb.id == candidate.get("playbook")), None)
        evals = candidate.get("evals")
        print("skill pack (extends matching vocabulary — read every field):")
        print(f"  id        : {candidate.get('id', '?')}")
        print(f"  match     : {candidate.get('match', '?')}")
        print(
            f"  playbook  : {candidate.get('playbook', '?')}"
            + (
                f" (tier T{int(playbook.tier)}, inherited — packs never set tiers)"
                if playbook
                else ""
            )
        )
        prov = candidate.get("provenance")
        provenance = prov.get("source", "?") if isinstance(prov, dict) else "?"
        eval_count = len(evals) if isinstance(evals, list) else 0
        print(f"  evals     : {eval_count} case(s), dry-run now")
        print(f"  provenance: {provenance}")
        if not _charter_consent(yes=args.yes, silent=bool(args.json)):
            print("refused: skill pack not installed (no consent)", file=sys.stderr)
            return 2
        try:
            installed = install_skill(pack_file, source=args.source)
        except SkillError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"installed: {installed['path']}")
        print(f"  sha256    : {installed['sha256']}")
        print("policy state changed — review it, then: jarvis doctor --write-baseline")
        return 0

    if args.skill_command == "list":
        rows = installed_skills()
        if not rows:
            print("no skill packs installed (install one with: jarvis skill install <file>)")
            return 0
        print(f"{'id':<24}{'status':<10}playbook")
        for row in rows:
            doc = json.loads(Path(str(row["path"])).read_text())
            errors = row["errors"]
            error_list = errors if isinstance(errors, list) else []
            suffix = (" — " + "; ".join(str(e) for e in error_list)) if error_list else ""
            print(f"{row['id']!s:<24}{row['status']!s:<10}{doc.get('playbook', '?')}{suffix}")
        return 0

    # remove
    if remove_skill(args.skill_id):
        print(f"removed {args.skill_id} — policy state changed; review: jarvis doctor")
        return 0
    print(f"error: no skill pack {args.skill_id!r} (list with: jarvis skill list)", file=sys.stderr)
    return 2


def _cmd_grow(args: argparse.Namespace) -> int:
    """Supervised growth (ADR-0012 M8d): draft, list, show, prune, export."""
    from jarvis.knowledge.store import load_kb
    from jarvis.planner.grow import (
        draft_fact,
        draft_skill,
        export_proposal,
        list_proposals,
        prune_proposal,
        show_proposal,
    )

    try:
        if args.grow_command == "fact":
            fact: dict[str, object] = {
                "id": args.fact_id,
                "topic": args.topic,
                "claim": args.claim,
                "patterns": [pat.strip() for pat in args.pattern.split(",") if pat.strip()],
                "sources": json.loads(args.sources),
            }
            if args.verify_kind:
                verify: dict[str, object] = {"kind": args.verify_kind}
                if args.verify_arg:
                    verify["arg"] = args.verify_arg
                fact["verify"] = verify
            try:
                load_kb()  # prove the live store loads before drafting against it
            except Exception as exc:  # pragma: no cover - defensive
                print(f"error: live KB unusable: {exc}", file=sys.stderr)
                return 1
            result = draft_fact(fact, rationale=args.rationale)
            print(f"drafted fact proposal: {result['path']}")
            print("the citation-required store accepted it; promote via: jarvis grow export")
            return 0
        if args.grow_command == "skill":
            pack_file = Path(args.pack_file)
            result = draft_skill(pack_file, rationale=args.rationale)
            print(f"drafted skill proposal: {result['path']}")
            print("owner installs it via: jarvis --yes skill install <file> (evals re-run)")
            return 0
        if args.grow_command == "list":
            rows = list_proposals()
            if not rows:
                print("no growth proposals pending")
                return 0
            for row in rows:
                print(
                    f"  [{row['kind']}] {row['id']:<28} proposed {row['proposed_utc']}"
                    + (f" — {row['rationale']}" if row["rationale"] else "")
                )
            return 0
        if args.grow_command == "show":
            print(show_proposal(args.proposal_id))
            return 0
        if args.grow_command == "prune":
            if prune_proposal(args.proposal_id):
                print(f"pruned {args.proposal_id}")
                return 0
            print(f"no proposal {args.proposal_id!r}", file=sys.stderr)
            return 2
        # export
        exported = export_proposal(args.proposal_id, Path(args.out))
        print(f"exported [{exported['kind']}] {args.proposal_id} -> {exported['artifact']}")
        print("owner actions (JARVIS never opens or merges PRs):")
        commands = exported["commands"]
        assert isinstance(commands, list)
        for command in commands:
            print(f"  {command}")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Policy-state integrity: baseline, drift verification, canaries (M9c)."""
    from jarvis.safety import integrity

    if getattr(args, "canaries", False):
        records = integrity.read_canaries()
        if not records:
            print("no canaries issued yet (each suggestion render records one)")
            return 0
        print(f"{len(records)} canary issuance(s) — if any string below appears off-machine,")
        print("the corresponding suggestion output leaked:")
        for record in records:
            print(f"  {record['issued_utc']}  [{record['surface']}] {record['canary']}")
        return 0
    if args.write_baseline:
        document = integrity.write_baseline(integrity.default_baseline_path())
        entries = document["entries"]
        assert isinstance(entries, dict)
        print(f"baseline written: {len(entries)} entries -> {integrity.default_baseline_path()}")
        print("re-baseline deliberately after each reviewed upgrade; `jarvis doctor` verifies.")
        return 0
    baseline = integrity.default_baseline_path()
    if not baseline.is_file():
        print("no integrity baseline yet — silent drift of policy-relevant state")
        print("(KB, playbooks, safety kernel, ingresses, cautious flag) cannot be detected.")
        print("review the current state, then write the baseline explicitly:")
        print("  jarvis doctor --write-baseline")
        return 2
    report = integrity.verify(baseline)
    context_report = ContextStore(default_context_path()).verify_integrity()
    poisoned = not bool(context_report["ok"])
    if args.json:
        print(
            json.dumps(
                {
                    "clean": report.clean and not poisoned,
                    "baseline_version": report.baseline_version,
                    "baseline_created_utc": report.created_utc,
                    "entries": len(report.rows),
                    "drift": [
                        {"path": str(row.path), "status": row.status, "detail": row.detail}
                        for row in report.drift
                    ],
                    "context_store": context_report,
                },
                indent=2,
            )
        )
        return 0 if report.clean and not poisoned else 1
    print(
        f"context store  : {'ok' if not poisoned else 'TAMPERED'}"
        f" ({context_report['total']} entries, {context_report['hashed']} hashed,"
        f" {context_report['legacy_unhashed']} legacy)"
        + (f" — {context_report['detail']}" if poisoned else "")
    )
    try:
        doctor_routing = plan_routing()
        doctor_views = _breaker().views()
        doctor_state = (
            ", ".join(f"{n}:{v['state']}" for n, v in sorted(doctor_views.items())) or "clean"
        )
        print(
            f"ai backend     : {doctor_routing.mode} (breaker: {doctor_state})"
            " — informational; env-dependent, not baseline-scoped (ADR-0014 D8)"
        )
    except Exception:
        pass
    if report.clean and not poisoned:
        print(
            f"integrity: OK — {len(report.rows)} entries match the baseline "
            f"({report.created_utc}, jarvis {report.baseline_version})."
        )
        return 0
    if poisoned:
        print(
            "context store integrity FAILED — see detail above; treat stored feedback as suspect."
        )
    if not report.clean:
        print(
            f"integrity: DRIFT — {len(report.drift)} of {len(report.rows)} entries differ "
            f"from the baseline ({report.created_utc}):"
        )
        for row in report.drift:
            print(f"  [{row.status}] {row.path} — {row.detail}")
        print(
            "review every change above; re-baseline only what is expected"
            " (e.g. a reviewed upgrade):"
        )
        print("  jarvis doctor --write-baseline")
    return 1


def _cmd_mcp_describe(args: argparse.Namespace) -> int:
    """Print the machine-readable front-end contract (J.A.V.R.I.S.-GUI wiring)."""
    from jarvis.cli.mcp_server import frontend_contract

    print(json.dumps(frontend_contract(), indent=2, sort_keys=True))
    return 0


def _cmd_mcp_serve(args: argparse.Namespace) -> int:
    """Serve the MCP tool/resource surface on stdio (ADR-0013 M9a)."""
    from jarvis.cli.mcp_server import MCPServer

    print(
        "[jarvis] MCP server on stdio: newline-delimited JSON-RPC 2.0; "
        "consent tiers unchanged (T2 needs per-call allow:true, T3 refused)",
        file=sys.stderr,
    )
    stdin = cast(io.TextIOBase, sys.stdin)
    stdout = cast(io.TextIOBase, sys.stdout)
    return MCPServer(stdin, stdout).serve()


def _cmd_serve_run(args: argparse.Namespace) -> int:
    """Run the resident doorway in the foreground (ADR-0018)."""
    from jarvis.cli.serve import ensure_token, run_server

    return run_server(args.bind, args.port, ensure_token())


def _cmd_serve_install(args: argparse.Namespace) -> int:
    """Install the opt-in residency (systemd --user unit, optional GUI autostart)."""
    from jarvis.cli.serve import install

    return install(
        args.port,
        with_gui=args.with_gui,
        home=Path.home(),
    )


def _cmd_serve_uninstall(args: argparse.Namespace) -> int:
    from jarvis.cli.serve import uninstall

    return uninstall(Path.home())


def _cmd_serve_status(args: argparse.Namespace) -> int:
    from jarvis.cli.serve import status

    return status(Path.home())


def _cmd_voice(args: argparse.Namespace) -> int:
    """Voice front-end (ADR-0019): doctor / say / ask — kernel parity, T2 typed-consent only."""
    from jarvis.voice.detect import detect
    from jarvis.voice.pipeline import VoicePipeline, _clean_text

    caps = detect()
    pipeline = VoicePipeline(caps)

    if args.voice_command in (None, "doctor"):
        import json

        print(json.dumps(caps.to_json_dict(), indent=2))
        missing = caps.missing_for_full_loop()
        if missing:
            print("missing for full spoken loop:")
            for item in missing:
                print(f"  - {item}")
        else:
            print("full spoken round-trip available")
        print(
            "consent: T0/T1 proceed as on a non-tty CLI; T2 is NOT voice-consentable "
            "(type it with --yes); hands-free wake word is parked (ADR-0019 D3)."
        )
        return 0

    if args.voice_command == "say":
        text = _clean_text(" ".join(args.text), "text")
        spoken = pipeline.speak(text)
        print(text if not spoken else f"[spoken] {text}")
        return 0

    # ask
    wav_arg = getattr(args, "wav", None)
    if wav_arg:
        wav = Path(wav_arg).expanduser()
        if not wav.is_file():
            print(f"error: no such wav file: {wav}", file=sys.stderr)
            return 2
    else:
        wav = pipeline.record(args.seconds)
    heard = pipeline.transcribe(wav)
    print(f"heard: {heard}")
    summary, _outcome, spoken = pipeline.ask(heard)
    print(summary if not spoken else f"[spoken] {summary}")
    return 0


def _cmd_memory(args: argparse.Namespace) -> int:
    """Owner-taught memory (ADR-0020): list / remember / forget / show."""
    from jarvis.memory.store import MemoryStore
    from jarvis.safety.tiers import SafetyRefusal

    store = MemoryStore()
    try:
        action = args.memory_command
        if action == "remember":
            entry = store.remember(" ".join(args.text), source="cli")
            print(f"remembered {entry.entry_id}: {entry.text}")
            return 0
        if action == "list":
            entries = store.list_entries()
            print(f"{len(entries)} memor{'y' if len(entries) == 1 else 'ies'}")
            for entry in entries:
                meta = f"[{entry.origin}/{entry.source}]"
                print(f"  {entry.entry_id}  {entry.created}  {meta}  {entry.text}")
            return 0
        if action == "show":
            entry = store.get(args.entry_id)
            print(f"id      : {entry.entry_id}")
            print(f"created : {entry.created}")
            print(f"origin  : {entry.origin} ({entry.source})")
            print(f"text    : {entry.text}")
            return 0
        # forget
        if args.all:
            count = store.forget_all()
            print(f"forgot {count} memor{'y' if count == 1 else 'ies'}")
            return 0
        if not args.entry_id:
            print("error: give a memory id or --all", file=sys.stderr)
            return 2
        store.forget(args.entry_id)
        print(f"forgot {args.entry_id}")
        return 0
    except SafetyRefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


def _cmd_brief(args: argparse.Namespace) -> int:
    """Scheduled briefings (ADR-0021): run / status / accept / dismiss / install / uninstall."""
    import json as _json

    from jarvis.brief.engine import BriefLedger, run_once
    from jarvis.safety.tiers import SafetyRefusal

    action = getattr(args, "brief_command", None)
    ledger = BriefLedger()
    try:
        if action in (None, "run"):
            payload = run_once(
                quiet=bool(getattr(args, "quiet", False)),
                json_output=bool(getattr(args, "json", False)),
            )
            if args.json:
                print(_json.dumps(payload, indent=2))
            return 0
        if action == "status":
            print(_json.dumps(ledger.stats(), indent=2))
            return 0
        if action in ("accept", "dismiss"):
            ledger.record_feedback(args.briefing_id, action)
            print(f"{action}ed {args.briefing_id} (recorded; policy learning is parked)")
            return 0
        if action == "install":
            from jarvis.brief.install import install_timer

            return install_timer(args.on, Path.home())
        if action == "uninstall":
            from jarvis.brief.install import uninstall_timer

            return uninstall_timer(Path.home())
    except SafetyRefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_desktop(args: argparse.Namespace) -> int:
    """Guarded desktop awareness (ADR-0022): read / status — walls + audit."""
    import json as _json

    from jarvis.desktop.read import DesktopAudit, read_desktop
    from jarvis.gui.atspi import atspi_available
    from jarvis.safety.tiers import SafetyRefusal

    action = getattr(args, "desktop_command", None) or "read"
    try:
        if action == "read":
            result, reason = read_desktop(source="cli")
            if result is None:
                print(f"desktop awareness unavailable here: {reason}")
                print("read-only tier; nothing was read and nothing was audited")
                return 0
            for line in result.lines:
                print(line)
            audit = DesktopAudit()
            print(
                f"guard summary: {len(result.apps_blocked)} app(s) withheld, "
                f"{result.roles_withheld} password field(s) withheld, "
                f"{result.names_redacted} name(s) redacted, "
                f"{result.nodes_read} node(s)"
                + (", TRUNCATED (node budget)" if result.truncated else "")
            )
            print(f"audit: {audit.path} (content-free: counts only, never titles)")
            return 0
        if action == "status":
            print(_json.dumps({"available": atspi_available(), **DesktopAudit().stats()}, indent=2))
            return 0
    except SafetyRefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_ai(args: argparse.Namespace) -> int:
    """AI subsystem status (ADR-0025 D3): both paths, honestly, never the key."""
    import json as _json

    from jarvis.providers.breaker import ProviderBreaker, default_breaker_path
    from jarvis.providers.ollama import DEFAULT_HOST, OllamaProvider
    from jarvis.providers.openai_compatible import (
        DEFAULT_BASE_URL,
        KEY_ENV,
        OpenAICompatibleProvider,
    )
    from jarvis.providers.router import NO_AI_ENV, remote_allowed

    enabled = _ai_enabled(args)
    local = OllamaProvider(
        host=os.environ.get("OLLAMA_HOST"), model=os.environ.get("JARVIS_LOCAL_MODEL")
    )
    key_set = bool(os.environ.get(KEY_ENV, "").strip())
    remote = OpenAICompatibleProvider()
    breaker = ProviderBreaker(default_breaker_path())
    views = breaker.views()

    def _breaker_of(name: str) -> dict[str, object]:
        record = views.get(name) or {"state": "closed"}
        return dict(record) if isinstance(record, dict) else {"state": "closed"}

    payload: dict[str, object] = {
        "ai_enabled": enabled,
        "disable_switches": ["--no-ai", f"{NO_AI_ENV}=1"],
        "local": {
            "endpoint": local._base if hasattr(local, "_base") else DEFAULT_HOST,
            "model": local.model,
            "endpoint_up": local.available(),
            "breaker": _breaker_of(local.name),
        },
        "remote": {
            "allowed": remote_allowed(),
            "configured": key_set,
            "base_url": remote._base if hasattr(remote, "_base") else DEFAULT_BASE_URL,
            "model": remote.model,
            "endpoint_up": remote.available() if key_set else False,
            "breaker": _breaker_of(remote.name),
        },
        "precedence": "deterministic engine -> local -> remote (opt-in) -> honest refusal",
        "failover": "local and remote are both attempted when configured; "
        "the serving backend is always disclosed (ADR-0025 D3)",
    }
    print(_json.dumps(payload, indent=2))
    return 0


def _cmd_appskill(args: argparse.Namespace) -> int:
    """Owner-taught app packs (ADR-0026 D4): wizard / list / show / remove."""
    import json as _json

    from jarvis.gui import appskill
    from jarvis.planner.playbooks import PLAYBOOKS
    from jarvis.safety.tiers import SafetyRefusal

    action = getattr(args, "appskill_command", None)
    try:
        if action == "wizard":
            raw = Path(args.file).read_text(encoding="utf-8")
            document = _json.loads(raw)
            pack_id_hint = ""
            if isinstance(document, dict) and isinstance(document.get("id"), str):
                pack_id_hint = document["id"]
            replacing = bool(pack_id_hint) and appskill.load_pack(pack_id_hint) is not None
            result: dict[str, object] = appskill.install_pack(document)
            raw_pack = result["pack"]
            pack = raw_pack if isinstance(raw_pack, dict) else {}
            pack_id = str(pack["id"])
            # the eval discipline: the real playbook must construct the pack
            playbook = next((pb for pb in PLAYBOOKS if pb.id == "gui.app"), None)
            if playbook is None:  # pragma: no cover - registry constant
                raise SystemExit("gui.app playbook missing")
            steps = playbook.build({"pack": pack_id}, None)  # type: ignore[arg-type]
            if replacing:
                print(
                    f"[jarvis] replacing existing pack {pack_id!r} (previous receipt invalidated)"
                )
            print(f"[jarvis] app pack {pack_id!r} validated: {len(steps)} step(s) constructed")
            for i, step in enumerate(steps, 1):
                print(f"  {i}. {step.description}")
            print(f"[jarvis] installed: {result['path']}")
            print(f"[jarvis] receipt sha256: {result['sha256']}")
            print('[jarvis] run it: jarvis do "<one of your phrases>"  (consent-gated T2)')
            return 0
        if action == "list":
            packs = appskill.installed_packs()
            if not packs:
                print("no app packs installed (jarvis app-skill wizard --file <pack> to teach one)")
                return 0
            for pack in packs:
                raw_phrases = pack.get("phrases")
                phrases = raw_phrases if isinstance(raw_phrases, list) else []
                first = str(phrases[0]) if phrases else ""
                raw_steps = pack.get("steps")
                step_count = len(raw_steps) if isinstance(raw_steps, list) else 0
                print(f"  {pack['id']!s:<24} steps={step_count:<3} {first}")
            return 0
        if action == "show":
            loaded = appskill.load_pack(args.pack_id)
            if loaded is None:
                print(
                    f"refused: pack {args.pack_id!r} is missing or its receipt has drifted",
                    file=sys.stderr,
                )
                return 2
            print(_json.dumps(loaded, indent=2))
            return 0
        if action == "remove":
            removed = appskill.remove_pack(args.pack_id)
            if not removed:
                print(f"nothing to remove for {args.pack_id!r}")
                return 0
            print(f"removed {args.pack_id!r} ({removed} file(s)); phrase(s) no longer match")
            return 0
    except SafetyRefusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except (_json.JSONDecodeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description=(
            "JARVIS — Just A Rather Very Intelligent System: a verified, "
            "safety-kernelled automation agent for Linux."
        ),
    )
    parser.add_argument("--version", action="version", version=f"jarvis {__version__}")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--yes", action="store_true", help="consent non-interactively to T2 actions"
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help=(
            "disable every AI/LLM path this run — deterministic engine, cited KB answers, "
            "journal only (also JARVIS_NO_AI=1)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="fingerprint this machine (read-only)")
    p_status.set_defaults(func=_cmd_status)

    p_do = sub.add_parser("do", help='execute a request, e.g. jarvis do "install htop"')
    p_do.add_argument("--dry-run", action="store_true", help="print the plan; execute nothing")
    p_do.add_argument(
        "--preview",
        action="store_true",
        help="show the full plan + blast radius; never asks, never executes",
    )
    p_do.add_argument(
        "--cautious-ok",
        action="store_true",
        help="execute this one T2+ action while cautious mode is ON",
    )
    p_do.add_argument("text", nargs="+", help="natural-language request")
    p_do.set_defaults(func=_cmd_do)

    p_undo = sub.add_parser("undo", help="undo a previous task by id (see: jarvis tasks)")
    p_undo.add_argument("--dry-run", action="store_true", help="print the undo plan only")
    p_undo.add_argument("task_id", help="task id from the journal")
    p_undo.set_defaults(func=_cmd_undo)

    p_pb = sub.add_parser("playbooks", help="list known playbooks")
    p_pb.set_defaults(func=_cmd_playbooks)

    p_tasks = sub.add_parser("tasks", help="list recent journaled tasks")
    p_tasks.add_argument("--limit", type=int, default=20)
    p_tasks.set_defaults(func=_cmd_tasks)

    p_ask = sub.add_parser(
        "ask",
        help="engine-first request; an LLM planner handles what playbooks cannot",
    )
    p_ask.add_argument("--dry-run", action="store_true", help="print the plan only")
    p_ask.add_argument("text", nargs="+", help="natural-language request")
    p_ask.set_defaults(func=_cmd_ask)

    p_chat = sub.add_parser("chat", help="interactive chat (engine + planner)")
    p_chat.set_defaults(func=_cmd_chat)

    p_file = sub.add_parser("file", help="guarded single-line file edits (ADR-0008)")
    p_file_sub = p_file.add_subparsers(dest="file_command", required=True)
    p_file_append = p_file_sub.add_parser(
        "append", help="append one line; a backup is taken and undo restores it"
    )
    p_file_append.add_argument("path", help="absolute target path (~ allowed)")
    p_file_append.add_argument("text", nargs="+", help="single-line text to append")
    p_file_append.add_argument("--dry-run", action="store_true")
    p_file_append.set_defaults(func=_cmd_file)

    p_explain = sub.add_parser(
        "explain", help="answer a question from cited knowledge (cite-or-abstain)"
    )
    p_explain.add_argument("question", nargs="+", help="e.g. 'what is ostype'")
    p_explain.set_defaults(func=_cmd_explain)

    p_facts = sub.add_parser("facts", help="browse the knowledge base")
    p_facts.add_argument("topic", nargs="?", default=None, help="filter by topic")
    p_facts.set_defaults(func=_cmd_facts)

    p_gui = sub.add_parser(
        "gui", help="desktop control: capability matrix + consent-gated actions (ADR-0010)"
    )
    p_gui_sub = p_gui.add_subparsers(dest="gui_command", required=True)
    for name, help_text in (
        ("status", "show this machine's GUI capability matrix"),
        ("wizard", "ydotool readiness wizard with distro-specific fixes"),
        ("windows", "list windows via the session backend"),
    ):
        p_sub = p_gui_sub.add_parser(name, help=help_text)
        p_sub.set_defaults(func=_cmd_gui, gui_command=name)
    p_open = p_gui_sub.add_parser("open", help="launch an app detached (T2, consent-gated)")
    p_open.add_argument("argv", nargs="+", help="app name + args, PATH lookup only")
    p_open.set_defaults(func=_cmd_gui, gui_command="open")
    p_focus = p_gui_sub.add_parser("focus", help="focus a window by title (T2)")
    p_focus.add_argument("title", help="case-insensitive substring; must be unique")
    p_focus.set_defaults(func=_cmd_gui, gui_command="focus")
    p_type = p_gui_sub.add_parser(
        "type", help="type text into the FOCUSED window (T2; target disclosed first)"
    )
    p_type.add_argument("text", nargs="+", help="single-line text, no control chars")
    p_type.set_defaults(func=_cmd_gui, gui_command="type")
    p_key = p_gui_sub.add_parser("key", help="send a key combo to the FOCUSED window (T2)")
    p_key.add_argument("combo", help="e.g. Return, ctrl+c, super")
    p_key.set_defaults(func=_cmd_gui, gui_command="key")
    p_shot = p_gui_sub.add_parser("screenshot", help="capture the screen (T2: privacy)")
    p_shot.add_argument("path", help="output PNG path")
    p_shot.set_defaults(func=_cmd_gui, gui_command="screenshot")
    p_close = p_gui_sub.add_parser("close", help="close a window (graceful WM delete, T2)")
    p_close.add_argument("title", help="case-insensitive substring; must be unique")
    p_close.set_defaults(func=_cmd_gui, gui_command="close")
    p_describe = p_gui_sub.add_parser(
        "describe", help="describe a screenshot with a local vision model (abstains if absent)"
    )
    p_describe.add_argument("path", help="PNG path (e.g. from 'jarvis gui screenshot')")
    p_describe.add_argument("question", nargs="*", default=[], help="optional question")
    p_describe.set_defaults(func=_cmd_gui, gui_command="describe")

    p_safety = sub.add_parser(
        "safety-check",
        help="prove the refusal guards are alive on this machine (no side effects)",
    )
    p_safety.set_defaults(func=_cmd_safety_check)

    p_cautious = sub.add_parser(
        "cautious",
        help="early-days guard: block T2+ actions until you trust this machine's setup",
    )
    p_cautious.add_argument("action", nargs="?", default="status", choices=["on", "off", "status"])
    p_cautious.set_defaults(func=_cmd_cautious)

    p_suggest = sub.add_parser(
        "suggest",
        help="evidence-backed suggestions (read-only; nothing runs without you)",
    )
    p_suggest_sub = p_suggest.add_subparsers(dest="suggest_command")
    p_suggest_acc = p_suggest_sub.add_parser(
        "accept", help="accept a suggestion (prints the command)"
    )
    p_suggest_acc.add_argument("suggestion_id")
    p_suggest_acc.set_defaults(func=_cmd_suggest, reason="")
    p_suggest_rej = p_suggest_sub.add_parser(
        "reject", help="reject a suggestion (suppressed henceforth)"
    )
    p_suggest_rej.add_argument("suggestion_id")
    p_suggest_rej.add_argument("--reason", default="", help="why (calibration signal)")
    p_suggest_rej.set_defaults(func=_cmd_suggest)
    p_suggest.set_defaults(func=_cmd_suggest)

    p_context = sub.add_parser(
        "context", help="local context store: show/prefer/rule/routines/forget (M8b)"
    )
    p_context_sub = p_context.add_subparsers(dest="context_command")
    p_context_show = p_context_sub.add_parser("show", help="show everything stored about you")
    p_context_show.set_defaults(func=_cmd_context)
    p_ctx_prefer = p_context_sub.add_parser(
        "prefer", help="set a preference (e.g. suppress.undo=1); tunes suggestions only"
    )
    p_ctx_prefer.add_argument("key")
    p_ctx_prefer.add_argument("value", nargs="?", default="")
    p_ctx_prefer.add_argument("--unset", action="store_true")
    p_ctx_prefer.set_defaults(func=_cmd_context)
    p_ctx_rule = p_context_sub.add_parser("rule", help="house rules: add (default) or --remove")
    p_ctx_rule.add_argument("text", nargs="*", help="rule text, e.g. never touch docker")
    p_ctx_rule.add_argument("--remove", dest="remove_id", default="")
    p_ctx_rule.set_defaults(func=_cmd_context)
    p_ctx_routines = p_context_sub.add_parser(
        "routines", help="inferred routines from the journal (read-only, never persisted)"
    )
    p_ctx_routines.set_defaults(func=_cmd_context)
    p_ctx_forget = p_context_sub.add_parser(
        "forget", help="delete the ENTIRE context store (consent-gated, destructive)"
    )
    p_ctx_forget.set_defaults(func=_cmd_context)
    p_context.set_defaults(func=_cmd_context)

    p_grow = sub.add_parser(
        "grow", help="supervised growth: draft fact/skill proposals; owner promotes (M8d)"
    )
    p_grow_sub = p_grow.add_subparsers(dest="grow_command", required=True)
    p_grow_fact = p_grow_sub.add_parser(
        "fact", help="draft a KB fact proposal (validated by the citation-required store)"
    )
    p_grow_fact.add_argument("--id", dest="fact_id", required=True)
    p_grow_fact.add_argument("--topic", required=True)
    p_grow_fact.add_argument("--claim", required=True)
    p_grow_fact.add_argument("--pattern", required=True, help="comma-separated question patterns")
    p_grow_fact.add_argument(
        "--sources", required=True, help="JSON list of sources (kind/ref[/url])"
    )
    p_grow_fact.add_argument(
        "--verify-kind",
        default="",
        choices=[
            "",
            "file_equals",
            "file_exists",
            "os_release_field",
            "binary_present",
            "command_ok",
        ],
    )
    p_grow_fact.add_argument("--verify-arg", default="")
    p_grow_fact.add_argument("--rationale", default="")
    p_grow_fact.set_defaults(func=_cmd_grow)
    p_grow_skill = p_grow_sub.add_parser(
        "skill", help="draft a skill-pack proposal (validated by the M9b machinery)"
    )
    p_grow_skill.add_argument("pack_file")
    p_grow_skill.add_argument("--rationale", default="")
    p_grow_skill.set_defaults(func=_cmd_grow)
    for name, help_text, extra in (
        ("list", "list pending growth proposals", False),
        ("show", "print a proposal's full JSON", False),
        ("prune", "delete a proposal", False),
        ("export", "export the ready-to-PR artifact + owner commands", True),
    ):
        p_grow_action = p_grow_sub.add_parser(name, help=help_text)
        if extra:
            p_grow_action.add_argument("--out", required=True)
            p_grow_action.add_argument("proposal_id")
        else:
            p_grow_action.add_argument("proposal_id", nargs="?" if name == "list" else None)
        p_grow_action.set_defaults(func=_cmd_grow)

    p_mcp = sub.add_parser("mcp", help="Model Context Protocol surface (ADR-0013 M9a)")
    p_mcp_sub = p_mcp.add_subparsers(dest="mcp_command", required=True)
    p_mcp_serve = p_mcp_sub.add_parser(
        "serve",
        help=(
            "serve fixed tools (status/facts/explain/suggest/preview/do) and "
            "resources over stdio JSON-RPC; an MCP client fronts the same "
            "kernel — consent tiers unchanged, no passthrough exec"
        ),
    )
    p_mcp_serve.set_defaults(func=_cmd_mcp_serve)
    p_mcp_describe = p_mcp_sub.add_parser(
        "describe",
        help="print the machine-readable front-end contract (transport, tools, consent)",
    )
    p_mcp_describe.set_defaults(func=_cmd_mcp_describe)

    p_serve = sub.add_parser(
        "serve",
        help="hybrid residency (ADR-0018): run / install / uninstall / status the loopback doorway",
        description=(
            "Opt-in resident doorway: loopback-only, token-authed HTTP over the SAME "
            "six MCP tools and consent semantics. The agent itself stays on-demand; "
            "'install' adds a systemd --user unit so the doorway exists after login. "
            "Packaging never enables this; only you do."
        ),
    )
    p_serve.add_argument("--bind", default="127.0.0.1", help="loopback address only")
    p_serve.add_argument("--port", type=int, default=8777)
    p_serve.set_defaults(func=_cmd_serve_run)  # bare `jarvis serve` runs the doorway
    p_serve_sub = p_serve.add_subparsers(dest="serve_command")
    p_serve_run = p_serve_sub.add_parser(
        "run", help="run the doorway in the foreground (default when no subcommand)"
    )
    p_serve_run.set_defaults(func=_cmd_serve_run)
    p_serve_install = p_serve_sub.add_parser(
        "install", help="write + enable the systemd --user unit (and optionally GUI autostart)"
    )
    p_serve_install.add_argument("--port", type=int, default=8777)
    p_serve_install.add_argument(
        "--with-gui",
        action="store_true",
        help="also write an XDG autostart entry for the GUI frontend (probed first)",
    )
    p_serve_install.set_defaults(func=_cmd_serve_install)
    p_serve_uninstall = p_serve_sub.add_parser(
        "uninstall", help="remove unit/autostart/token; back to pure on-demand"
    )
    p_serve_uninstall.set_defaults(func=_cmd_serve_uninstall)
    p_serve_status = p_serve_sub.add_parser(
        "status", help="report the truth of each residency piece"
    )
    p_serve_status.set_defaults(func=_cmd_serve_status)

    p_voice = sub.add_parser(
        "voice",
        help="voice front-end (ADR-0019): doctor / say / ask — same kernel, same consent tiers",
        description=(
            "Push-to-talk voice: record -> transcribe -> the SAME safety kernel -> speak. "
            "External binaries only (whisper-class STT, piper TTS; arecord recorder); "
            "no new Python dependencies. T2 is not voice-consentable: type such requests "
            "with --yes. 'doctor' reports honestly what this machine can do."
        ),
    )
    p_voice_sub = p_voice.add_subparsers(dest="voice_command")
    p_voice.set_defaults(func=_cmd_voice, voice_command=None)  # bare = doctor
    p_voice_sub.add_parser("doctor", help="report voice capability truthfully").set_defaults(
        func=_cmd_voice, voice_command="doctor"
    )
    p_voice_say = p_voice_sub.add_parser("say", help="speak a short text (<=500 chars)")
    p_voice_say.add_argument("text", nargs="+")
    p_voice_say.set_defaults(func=_cmd_voice, voice_command="say")
    p_voice_ask = p_voice_sub.add_parser(
        "ask", help="record (or --wav), transcribe, run through the kernel, speak the outcome"
    )
    p_voice_ask.add_argument("--wav", help="transcribe this file instead of recording")
    p_voice_ask.add_argument(
        "--seconds", type=int, default=5, help="record duration, 1..15 (default 5)"
    )
    p_voice_ask.set_defaults(func=_cmd_voice, voice_command="ask")

    p_memory = sub.add_parser(
        "memory",
        help="owner-taught memory (ADR-0020): list / remember / forget / show",
        description=(
            "Small, plain-file, owner-taught memories. Writes are hygiene-checked "
            "and prompt-injection-scanned; the LLM planner reads them as bounded, "
            "delimited, non-instructional context. Purge anytime: forget --all."
        ),
    )
    p_memory_sub = p_memory.add_subparsers(dest="memory_command", required=True)
    p_mem_list = p_memory_sub.add_parser("list", help="list memories, newest first")
    p_mem_list.set_defaults(func=_cmd_memory, memory_command="list")
    p_mem_remember = p_memory_sub.add_parser(
        "remember", help='store a fact, e.g. remember "deploy user is admin"'
    )
    p_mem_remember.add_argument("text", nargs="+")
    p_mem_remember.set_defaults(func=_cmd_memory, memory_command="remember")
    p_mem_forget = p_memory_sub.add_parser("forget", help="forget one id, or --all")
    p_mem_forget.add_argument("entry_id", nargs="?")
    p_mem_forget.add_argument("--all", action="store_true")
    p_mem_forget.set_defaults(func=_cmd_memory, memory_command="forget")
    p_mem_show = p_memory_sub.add_parser("show", help="show one memory with provenance")
    p_mem_show.add_argument("entry_id")
    p_mem_show.set_defaults(func=_cmd_memory, memory_command="show")

    p_brief = sub.add_parser(
        "brief",
        help="scheduled propose-only briefings (ADR-0021): run / status / feedback / install",
        description=(
            "Level-2 proactivity: a daily computed briefing (failures, suggestions, "
            "unmapped requests, disk pressure) with a deterministic notify-or-silence "
            "policy. Briefings never execute anything; every decision is ledgered; "
            "silence is reported. The timer is opt-in: 'brief install'."
        ),
    )
    p_brief_sub = p_brief.add_subparsers(dest="brief_command")
    p_brief.set_defaults(func=_cmd_brief, brief_command=None)  # bare = run
    p_brief_run = p_brief_sub.add_parser("run", help="compose + decide + deliver + ledger")
    p_brief_run.add_argument("--quiet", action="store_true", help="print only when notifying")
    p_brief_run.set_defaults(func=_cmd_brief, brief_command="run")
    p_brief_sub.add_parser("status", help="runs, silence rate, feedback counts").set_defaults(
        func=_cmd_brief, brief_command="status"
    )
    p_brief_acc = p_brief_sub.add_parser("accept", help="record acceptance of a briefing id")
    p_brief_acc.add_argument("briefing_id")
    p_brief_acc.set_defaults(func=_cmd_brief, brief_command="accept")
    p_brief_dis = p_brief_sub.add_parser("dismiss", help="record dismissal of a briefing id")
    p_brief_dis.add_argument("briefing_id")
    p_brief_dis.set_defaults(func=_cmd_brief, brief_command="dismiss")
    p_brief_ins = p_brief_sub.add_parser(
        "install", help="write + enable a systemd --user timer (opt-in)"
    )
    p_brief_ins.add_argument("--on", choices=("daily", "weekly"), default="daily")
    p_brief_ins.set_defaults(func=_cmd_brief, brief_command="install")
    p_brief_sub.add_parser("uninstall", help="remove the timer; back to on-demand").set_defaults(
        func=_cmd_brief, brief_command="uninstall"
    )

    p_desktop = sub.add_parser(
        "desktop",
        help="guarded desktop awareness: read-only AT-SPI with walls + audit (ADR-0022)",
    )
    p_desktop_sub = p_desktop.add_subparsers(dest="desktop_command")
    p_desktop.set_defaults(func=_cmd_desktop, desktop_command=None)  # bare = read
    p_desktop_read = p_desktop_sub.add_parser(
        "read", help="guarded outline of the accessibility tree (read-only, audited)"
    )
    p_desktop_read.set_defaults(func=_cmd_desktop, desktop_command="read")
    p_desktop_status = p_desktop_sub.add_parser(
        "status", help="availability + audit totals (reads, withheld, redacted)"
    )
    p_desktop_status.set_defaults(func=_cmd_desktop, desktop_command="status")

    p_appskill = sub.add_parser(
        "app-skill", help="owner-taught app packs: teach JARVIS a new app (ADR-0026)"
    )
    p_appskill_sub = p_appskill.add_subparsers(dest="appskill_command")
    p_as_wizard = p_appskill_sub.add_parser(
        "wizard", help="validate + install a pack file (eval-constructed, receipt-pinned)"
    )
    p_as_wizard.add_argument("--file", required=True, help="path to the app-skill JSON pack")
    p_as_wizard.set_defaults(func=_cmd_appskill, appskill_command="wizard")
    p_appskill_sub.add_parser("list", help="installed app packs").set_defaults(
        func=_cmd_appskill, appskill_command="list"
    )
    p_as_show = p_appskill_sub.add_parser("show", help="print one installed pack")
    p_as_show.add_argument("pack_id")
    p_as_show.set_defaults(func=_cmd_appskill, appskill_command="show")
    p_as_rm = p_appskill_sub.add_parser("remove", help="remove an installed pack")
    p_as_rm.add_argument("pack_id")
    p_as_rm.set_defaults(func=_cmd_appskill, appskill_command="remove")

    p_ai = sub.add_parser("ai", help="AI subsystem status: both paths, models, breakers (ADR-0025)")
    p_ai_sub = p_ai.add_subparsers(dest="ai_command")
    p_ai.set_defaults(func=_cmd_ai, ai_command=None)  # bare = status
    p_ai_status = p_ai_sub.add_parser(
        "status", help="local + remote backends, breakers, precedence"
    )
    p_ai_status.set_defaults(func=_cmd_ai, ai_command="status")

    p_doctor = sub.add_parser(
        "doctor",
        help="policy-state integrity: baseline, drift check, canaries (ADR-0013 M9c)",
    )
    p_doctor.add_argument(
        "--write-baseline",
        action="store_true",
        help="write or re-write the integrity baseline (explicit; after reviewed upgrades)",
    )
    p_doctor.add_argument(
        "--canaries",
        action="store_true",
        help="list issued suggestion canaries (leak tracing)",
    )
    p_doctor.set_defaults(func=_cmd_doctor)

    p_charter = sub.add_parser(
        "charter", help="circuit-broken standing orders: install/list/run/pause/resume/revoke (M9d)"
    )
    p_charter_sub = p_charter.add_subparsers(dest="charter_command", required=True)
    p_ch_install = p_charter_sub.add_parser(
        "install", help="install a charter (the contract is shown; T2 consent required)"
    )
    p_ch_install.add_argument("charter_id", help="short id: [a-z][a-z0-9-]{1,30}")
    p_ch_install.add_argument(
        "--request", required=True, help="the exact NL request to pre-authorize"
    )
    p_ch_install.add_argument(
        "--playbook",
        action="append",
        required=True,
        dest="playbook",
        help="allowlisted playbook id (repeatable)",
    )
    p_ch_install.add_argument(
        "--tier-ceiling", type=int, default=1, help="hard tier ceiling, 0..2 (T3 never charterable)"
    )
    p_ch_install.add_argument(
        "--max-steps", type=int, default=8, help="circuit breaker: steps per run"
    )
    p_ch_install.add_argument(
        "--monthly-runs", type=int, default=30, help="circuit breaker: runs per rolling 30 days"
    )
    p_ch_install.add_argument(
        "--on-calendar", default=None, help="systemd OnCalendar value (omit for manual scheduling)"
    )
    p_ch_install.add_argument(
        "--timeout-start-sec",
        type=int,
        default=900,
        help="systemd TimeoutStartSec wall-clock bound",
    )
    p_ch_install.add_argument(
        "--no-timer", action="store_true", help="do not touch systemd even if present"
    )
    p_ch_install.set_defaults(func=_cmd_charter)
    for name, help_text in (
        ("list", "list charters with state and budget usage"),
        ("run", "one firing (timer ExecStart; precheck enforces the charter scope)"),
        ("pause", "pause a charter (stops the timer best-effort)"),
        ("resume", "resume a paused charter"),
        ("revoke", "revoke permanently (audit file kept)"),
    ):
        p_ch_action = p_charter_sub.add_parser(name, help=help_text)
        p_ch_action.add_argument("charter_id", nargs="?" if name == "list" else None)
        if name == "run":
            p_ch_action.add_argument("--dry-run", action="store_true")
        p_ch_action.set_defaults(func=_cmd_charter)

    p_skill = sub.add_parser(
        "skill", help="verified skill packs: install/list/remove (ADR-0013 M9b)"
    )
    p_skill_sub = p_skill.add_subparsers(dest="skill_command", required=True)
    p_sk_install = p_skill_sub.add_parser(
        "install", help="validate, eval-dry-run, pin, and install a pack (T2 consent)"
    )
    p_sk_install.add_argument("pack_file", help="path to a *.skill.json pack")
    p_sk_install.add_argument(
        "--source", default="", help="override provenance source label for the receipt"
    )
    p_sk_install.set_defaults(func=_cmd_skill)
    p_sk_list = p_skill_sub.add_parser("list", help="list installed packs with load status")
    p_sk_list.set_defaults(func=_cmd_skill)
    p_sk_remove = p_skill_sub.add_parser("remove", help="remove an installed pack")
    p_sk_remove.add_argument("skill_id")
    p_sk_remove.set_defaults(func=_cmd_skill)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = int(args.func(args))
    except KeyboardInterrupt:
        print("\n[jarvis] interrupted", file=sys.stderr)
        return 130
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
