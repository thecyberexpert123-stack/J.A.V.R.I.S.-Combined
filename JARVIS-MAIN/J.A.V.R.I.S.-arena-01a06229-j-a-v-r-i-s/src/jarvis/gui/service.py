"""GUI service: consent-gated, journaled desktop actions (ADR-0010).

Every mutating action:
1. resolves the backend honestly for THIS session,
2. discloses the affected target (focused window) BEFORE acting,
3. goes through the same ApprovalPolicy as all of JARVIS (T2),
4. is journalled — typed text content is NOT stored (length + hash only).

Injection is reachable ONLY through the explicit CLI — never from NL
playbooks — because injected keystrokes land in whatever window has focus.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jarvis.execution.runner import ExecResult, Runner
from jarvis.gui import backends
from jarvis.gui.atspi import desktop_window_titles
from jarvis.gui.backends import GuiBackendError, Window
from jarvis.gui.capabilities import CapabilityBinding, available
from jarvis.gui.detect import probe, ydotool_socket
from jarvis.gui.vision import VisionUnavailable, describe_image
from jarvis.journal.sqlite import Journal
from jarvis.safety.approval import ApprovalPolicy
from jarvis.safety.tiers import Tier

MAX_TEXT_CHARS = 500
MAX_COMBO_CHARS = 40

_WmRunner = Callable[[Runner], object]


class _QuietRunner(Runner):
    """Wraps a runner to suppress stdout echoing (JSON-mode purity)."""

    def __init__(self, inner: Runner) -> None:
        self._inner = inner

    def run(
        self,
        argv: Sequence[str],
        *,
        requires_root: bool = False,
        timeout_s: float = 300.0,
        extra_env: Mapping[str, str] | None = None,
        echo: bool = True,
        stdin_text: str = "",
        detach: bool = False,
    ) -> ExecResult:
        del echo
        return self._inner.run(
            argv,
            requires_root=requires_root,
            timeout_s=timeout_s,
            extra_env=extra_env,
            echo=False,
            stdin_text=stdin_text,
            detach=detach,
        )

    def terminate_current(self) -> None:
        self._inner.terminate_current()


class GuiUnavailable(RuntimeError):
    """The requested capability has no backend on this machine."""


class GuiPolicyError(ValueError):
    """The request violates GUI policy (bad text/combo/no focused target)."""


def validate_text(text: str) -> str:
    if not text.strip():
        raise GuiPolicyError("nothing to type")
    if len(text) > MAX_TEXT_CHARS:
        raise GuiPolicyError(f"text too long ({len(text)} > {MAX_TEXT_CHARS} chars)")
    for ch in text:
        if ord(ch) < 32 or ord(ch) == 127:
            raise GuiPolicyError(
                "control characters are not allowed (use 'jarvis gui key' for Enter/Tab)"
            )
    return text


def validate_combo(combo: str) -> str:
    if not combo or len(combo) > MAX_COMBO_CHARS:
        raise GuiPolicyError(f"key combo must be 1..{MAX_COMBO_CHARS} chars")
    ok = all(c.isalnum() or c in "+-._" for c in combo)
    if not ok:
        raise GuiPolicyError("key combo may contain only alphanumerics and + - . _")
    return combo


def validate_launch_tokens(tokens: Sequence[str]) -> tuple[str, ...]:
    if not tokens:
        raise GuiPolicyError("nothing to launch")
    for i, token in enumerate(tokens):
        if not token or any(ord(c) < 32 for c in token):
            raise GuiPolicyError(f"invalid launch argument #{i}")
        if i == 0 and ("/" in token or token.startswith(".")):
            raise GuiPolicyError("launch by PATH name on PATH (e.g. 'xterm'), not by file path")
    return tuple(tokens)


@dataclass(frozen=True)
class GuiActionResult:
    action: str
    status: str  # done | refused | unavailable
    detail: str
    target: str = ""  # affected window, when applicable

    def to_json_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "status": self.status,
            "detail": self.detail,
            "target": self.target,
        }


class GuiService:
    def __init__(
        self,
        runner: Runner,
        approval: ApprovalPolicy,
        journal: Journal,
        env: Mapping[str, str] | None = None,
        which_fn: Callable[[str], str | None] | None = None,
        echo: bool = True,
    ) -> None:
        self._runner: Runner = runner if echo else _QuietRunner(runner)
        self._approval = approval
        self._journal = journal
        self._env = dict(env) if env is not None else None
        self.gui_env = probe(self._env, which_fn=which_fn) if which_fn else probe(self._env)
        self._caps = available(self.gui_env)

    # -- introspection ------------------------------------------------------------

    def status(self) -> dict[str, object]:
        caps: dict[str, object] = {
            cap: {"backend": binding.backend, "path": binding.path, "reason": binding.reason}
            for cap, binding in self._caps.items()
        }
        titles, atspi_reason = desktop_window_titles()
        result: dict[str, object] = {
            "session": self.gui_env.to_json_dict(),
            "capabilities": caps,
            "atspi": {"available": titles is not None, "detail": atspi_reason},
        }
        if self.gui_env.session_type == "wayland" and self._caps["type_text"].backend is None:
            result["hint"] = "run 'jarvis gui wizard' to set up ydotool input"
        return result

    def windows(self) -> list[Window]:
        binding = self._require("windows")
        if binding.backend in ("i3-msg", "swaymsg"):
            return backends.i3_list(self._runner, backend=str(binding.backend))
        if binding.backend == "hyprctl":
            return backends.hyprland_list(self._runner)
        if binding.backend == "kdotool":
            return backends.kdotool_list(self._runner)
        return backends.wmctrl_list(self._runner)

    def focused_title(self) -> str | None:
        backend = self._focused_backend()
        if backend == "i3-msg" or backend == "swaymsg":
            return backends.i3_focused_title(self._runner, backend=backend)
        if backend == "hyprctl":
            return backends.hyprland_focused_title(self._runner)
        if backend == "kdotool":
            return backends.kdotool_active_title(self._runner)
        if self.gui_env.has_tool("xdotool"):
            return backends.xdotool_active_title(self._runner)
        return None

    # -- actions --------------------------------------------------------------------

    def open_app(self, tokens: Sequence[str]) -> GuiActionResult:
        argv_tail = validate_launch_tokens(tokens)
        self._require("launch")
        argv = backends.setsid_launch(argv_tail)
        self._consent(f"launch {argv_tail[0]}", argv)
        result = self._runner.run(argv, timeout_s=30.0, detach=True)
        self._journal_action(
            "gui.launch",
            {"app": argv_tail[0], "tokens": list(argv_tail)},
            argv,
            result.exit_code,
        )
        if not result.ok:
            raise GuiBackendError(f"launch failed (exit {result.exit_code})")
        return GuiActionResult(
            "launch",
            "done",
            f"spawned detached: {' '.join(argv_tail)} (window appearance not awaited)",
        )

    def focus(self, title: str) -> GuiActionResult:
        self._require("focus")
        window = self._find_unique(title)
        backend = str(self._require("focus").backend)
        if backend in ("i3-msg", "swaymsg"):
            backends.i3_focus_title(self._runner, window.title, backend=backend)
            verify = backends.i3_focused_title(self._runner, backend=backend)
        elif backend == "hyprctl":
            backends.hyprland_focus(self._runner, window.title)
            verify = backends.hyprland_focused_title(self._runner)
        elif backend == "kdotool":
            backends.kdotool_focus(self._runner, window.id)
            verify = backends.kdotool_active_title(self._runner)
        else:
            backends.wmctrl_focus(self._runner, window.id)
            verify = (
                backends.xdotool_active_title(self._runner)
                if self.gui_env.has_tool("xdotool")
                else None
            )
        verified = verify is not None and title.lower() in verify.lower()
        self._journal_action(
            "gui.focus", {"title": title}, ("focus", title), 0, target=window.title
        )
        detail = f"focused '{window.title}'" + (
            "" if verified else " (activation sent; focused-window verification unavailable)"
        )
        return GuiActionResult("focus", "done", detail, target=window.title)

    def _text_injection_argv(self, text: str) -> tuple[list[str], str] | None:
        """Synthetic-input argv for text, per what this machine actually has."""
        if self.gui_env.has_tool("xdotool"):
            return ["xdotool", "type", "--delay", "40", "--", text], "xdotool"
        if self.gui_env.has_tool("ydotool") and ydotool_socket().exists():
            return ["ydotool", "type", "--", text], "ydotool"
        return None

    def _recheck_focus(self, target: str) -> None:
        recheck = self.focused_title()
        if recheck != target:
            raise GuiPolicyError(
                f"focus changed during approval ({target!r} -> {recheck!r}); "
                "aborting the action (TOCTOU guard)"
            )

    def type_text(self, text: str) -> GuiActionResult:
        """M9e API-first text entry (ADR-0013): AT-SPI EditableText when the
        machine offers it, synthetic input as the disclosed fallback under the
        same consent — never a silent mechanism switch (the journal and the
        result detail name every attempt)."""
        self._require("type_text")
        text = validate_text(text)
        target = self.focused_title()
        if target is None:
            raise GuiPolicyError(
                "no focused window — keystrokes would go nowhere; focus a window first"
            )
        binding = self._require("type_text")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        injection = self._text_injection_argv(text)

        api_note = ""
        if binding.path == "api":
            from jarvis.gui.atspi import set_focused_text

            pseudo_argv = [
                "at-spi",
                "EditableText.setTextContents",
                f"<redacted: {len(text)} chars>",
            ]
            consent_argv = injection[0] if injection else pseudo_argv
            self._consent(
                f"type {len(text)} chars into focused window"
                " (AT-SPI preferred; synthetic input as fallback)",
                consent_argv,
            )
            self._recheck_focus(target)
            ok, detail = set_focused_text(text)
            if ok:
                self._journal_action(
                    "gui.type",
                    {"length": len(text), "sha256_16": digest, "backend": "atspi-editable"},
                    pseudo_argv,
                    0,
                    target=target,
                    store_text=False,
                )
                return GuiActionResult(
                    "type",
                    "done",
                    f"{detail}; the application received an edit, not keystrokes",
                    target=target,
                )
            api_note = f"AT-SPI unavailable ({detail})"

        if injection is None:
            self._journal_action(
                "gui.type",
                {
                    "length": len(text),
                    "sha256_16": digest,
                    "backend": "none",
                    **({"api_attempt": api_note} if api_note else {}),
                },
                [f"<redacted: {len(text)} chars sha256_16={digest}>"],
                1,
                target=target,
                store_text=False,
            )
            raise GuiBackendError(
                f"{api_note + '; ' if api_note else ''}no synthetic-input backend available"
            )
        argv, backend = injection
        if binding.path != "api":  # api path already consented above
            self._consent(f"type {len(text)} chars into focused window", argv)
            self._recheck_focus(target)
        result = self._runner.run(argv)
        redacted_argv = [
            f"<redacted: {len(text)} chars sha256_16={digest}>" if a == text else a for a in argv
        ]
        params: dict[str, object] = {
            "length": len(text),
            "sha256_16": digest,
            "backend": backend,
        }
        if api_note:
            params["api_attempt"] = api_note
        self._journal_action(
            "gui.type",
            params,
            redacted_argv,
            result.exit_code,
            target=target,
            store_text=False,
        )
        if not result.ok:
            raise GuiBackendError(f"injection failed (exit {result.exit_code})")
        detail = (
            f"injected via {backend}; delivery to the application cannot be verified"
            if not api_note
            else f"{api_note}; fell back to injection via {backend}; delivery cannot be verified"
        )
        return GuiActionResult("type", "done", detail, target=target)

    def key(self, combo: str) -> GuiActionResult:
        self._require("key")
        combo = validate_combo(combo)
        target = self.focused_title()
        if target is None:
            raise GuiPolicyError("no focused window — keystrokes would go nowhere")
        backend = str(self._require("key").backend)
        argv = (
            ["xdotool", "key", "--", combo] if backend == "xdotool" else ["ydotool", "key", combo]
        )
        self._consent(f"press {combo} in focused window", argv)
        recheck = self.focused_title()
        if recheck != target:
            raise GuiPolicyError(
                f"focus changed during approval ({target!r} -> {recheck!r}); "
                "aborting injection (TOCTOU guard)"
            )
        result = self._runner.run(argv)
        self._journal_action(
            "gui.key",
            {"combo": combo, "backend": backend},
            argv,
            result.exit_code,
            target=target,
        )
        if not result.ok:
            raise GuiBackendError(f"key injection failed (exit {result.exit_code})")
        return GuiActionResult("key", "done", f"sent {combo} via {backend}", target=target)

    def screenshot(self, path: Path) -> GuiActionResult:
        binding = self._require("screenshot")
        out = str(path)
        argv_by_backend = {
            "scrot": ["scrot", "-o", "-q", "90", out],
            "grim": ["grim", out],
            "spectacle": ["spectacle", "-b", "-n", "-o", out],
            "gdbus-gnome-screenshot": [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.Shell.Screenshot",
                "--object-path",
                "/org/gnome/Shell/Screenshot",
                "--method",
                "org.gnome.Shell.Screenshot.Screenshot",
                "true",
                "false",
                out,
            ],
        }
        argv = argv_by_backend.get(binding.backend or "")
        if argv is None:
            raise GuiUnavailable(f"screenshot backend {binding.backend!r} has no argv map")
        self._consent(f"screenshot to {out} (captures the screen: privacy-sensitive)", argv)
        result = self._runner.run(argv)
        self._journal_action(
            "gui.screenshot",
            {"path": out, "backend": binding.backend},
            argv,
            result.exit_code,
        )
        if not result.ok:
            raise GuiBackendError(f"screenshot failed (exit {result.exit_code})")
        if not path.exists() or path.stat().st_size == 0:
            raise GuiBackendError(f"screenshot tool reported success but {out} is missing/empty")
        return GuiActionResult("screenshot", "done", f"saved {out} ({path.stat().st_size} bytes)")

    def close(self, title: str) -> GuiActionResult:
        self._require("close")
        window = self._find_unique(title)
        backend = str(self._require("close").backend)
        if backend in ("i3-msg", "swaymsg"):
            argv = [backend, f'[title="{window.title}"]', "kill"]
            backends.i3_close_title(self._runner, window.title, backend=backend)
        elif backend == "hyprctl":
            argv = ["hyprctl", "dispatch", "closewindow", f"title:{window.title}"]
            backends.hyprland_close(self._runner, window.title)
        else:
            argv = ["wmctrl", "-i", "-c", window.id]
            backends.wmctrl_close(self._runner, window.id)
        self._consent(f"close window '{window.title}' (apps may prompt to save unsaved data)", argv)
        result = self._runner.run(argv)
        self._journal_action(
            "gui.close",
            {"title": window.title},
            argv,
            result.exit_code,
            target=window.title,
        )
        if not result.ok:
            raise GuiBackendError(f"close failed (exit {result.exit_code})")
        return GuiActionResult(
            "close",
            "done",
            "close requested (graceful WM delete; app may still prompt)",
            target=window.title,
        )

    def describe(self, image_path: Path, question: str) -> str:
        try:
            return describe_image(image_path, question, env=self._env)
        except VisionUnavailable as exc:
            raise GuiUnavailable(str(exc)) from exc

    # -- internals ------------------------------------------------------------------

    def _require(self, cap: str) -> CapabilityBinding:
        binding = self._caps.get(cap)
        if binding is None or binding.backend is None:
            raise GuiUnavailable(
                f"GUI capability '{cap}' is unavailable here: "
                f"{binding.reason if binding else 'no session'}"
            )
        return binding

    def _focused_backend(self) -> str | None:
        if self.gui_env.desktop in ("i3", "sway") and (
            self.gui_env.has_tool("i3-msg") or self.gui_env.has_tool("swaymsg")
        ):
            return "i3-msg" if self.gui_env.has_tool("i3-msg") else "swaymsg"
        if self.gui_env.desktop == "hyprland" and self.gui_env.has_tool("hyprctl"):
            return "hyprctl"
        if self.gui_env.desktop == "kde" and self.gui_env.has_tool("kdotool"):
            return "kdotool"
        if self.gui_env.has_tool("xdotool"):
            return "xdotool"
        return None

    def _find_unique(self, title: str) -> Window:
        if not title.strip():
            raise GuiPolicyError("empty window title")
        matches = [w for w in self.windows() if title.lower() in w.title.lower()]
        if not matches:
            known = ", ".join(f"'{w.title}'" for w in self.windows()[:8]) or "(none)"
            raise GuiPolicyError(f"no window matching {title!r} (open windows: {known})")
        if len(matches) > 1:
            names = ", ".join(f"'{w.title}'" for w in matches)
            raise GuiPolicyError(
                f"{len(matches)} windows match {title!r} — be more specific: {names}"
            )
        return matches[0]

    def _consent(self, what: str, argv: Sequence[str]) -> None:
        from jarvis.planner.models import PlannedStep

        step = PlannedStep(description=what, argv=tuple(argv), tier=Tier.T2)
        self._approval.decide(Tier.T2, [step])

    def _journal_action(
        self,
        action: str,
        params: dict[str, object],
        argv: Sequence[str],
        exit_code: int,
        *,
        target: str = "",
        store_text: bool = True,
    ) -> str:
        task_id = uuid.uuid4().hex[:12]
        fingerprint: dict[str, object] = {
            "session_type": self.gui_env.session_type,
            "desktop": self.gui_env.desktop,
        }
        journal_params = dict(params)
        if not store_text:
            journal_params.pop("text", None)
        self._journal.begin_task(
            task_id,
            intent_text=action,
            playbook_id="gui",
            tier=int(Tier.T2),
            params=journal_params,
            fingerprint=fingerprint,
        )
        self._journal.record_step(
            task_id,
            1,
            description=f"{action} {target}".strip(),
            argv=list(argv),
            requires_root=False,
            tier=int(Tier.T2),
            status="done" if exit_code == 0 else "failed",
            exit_code=exit_code,
        )
        self._journal.finish_task(task_id, "done" if exit_code == 0 else "failed")
        return task_id
