# Agent Experience Log

A candid record of what was attempted, what broke, what was learned, and what remains
unverified. Every claim of verification names the command that produced it.

---

## M0 — Research & Planning (2026-09-03)

### What I set out to do

Choose between the four named toolkits (Qt6, Flutter, Tauri, GTK4/GSK) on evidence
rather than preference, research what a JARVIS HUD actually is, and produce a plan
before writing any product code.

### Challenges encountered

**1. The repository was effectively empty.**
`git log` showed a single "Initial commit" and the tree contained one file, a two-line
`README.md`. There was no existing architecture, dependency set, configuration or test
suite to inspect — so guideline 12 ("inspect before modifying") resolved to
"there is nothing to preserve, and every decision is still open". That raised the bar
on guideline 9: with no precedent, the stack choice must be justified from scratch.

**2. The sandbox has no system package manager access.**
`apt-get update` failed on every Debian mirror; `deb.debian.org`, `ftp.debian.org`,
`mirrors.kernel.org` and `snapshot.debian.org` all returned connection failures, while
PyPI and GitHub were reachable. `apt-get install libgl1` returns *Unable to locate
package*. This single fact eliminated three of the four candidate toolkits from being
*verifiable* here: Tauri needs a Rust toolchain (`static.rust-lang.org` blocked),
Flutter needs its SDK (`storage.googleapis.com` blocked) plus CMake/GTK dev packages,
and GTK4 needs `pkg-config` and dev headers. Qt 6 survived only because PySide6 ships
self-contained manylinux wheels.

The important discipline here was **not to let convenience masquerade as architecture**
(guideline 20). "Qt is the only one I can build" is a real and decisive constraint, but
it is not by itself a good technical reason — so I went and found the independent
technical case too, and the strongest one turned out to be about GTK: `GskGLShader` was
deprecated in GTK 4.16 because the 4.14 renderer rewrite dropped support for it. For a
glow-and-scanline HUD that is a deprecated critical path, which is a genuine
architectural disqualifier independent of this sandbox. I have written both reasons
into `docs/RESEARCH.md` and still escalated the decision rather than assuming it.

**3. Qt would not import: four missing shared libraries.**
`from PySide6.QtGui import QGuiApplication` failed with
`ImportError: libGL.so.1: cannot open shared object file`. `ldd libQt6Gui.so.6` showed
four unresolved: `libGL.so.1`, `libEGL.so.1`, `libdbus-1.so.3`, `libxkbcommon.so.0`.

My first attempt — trivial one-symbol stub `.so` files — got further but then failed
with `undefined symbol: dbus_server_get_address, version LIBDBUS_1_3`. The lesson: the
loader checks *symbol versions*, not just soname. The fix that worked was to extract
every undefined `gl*`/`egl*`/`dbus_*`/`xkb_*` symbol from all the Qt shared objects and
plugins with `nm -D --undefined-only --with-symbol-versions`, generate no-op C stubs
(41 GL, 26 EGL, 89 dbus, 42 xkb), and link each with a matching `--version-script`.

**This shim is a sandbox artefact and must never touch product code.** Real Linux
desktops have these libraries. I am recording it because a future maintainer running
tests in a minimal container will hit exactly this wall — and because silently shipping
stubbed graphics libraries would be precisely the kind of thing guideline 1 forbids.

**4. Verifying the stack for real rather than assuming it.**
With the shim in place I ran a genuine end-to-end check: a QML file using
`Shape`/`ShapePath`/`PathAngleArc` — the exact primitive the reactor gauges will be
built from — loaded through `QQuickView` under `QT_QPA_PLATFORM=offscreen` with the
software backend, then `grabWindow()` to a PNG. It produced a correct 400×300 image
with a clean cyan arc and letter-spaced type. That is the difference between "Qt should
work" and "Qt works here, and here is the picture".

**5. `pyside6-qsb` is broken in this venv.** It tracebacks on `--help`. Qt 6 removed
inline GLSL and requires shaders pre-baked to `.qsb`, so custom shaders are simply not
available to me right now. Rather than write shader code I cannot compile or test, I
scoped v1 to achieve glow with layered `Shape` strokes and opacity, and recorded shaders
as an honestly-deferred future milestone.

### Learning moments

- **Deprecation notices are architecture signals.** The GTK 4.16 `GskGLShader`
  deprecation was worth more to this decision than any framework benchmark blog post.
