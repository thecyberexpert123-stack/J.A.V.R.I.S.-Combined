# RESEARCH — J.A.V.R.I.S. GUI

Status: **Research complete for Milestone 0 (stack selection + design language).**
Date: 2026-09-03. All statements below are either (a) cited to a source, or (b) marked
`VERIFIED-LOCAL` meaning I executed it in this workspace and observed the result.

---

## 1. What the JARVIS/Iron-Man HUD design language actually is

Findings are drawn from primary interviews with the people who designed the screens
(Jayse Hansen, Kent Seki), the VFX houses (Prologue, Cantina Creative), and the
sci-fi-interface critical literature.

| # | Design principle | Evidence |
|---|---|---|
| D1 | **Cyan/blue wireframe on near-black.** The HUD is "a dizzying mixture of blue wireframe motion graphics"; cyan was the deliberate dominant hue. | [scifiinterfaces — 1st person view](https://scifiinterfaces.com/2015/07/21/iron-man-hud-1-person-view/), [vfxblog oral history](https://vfxblog.com/ironman/) |
| D2 | **Mode-driven layouts, not one static screen.** The HUD reconfigures wholesale between "Analysis Mode", "Flight Mode", etc. — widgets migrate and the whole composition converts. | [vfxblog oral history](https://vfxblog.com/ironman/) |
| D3 | **Three input paths into the same surface:** JARVIS pushes info; Tony asks by voice; gaze/focus promotes a widget forward ("artificial foveation"). | [vfxblog oral history](https://vfxblog.com/ironman/) |
| D4 | **Elements live on concentric invisible spheres around the viewer**, so peripheral panels appear bowed/off-facing rather than flat. | [scifiinterfaces glossary](https://scifiinterfaces.com/category/marvel-cinematic-universe/iron-man/?order=asc) |
| D5 | **Later films moved from "2D elements in 3D space" to volumetric/holographic**, with optical flares and light interaction as a core motif. | [Maxon — Cantina Creative on Iron Man 3](https://www.maxon.net/en/article/cantina-creative-gives-iron-man-3-a-heads-up-with-maxon-cinema-4d) |
| D6 | **Every screen carries one message.** Each HUD beat was designed to say exactly one thing ("he's targeting all the aliens"). Decoration exists to *support* a readable state. | [TNW — interview with Jayse Hansen](https://thenextweb.com/news/jayse-hansen-on-creating-tools-the-avengers-use-to-fight-evil-touch-interfaces-and-project-glass) |
| D7 | **A written design bible governed consistency** — every component documented with purpose and lineage across suit versions. | [TNW — Jayse Hansen](https://thenextweb.com/news/jayse-hansen-on-creating-tools-the-avengers-use-to-fight-evil-touch-interfaces-and-project-glass) |
| D8 | **Documented usability flaw to avoid:** cryptic unlabelled telemetry (`N -8 W -97 RNG EL`) raises cognitive load; the stereoscopic multi-layering is physically impossible. | [scifiinterfaces](https://scifiinterfaces.com/2015/07/21/iron-man-hud-1-person-view/), [scifiinterfaces — impossible thing](https://scifiinterfaces.com/tag/iron-hud/?order=asc) |

**Design conclusions carried into our spec:** adopt D1–D7 as a *token-driven design
system* with a real, documented component bible (mirroring D7). Explicitly reject the
D8 failure mode: every numeric readout in our UI gets a human-readable label and unit.

## 2. Survey of existing JARVIS-GUI projects (what to learn, what to avoid)

| Project | Stack | Useful pattern | Gap we must not repeat |
|---|---|---|---|
| [hzaid01/Jarvis](https://github.com/hzaid01/Jarvis) | Electron + React + Tailwind | Clean split: HUD chrome / arc reactor / system stats / status bar; provider-registry abstraction over LLM backends | Windows-only; heavy Electron footprint |
| [dmrr35/Open.Jarvis](https://github.com/dmrr35/Open.Jarvis) | Python | **Explicit assistant state machine** — BOOTING, STANDBY, LISTENING, PROCESSING, EXECUTING, SPEAKING, ERROR, OFFLINE — driving the UI via a structured event stream. Also: "keyless degraded mode" so the UI is fully usable with no API keys | Windows-first |
| [eadmin2/jarvis_ai](https://github.com/eadmin2/jarvis_ai) | Python + vanilla-JS HUD | Cinematic entrance choreography for panels (Z-depth swoop, frame trace, scanline materialise); barge-in/interrupt handling | Browser-hosted, macOS-tested |
| [jincocodev/openclaw-jarvis-ui](https://github.com/jincocodev/openclaw-jarvis-ui) | Three.js | Three-layer audio visualiser (spectrum / ring / waveform) tied to a central orb reflecting agent state | Web app, not a Linux desktop app |
| [adityam1313/jarvis-hud](https://github.com/adityam1313/jarvis-hud) | React + Vite | Central orb w/ rotating dashed rings + tick marks; CRT scanline overlay; animated grid | Mock data only |
| [MuhammadFahru/jarvis-hud](https://github.com/MuhammadFahru/jarvis-hud) | Three.js + MediaPipe | Holographic globe, streaming severity-coloured terminal log | Simulated telemetry |

**Key gap in the field:** nearly every JARVIS GUI is Electron/web or Windows-first.
A native, GPU-accelerated, *Linux-native* HUD with real telemetry is genuinely
unoccupied ground — which justifies this project (Guideline 2).

**Adopted patterns (credited):** the explicit assistant state machine and
keyless/degraded-mode posture (Open.Jarvis, MIT); mode-driven layout switching (D2);
panel entrance choreography (jarvis_ai, MIT). No source code is copied; these are
architectural patterns, re-implemented in QML. Credits will also appear in
`docs/CREDITS.md` at implementation time.

## 3. Toolkit evaluation — Qt6 vs Flutter vs Tauri vs GTK4/GSK

The brief names four candidates. Only one can be the implementation stack; here is the
evidence-based comparison, including what I could actually verify in this environment.

### 3.1 Capability evidence

- **Qt 6 / Qt Quick.** GPU scene graph over QRhi (Vulkan/Metal/D3D/OpenGL). Custom
  shaders are first-class but must be pre-baked to `.qsb` via the `qsb` tool; inline
  GLSL strings were removed in Qt 6 and `ShaderEffect.fragmentShader` is now a URL
  ([Qt — Changes to Qt Quick](https://doc.qt.io/qt-6/quick-changes-qt6.html),
  [Qt blog — Graphics in Qt 6.0](https://www.qt.io/blog/graphics-in-qt-6.0-qrhi-qt-quick-qt-quick-3d)).
  `Shape`/`ShapePath` gives resolution-independent vector arcs rendered through the
  scene graph rather than software rasterisation, which is the recommended way to
  build animated gauges/rings — with the documented caveat that geometry generation
  is CPU-side, so prefer *one* `Shape` with multiple `ShapePath`s over many `Shape`s
  ([Qt — Shape](https://doc.qt.io/qt-6/qml-qtquick-shapes-shape.html)).
- **GTK4/GSK.** `GskGLShader` — the natural route for HUD glow/scanline effects — was
  **deprecated in GTK 4.16**; the 4.14 renderer rewrite dropped support and Vulkan
  integration made it impractical to keep. GTK now points custom-GL users at
  `GtkGLArea`, i.e. hand-rolled OpenGL outside the scene graph
  ([GTK docs — Gsk.GLShader](https://docs.gtk.org/gsk4/class.GLShader.html)).
  For a shader-heavy HUD this is a **material architectural risk**, not a preference.
- **Flutter.** Owns its renderer (Impeller), giving consistent frame pacing for
  animation-heavy UIs; cost is a ~30–80 MB bundle and Dart
  ([Tauri vs Flutter 2026](https://rustify.rs/articles/rust-tauri-vs-flutter-2026)).
- **Tauri.** Smallest footprint, but rendering is delegated to the OS WebView — on
  Linux that is WebKitGTK, and *"animation smoothness on Linux with WebKitGTK can be
  inconsistent"*. The same source concludes: apps with complex custom animations and
  pixel-critical graphics favour an owned renderer
  ([Tauri vs Flutter 2026](https://rustify.rs/articles/rust-tauri-vs-flutter-2026)).
  A HUD is precisely that category.
- Independent toolkit comparison reaches the same split: *"GTK is better for
  lightweight apps, while Qt excels at complex, animated UIs"*
  ([GTK vs Qt](https://linuxvox.com/blog/what-should-i-choose-gtk-or-qt/)).

### 3.2 Environment evidence — `VERIFIED-LOCAL`

Commands were run in this workspace on 2026-09-03 (Debian 12, x86_64, 2 vCPU, 3 GB RAM,
no `$DISPLAY`). Observed results:

| Check | Result |
|---|---|
| Debian apt mirrors (`deb.debian.org`, `ftp.debian.org`, mirrors.kernel.org, snapshot.d.o) | **unreachable** — `apt-get update` fails, `apt-get install libgl1` → *Unable to locate package* |
| PyPI / `files.pythonhosted.org` | reachable (HTTP 200) |
| `static.rust-lang.org`, `sh.rustup.rs`, `storage.googleapis.com` | **unreachable** |
| `cmake`, `pkg-config`, `cargo`, `rustc`, `flutter`, `qmake6` | not installed, not installable here |
| `gcc` 12.2.0, `node` v22, `python` 3.11.2 | present |
| `pip install PySide6-Essentials` (venv) | **succeeded — PySide6 6.11.2 / Qt 6.11.2** |
| Rendering a QML `Shape`+`PathAngleArc` HUD arc headless (`-platform offscreen`, software backend) and grabbing the frame | **succeeded — 400×300 PNG produced, arc + letter-spaced type rendered correctly** |

Consequences, stated plainly:

- **Tauri is not buildable here** (no Rust toolchain, no way to fetch one).
- **GTK4 is not buildable here** (no apt, no `pkg-config`, no GTK dev headers) — and
  is independently disqualified on the deprecated-shader grounds above.
- **Flutter is not buildable here** (no SDK, `storage.googleapis.com` blocked) and its
  Linux desktop build additionally needs CMake/GTK dev packages we cannot install.
- **Qt 6 is buildable, runnable and testable here today** via the PySide6 wheels.

`libGL.so.1`/`libEGL.so.1`/`libdbus`/`libxkbcommon` are absent from the base image; I
made Qt import by generating version-scripted no-op stub libraries from the exact
undefined symbols in the Qt shared objects. **This is a sandbox-only CI shim for
headless rendering — it is not part of the product and will be confined to a clearly
labelled test-harness script, never to runtime code.** On a real Linux desktop these
libraries are present and no shim is involved.

### 3.3 Licensing

PySide6 is **LGPLv3 / GPLv2 / GPLv3** (commercial optionally available)
([PyPI — PySide6](https://pypi.org/project/PySide6/)). Using it as an unmodified
imported library does not impose source-disclosure on our application code, unlike
PyQt6 which is GPLv3 ([PythonGUIs — PyQt6 vs PySide6 licensing](https://www.pythonguis.com/faq/not-an-open-source-application-which-one-to-use-pyqt5-or-pyside2/)).
**Therefore: PySide6, not PyQt6.** We will dynamically link (normal pip install), keep
Qt unmodified, and ship LGPL notices.

### 3.4 Recommendation

**Qt 6 (Qt Quick / QML + PySide6), targeting Linux.** It is the only named candidate
that is simultaneously (a) documented-best for complex animated GPU UIs, (b) free of a
deprecated-critical-path problem, and (c) verifiably buildable, runnable and testable
in this environment. Flutter/Tauri/GTK4 remain documented alternatives in this file;
the decision is reversible only at high cost, so it is escalated to you before any
product code is written (Guideline 20).

## 4. Testing approach evidence

- Qt Quick Test (`tst_*.qml` + `TestCase`) is the supported QML unit-test harness, and
  Qt documents `-platform offscreen` as the way to run it without a display
  ([Qt Quick Test](https://doc.qt.io/qt-6/qtquicktest-index.html)).
- Qt's own test guidance says to **avoid bitmap capture/comparison** as a primary
  assertion (resolution, theme, fonts make it flaky) and to prefer property assertions
  plus `QTRY_*`-style polling over fixed sleeps
  ([Qt Test Best Practices](https://doc.qt.io/qt-5/qttest-best-practices-qdoc.html)).
  Our plan follows this: property/state assertions are the gate; screenshots are
  review artefacts only, never a pass/fail condition.
- `pyside6-qmllint` 6.11.2 is available in the venv (`VERIFIED-LOCAL`) and will be a
  CI gate.

## 5. Open questions requiring your direction

Recorded here for auditability; asked of you directly in chat.

1. Confirm Qt 6 + QML/PySide6 as the stack (vs. Flutter / Tauri / GTK4).
2. Is this a **standalone HUD shell with real local telemetry**, or must it integrate
   an existing assistant backend (LLM / STT / TTS)?
3. Python (PySide6) or C++ (Qt6 native) for the backend layer — noting only Python is
   verifiable in this sandbox.

---

# Addendum — Round 2 research (2026-09-03)

Deeper research into *behaviour* rather than appearance, to answer "what makes it
JARVIS, not just a cyan dashboard". Sources fetched in full rather than from snippets.

## 6. The four awarenesses

The definitive critical framework for this HUD, from the *Make It So* augmented-reality
chapter, applied to the Iron HUD
([scifiinterfaces](https://scifiinterfaces.com/2015/07/21/iron-man-hud-1-person-view/)):

| # | Awareness | In the film | Our analogue |
|---|---|---|---|
| A1 | **Sensor display** | Compass, altimeter, Mach speed, status readouts | CPU, memory, swap, thermal, load, network, storage |
| A2 | **Location awareness** | Wireframe coastline, live air-traffic overlay | Not applicable — deliberately not faked |
| A3 | **Context awareness** | Reticles jump to objects, then outline them and attach information | Reticle brackets lock onto the subsystem currently in trouble |
| A4 | **Goal awareness** | Graphics tailored to the task at hand | Mode-driven layout, already implemented |

We implement A1, A3 and A4. **A2 is deliberately omitted**: we have no location data,
and inventing a map would be exactly the fabrication the project forbids.

## 7. Attention escalation — the single most important behaviour

This is the finding that most changes the product, and it is stated directly in the
source analysis:

> "having those teeny little gauges dancing around as a signal of troubles ahead won't
> really get Tony's attention… Fortunately, JARVIS… is able to track where Tony is
> looking, and **if he's *not* looking at the wiggling gauge, JARVIS can choose to
> escalate the signal**: hide the air traffic data temporarily and show the problem in
> the main screen. Here, as in other mission critical systems, **attention management
> is crisis management**."
> — [scifiinterfaces, 1st-person view](https://scifiinterfaces.com/2015/07/21/iron-man-hud-1-person-view/)

The same source grounds this in perceptual science: the **fovea** covers only a few
dozen degrees, so localised detail and motion in the periphery are *not* enough to
capture attention. A commenter adds, and the linked demonstration supports, that
**sharp gradients — high contrast — are detectable outside foveal extent** where fine
detail is not.

**Design consequences, adopted:**

- **D9 — Escalate, do not merely indicate.** A critical condition displayed only in a
  peripheral panel is a *failed* notification. When a metric goes critical while it is
  only shown peripherally, the HUD must promote it to the centre of the display.
- **D10 — Peripheral signals must be high-contrast, not high-detail.** Escalated
  alerts use large type and strong contrast rather than small, finely-detailed
  indicators.
- **D11 — Escalation must be stable.** Real crisis management is undermined by
  flapping, so escalation requires the condition to persist and uses hysteresis on the
  way back down. (Our engineering addition, not from the source.)

**Honest limitation:** we have no eye tracking, and will not pretend to. Where JARVIS
uses gaze, we use an explicit, documented proxy — whether the metric is currently
presented centrally or peripherally in the active mode. This is recorded in the code
and the design system as a proxy, never described as attention sensing.

## 8. Gauge inventory and progressive disclosure

Five gauges persist across every iteration of the HUD: **suit status, targeting and
optics, radar, artificial horizon, and map**
([breakdown](https://scifiinterfaces.com/2015/07/01/iron-man-hud-a-breakdown/)).

Critically, they are **small and peripheral while not needed, and become larger and
more central when they are** — and Tony can summon greater detail, or a different
visualisation of the same information, for any gauge
([functions](https://scifiinterfaces.com/2015/07/13/iron-man-hud-just-the-functions/)).

**D12 — Size encodes relevance.** A component's prominence should track its current
importance, not sit fixed in the layout.

## 9. Context awareness: the reticle behaviour

> "As Tony sweeps his glance across his garage, complex reticles jump to each car.
> Split-seconds afterwards, the car's outline is overlaid and some adjunct information
> about it is presented."

**D13 — Acquire, then annotate.** The interface first *brackets* the object of
interest, then attaches information — a two-stage motion, not a single fade-in.

## 10. Design discipline from the designer

Jayse Hansen, on the stereo work for *The Avengers*
([Pushing Pixels](https://www.pushing-pixels.org/2012/06/01/the-craft-of-screen-graphics-and-movie-user-interfaces-conversation-with-jayse-hansen.html)):

> "everything is in focus – so everything is readable. We ended up with a much more
> detailed look where we can read, for the first time, the small micro text and so we
> made sure that **all the text is related to the scene, and all the graphics had a
> purpose**"

He also coins the counterpoint — the "**NUI**", or *non-usable interface*: film UI
deliberately breaks usability rules to show what the computer is doing, whereas real UI
hides it ([TNW](https://thenextweb.com/news/jayse-hansen-on-creating-tools-the-avengers-use-to-fight-evil-touch-interfaces-and-project-glass)).

**D14 — Borrow the expressiveness, not the illegibility.** This is a real tool, so
where the film's NUI conventions conflict with usability, usability wins. Every
graphic must still carry a purpose — which is the film's own stated rule anyway.

## 11. Typography

The sci-fi baseline is the squared-geometric sans — Eurostile, Microgramma, Bank
Gothic — whose rounded-rectangle forms read as machined
([FilmFont](https://filmfont.com/articles/best-sci-fi-movie-fonts),
[TV Tropes](https://tvtropes.org/pmwiki/pmwiki.php/Main/TypesetInTheFuture)). Method
Studios built a squared Bank Gothic variant for *The Avengers* credits.

**Decision: do not bundle a font.** Eurostile and Bank Gothic are commercially
licensed, and adding a font dependency is not justified for the gain
(guideline 16). `VERIFIED-LOCAL`: this environment exposes only DejaVu Sans, DejaVu
Sans Mono, DejaVu Serif and the generic aliases. We therefore keep the system
monospace and obtain the machined feel through **wide letter-spacing on upper-case
labels**, which is the dominant characteristic of the look and costs nothing. A
squared OFL face may be revisited later as an explicit, justified dependency.

## 12. What this round deliberately does NOT add

Recorded as considered-and-rejected, per guideline 19:

- **Webcam, face mesh, gesture control** — several surveyed projects do this. It is a
  large dependency and a privacy surface, with no requirement behind it.
- **3D/holographic depth, curved panels on a sphere** (D4) — genuinely part of the
  source design, but it needs Qt Quick 3D and would be decoration on a 2D monitor.
- **A world map or location panel** — no data source; would be fabrication.
- **Red/gold "Iron Man" palette variant** — the HUD proper is cyan-dominant; the
  red/gold suggestion comes from an AI-prompt marketing page, not a primary source.

---

# Addendum — Round 3: motion language (2026-09-04)

The user's brief: make it feel like *an actual JARVIS*, not just a GUI — more
animation, more "tech". This round researched **how the reference material
moves**, and studied a prior JARVIS GUI the user built themselves.

## 13. Primary source: the original HUD team

From the oral history of the 2008 HUD
([befores & afters](https://beforesandafters.com/2019/03/18/heads-up-the-oral-history-of-iron-mans-original-hud/)),
VFX supervisor John Nelson's three rules, quoted by Kent Seki:

1. **Driven by the performance.** The graphics react to the person, not the
   other way round.
2. **Let the Z-axis work.** "The implied Z-space depth *behind* the camera was
   just as important as what the audience could see." Elements fly in and out
   from beyond the frame, not from within it.
3. **An "alpha event" in every shot.** "There needs to be a story point that
   you hit home with a graphic… Most alpha events weren't noticeable or even
   obvious; however, they reinforced the subtext of the moment."

Kent Seki on depth: *"the success of the depth… the movement of the HUD.
Meaning, using the way the HUD graphics moved and got attention/activation were
used to create depth."* **Depth is created by motion, not by perspective.**
This matters enormously for us: we are on a flat monitor with no stereo, and
this says we do not need one — staggered, differently-timed motion *reads* as
depth.

Jonathan Rothbart notes the elements "could go all the way around his head and
fade on and off", and that graphics fly in "as if they were coming in and out
behind camera".

**Adopted principles:**

- **D15 — Motion creates depth.** Layers move at different rates and arrive
  from beyond the frame. No Qt Quick 3D, no fake perspective; parallax and
  stagger do the work.
- **D16 — Every state change deserves an alpha event.** A state transition
  should be *punctuated* by a graphic, not merely reflected in a label. The
  research explicitly notes these are usually subtle.
- **D17 — Nothing snaps.** Elements arrive and leave; they do not appear and
  disappear.

## 14. The honest counterweight

The same body of criticism is blunt about the cost, and it is the reason this
round is a *disciplined* addition rather than a free-for-all
([scifiinterfaces](https://scifiinterfaces.com/category/marvel-cinematic-universe/iron-man/)):

> "The HUD is a massive distraction… there are 29 elements… Of those **87%
> reposition themselves against his field of view without his having asked for
> it**. **6 risk dangerous mid-flight startle reactions by expanding quickly in
> place.** Every one of them is overlaid via transparency with at least one
> other element."

**D18 — Ambient motion must never startle, and never relocate data.** Animation
is permitted to: rotate decorative rings, drift particles, pulse glow, sweep a
scanline, and stagger entrances. It is **forbidden** to: move a readout the
operator may be reading, or expand something quickly in place. Escalation (D9)
is the sole exception, and it is deliberate, hysteresis-damped and rare.

**D19 — Motion is a budget, not a feature.** Ambient animation must be
disableable, must stop when it cannot be seen, and must not be the reason a
reading is late.

## 15. Prior art: the user's own JARVIS_GUI

Studied at `github.com/Anish932-hash/JARVIS_GUI` (Next.js/React/Tailwind,
committed 2026-02). Its `tailwind.config.ts` defines a **34-keyframe motion
vocabulary**, which is the most directly relevant reference available because
it represents the user's own taste. Concepts adopted, reimplemented natively in
QML (no code copied — different language and framework entirely):

| Their keyframe | What it does | Our adaptation |
|---|---|---|
| `trace-in` (stroke-dashoffset) | Rings/circuits draw themselves on | Boot ring tracing via `PathAngleArc.sweepAngle` |
| `particle-line-in` | Streaks converge on the core from a radius | Boot convergence streaks |
| `jarvis-letter-in` | Title letters rise, blur→sharp, staggered | Per-letter staggered title boot |
| `scanline` | Gradient band sweeps down | Ambient HUD scanline |
| `breathing-glow` | Slow glow in/out on the core | Core breathing halo |
| `scanner-line-rotate/fade` | Radar sweep line during "thinking" | PROCESSING-state sweep |
| `particle-drift` | Ambient particles around the core | Ambient drift field |
| `waveform-bar` | Radial bars pulse around a circle | Reserved — needs audio we do not have |
| `spin-slow` / `orbit` | Multi-speed concentric rotation | Already present; extended with stagger |
| `flicker` / `holographic-flicker` | Border opacity instability | Used sparingly on the core only |

Their `central-core.tsx` also does per-status ring speed changes and a
**mouse-parallax tilt** on the core — the latter is a direct, cheap
implementation of D15 (motion creates depth) and is adopted.

Deliberately **not** adopted from that project: the Orbitron webfont (licensing
+ no bundled fonts policy), the AI chat/TTS flows (explicitly out of v1 scope),
and the `waveform-bar` audio visualiser (we have no audio input — animating it
would be fabricating a signal, violating the honesty contract).

## 16. Capability check — `VERIFIED-LOCAL`

Probed this environment directly rather than assuming:

- `QtQuick.Particles` **is available and loads under the software backend.**
- `QtQuick.Effects` (`MultiEffect`, for blur/glow) **is available and loads.**
  This supersedes the earlier note that glow required layered strokes — that
  workaround was for the *shader* toolchain (`.qsb`), which is still broken.
  `MultiEffect` needs no shader compilation from us.
- `QtQuick.Timeline` is present but not needed.

Both were confirmed by loading a probe QML file offscreen and grabbing a
non-null frame. **Still not verified:** GPU behaviour, real frame rates. All
performance claims remain unmade.

---

# Addendum — Round 4: the assistant orb (2026-09-04)

Brief: "make the Voice HUD, and all, more better like my web GUI." Studied
`voice-hud.tsx`, `looping-voice-hud.tsx`, `central-core.tsx` and
`use-voice-assistant.ts` in the user's project.

## 17. What their Voice HUD actually is

A **full-screen modal takeover**. The ambient HUD recedes and a single large
orb owns the display, cycling through five statuses with a distinct visual
signature for each:

| Status | Visual signature |
|---|---|
| `idle` | Rings only, slow rotation |
| `listening` | **120 radial bars** around the rim + particles sucked inward |
| `thinking` | Two counter-rotating scanner lines + floating hexagon glyphs; rings speed up and the whole assembly scales to 1.05 |
| `speaking` | **Four ripple rings** expanding outward on a 0.5 s stagger + an energy pulse |
| `error` | Rings only, message shown |

Structural notes: the core sits on ~7 `translateZ` planes from −150 px to
+80 px; ring rotation periods change per status (40 s idle → 10 s thinking);
status text sits below the orb; the name is rendered at the centre.

## 18. The decisive observation — it is not an audio meter

The obvious reading of "120 bars around a circle" is a microphone visualiser.
**It is not.** In `voice-hud.tsx` each bar is:

```
className="animate-waveform-bar"
style={{ animationDelay: `${i * 0.025}s`, animationDuration: '1.5s' }}
```

A fixed CSS keyframe with an index-derived delay. It never touches the audio
stream. The microphone lives entirely in `use-voice-assistant.ts`
(`webkitSpeechRecognition`), which produces a *transcript* — and the transcript
is displayed as **text**, not as a waveform.

So the ring is a **state visualiser**: it means "the assistant is in the
listening state", not "this is the sound arriving right now". That distinction
is what makes it reimplementable here without violating the honesty contract.

**D20 — A visualiser may encode state; it must never imply a signal that is not
being measured.** The rim animation is legitimate because it is driven by, and
only claims to represent, the assistant state. Sizing those bars from fake
amplitude data would be fabrication, and is refused.

## 19. Capability check — `VERIFIED-LOCAL`

- **`PySide6.QtMultimedia` is not installed** in this environment
  (`ModuleNotFoundError`). There is no audio capture path, and none is added:
  the runtime dependency stays PySide6-Essentials only.
- Consequently **no microphone, no STT, no TTS, no wake word** — unchanged from
  the v1 scope decision. The orb is driven by the existing eight-state machine.

## 20. State mapping

Their five statuses map onto our eight states, which are already real and
already validated by a transition table:

| Theirs | Ours |
|---|---|
| `idle` | `STANDBY` |
| `listening` | `LISTENING` |
| `thinking` | `PROCESSING`, `EXECUTING` |
| `speaking` | `SPEAKING` |
| `error` | `ERROR`, `OFFLINE` |

`EXECUTING` gains its own treatment rather than being folded into thinking:
we can distinguish "deciding" from "doing", and the user's design has no
equivalent only because their pipeline has no such stage.

## 21. What is adopted, and what is not

**Adopted:** modal full-screen takeover; per-state visual signatures; radial rim
bars for `LISTENING`; counter-rotating scanners for `PROCESSING`; staggered
ripples for `SPEAKING`; status caption beneath the orb; per-state ring speed.

**Not adopted:**

- **Real 3D `translateZ` planes.** We get the depth read from motion and
  parallax instead (D15), which is already the project's established approach
  and needs no Qt Quick 3D.
- **The transcript line.** There is nothing to transcribe.
- **Auto-cycling through statuses on a timer** (their `central-core.tsx` demos
  this). Ours reflects the genuine state machine; a decorative cycle would be
  theatre implying activity that is not happening.

## 22. Round 5 addendum — the user's Neon OS screenshots

Two screenshots of the user's running web GUI (`localhost:3000`), supplied
directly. Unlike §17-21, which came from reading their source, these show the
composed result and so are evidence about *layout*, not implementation.

**Observed elements.** Screen-edge corner brackets; a very large monospaced
clock with date and weekday; a centred JARVIS orb with concentric rings and a
drifting particle field; a left "SYSTEM DIAGNOSTICS" column with ring gauges for
CPU/GPU/RAM plus network, storage and power bars; a right column of "USER PC
SPECS" and "OPENED APPS"; a bottom-left "Boost Performance" button; a chat
composer as the primary input.

### D21 — Adopt the composition, re-source the content

The layout is genuinely good: brackets and a large clock give the display
structure and a fixed reference point, and flanking columns leave the centre
clear for the assistant. All of that is adopted.

The *content* of two panels cannot be. "CPU: ARK-2500 Reactor", "GPU: Stark
Industries GFX-9000", "RAM: 128 ZB" and a permanently full 100% battery are
decoration in the shape of telemetry. Reproducing them would break the
project's central rule.

The resolution is to keep the panel and change where its numbers come from:

| Reference element | This project |
|---|---|
| PC SPECS (fictional) | `HostIdentity` from `/proc/cpuinfo`, `/proc/meminfo`, `/etc/os-release`, `/proc/sys/kernel/*` |
| Power 100% CHARGING (static) | `BatterySnapshot` from `/sys/class/power_supply`, hidden entirely when the host has no battery |
| GPU ring gauge | **Not built.** No vendor-neutral GPU utilisation counter is readable here: no `gpu_busy_percent`, no `nvidia-smi`. Verified absent rather than assumed. |
| OPENED APPS | **Not built.** Enumerating windows needs a compositor protocol this project does not speak, and reading other processes' identities is a privacy question that has not been asked. |
| Boost Performance | **Not built.** A button that claims to make the machine faster and does nothing is the purest form of the fabrication this project refuses. Real work would mean writing to cpufreq governors — privileged, dangerous, and out of scope. |

### D22 — Absence and degradation are different states

`degraded_sources` means "a source that should exist could not be read". A
desktop with no battery is not degraded; it has no battery. Conflating the two
would show a permanent false fault on every desktop. Absent readings are hidden;
degraded readings are announced.

---

## 22. Showing work in progress — what the kernel can actually tell us

The question this round: **when the backend is doing a task, how should the HUD
show it?** The design is constrained far more by what the kernel emits than by
what would look good, so the measurements come first.

### 22.1 What the kernel emits during a task — `VERIFIED-LOCAL`

Measured against a live `jarvis mcp serve` at kernel **1.19.0**.

**There are no progress notifications.** The MCP server is strictly
request/response: `_handle` returns one frame per request and the only
notification in the contract is `notifications/initialized`, client-to-server.
Nothing arrives between sending `tools/call` and receiving its result. Verified
by reading `cli/mcp_server.py` (508 lines, no server-initiated frames) and by
observing the wire.

**The journal is written during execution, but not usefully.** `Orchestrator`
calls `begin_task` (status `running`, committed immediately) and then
`record_step` per step inside the execution loop, each with its own commit. So
in principle the journal is a live progress source. In practice it is nearly
useless for progress, because a step row is written **after** the command
returns. Polling `~/.local/state/jarvis/journal.db` every 30 ms across a
7.2-second single-step task produced exactly three distinct states:

| Time | Task status | Steps visible |
|---|---|---|
| +0.12s | `running` | *(none)* |
| +7.21s | `succeeded` | both steps, both `succeeded` |

The entire wait is a single opaque interval. **A step-level progress display
would show "0 of ?" for the whole task and then jump to done.** That rules out
the dynamic-checklist pattern that the agentic-UX literature otherwise
recommends — we have the plan, but no live position within it.

**Round-trip durations are bimodal** (measured, same session):

| Call | Duration |
|---|---|
| handshake | 0.09 s |
| `jarvis_status`, `jarvis_facts`, `jarvis_suggest` | ≤ 0.01 s |
| `jarvis_explain` (KB hit), `jarvis_preview` | ≤ 0.01 s |
| `jarvis_do` — T2 refusal | 0.01 s |
| `jarvis_do` — real execution (`ping`) | **7.09 s** |
| AI provider timeout (`providers/base.py`) | **90 s** budget |

Everything that does not execute a command or call an LLM returns in under
10 ms. Everything that does can run for seconds to a minute and a half.

**The UI thread is free during a task** — `VERIFIED-LOCAL`. Both transports are
signal-driven and non-blocking: the spawned client uses `QProcess` with
`readyReadStandardOutput`/`finished` signals, and the resident client uses
`QNetworkReply.finished`. Neither blocks on the wait (the only
`waitForFinished` calls are in teardown). So an animated indicator and a
running elapsed counter are actually renderable during a 7-second task — worth
confirming, because a blocking bridge would have made every option below moot.

### 22.2 The literature

**Nielsen's three response-time limits** (from *Usability Engineering*, 1993;
Miller 1968 found the same breakpoints): 0.1 s feels instantaneous, 1 s keeps
the user's flow, **10 s is the limit of attention**. Past 10 s users task-switch
and need to be told when to come back.
<https://www.nngroup.com/articles/powers-of-10-time-scales-in-ux/>

**Myers (CHI '85)** ran 48 students with and without a percent-done bar:
**86% preferred having the bar**, even though it made nothing faster. People
want to know.

**Maister's *Psychology of Waiting Lines* (1985)**, four laws that transfer
directly: occupied time feels shorter than unoccupied; **uncertain waits feel
longer than known finite waits**; **unexplained waits feel longer than explained
waits**; anxious waits feel longer than calm ones.

**Buell & Norton, *Management Science* (2011)** — the **labor illusion**: users
rated a travel site that narrated its work ("now searching Delta…") as more
valuable, and preferred a *slower* site that showed its work to a faster one
that hid it. Visible effort reads as value — but only when the work is real.

**NN/g's threshold rule**: looped animation for 2–10 s, percent-done for 10 s+;
lower the cutoff when the estimate is uncertain.
<https://www.nngroup.com/articles/progress-indicators/>

**UX Tigers, "Progress Indicators Ease the Wait" (2026)** — the most directly
applicable source, because it addresses agentic waits specifically. Two ideas
govern our design:

- **The denominator problem.** "Percent-done requires a known total, and
  open-ended knowledge work has none… Faking a percentage would be progress
  theater with extra steps, so don't."
- **Progress theater**: "animation that mimics measurement while measuring
  nothing… fake 'thinking' animations, padded reasoning streams, chirpy status
  lines that map to no actual work." And the rule that settles every question
  below: **"tie the display to real measurements, or don't display it."**

Its prescription when percent-done is impossible: the plan as a live step list;
activity narration in user units; interim artifacts; **elapsed time always,
remaining time only when honest**; and a completion call for waits past a
minute. Also: *"An honest slow bar beats a lying fast one."*
<https://www.uxtigers.com/post/progress-indicators>

**Smashing Magazine, "Practical Interface Patterns For AI Transparency"
(2026)** — names the four containers and, usefully, when each is wrong: the
Living Breadcrumb (low-stakes background work), the Dynamic Checklist
(high-stakes, variable duration), the Thinking Toggle (progressive disclosure
into raw logs), and the Audit Trail ("real-time transparency is fleeting… if a
user walks away they miss the checklist").
<https://www.smashingmagazine.com/2026/05/practical-interface-patterns-ai-transparency/>

### 22.3 What follows for this HUD

Applying the above to the measurements, not to a general idea of "showing
progress":

### D23 — No percentage, no step counter, no ETA. Ever.

We cannot compute any of them. The kernel gives us no position within a task,
and step rows land only after the fact. A "step 1 of 2" display would sit at
1 of 2 for the entire wait and be a lie about position; a percentage would be
pure invention. This is the denominator problem in its exact form, and the
answer from the literature is unambiguous: don't fake it.

### D24 — Elapsed time is the honest denominator-free number, and the only number shown.

Wall-clock elapsed is real, measurable by us, and needs nothing from the
kernel. It is the one quantity we can display without asserting anything we
do not know.

### D25 — The activity display is a ladder keyed to measured durations.

Because durations are bimodal, one treatment cannot serve both ends. Onset
thresholds follow Nielsen/NN/g, cut against our own measurements:

| Elapsed | Treatment | Why |
|---|---|---|
| < 1 s | nothing beyond the existing state change | Sub-second indicators are visual noise (guideline 1). Covers every read-only call we measured. |
| 1–10 s | activity indicator + what was asked, no number | The "system is alive" claim, which is all we can honestly make. Covers the 7 s execution case. |
| > 10 s | the above + elapsed counter + a plain-language note that this is taking a while | Past the attention limit the owner deserves to know it is unbounded, and elapsed is the only honest figure. |
| > 60 s | the above + the run stays inspectable and the completion is announced on return | Assume the owner has left, and rightly so. |

### D26 — Narrate the request, not the plumbing.

"Executing: restart the ssh service" is a user unit. "tools/call id=7" is not.
Where a plan was previewed we already hold the step descriptions and argv, so
the display can name **what was asked for** and, on demand, what will run —
the labor illusion deployed honestly, because the work is real.

### D27 — The wait is a state of the HUD, not a modal overlay.

The HUD already has an eight-state machine with `PROCESSING` and `EXECUTING`,
an orb that reflects state, and a reactor whose spin rate is state-driven. A
foreign modal spinner would be a second, competing status language. The
existing states *are* the indeterminate indicator; what is missing is the
**subject** of the wait and its **elapsed time**, not a new widget.

### D28 — Distinguish "working" from "waiting on you".

`PROCESSING` (kernel is busy) and a pending consent prompt (kernel is idle,
waiting on the owner) are opposite conditions that both suspend the console. If
they look alike the owner will wait for a machine that is waiting for them.
The consent prompt already owns the display when it is up; the activity
indicator must be absent then, not merely behind it.

### D29 — Cancellation must not claim more than it does.

We can stop *listening* to a request, and on the spawned transport we can kill
the process. Neither retracts a command the kernel has already handed to
`apt-get`. A control labelled "Cancel" would imply the action is undone. If a
stop control is offered it says **"Stop waiting"**, and the log records that the
task may still be running — the same honesty rule as the reversibility gate.

### D30 — The transcript is the audit trail; the indicator is for monitoring.

Real-time transparency is fleeting: an owner who walks away misses it entirely.
The console log already persists what was asked, what was refused and what ran.
The activity indicator therefore does not need to be a scrolling record — it
needs to be glanceable, and the log needs to remain complete enough to answer
"what happened while I was gone?" afterwards.
