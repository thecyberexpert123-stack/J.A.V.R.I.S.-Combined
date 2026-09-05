# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Refusal-to-guess is no longer mislabelled as a consent refusal**
  (`bridge/protocol.py`, `controller.py`). The kernel answers an unmappable
  request with `status: "refused"` and `tier: 0`, the same envelope it uses for
  a genuine consent refusal. `classify_outcome` keyed off the tier alone, so
  under `confirm KERNEL_ONLY` — the one policy that skips the preview and calls
  `jarvis_do` directly, bypassing the existing `plan.unmatched` guard — the HUD
  raised a consent prompt for a request the kernel never understood. Approving
  it would have re-sent the request and earned the identical refusal.
  `OutcomeKind.UNMATCHED` now carries the distinction at the classifier, so it
  holds on every path rather than only the previewed one, and both routes share
  one `_report_unmatched` renderer. Reported by the backend agent; reproduced
  against live kernel 1.20.0 before fixing. No safety impact — the kernel never
  guesses — but it mislabelled the kernel's most honest message.

### Verified
- **Bridge re-verified against kernel 1.20.0.** The backend moved 1.18.0 →
  1.19.0 (ADR-0025) → 1.20.0 (ADR-0026) during this work. Probed rather than
  assumed: the six-tool surface, argument schemas, handshake version, doorway
  `Server` header, `classify_outcome` and `parse_plan` all still hold. ADR-0026's
  new `gui.app`/`gui.launch` playbooks (57 → 58) parse, gate at tier 2 and
  decline correctly with no GUI change, because the bridge models plan *shape*
  rather than a list of known playbooks. Version references in
  `docs/BACKEND-BRIDGE.md`, `bridge/plan.py`, `bridge/consent.py` and
  `bridge/resident.py` updated from 1.18.0 to the version actually tested.

### Added
- **Resident-mode transport** (`bridge/resident.py`, `bridge/resident_client.py`).
  Optional connection to the kernel's loopback doorway (ADR-0018) instead of
  spawning a process, preferred automatically when the owner has run
  `jarvis serve install`. Loopback-only by refusal, 0600 token enforced, token
  sent only as a header. The HTTP envelope is normalised into the stdio shape so
  `classify_outcome` stays the single implementation of the refusal-versus-
  failure distinction. Uses `QtNetwork` from PySide6-Essentials — no new
  dependency.
- **Structured plan review** (`bridge/plan.py`). `jarvis_preview` returns steps,
  exact argv, per-step tier and root requirement, blast radius (commands, paths,
  network) and an `undo` verdict; all of it is now rendered instead of being
  flattened into one console line. The argv is shown unquoted because the kernel
  never uses a shell.
- **The hybrid consent gate** (`bridge/consent.py`). Two gates, deliberately
  different in kind: the kernel's tier-2 consent gate (grants authority, cannot
  be disabled) and a GUI reversibility gate (acknowledges risk, grants nothing,
  owner-configurable). The second exists because live probing found
  `do remove the file /tmp/x` to be **tier 1** — executed immediately, no
  prompt, `undo: unavailable`. Driven entirely by the kernel's own `undo`
  field, never by pattern-matching request text.
- **Push-to-talk voice input** (`bridge/voice.py`, `bridge/voice_client.py`,
  `MicButton.qml`). Records and transcribes, then puts the text **in the input
  field** — never executes it. The kernel's own `voice ask` is deliberately not
  used because it runs the transcript directly, which would bypass both gates.
  Hidden entirely when the machine cannot transcribe.
- Console verbs `suggest` and `confirm irreversible|always|kernel-only`.
- Readable rendering for `jarvis_suggest` (evidence-backed entries) and
  `jarvis_status` (machine description) instead of raw JSON.
- **Backend bridge to the J.A.V.R.I.S. kernel** (`src/javris/bridge/`). This GUI
  is now the front-end for the sibling `jarvis-agent` backend, speaking its
  published `javris-frontend/1` contract over newline-delimited JSON-RPC on
  stdio. `protocol.py` is Qt-free and I/O-free so that framing and — more
  importantly — consent classification are testable without a subprocess;
  `client.py` owns the `QProcess`, with separate stdout/stderr channels so a
  diagnostic banner can never be parsed as a protocol frame.
- **Consent prompt** (`ConsentPrompt.qml`, `ConsentButton.qml`). Shown only when
  the kernel refuses a tier-2 action pending approval. It quotes the request
  verbatim, has no default action, no timeout and no keyboard activation;
  Escape declines. The exact text the owner was shown is what gets re-sent.