- **Cinema research changed the requirements, not just the palette.** Reading the
  designers' own accounts surfaced two things I would not have invented: the HUD is
  *mode-driven* (it recomposes wholesale between Analysis and Flight modes), and the
  critical literature identifies a real usability flaw — unlabelled cryptic telemetry
  like `N -8 W -97 RNG EL`. So R4 now mandates a label and unit on every readout. The
  reference is the *inspiration*, not the specification.
- **Surveying prior art paid off twice**: it produced a genuinely reusable pattern (the
  explicit eight-state assistant machine from Open.Jarvis, credited) and it justified
  the project's existence — almost every JARVIS GUI out there is Electron/web or
  Windows-first, so a Linux-native GPU HUD is an unoccupied niche rather than
  another showcase.
- **Licensing is a design input.** PySide6's LGPLv3 vs PyQt6's GPLv3 is a real
  downstream constraint, and choosing the binding on licence rather than habit costs
  nothing now and can save a lot later.

### Explicitly NOT verified

- Any rendering on real GPU hardware, X11, or Wayland — this sandbox has no `$DISPLAY`
  and no GL driver.
- Any frame-rate or performance claim. **The 60 fps target in the plan is a target,
  not a measurement.**
- Flutter, Tauri and GTK4 were evaluated from documentation only; none could be built
  or benchmarked here, and I make no first-hand performance claim about any of them.
- The plan's architecture is designed, not implemented. Nothing in `src/` exists yet.

### Where things stand

Three questions are blocking implementation and have been put to the stakeholder:
the toolkit confirmation, the v1 scope boundary (HUD shell with real telemetry vs.
integrating an assistant backend), and Python vs C++. No product code until then.

---

## M1-M6 — Implementation (2026-09-03)

### What I set out to do

Build the HUD the plan described: real telemetry, two modes, an enforced state
machine, honest failure states, and a quality gate that actually runs.

### Challenges encountered

**1. The QML `id: root` shadowing bug — the subtlest defect of the session.**

Every mode file declared `id: root`, and the shell instantiated them inside a
`Component` with `controller: root.controller`. That reads naturally, and it is wrong:
inside a `Component`, an unqualified `root` resolves to the *component's own* root
object, not the enclosing file's. So each mode was binding its `controller` property
to itself, and every child then read properties of `undefined`.

What made this dangerous is that **it rendered anyway**. The layout appeared, the frame
grabbed successfully, and the only evidence was `TypeError` lines in stderr that were
easy to dismiss as noise. Had I judged by the screenshot alone, I would have shipped a
HUD where an entire mode silently showed nothing.

The fix was to give the shell a distinct id (`hudSurface`) so the reference is
unambiguous. The general lesson: in QML, never reuse `root` across files that
instantiate one another, and treat `TypeError` in output as a failure, not as noise.

**2. `required property` fights `Loader`.**

The plan called for a `Loader` to swap modes. But a `Loader` evaluates the component's
bindings *before* applying initial properties, so a `required property var controller`
is still unset on the first evaluation pass and every binding sees null. I tried
gating with `active:` and a `ready` flag; both still produced a null pass.

I stopped working around it and removed the `Loader`. Both modes are now instantiated
directly and cross-faded by opacity. That is simpler, eliminates the entire bug class,
costs nothing (both modes are cheap), and makes switching instant since there is no
re-layout. A case where the simpler design was also the correct one.

**3. Context properties are invisible to the tooling.**

`setContextProperty("hudController", ...)` works at runtime but `qmllint` cannot see
it, so every single reference was reported as an unqualified access — six warnings I
could not fix without either suppressing them or changing the approach.

Suppression would have been the easy call. Instead I migrated to
`qmlRegisterSingletonInstance`, the modern Qt 6 mechanism, and wrote
`tools/generate_qmltypes.py` to emit the QML type description **from the live
`QMetaObject`** rather than by hand, so the description cannot drift from the code.
That got qmllint to *zero* warnings across all ten QML files and gave the linter real
type information about the Python object. It also forced renaming `Hud.qml` to
`HudSurface.qml`, since `Hud` now names the singleton.

