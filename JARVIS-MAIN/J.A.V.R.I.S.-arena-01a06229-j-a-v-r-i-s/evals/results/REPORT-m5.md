# JARVIS Evaluation Report — M5 addendum: GUI Control

**Date:** 2026-09-02 · **Version:** 0.5.0 · **Scope:** M5 GUI control (ADR-0010)
**Companion to:** [REPORT-m4.md](REPORT-m4.md) (M1–M4 gates remain in force and green).

---

## 1. What was verified (observed)

| Verification | Where | Result |
|---|---|---|
| Headless honesty subset (4 tasks: honest status, injection refused, windows refused, wizard runs) | local sandbox + CI job | **4/4** |
| **15-task GUI suite on a real X stack** (Xvfb + i3 + xterm + xdotool + wmctrl + scrot) through the real CLI | CI `gui-eval` job | **15/15 — gate ≥98% met** (annotation `m5-gui :: 15/15 GUI tasks (xvfb-i3)`, commit `5b17ed5`) |
| Detection & matrix unit tests (headless/x11/wayland, i3/hyprland/kde/sway selection, ydotoold-socket gating) | unit suite | 34 GUI tests |
| Consent enforcement (T2 refusal without `--yes` in non-tty; injection never runs) | task 15 of catalog + unit tests | enforced |
| Vision abstention (no Ollama → refuse, never fabricate) | task 12 + stubbed unit test | honest |
| Typed-text privacy: injection content **not** persisted (length + sha256 prefix only) | unit test caught the leak, fixed in service | verified |

Reproduce locally (needs an X stack): `python3 evals/harness/m5_gui.py --catalog evals/catalog/m5.json --results /tmp/m5.json --xvfb` · Headless: `... --headless`.

## 2. Architecture in one paragraph

`jarvis gui status` is the contract: it prints this machine's **capability matrix** — session (x11/wayland/headless), desktop, and per-capability backend with an explicit reason when unavailable. Backends v1: X11 (wmctrl/xdotool/scrot), i3/sway IPC (get_tree JSON; also used for focus-verification), Hyprland (hyprctl -j), KDE Wayland (kdotool when present; spectacle), GNOME Wayland (gdbus Shell screenshot; window listing honestly unavailable without AT-SPI), Wayland input via ydotool (gated on the `ydotoold` socket). AT-SPI is an optional read layer via `pyatspi` with honest absence. Every mutating action: backend resolution → **target disclosure** (focused window) → T2 approval through the standard `ApprovalPolicy` → journal. Injection is CLI-only by design — NL playbooks expose only `gui.launch` (app-name argv, no paths, case-preserving).

## 3. The 15-task catalog (X11/i3 lane)

detect-x11 · backend-i3 · input-xdotool · windows-empty · launch-xterm (window appears) · launch-reader (xterm running a `read` shell) · focus-by-title · type-into-focused · key-Return-commits (reader writes the typed line to a file — **real input-injection proof**) · type-rejects-control-chars (policy) · screenshot-png (real capture, magic-checked) · vision-honest-abstain · atspi-honest-state · close-window (graceful WM delete) · **consent-enforced** (T2 launch without `--yes` must refuse).

## 4. Known limitations (honest)

1. **Wayland backends are unit-fixture-verified only.** This project has no GNOME/KDE/Hyprland Wayland session in CI or the sandbox; the PLAN's "wizard works on fresh Fedora & Ubuntu Wayland sessions" could therefore NOT be observed on real Wayland. The wizard's checks (binary, ydotoold socket, /dev/uinput, input group) and fix commands are real code validated by fixtures; on-session verification remains open.
2. AT-SPI tree reading is implemented but only its *honesty* is gated (CI installs `python3-pyatspi` best-effort); tree-content correctness on a real desktop is unverified.
3. `gui describe` requires a local Ollama vision model; the HTTP contract is stub-verified, no real vision model was available.
4. Screenshot privacy: captures are T2-consented, but a consented capture still captures everything on screen — inherent to the capability.