- **Console verbs** `ask`, `plan`, `do`, `agent status` and `agent disconnect`.
  The agent is not started automatically: spawning a process that can change the
  machine is the owner's decision.
- `docs/BACKEND-BRIDGE.md` — the wiring contract as *verified against a running
  kernel*, including the places where live behaviour differs from a first
  reading of the backend's docs. Re-verified against 1.18.0 and extended with
  the resident doorway's probed security posture, the hybrid gate, plan review
  and the voice boundary.
- **`TaperedArc`** — an arc whose stroke fades along its own length. Qt Quick
  has no per-length stroke gradient, so this builds the effect from short
  overlapping segments on an eased opacity profile. Uniform arcs read as hard
  mechanical parts and make their arbitrary start and end points conspicuous;
  tapered ones emerge from and dissolve into nothing. Supports a comet profile
  (`peakPosition` near 1.0) so a rotating element's direction is legible from
  the stroke itself.
- 4x multisampling requested at startup. This improves the hardware path only;
  it is a no-op under the software backend, and `Shape` already antialiases
  itself. Stated plainly rather than claimed as a general smoothness win.
- `Theme.easingSoft` (OutQuint) for long travels, where OutCubic's hard
  deceleration reads as the element visibly arriving rather than settling.

### Changed
- **The consent prompt now shows the plan**, not just the request: the exact
  argv that will run, per-step root requirement, tier badge, playbook id and
  blast radius. Approving a change you cannot see is not informed consent.
- **The two gates are visually distinct.** Kernel consent is error-red with
  "APPROVE AND RUN"; the reversibility warning is amber with "RUN ANYWAY".
  Presenting them identically would train the owner to read both as the same
  kind of warning and devalue the one carrying real authority.
- `do` now previews before executing (unless the policy is `kernel-only`), so
  the reversibility gate can see the kernel's `undo` verdict. The preview is
  read-only and changes nothing.
- An unmatched request no longer reports as a failure. The kernel's
  anti-hallucination refusal is shown as a refusal, with the count and first
  several of its 57 known playbooks.
- **Glow is no longer applied uniformly.** Panels do not light by default; they
  gained an `attention` property and emit only when they have something to say.
  The vitals rail lights while a condition is escalated, and the console lights
  briefly when a line is appended. Lighting every frame made the bloom uniform,
  and a uniform signal carries no information -- it only raises the noise floor.
- The orb's standing arcs and the reactor's rotating arcs are now tapered.
- The orb's outer dashed ring is deliberately left uniform: it is the fixed
  reference everything else moves against.

### Fixed
- `TaperedArc` leaked its segment objects on every rebuild -- 60 live objects
  where 30 were expected after repeated sweep changes. `destroy()` is deferred
  to the next event-loop pass, so reading `Shape.data.length` immediately after
  a rebuild returns a stale count and hid the leak. Segments are now tracked in
  an owned list, and released on destruction.

### Added
- **Real host identity panel.** CPU model, logical core count, total memory,
  OS, kernel release and hostname, all read from `/proc` and `/etc/os-release`.
  Rows that the kernel does not expose are omitted entirely -- the panel gets
  shorter on a restricted host rather than showing placeholder hardware.
- **Battery telemetry** (`/sys/class/power_supply`): charge, charging state and
  a time-to-empty estimate derived from the kernel's own charge and current
  counters. Non-battery supplies (mains, HID peripherals) are skipped, so a
  wireless mouse at 40% is never mistaken for the machine's charge. Hosts
  without a battery show no cell at all.
- **`HudClock`** — large wall clock with date and weekday, ticking on its own
  one-second timer rather than a frame-driven binding.
- **`CornerBrackets`** — L-shaped corner marks framing the display, applied at
  the screen edge. Implies a frame without enclosing the content.
- **`FactList`** and **`PowerCell`** components.

### Changed
- The centre stage yields the left gutter to the host panel in DIAGNOSTICS so
  the two no longer overlap, and reclaims the full width in ASSISTANT, which is
  a takeover and must stay optically centred.

### Fixed
- `PowerCell` lit segments on their upper edge, so any charge below 10% lit
  nothing and a nearly-flat battery rendered identically to a dead one -- the
  most important reading on the control was the one it could not express.
  Segments now light from their lower edge; only a literal zero shows empty.