Two follow-on details: the generated file needs `exportMetaObjectRevisions` encoding
the same version as the export (`(major << 8) | minor`) or the tooling complains that
they differ; and PySide6 6.11's type stub declares the singleton name parameter as
`bytes` while the runtime rejects bytes and demands `str`. The stub is simply wrong —
I used the runtime-correct value with a documented, narrowly-scoped `type: ignore`.

**4. A test that was wrong, not code that was wrong.**

`test_format_percent` asserted `format_percent(42.55) == "42.6"` and failed with
`"42.5"`. The temptation is to "fix" the code. But 42.55 is not representable in binary
floating point — it is stored as 42.549999…, so `.1f` correctly rounds down. The code
was right and my expectation was wrong. I rewrote the test with values that do not
depend on float representation. Worth recording because the reflex to make the failing
assertion pass by changing the implementation is exactly how a real rounding bug gets
introduced.

**5. Layout bugs a screenshot caught that no unit test would.**

Rendering to PNG and actually *looking* at it caught three defects that were invisible
to property assertions: values in the vitals rail overlapping their own labels (a `Row`
has no baseline of its own, so baseline-anchoring one silently misaligns); panels in
monitor mode clipped, because callers were computing panel height from the panel's own
children — a circular binding; and the reactor core rendering as a flat disc, which
looked like a sticker rather than an instrument.

This is why the headless render is in the gate even though Qt's own guidance says not
to use bitmaps as a pass/fail assertion. The image is not the test; it is the thing
that tells a human where to point the tests.

**6. Getting Qt to import at all in a container with no graphics stack.**

Covered in M0, but it bit again during CI design. The stub libraries are now generated
by a committed, documented script rather than existing as loose binaries I built by
hand, and the gate opts into them explicitly with `JAVRIS_GL_STUBS=1`. They are clearly
marked as never-for-production. A future maintainer hitting `ImportError: libGL.so.1`
in a minimal container now has an answer instead of a mystery.

### Learning moments

- **A rendering that appears is not a rendering that is correct.** The shadowing bug
  produced a plausible screenshot and a broken binding. Warnings in output deserve the
  same seriousness as a failed assertion.
- **Fighting the framework is a signal.** Both the `Loader` and the context-property
  problems dissolved when I stopped working around the framework and adopted the
  mechanism it actually intends. The workaround attempts were strictly worse code.
- **Generate descriptions, never hand-write them.** The `.qmltypes` file could have
  been written by hand in ten minutes and would have started rotting immediately.
  Deriving it from the `QMetaObject` makes drift structurally impossible.
- **`state` is a `QQuickItem` property.** Naming a custom property `state` compiles,
  runs, and misbehaves. qmllint caught the analogous `radius` shadowing on a
  `Rectangle`; the linter earns its place in the gate.
- **Designing for absent data changed the whole architecture.** Deciding early that a
  missing sensor must render as `--` and never as `0` propagated everywhere: `None`
  throughout the models, `-1` sentinels at the QML boundary, a distinct `unavailable`
  colour, and `degraded_sources` on every snapshot. Retrofitting that honesty later
  would have been a rewrite. The sandbox has no thermal zone, so the degraded path was
  exercised constantly rather than being theoretical.

### Explicitly NOT verified

- **No rendering on real GPU hardware, X11 or Wayland.** No `$DISPLAY` and no GL
  driver here; everything used the software rasteriser via `-platform offscreen`.
- **No frame-rate measurement whatsoever.** The 60 fps figure in the plan is a target,
  not a result. Animation smoothness, GPU behaviour and compositor interaction are all
  unverified and need testing on real hardware.
- **Full-screen and frameless window behaviour is untested** — it cannot be exercised
  offscreen and varies by window manager.
- **Keyboard interaction (Tab, Esc) and the console are untested end to end** through
  real input events; the command router beneath them has full unit coverage.
- Flutter, Tauri and GTK4 remain evaluated from documentation only.

### Where things stand

The gate passes end to end: ruff, ruff format, mypy `--strict`, 120 unit tests,
qmllint clean on all 10 QML files, 18 QML tests, and a headless render. The honest
next step is for a human to run it on a real Linux desktop, because the one thing I
cannot do from here is look at it moving.

## M7 — attention escalation

### Research that actually changed the product

The first research round gathered *appearance*: cyan, wireframes, cut corners.
Useful, but it produced a themed dashboard. The second round asked a different
question — what does the system *do* — and the answer reframed the work. The
single most valuable sentence found was the source analysis criticising its own
subject: little gauges wiggling in the periphery will not get the operator's
attention, so escalate the problem into the main display.

