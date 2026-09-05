# Research Dossier — J.A.V.R.I.S.

> Guideline #3 compliance artifact. Findings gathered 2026-09-02 before any design or code.
> Every architectural decision in `docs/PLAN.md` traces back to an item here.

---

## R1. What is actually achievable today? (Benchmark evidence)

| Benchmark | Measures | Best known result | Implication |
|---|---|---|---|
| **OSWorld** (369 real Ubuntu/Windows/macOS tasks, execution-based) | Real computer operation: GUI, terminals, cross-app workflows | **~63.5%** (Agent S3 w/ bBoN, 2026 leaderboard); one team reports **76.26%** (Oct 2025) vs **72.36% human baseline** | Even the world's best computer-use agents fail ~1 in 3 real OS tasks |
| **OSWorld 2.0** (long-horizon tasks, 2026) | Multi-step, stateful real-world tasks | Best model reaches only **20.6%** full success (Claude Opus-class, max thinking); most agents 4.6–14% | Long-horizon open-ended autonomy is far from solved |

**Sources:**
- OSWorld leaderboard tracking: https://www.codesota.com/benchmark/osworld
- 76.26% OSAgent result & human baseline: https://theagi.company/blog/osworld
- OSWorld 2.0 paper (arXiv): https://arxiv.org/html/2606.29537v1

**Consequence for us:** A blanket "98% on anything" claim is not honestly reachable with 2026 technology.
The production-honest strategy (and the one that matches the owner's own rule *"does not blindly do any task"*):
scope the 98% target to a **curated, verified task catalog** executed through plan→verify gates, and
**gracefully refuse/escalate** outside it. Detailed in PLAN.md §3.

---

## R2. Prior art & lessons from existing Linux/terminal agents

| Project/pattern | Lesson |
|---|---|
| AI Bash copilots (Ollama/OpenAI-based) | Local-first is viable; **prepend distro context** ("We're on Fedora 40") to measurably boost accuracy; log everything for audit; propose backup + rollback hint for any write |
| Community AI shells | Two-layer safety check works in practice: **(1) static blocklist of known-dangerous patterns, (2) LLM-as-safety-reviewer** on top; confirmation prompt before execution caught real harmful commands |
| DevOps practice (Copilot-for-Bash guidance) | **Never pipe AI output into a privileged shell.** Pipeline is: generate → understand → `bash -n` syntax check → ShellCheck → test on disposable target → then run. Approval-gating exists in commercial tools for exactly this reason |
| Sandboxed replay | Podman/Docker containers usable as disposable rehearsal environments for risky commands |

**Sources:**
- https://linuxbash.sh/post/building-an-artificial-intelligence-copilot-for-linux-servers
- https://devopsaitoolkit.com/github-ai/github-copilot-bash/
- https://medium.com/@varajesh/developing-an-ai-shell-with-ai-d2e460421917

**Consequence for us:** Our execution layer MUST implement: static validation → syntax check →
lint (ShellCheck-class) → dry-run/rehearsal → tiered approval → post-execution verification.
This is not gold-plating; it is the proven minimum for non-blind execution.

---

## R3. GUI control on Linux — the Wayland wall

Hard findings:

1. **Wayland deliberately blocks global synthetic input.** `xdotool`, `pyautogui`, `wmctrl` do NOT
   work natively on Wayland. This is a security design decision, not a bug.
   (https://www.reddit.com/r/linux/comments/1kkuafo/wayland_an_accessibility_nightmare/)
2. **X11 is dying as a default.** Ubuntu 22.04+, Fedora, Pop!_OS default to Wayland;
   **Fedora 43+ dropped X11 sessions entirely.** Wayland support is mandatory, not optional.
   (https://linuxvox.com/blog/autoclick-linux/)
3. **Viable Wayland paths** (https://linuxvox.com/blog/autoclick-linux/):
   - `ydotool`/`dotool` — kernel-level input injection via **uinput**; needs `ydotoold` daemon running
   - **AT-SPI 2** accessibility tree — works on both X11 and Wayland for *reading* UI structure
4. **Compositor fragmentation requires per-compositor backends.** Production project
   `agent-sh/computer-use-linux` ships separate backends: GNOME (Shell extension /
   `org.gnome.Shell.Introspect`), KDE (KWin DBus scripting), Hyprland (`hyprctl`), i3 (`i3-msg`),
   COSMIC (helper binary), generic X11 (wmctrl/xdotool). Sway/wlroots: no exact window management yet.
   (https://github.com/agent-sh/computer-use-linux)

**Consequence for us:** GUI subsystem = layered strategy, in reliability order:
**AT-SPI structured automation > compositor-specific DBus APIs > uinput synthetic input (ydotool) > vision-model fallback.**
Each layer degrades gracefully; an interactive setup wizard enables the required daemons/permissions with user consent.

---

## R4. Anti-hallucination & grounding (synthesis of sources + established practice)

Techniques with strong support in the agent-engineering literature and the sources above:

1. **Ground in local system truth** — before running any command: does the binary exist
   (`command -v`), do the flags exist (parse `man`/`--help`), does the package exist in THIS distro's
   repos (`apt-cache`, `dnf info`, `pacman -Si`)? A hallucinated command fails here, harmlessly.
2. **Structured tool-calling** (strict JSON schema, function calling) instead of free-text shell —
   eliminates whole classes of invented syntax.
3. **Post-condition verification** — after execution, assert the intended effect actually happened
   (package installed? service active? file content matches?). Close the loop; never assume success.
4. **Self-check/verification-generation loop** — the technique behind the 76% OSWorld result:
   verify outcomes in real time and correct on the next turn (https://theagi.company/blog/osworld).
5. **Cite-or-abstain policy** — for factual system questions, answer only from local evidence
   (`os-release`, man pages, package metadata) or fetched official docs with URL attribution;
   otherwise say "I don't know / cannot verify".
6. **Static + LLM dual safety review** before execution (R2).
7. **Regression evaluation** — run the task catalog against disposable VMs/containers in CI so
   capability claims are measured, not asserted.

---

## R5. Distro abstraction surface (domain knowledge, to be validated in M1)

- Identity: `/etc/os-release` (systemd-standard) is the reliable detection source on effectively all modern distros.
- Package managers to abstract: `apt` (Debian/Ubuntu), `dnf` (Fedora/RHEL), `pacman` (Arch),
  `zypper` (openSUSE), `apk` (Alpine), `emerge` (Gentoo), `nix` (NixOS), plus universal layers
  **Flatpak / Snap / AppImage**.
- Service managers: systemd (dominant), OpenRC (Alpine/Gentoo), runit (Void).
- Firewalls: `ufw`, `firewalld`, `nftables`, `iptables`.
- **Validation method:** an integration test matrix of distro containers (Debian, Ubuntu, Fedora,
  Arch, openSUSE, Alpine) in CI — adapters are certified per distro, never assumed.

---

## Open items carried into PLAN.md §13 (stakeholder confirmation)

- ~~Name ruling~~ **RESOLVED (2026-09-02):** canonical name **JARVIS** — *"Just A Rather Very Intelligent System"*; package/CLI `jarvis`; repo name unchanged.
- Definition of the 98% success metric (catalog-gated vs aspirational). — **OPEN**
- Primary interaction surface (CLI / TUI chat / GUI overlay) for v1. — **OPEN**
- Default model posture (hybrid router / local-first / API-first). — **OPEN**