### Added
- **Emissive lighting across the HUD.** A new `Glow` component provides a soft
  radial bloom, applied to the assistant orb (ambient + hot core), the reactor
  core aperture, panel top edges, the wordmark, and the gauges. The HUD now
  reads as a lit instrument rather than a line drawing.
- **Load-proportional gauge backlight** — a dial's bloom brightens with its
  value and takes the load colour, so a hot gauge is visible peripherally
  before the number is read (D10). Unavailable gauges emit no light at all.
- `Theme.glowSubtle` / `glowNormal` / `glowStrong` intensity tokens and a
  `Theme.glowScale` master multiplier that can extinguish all bloom at once.
- `coreLift` on the orb: the core burns brighter while the assistant is
  actually working, easing between levels rather than snapping.

### Changed
- Core discs on both the orb and the reactor are now translucent. They were
  opaque, which punched a dark hole through the middle of their own glow --
  backwards for something meant to read as a light source.
- Panel fills are slightly translucent so the inner edge light reads through.
- The reactor's breathing halo is a real radial falloff instead of a
  flat-colour circle, which read as a grey disc rather than light.

### Added
- **ASSISTANT mode** — a modal takeover in which the assistant itself, rather
  than the machine, owns the display. Reachable with `mode assistant` or by
  cycling with TAB. The instrument rail is withdrawn while it is up.
- **`AssistantOrb` component** — a per-state presence modelled on the Voice HUD
  in the user's own web project (`docs/RESEARCH.md` §17-21): a travelling-wave
  rim for LISTENING, counter-rotating scanners for PROCESSING, staggered
  ripples for SPEAKING, and a determinate arc for EXECUTING. One shared 1500 ms
  phase clock drives every derived animation rather than one animator per bar.
- Plain-language caption under the orb naming what each state means, which is
  the corrective to the unlabelled-telemetry problem recorded as D8.

### Changed
- A fault is now coherent across the whole orb: the standing arcs follow the
  fault colour instead of staying cyan, which previously read as "partly fine".
- Faulted states are **still**. A fault is not a mood.

### Fixed
- `tools/headless_render.py` walked illegal state transitions (e.g. straight
  from STANDBY to SPEAKING), which the state machine correctly refused, so it
  silently captured the wrong state. It now follows a legal route and fails
  loudly if it does not arrive.

### Added — M8: motion language (2026-09-04)

A third research round, this time into how the reference material *moves*, plus
a study of the user's own earlier JARVIS GUI
(`github.com/Anish932-hash/JARVIS_GUI`, Next.js). Principles D15-D19 in
`docs/RESEARCH.md`. The governing finding is from the original HUD team: depth
came from *how elements moved*, not from perspective — which means a flat
monitor loses nothing.

- `AmbientField.qml` — the atmosphere layer: area-scaled drifting motes
  (`QtQuick.Particles`), one slow scanline, and a vignette that also raises
  central contrast for escalated alerts.
- `BootSequence.qml` — power-on choreography in three phases: energy streaks
  converge from beyond the frame, three rings trace themselves in at different
  rates, then the name assembles letter by letter. Implemented as a **pure
  function of `progress`** rather than a timer chain, so any frame is
  reproducible and testable.
- **Alpha events** (`ReactorCore.pulse()`): every assistant state change now
  emits one outward-travelling ring, so a transition is felt rather than merely
  relabelled.
- **Breathing halo** and a **PROCESSING radar sweep** on the core — the sweep
  runs only while the assistant is actually working, so the motion means
  something.
- **Pointer parallax** across three depth layers, and **staggered entrances**
  via `HudSurface.entrance()`.
- Motion tokens in `Theme.qml`, with mutually non-harmonic periods so the
  ambient field never visibly loops.
- `javris --no-ambient` and `Theme.ambientMotion` — a real off switch for all
  decorative motion.
- `tools/headless_render.py --boot-progress`, to capture any frame of the boot
  sequence for review.

### Changed
- Every pre-existing infinite animation (ring rotation, inner-ring pulse) is now
  gated on `Theme.ambientMotion`, so the off switch is genuinely complete rather
  than covering only the new work.

### Fixed
- The boot title used a `Row`, which sizes itself to its *visible* children, so
  the word crept sideways as letters revealed. Letters are now placed at fixed
  offsets measured from the font.
- The boot overlay had no backdrop, so the live HUD showed through and the two
  competed. It now owns the screen and clears just before the title lands.