That is a *behaviour*, and it is what makes the thing feel like an assistant
rather than a monitor. Lesson: when researching a visual reference, deliberately
spend a pass looking for critique of it, not just description of it. The
criticism is where the design requirements are.

### The gaze proxy

The reference behaviour depends on eye tracking. We have none. The temptation
was to skip the feature or, worse, to imply capability we lack. Instead the
substitute — is this metric already central in the active mode? — is named
`Prominence`, documented as a proxy in three places, and never described as
attention sensing. It also turned out to be *better* than a hack: "don't escalate
what is already big and central" is genuinely correct on its own merits.

The cost is a coupling that will rot silently: `_CENTRAL_METRICS` in Python has
to match the mode QML layouts. That is called out in the design system, because
nothing enforces it.

### Hysteresis was not optional, and I got its scope wrong

Escalation dims the entire HUD, so a metric hovering at 0.70 would strobe the
whole display once per second. Streak counters plus a release margin fixed that.

But I applied the recovery streak to *every* release path, including "the
operator switched to a mode where this metric is central". A test asserting
immediate release failed, and the failure was right and the code was wrong. The
distinction I had missed: hysteresis exists to damp an oscillating **value**. A
mode change is not an oscillation, and neither is a sensor disappearing —
delaying those just leaves something untrue on the screen. Both now bypass the
streak entirely.

Worth noting the test caught this only because it was written from the docstring
I had already written, which described the intended behaviour correctly. Writing
the rationale first made the bug visible.

### The screenshot found what 158 tests did not

Every gate was green, and the rendered frame showed the header cheerfully
reporting **NOMINAL** next to a **CRITICAL** 96.0% memory alert. No test covered
"the header and the banner must agree" because it had not occurred to me that
they could disagree.

Same frame, two more: the mode surface was still at full brightness fighting the
alert, and the reactor core was ghosting straight through the hero number at
0.88 backdrop opacity — the precise low-contrast failure the research had warned
about, reintroduced by my own tasteful transparency.

This is the second milestone running where rendering an image caught a class of
bug the test suite structurally could not. The suite asserts that components
behave; it never asserts that they are *coherent with each other*. Rendering the
unhappy path is now a step, not an afterthought — which is why
`--simulate-alert` exists as a tool rather than as a throwaway snippet.

### Small things

- A `Behavior` cannot animate a `readonly property`. The error message
  ("Invalid property assignment") does not mention `Behavior`, so it reads like a
  binding mistake.
- `ruff` removes `# noqa: SLF001` when the rule is not enabled, and the fix
  suggestion silently discards the explanatory comment attached to it. Prefer a
  real comment over a `noqa` when the rule is not on.
- `.venv/` and `build/` are excluded from workspace snapshots, so both must be
  rebuilt at the start of a session. `pip install -e ".[dev]"` plus
  `tools/sandbox_gl_stubs.py` takes about 20 seconds. Worth checking before
  assuming a tool is broken.

## M8 — motion language

### Reading the user's own code was the highest-value research

The brief said "take inspirations from" a JARVIS GUI the user built two years
ago. That repo's `tailwind.config.ts` turned out to be a **34-keyframe motion
vocabulary** — `trace-in`, `particle-line-in`, `jarvis-letter-in`,
`breathing-glow`, `scanner-line-rotate`. That is a far more precise statement of
what the user actually wants than any amount of prose could be, because it is
their taste expressed as code.

None of it was copied — different language, different framework — but the
*concept inventory* drove the whole milestone. Lesson: when a user points at
prior work of their own, mine it for intent, not for snippets. Their config file
was effectively the design brief.

### Probe capabilities, don't assume them

Earlier notes said glow required layered strokes because the shader toolchain
(`.qsb`) was broken. I nearly carried that forward as "no effects available".
Actually probing found `QtQuick.Particles` **and** `QtQuick.Effects` both
present and loading fine under the software backend — the `.qsb` limitation only
ever applied to shaders *I* would have to compile. A 30-second probe file
invalidated an assumption that would have shaped the whole design.

### The review tool was lying to me

`--boot-progress` printed a filename and looked like it worked. It rendered a
different frame than requested every time, because `bootProgress` carries a
`Behavior`: assigning to it *retargets an animation* instead of setting a value,
and by capture time the animation had moved on. I only caught it because a frame
at progress 1.0 still showed the overlay, which contradicted the code.

The fix was not just reasserting the value at capture — it was making the tool
**print the value it actually captured**. A review tool that cannot tell you
what it rendered is worse than no tool, because it launders a wrong frame as
evidence. Any future capture flag should read back and report.

### Research that argues against the feature is the most useful kind

This round's brief was "more animations". The strongest source I found was the
critique counting **29 HUD elements, 87% of which move unasked, 6 of which risk
startle by expanding in place**. That is an argument *against* the request as
stated.

It did not mean refusing — it meant the difference between decoration and a
motion *language*: ambient motion is slow, low-contrast, behind everything, and
switchable off; nothing expands in place; nothing relocates a reading. The
`--no-ambient` flag and the `visible`-gating exist entirely because of that
critique. Taking the brief seriously meant finding the constraint that makes it
good, not maximising the literal ask.

### Small things

- A `Row` sizes to its *visible* children. Animating per-letter opacity inside
  one makes the whole word creep sideways. Fixed positions, measured from the
  font, are the answer for text that reveals.
- `Behavior` cannot animate a `readonly property` — the error says "Invalid
  property assignment", which does not point at the `Behavior`.
- An overlay without an opaque backdrop composites over live content and both
  become unreadable. Obvious in hindsight; invisible until rendered.
- Every new infinite animation needs gating on both the master switch *and*
  `visible`. Easy to add the first and forget the second.

## Round 4 — the assistant orb

**A refusal that the render tool exposed.** `headless_render.py` was asking for
`SPEAKING` and quietly getting `STANDBY`. The cause was not a bug in the orb: it
was the state machine correctly rejecting an illegal `STANDBY -> SPEAKING` jump
and logging the refusal to the console, where the screenshot dutifully captured
it. Two lessons. Rendering the wrong thing successfully is worse than crashing,
so the tool now fails loudly when it does not arrive at the requested state.
And a tool that drives a system under test must obey that system's rules rather
than assume it can set any field it likes.

**`readonly` and `Behavior` remain incompatible, and the linter does not care.**
`swell` was declared `readonly` with a `Behavior` attached. `pyside6-qmllint`
passed it clean; the runtime rejected it on the first frame. This is the second
time this exact trap has cost a cycle. Static analysis here covers types and
names, not the animation system — anything animated has to be seen running.

**Coherence is a correctness property, not a polish item.** During a fault the
orb went red but two standing arcs stayed cyan, because they were hardcoded to
`primaryDim` rather than derived from the tint. It read as "partly fine", which
is a false statement about system state. Any element that can be present during
a fault must derive its colour from the fault, not merely most of them.

**Three test failures, zero component bugs.** All three came from the harness:
`anchors.fill` silently overrode the width the clamping test was setting, so it
asserted against an unchanged 100 bars, and `swell` could not be read
synchronously once a `Behavior` eased it. A test that passes for the wrong
reason is the real hazard — the sizing test would have "passed" at any clamp
values had the range been wider.

**What was refused.** The 120 rim bars are tempting to drive from audio
amplitude. There is no audio: `PySide6.QtMultimedia` is not installed, verified
by import. Sizing bars from an invented signal would have looked convincing and
been a lie, so the ring encodes state only (D20). Likewise `EXECUTING` renders
no progress arc unless a caller supplies a real `activity` value; the default of
`-1` means "unknown" and draws nothing.

## Round 5 — lighting

**`MultiEffect` is a trap on this deployment.** It is the obvious tool for
bloom, it is present in the runtime, and `pyside6-qmllint` accepts it happily.
Under `QT_QUICK_BACKEND=software` it renders the source item as *nothing at
all* — not an unblurred fallback, but a blank rectangle. I only caught it
because I rendered the effect and its control side by side before building on
it. An always-on HUD cannot ship a decoration that can silently erase content
on a machine with no working GL, so the bloom is built from radial gradients
instead, which the software renderer draws correctly.

**Opaque fills defeat their own glow.** Both the orb core and the reactor
centre had solid gradient fills. Adding a bloom behind them produced a bright
ring around a black hole: the brightest object on screen was punched out at its
own centre. Making the fills translucent was what turned "a circle with a halo
sticker" into "a light source". The general rule: anything meant to read as
emissive must let light pass through it.