- The boot streaks were short and dim enough to read as tick marks rather than
  converging energy.
- Header chrome was fully visible during boot, over the overlay. It now enters
  on the same stagger as the rest of the HUD.
- `--boot-progress` silently rendered a *different* frame than requested,
  because `bootProgress` carries a `Behavior` and assigning it retargets an
  animation rather than setting a value. The tool now reasserts the value at
  capture time and prints what it actually captured.

### Verified
- `QtQuick.Particles` and `QtQuick.Effects` were confirmed available and loading
  under the software backend by rendering a probe file — not assumed.
- All seven gates pass: ruff, mypy strict (12 files), 158 unit tests, qmllint
  clean on 14 QML files, **48 Qt Quick tests** (up from 29), headless render.
- `set_ambient_motion()` was exercised against the real `Theme` singleton and
  observed to toggle and restore.
- Boot frames at progress 0.30 / 0.80 / 0.85 / 1.00 rendered and visually
  inspected, plus the escalation and PROCESSING frames re-checked for
  regressions.

### Not verified
- No GPU, X11 or Wayland rendering; software backend only. **No frame-rate
  measurement was taken, so no claim is made that the particle field, parallax
  or boot sequence hold 60 fps on real hardware.** This is the change most
  likely to cost performance and it is the one thing that could not be measured
  here.
- Pointer parallax has not been exercised with a real mouse; only the binding
  path was verified.

### Fixed (docs)
- `docs/images/hud-diagnostics.png` — the README's lead screenshot — was still
  the M6 render, predating both attention escalation and the motion language.
  Regenerated, so the first image a reader sees matches the current build.
- `docs/images/hud-monitor.png` was committed but referenced by no document.
  Now shown in the README with the reactor core in `PROCESSING`.

### Considered and rejected
- The `waveform-bar` audio visualiser from the reference project. We have no
  audio input, so animating it would be fabricating a signal.
- The Orbitron webfont used by that project — no bundled fonts, and only DejaVu
  is available here.
- A full scanline raster over the whole HUD: it reduces glyph legibility, which
  D14 rules out for a tool. One soft travelling band is used instead.

### Added — M7: attention escalation (2026-09-03)

A second research round focused on HUD *behaviour* rather than appearance. The
findings are recorded as principles D9-D14 in `docs/RESEARCH.md`, and the one
that changed the product is this, from the source analysis itself: small
peripheral gauges cannot capture attention, because foveal vision is narrow, so
a competent assistant hides lower-priority data and promotes the problem into
the main display. "Attention management is crisis management."

- `src/javris/attention.py` — the escalation policy, as pure testable Python
  with no Qt dependency. Classifies each metric, requires a **sustained**
  condition before raising (3 polls), applies **hysteresis** on release so a
  value hovering on a threshold cannot flap the centre of the HUD, and promotes
  **at most one** condition at a time.
- `AlertBanner.qml` — the escalated condition rendered large and high-contrast
  over the mode surface, with the rest of the HUD dimmed to 0.28. Carries one
  number and one sentence; no additional detail, per principle D10.
- `TargetReticle.qml` — four corner brackets that converge from an oversized
  scale, implementing "acquire, then annotate" (D13). Reusable independently of
  alerts.
- `Theme.fontSizeHero` (64 px), reserved for the escalated readout.
- Controller: `alertActive`, `alertLabel`, `alertReadout`, `alertUnit`,
  `alertAdvice`, `alertSeverity`, `alertFraction` and the `alertChanged` signal.
- CPU, memory, swap and every mounted filesystem are escalatable. Uptime,
  throughput and load average deliberately are **not**: they have no saturation
  point, so a "how full is it" fraction would have to be invented.
- `tools/headless_render.py --simulate-alert`, a review-only synthetic reading
  so the overlay can be photographed on an idle machine. Not reachable from the
  application.

### Fixed
- The header claimed `NOMINAL` while a `CRITICAL` alert was on screen — caught
  only by looking at a rendered frame, not by any test. The status now reports
  the escalated severity, which outranks both the degraded notice and
  `NOMINAL`.
- The alert backdrop at 0.88 opacity let the reactor core ghost through the hero
  readout — the exact low-contrast failure the research warns against. Now fully
  opaque.
- Suppression initially dimmed only the vitals rail, leaving the mode surface at
  full brightness competing with the alert. It now dims the mode surface too.