**Animating a property that already carries a binding.** The reactor's breathing
animation drove `opacity`, and `opacity` had just been rebound to
`bootProgress`. A `SequentialAnimation on opacity` overwrites that binding
outright, so the boot fade would have been silently lost. Retargeting the
animation to `intensity` kept both behaviours. This is the same class of bug as
the `--boot-progress` `Behavior` retargeting trap from an earlier round.

**A test that asserted nothing.** My first draft of the Glow suite contained
`verify(!glow.enabled || true, "placeholder for hit-testing")` — a tautology
that can never fail, dressed as a test. Replaced with a real check: a
`MouseArea` underneath a larger glow with `z: 1`, clicked through the middle,
asserting the control below still receives the event. Bloom overlaps
neighbouring controls everywhere in this HUD, so had it been hit-testable it
would have broken input in a way no visual review would catch.

**Verified against real values, not the local machine.** The gauge backlight
looked untested on screen because this container idles near zero, so every dial
stayed dark — which is correct behaviour but proves nothing. Rendering a strip
at 5% / 55% / 93% / unavailable confirmed the load ramp and the colour handoff.
A feature that only activates under conditions the dev machine never reaches
needs a synthetic harness, or it ships unverified.

## Round 6 — taking the reference further without copying it

**The reference had four ideas worth taking and one worth refusing.** The
screenshots showed corner brackets, a large clock, a specs panel and a power
readout. The first two are pure structure and were adopted directly. The specs
panel listed "ARK-2500 Reactor / Stark Industries GFX-9000 / 128 ZB RAM" and the
power cell read a permanent 100% — decorative fiction. Refusing them outright
would have lost a genuinely good layout idea, so both were rebuilt against real
kernel sources: `/proc/cpuinfo`, `/proc/meminfo`, `/etc/os-release` and
`/sys/class/power_supply`. The panel now shows this machine's actual Xeon and
3.8 GiB, and shrinks on a host that reports less.

**A visual bug three passing tests missed.** `PowerCell` lit each segment when
charge reached its *upper* edge. At 8% on a ten-segment cell that lights
nothing, so a nearly-flat battery looked exactly like a dead one. Every unit
test passed — they checked colour and the `low` flag, never the rendered
segment count. It was only visible by rendering the four states side by side.
The lesson repeats from Round 5: this container has no battery, so the control
could never have been exercised in situ, and a synthetic harness was the only
way to see it. Now covered by a data-driven test at 0 / 0.01 / 0.08 / 0.5 / 1.0.

**Absence is not degradation.** The sampler tracks `degraded_sources` for
telemetry it *should* have read and could not. A missing battery is not that —
desktops and VMs simply have none. Filing it as degraded would have put a
permanent false "DEGRADED: battery" in the header of every desktop. Absent and
broken are different states and must stay different.

**Peripherals lie about being batteries.** `/sys/class/power_supply` contains
mains adapters, USB supplies and HID devices alongside the real cell. A naive
"read the first entry" would report a wireless mouse's charge as the laptop's.
Filtering on `type == "Battery"` is the difference between telemetry and a
plausible-looking number.

**Layout collisions do not show up in the linter.** The host panel sat directly
on top of the CPU gauge, and qmllint was perfectly happy. Anchoring the centre
stage to the panel's right edge fixed it, but only after seeing it rendered —
and the fix then had to be made conditional, because ASSISTANT mode has no
panel and was left visibly off-centre by the first version of it.

## Round 7 — softness, and using light sparingly

**I had over-applied the thing I built last round.** Round 5 added bloom and
then put it on every panel. Uniform light is not atmosphere, it is a raised
noise floor: if every frame glows, the glow distinguishes nothing. Panels now
default to dark and expose an `attention` property, and exactly two things use
it — the vitals rail while a condition is escalated, and the console for a
moment after it gains a line. The light means "look here" again because it is
no longer always on. Worth recording as a pattern: adding an effect and
applying it everywhere are two separate decisions, and the second one deserves
its own scrutiny.

**Two dimming factors stacked to zero.** Converting the orb's standing arcs to
tapers, I kept their existing `tintDim` colour. The taper supplies falloff and
`tintDim` supplies falloff, so the arcs vanished entirely against the core
bloom — the render came back with a visibly empty ring. When swapping a
technique in, check what the old technique was already doing; the two are not
additive in the way you expect.