- An alert held inside the hysteresis band classified as `NORMAL` and would have
  rendered with no severity colour; it now reports `WARN`.
- Releasing on "metric became central" or "metric became unavailable" was
  incorrectly subject to the recovery streak. Both now release immediately:
  hysteresis guards against a *value* oscillating, and delaying either would
  leave the HUD displaying something untrue. Caught by a failing test.

### Changed
- Mode switching re-runs the escalation policy synchronously, because prominence
  is mode-dependent. Previously the HUD could be wrong for up to one poll.

### Verified
- All seven quality gates pass: ruff lint + format, mypy strict (12 files),
  **158 unit tests** (up from 120), qmllint clean on 12 QML files, **29 Qt Quick
  tests** (up from 18), headless render at 1440x900.
- The escalation overlay was rendered and visually inspected at
  `build/hud-alert.png`; the unescalated MONITOR frame was re-rendered and
  confirmed unchanged.

### Not verified
- No GPU, X11 or Wayland rendering; the software backend is all that is
  available here. No frame-rate measurement, so no claim is made about the
  animation smoothness of the escalation transition.
- The escalation has not been observed against a *genuinely* saturated machine —
  only against fixture and synthetic readings driven through the real policy.

### Considered and rejected
- Bundling a squared-geometric font (Eurostile, Bank Gothic). Both are
  commercially licensed; the machined feel is obtained instead through wide
  letter-spacing on upper-case labels. Only DejaVu is available in this
  environment (verified).
- Webcam/gesture input, 3D holographic depth, and a location/map panel. The last
  is the important one: with no location data, a map would be fabrication.

### Added — M1-M6: first working HUD (2026-09-03)

#### Telemetry (`src/javris/telemetry/`)
- `ProcReader`, the single module permitted to read `/proc` and `/sys`. Parses
  `/proc/stat` (aggregate and per-core jiffies), `/proc/meminfo`, `/proc/loadavg`,
  `/proc/uptime`, `/proc/net/dev`, `/proc/mounts` and `/sys/class/thermal`.
  The filesystem root is injectable, so the layer is tested entirely against
  fixtures with no access to the real `/proc`.
- Rejects incoherent samples rather than reporting nonsense: counters that move
  backwards across suspend or CPU hotplug, mismatched CPUs, non-positive
  intervals, and thermal readings outside a physically plausible range.
- Excludes pseudo-filesystems from storage reporting and loopback from network
  throughput.
- `TelemetrySampler` converts successive readings into `TelemetrySnapshot`
  values, computing rate-derived metrics from deltas. The first sample after
  start reports rates as unknown rather than inventing them from one reading.
- Every unreadable source is named in `degraded_sources` and surfaced in the UI.

#### State and commands
- `AssistantState` with an explicit eight-state transition table; illegal
  transitions raise `InvalidTransitionError`. `ERROR` and `OFFLINE` are
  reachable from anywhere, and a test proves no state is a dead end.
  Pattern credited to Open.Jarvis (MIT) in `docs/CREDITS.md`.
- `CommandRouter`: allow-list dispatch with no shell execution, no process
  spawning and no network. Input is length-capped and control characters are
  stripped before parsing.

#### Controller
- `HudController`, the single QML-facing object. Owns assistant state, drives
  telemetry polling on a `QTimer`, routes console commands, and performs all
  display formatting so QML holds no business logic.
- Telemetry degradation is logged once on transition rather than on every poll.
- The console log is bounded at 200 lines.
- Polling interval is floored at 200 ms.

#### Interface (`src/javris/ui/`)
- `Theme.qml`, a singleton holding every colour, spacing, duration and type
  token, plus the semantic `loadColor` and `severityColor` functions. No
  component declares a literal colour or magic number.
- Components: `Panel` (self-sizing, cut-corner frame), `Gauge` (labelled radial
  gauge with an explicit unavailable state), `ReactorCore` (state- and
  load-encoding concentric rings with a tick scale), `TelemetryRow`, `LogStream`
  (severity-coloured, auto-scrolling) and `HudGrid`.
- Modes: `DiagnosticsMode` and `MonitorMode`, cross-faded within a 300 ms budget.
- `HudSurface.qml` shell with boot sequence, header, vitals rail and console;
  `Main.qml` frameless full-screen window with a `--windowed` alternative.
- Keyboard: `Tab` cycles mode, `Esc` focuses the console.

#### Tooling and tests
- 120 Python unit tests and 18 Qt Quick Test cases, all passing. 89% total
  coverage; 95-100% on the telemetry, state and command modules.
- `tools/check.sh`, the quality gate: ruff lint, ruff format, mypy `--strict`,
  pytest, qmllint, Qt Quick Test, headless render.
- `tools/generate_qmltypes.py` generates the QML type description from the live
  `QMetaObject`, so tooling cannot drift from the implementation.
- `tools/headless_render.py` renders the HUD offscreen to a PNG for review.
- `tools/sandbox_gl_stubs.py` generates version-scripted stub libraries so Qt can
  be imported in containers lacking `libGL`/`libEGL`/`libdbus`/`libxkbcommon`.
  Development-only and never part of the product.

#### Documentation
- `README.md`, `docs/DESIGN-SYSTEM.md` (the component bible),
  `docs/CREDITS.md`, `THIRD-PARTY-NOTICES.md`, `LICENSE` (MIT).

### Fixed
- `ReactorCore` exposed a property named `state`, shadowing the built-in
  `QQuickItem.state`. Renamed to `coreState`.
- Mode components declared `id: root`, which shadowed the shell's `root` inside
  `Component` scope and silently bound `controller` to the mode itself.
- `Panel` required callers to compute a height from the panel's own children,
  which is a circular binding. It now sizes itself to its content.
- `TelemetryRow` anchored a `Row` by baseline; a `Row` has no baseline of its
  own, so values misaligned and could overlap the label.
- Replaced context properties with a registered QML singleton, eliminating every
  remaining `qmllint` unqualified-access warning.
- `Loader` evaluated mode bindings before initial properties were applied, so a
  `required property` read as null on the first pass.
- The headless renderer destroyed its view during interpreter shutdown, after
  context properties had gone, producing a wall of spurious `TypeError` output.
- Packaging omitted the `qmldir` and `.qmltypes` files, so a clean
  `pip install .` produced an application that could not resolve its own QML
  modules. Caught by installing into a fresh virtualenv and launching it.

### Changed
- Chose Qt 6 / QML with PySide6 over Flutter, Tauri and GTK4/GSK, on the evidence
  recorded in `docs/RESEARCH.md` and confirmed by the stakeholder.
- PySide6 (LGPLv3) over PyQt6 (GPLv3), to avoid imposing source-disclosure terms.
- Zero runtime dependencies beyond PySide6; `psutil` was deliberately rejected,
  since its Linux data comes from the same `/proc` files.

### Verified
- `./tools/check.sh` passes end to end: ruff clean, ruff format clean, mypy
  `--strict` clean on 11 files, 120 unit tests passing, qmllint clean on all 10
  QML files, 18 QML tests passing, headless render producing a 1440x900 frame.
- A clean `pip install .` into a fresh virtualenv, launched via the `javris`
  entry point, starts and exits 0 with no QML errors.

### Not verified
- No rendering on real GPU hardware, X11 or Wayland: the development sandbox has
  no `$DISPLAY` and no GL driver. All rendering used the software rasteriser via
  `-platform offscreen`.
- No frame-rate measurement. Any performance target in the plan is a target, not
  a measurement.

## [Unreleased] — earlier

### Added — M0: Research & Planning (2026-09-03)

- `docs/RESEARCH.md` — structured research with citations covering:
  - the JARVIS/Iron Man HUD design language, sourced from primary interviews with
    its designers (Jayse Hansen, Kent Seki), Cantina Creative/Prologue coverage,
    and the sci-fi-interface critical literature, distilled into eight design
    principles (D1-D8);
  - a survey of six existing open-source JARVIS GUI projects, recording the
    patterns worth adopting, the credits owed, and the gap this project fills;
  - an evidence-based toolkit evaluation of Qt 6, Flutter, Tauri and GTK4/GSK,
    including the GTK 4.16 deprecation of `GskGLShader`;
  - PySide6 (LGPLv3) vs PyQt6 (GPLv3) licensing analysis;
  - a `VERIFIED-LOCAL` record of what was actually executed in this workspace,
    including a successful headless QML render.
- `docs/PLAN.md` — scope and requirements with acceptance criteria, architecture,
  tech-stack decision table, coding standards and quality gates, six milestones,
  risk register, changelog/experience workflow, folder structure, and a starter
  vertical-slice outline.
- `AGENT-EXPERIENCE.md` — development log.

[Unreleased]: https://github.com/thecyberexpert123-stack/J.A.V.R.I.S.-GUI/commits/main