**`Repeater` cannot produce `ShapePath`.** It requires `Item` delegates and
emits "Delegate must be of Item type", then draws nothing. Building the
segments imperatively into `Shape.data` works, but trades a declarative
guarantee for manual lifetime management — which is exactly where the next bug
came from.

**The manual leak probe passed; the real test failed.** I checked for leaked
segments by logging `Shape.data.length` after thrashing the sweep, and it
reported the correct 30. The QML test reported 60. The probe was wrong:
`destroy()` is deferred to the next event-loop pass, and `data` is not
notifiable, so the reading was stale twice over. The leak was real and would
have grown every time an animated sweep crossed a segment-count boundary.
Fixed by tracking the created objects in an owned list and releasing them on
destruction. The lesson is uncomfortable: I nearly accepted a hand-rolled check
as verification when it was measuring the wrong thing at the wrong time.

**Being precise about what multisampling does.** It was tempting to describe
`setSamples(4)` as fixing the "too solid" look. It does not: it is inert under
the software backend used for every screenshot in this repo, and `Shape` with
`CurveRenderer` already antialiases. It genuinely helps `Rectangle` borders and
rotated edges on the hardware path, which is worth having, and the comment in
`__main__.py` now says exactly that and nothing more. The softness the user
asked for came from the taper, not from MSAA.

## Round 8 — wiring to the real backend

**Reading the docs would have shipped a lie.** The backend publishes
`jarvis_do` as `explicit-allow`, and the obvious implementation is a
confirmation dialog on every `do`. I nearly built that. Driving the actual
kernel instead showed something different: `jarvis_do "install htop"` ran
`apt-get install -y -- htop` immediately, with no refusal and nothing to
approve. The gate is per-*tier*, not per-tool — only tier 2 asks, and tier 3
refuses no matter what anyone clicks.

Both possible UIs built on the doc-only reading would have misrepresented the
system. A dialog on every `do` implies the GUI is holding the gate when the
kernel is; no dialog at all would have missed the tier-2 case entirely. The
correct design — surface the kernel's decision, never invent one — was only
visible from the live behaviour. Two probes against a running binary were worth
more than the whole document.

**`isError` means two different things.** A refusal and a genuine failure both
arrive with `isError: true`, separated only by `outcome.status == "refused"`.
Had I taken the flag at face value, the HUD would have reported the safety
kernel *working correctly* as a malfunction — teaching the operator to distrust
exactly the component most worth trusting.

**A bug that tests would not have caught.** I wired the consent path referencing
`self._last_do_request`, a field I never assigned. Every unit test passed;
`import` succeeded; qmllint was clean. It would have raised `AttributeError` the
first time a real tier-2 refusal arrived — that is, only ever in front of a user,
only ever at the security-critical moment. It surfaced because I ran the whole
flow against the live kernel rather than trusting green gates. Static checks
verify the paths you wrote; only execution verifies the paths you forgot.

**Designing a dialog to be hard to answer.** The consent prompt has no default
button, no focus, no Enter binding and no timeout, and its buttons are
pointer-only. Every one of those is a deliberate removal of a convenience.
Consent that a keyboard rhythm can complete by accident is not consent, and an
unattended machine must not drift into either answer. Escape declines, because
the reflexive exit should be the safe one.

**Honest discovery, not helpful guessing.** `available()` initially returned
false whenever the kernel lived in a venv rather than on `PATH`. The fix was to
search exactly one additional location — the running interpreter's own bin
directory, which is unambiguously the same install — and stop there. Scanning
likely paths would have been more convenient and would have meant the GUI could
execute a binary the operator never pointed it at.

I did not run the approve path to completion: it was a real `apt` upgrade in
this sandbox. I verified that consent is re-sent verbatim with `allow: true` and
that the kernel accepts it, then cut the process off. Recording that boundary
matters more than claiming a clean finish.

## Round 9 — aligning with a backend that moved eight versions

The kernel went 1.10.2 → 1.18.0. The tool surface did not change at all: still
six tools, same schemas, same contract id. Everything that mattered was
underneath, and none of it was reachable by reading the wiring doc — which was
last revised for 1.12.0 while the kernel shipped 1.18.0. **A stale integration
doc is more dangerous than a missing one**, because it reads as current. Every
claim in this round came from driving the running binary.

**The bug I went looking for.** Last round I found that `jarvis_do` gates by
tier, not by tool. This round I pushed on that and found the corollary:

    do remove the file /tmp/x  ->  tier 1, ran immediately, undo: unavailable

An irreversible deletion with no prompt. The kernel is *right* — `rm` of a
user-owned file is user-level, and demanding system-level consent for it would
be wrong. But "how much authority does this need" and "can this be taken back"
are different questions, and only the first was being asked. The owner told me
to handle both, and the shape that fell out was two gates that are deliberately
different in kind: one grants authority and cannot be disabled, one
acknowledges risk and grants nothing. I made them different colours and
different verbs — "APPROVE AND RUN" versus "RUN ANYWAY" — because if both
prompts look the same the owner learns to dismiss both, and the one that
carries real authority is the one that suffers.

The gate is driven entirely by the kernel's own `undo.status`. I considered a
list of dangerous-looking verbs and rejected it: it would be security theatre,
and it would disagree with the kernel about what a request actually does.
`none_needed` counts as reversible; anything unrecognised counts as
irreversible, because optimism about reversibility is the one error that cannot
be corrected afterwards.

**Refusing to reuse the backend's own voice command.** `jarvis voice ask`
records, transcribes, and *runs* the request. Wiring the GUI to it would have
been three lines and would have quietly bypassed both gates — a misheard
sentence would reach the kernel without the owner ever seeing the words. So the
GUI uses only the first half of the pipeline and puts the transcript in the
input field. Speech is a keyboard that can mishear. ADR-0019 says voice must
never manufacture consent; here it cannot even initiate an action.

**`str()` on a QByteArray is a silent liar.** Reading the doorway's version, my
first attempt was `str(reply.rawHeader("Server"))`, which returns the Python
*repr* — `"b'jarvis-serve/1.18.0'"` — and parsed to an empty string. No error,
no warning; the UI would just have said the version was unknown forever. It
surfaced only because I printed the value during a live probe instead of
trusting that a plausible-looking line worked. The same lesson as the `destroy()`
leak two rounds ago: plausible code plus no observation equals no verification.

**Verifying a security posture instead of citing it.** ADR-0018 lists the
doorway's hardening. I ran it and checked: 401 unauthenticated, 421 on a foreign
Host header, 0600 token, token absent from the logs. All true. Citing the ADR
would have been faster and would have been an assumption; the four probes cost
a minute and turned it into a fact. I also refuse a token file that is
group-readable — if another account can read it, that account can already act
as the owner, and papering over that would be the wrong help.

**One classifier, two transports.** It was tempting to give the HTTP path its
own outcome parsing, since its envelope differs (decoded object versus a JSON
string needing a second parse). I normalised HTTP into the stdio shape instead.
The refusal-versus-failure distinction is the one piece of logic in this bridge
that must never drift, and two implementations of it are two places for it to.

**What I did not verify.** The spoken loop has never run against real
`arecord`/`whisper` binaries — they are not installed here, and I tested with
stubs I wrote myself. The argv matches the kernel's own and is unit-tested, but
no microphone has been exercised, and the docs say so rather than implying a
working feature.

**The defect I found by attacking my own work.** After the gates passed all
their tests, I went looking for a case the tests could not see: what happens to
the *cached plan* when no preview runs? Under `confirm kernel-only` the GUI
sends `do` directly, so `_last_plan` still holds whatever the last `plan`
command produced. I drove it live — `plan remove the file /tmp/zzz`, then
`do upgrade the whole system` — and the consent prompt for the upgrade rendered
`rm -f /tmp/zzz` as the command that would run.

The owner would have been reading one command while approving another, in the
one dialog where that matters most. Every unit test passed, mypy was clean, and
the render looked perfect, because the bug lived in the relationship between
two pieces of state rather than in either one. The fix pins each plan to the
request it was computed for and shows nothing when they disagree — an empty
plan block is honest; a confident wrong one is not.

Two rounds running, the serious bug has been in a path the gates cannot reach
and only adversarial live driving exposed. I have stopped treating a green
check run as evidence that a security-relevant flow is correct; it is evidence
that the flows I thought to write down are correct.
