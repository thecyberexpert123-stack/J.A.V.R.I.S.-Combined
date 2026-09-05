# Design System — the component bible

Modelled on the "HUD Bible" that governed the original design work: every component is
documented with its purpose, the information it carries, and the rules it must obey
([`CREDITS.md`](./CREDITS.md)).

**The governing rule:** every element must carry information. If it cannot state what
it tells the operator, it does not belong on screen.

## Tokens

All tokens live in `src/javris/ui/Theme.qml`, a QML singleton. **No component may
declare a literal colour, spacing value or duration.** Changing the design language
happens in one file.

### Colour

| Token | Value | Meaning |
|---|---|---|
| `background` / `backgroundDeep` | `#04080c` / `#010305` | Field, top and bottom of the gradient |
| `panel` | `#0a1620` | Panel fill |
| `grid` | `#0e2735` | Background grid rules |
| `primary` | `#3fe0ff` | Active elements, live data |
| `primaryDim` | `#1c7d96` | Idle elements |
| `primaryFaint` | `#0f3d4a` | Frames, unfilled gauge tracks |
| `accent` | `#ffb648` | Current mode indicator |
| `textPrimary` / `textSecondary` / `textMuted` | `#c8f4ff` / `#6f9fb0` / `#40606d` | Values / labels / units |
| `ok` / `warn` / `error` | `#4dffb8` / `#ffb648` / `#ff5f6d` | Severity |
| `unavailable` | `#4a5a63` | **No reading available** — never used for a real value |

Cyan-on-near-black follows the documented palette of the source material
([`RESEARCH.md`](./RESEARCH.md) D1).

### Load colour is semantic, not decorative

`Theme.loadColor(fraction)` maps utilisation to the palette so pressure can be read
without reading digits:

| Range | Colour |
|---|---|
| `< 0` | `unavailable` |
| `0.0 – 0.7` | `primary` |
| `0.7 – 0.9` | `warn` |
| `≥ 0.9` | `error` |

### Spacing, motion, type

- Spacing sits on a 4 px grid: `spaceXs` 4, `spaceSm` 8, `spaceMd` 16, `spaceLg` 24,
  `spaceXl` 40.
- Motion is short and instrument-like: `durationFast` 120 ms, `durationNormal` 220 ms,
  `durationSlow` 300 ms (the mode cross-fade budget), `durationBoot` 1800 ms. Easing is
  `Easing.OutCubic`.
- Type is monospace throughout, so telemetry columns do not reflow as digits change.
  Labels are upper-case with wide tracking; values are plain.

## Components

### `Theme` (singleton)
Design tokens and the two semantic functions `loadColor` and `severityColor`.

### `Panel`
Framed surface with cut corners and a titled header rule. Sizes itself to its content
by default, so a caller never has to compute a height from the very children the panel
contains. Built as one `Shape` with one `ShapePath`, per Qt's guidance that path
geometry is triangulated on the CPU.

### `Gauge`
Radial gauge carrying **label, value and unit** — all three, always. A negative value
means unavailable: the arc is not drawn and the readout shows `--`. It never renders a
fabricated number. `sweepAngle` is exposed and directly unit-tested.

### `ReactorCore`
The central instrument. Every ring means something:

| Ring | Encodes |
|---|---|
| Outer arcs (clockwise) | Assistant state, via rotation rate; stationary when faulted |
| Inner arcs (counter-clockwise) | Depth and activity |
| Tick ring | The fixed scale the load arc is read against |
| Load arc | CPU load, by sweep and by colour |
| Inner ring pulse | Load, by amplitude, for peripheral awareness |
| Centre readout | The exact figure, with its unit |

Rotation periods: `PROCESSING` 2600 ms, `EXECUTING` 3400 ms, `SPEAKING` 4200 ms,
`LISTENING` 5200 ms, `BOOTING` 1800 ms, `STANDBY` 14000 ms, faulted 0 (stopped).

Glow is produced by layering a wide translucent stroke beneath a narrow bright one,
not by a shader: Qt 6 requires shaders pre-baked to `.qsb`, and that toolchain is
unavailable in the development sandbox. Layered strokes are fully scene-graph native.

Note the property is `coreState`, not `state` — `state` is a built-in `QQuickItem`
property and binding to it would have silently misbehaved.

### `TelemetryRow`
One labelled line: name left, value and unit right, optional load bar beneath. The
value elides rather than overlapping the label. `--` renders in `unavailable`.

### `LogStream`
Severity-coloured auto-scrolling console. Lines arrive as `SEVERITY\x1fmessage`; the
router strips control characters from user input, so a message cannot forge a severity
tag.

### `HudGrid`
Background field: faint grid plus a slow vertical scan line. Line count is bounded by
cell size, so cost scales with window size.

## Modes

Modes recompose the entire surface rather than swapping a tab
([`RESEARCH.md`](./RESEARCH.md) D2). Both are instantiated and cross-faded within the
300 ms budget.

- **`DiagnosticsMode`** — "what is loaded right now, and by how much": three large
  gauges, per-core bars with numeric readouts, storage pressure.
- **`MonitorMode`** — sustained ambient awareness: reactor core centred, with storage
  and network panels flanking it.

## Accessibility and honesty rules

1. **Every numeric readout carries a name and a unit.** This directly fixes the
   cognitive-load flaw identified in the source material ([`RESEARCH.md`](./RESEARCH.md) D8).
2. **Unavailable is a distinct visual state**, never zero and never a plausible guess.
3. **Colour is never the only channel.** Load is shown by arc length and bar height as
   well as by hue.
4. **Motion always means something.** Nothing animates purely for effect; a stopped
   ring is itself the signal that the system has faulted.

---

## Attention escalation

The behaviour that most distinguishes this HUD from a dashboard. Full rationale
and citations in `docs/RESEARCH.md` §7 (principles D9-D13).

### The rule

> A critical condition shown only in the periphery is a **failed** notification.

Peripheral gauges do not capture attention, because foveal vision is narrow. So
when a metric goes bad while it is *not* already central, the HUD promotes it
into the middle of the display and dims everything else.

### Where the policy lives

| Concern | Location | Why |
|---|---|---|
| When to escalate, hysteresis, priority | `src/javris/attention.py` | Pure Python, unit-testable without Qt |
| Which metrics are central per mode | `_CENTRAL_METRICS` in `controller.py` | Must be kept in step with the mode QML |
| How it looks | `ui/components/AlertBanner.qml` | Presentation only; decides nothing |
| Acquisition motion | `ui/components/TargetReticle.qml` | Reusable; also usable outside alerts |

### Thresholds

| Constant | Value | Meaning |
|---|---|---|
| `WARN_THRESHOLD` | 0.70 | Matches `Theme.loadColor`, so the banner and the small gauge never disagree |
| `ERROR_THRESHOLD` | 0.90 | Renders as `CRITICAL` in `Theme.error` |
| `RELEASE_MARGIN` | 0.05 | Hysteresis band; below this the alert may clear |
| `RAISE_SAMPLES` | 3 | ~3 s at the default poll interval — a sustained condition, not a spike |
| `CLEAR_SAMPLES` | 3 | Sustained recovery required before releasing |

### The gaze proxy — and its honest limits

The reference system escalates when it detects the operator is *not looking* at
the gauge. **We have no eye tracker and do not pretend to.** The documented
substitute is `Prominence`:

- `CENTRAL` — the metric is already a large element near the middle in this
  mode. **Never escalated**; it is already doing escalation's job.
- `PERIPHERAL` — the metric appears only as a small rail row. **Escalatable.**

`_CENTRAL_METRICS` currently maps `DIAGNOSTICS` → cpu, memory, swap (three large
gauges) and `MONITOR` → cpu (the reactor core). **Changing a mode's layout
requires updating this table**, or the HUD will either escalate something the
operator is staring at or fail to escalate something they cannot see.

### Release conditions

Two conditions release an alert **immediately, without hysteresis**, because
neither is a value oscillation and delaying them would leave something untrue on
screen:

1. **The metric became unavailable.** Holding the last known number as a live
   alert would be a fabricated reading.
2. **The metric became central** (the operator changed mode). They are now
   looking straight at it.

Falling below `WARN_THRESHOLD - RELEASE_MARGIN` for `CLEAR_SAMPLES` polls is the
only *streaked* release.

### Invariants

- **At most one alert at a time.** Escalating two things recreates the
  attention-splitting the mechanism exists to prevent. Worst severity wins;
  highest fraction breaks ties; the key is the final, deterministic tiebreaker.
- **An unavailable metric is never escalated.** No data is not evidence of a
  fault.
- **The header never contradicts the banner.** While an alert is up the status
  reads `WARN`/`CRITICAL`, never `NOMINAL`.
- **An active alert never renders in a calm colour.** Inside the hysteresis band
  the raw classification is `NORMAL`; the alert reports `WARN` instead.
- **The console announces each escalation once**, on the transition — not once
  per poll.

### Suppression

`surface.suppression` (0.28 while an alert is active) multiplies the opacity of
both modes and the vitals rail. Lower-priority data **recedes but does not
vanish**, so the operator can still see the rest of the system is being watched.
The banner's own backdrop is fully opaque: at 0.88 the reactor core ghosted
through the hero readout, which is precisely the low-contrast failure D10 warns
against.

### Type

`Theme.fontSizeHero` (64 px) exists only for the escalated readout. D10 calls
for **high contrast and large type**, not more detail — the banner carries one
number and one sentence, deliberately.

---

## Motion language

Research and citations in `docs/RESEARCH.md` §13-16 (principles D15-D19).

### The two rules that govern everything here

1. **Motion creates depth** (D15). The original HUD supervisor's rule was to
   "let the Z-axis work", and his colleague is explicit that the depth came
   from *how elements moved*, not from perspective. We have no 3D and need
   none: staggered timing and per-layer parallax do the work.
2. **Motion must never startle or displace** (D18). The same body of criticism
   counts 29 elements in the reference HUD, of which **87% reposition
   themselves unasked** and **6 risk startle by expanding in place**. That is
   the failure mode this project is explicitly avoiding.

### What is allowed to move, and what is not

| Allowed | Forbidden |
|---|---|
| Rotating decorative rings | Moving a readout the operator may be reading |
| Drifting motes, scanline, vignette | Expanding anything quickly in place |
| Glow / breathing luminance | Animation that delays a reading |
| Staggered entrances, parallax | Ambient motion that cannot be switched off |

The single exception is attention escalation (D9), which *does* take over the
centre of the display — deliberately, rarely, and damped by hysteresis.

### Motion tokens

| Token | Value | Use |
|---|---|---|
| `periodDrift` | 22000 ms | Mote lifespan |
| `periodScanline` | 9000 ms | One scanline traverse |
| `periodBreath` | 4200 ms | Core luminance swell |
| `periodSweep` | 3600 ms | PROCESSING radar sweep |
| `staggerStep` | 70 ms | Gap between successive entrances |
| `parallaxFar/Mid/Near` | 0.22 / 0.55 / 1.0 | Per-layer depth factor |
| `parallaxRange` | 14 px | Maximum excursion — small on purpose |

Periods are mutually non-harmonic so the field never visibly loops or beats.

### Layer depth map

| Layer | Parallax | Notes |
|---|---|---|
| `HudGrid`, `AmbientField` | `parallaxFar` | Background plate |
| Mode surface | `parallaxMid` | Gauges, reactor core |
| Vitals rail, console | `parallaxNear` | Foreground chrome |

### Boot sequence

`BootSequence.qml` is a **pure function of `progress`** — no timer chain. The
same value always yields the same frame, which is what makes it reviewable from
a still and testable without waiting on animations.

| Phase | Range | What happens |
|---|---|---|
| Streaks | 0.00 – 0.45 | Energy converges from 2.6x the core radius |
| Rings | 0.15 – 0.68 | Three rings trace at different rates |
| Title | 0.68 – 1.00 | Letters rise and sharpen, staggered |
| Handoff | 0.55 – 0.90 | Backdrop clears; HUD chrome enters behind it |

Entrance staggering uses `HudSurface.entrance(threshold)`. Letters are placed at
**fixed offsets**, not in a `Row`: a `Row` sizes to its visible children, so the
word crept sideways as letters revealed.

### Alpha events

Rule three from the original team: every shot carries an "alpha event" — a
graphic that punctuates the moment, usually subtle. Here a **state change**
fires `ReactorCore.pulse()`, emitting one ring that travels *outward*. It
travels rather than expanding in place precisely because D18 forbids the latter.

### The off switch

`Theme.ambientMotion` (CLI: `javris --no-ambient`) stops **all** decorative
motion. It deliberately does **not** touch informational motion — escalation,
gauge transitions, state colour — because suppressing those would hide data.

Every ambient animation must additionally stop when its item is not `visible`.
An unseen HUD must burn no cycles; `AmbientField.running` and
`ReactorCore.animating` encode this and are asserted by tests.

## Light

The HUD is an emissive display: elements should read as *lit*, not *drawn*.
Bloom is what separates a wireframe diagram from an instrument that is powered.

### The `Glow` component

A soft radial bloom, placed behind the element it lights and centred on it.

```qml
Glow {
    anchors.centerIn: ring
    size: ring.width * 1.8      // typically 1.5-2x the lit element
    color: Theme.primary
    intensity: Theme.glowNormal * Theme.glowScale
}
```

**Why not `MultiEffect`.** Qt's blur effect requires a GPU shader path. Under
`QT_QUICK_BACKEND=software` it renders its source item as nothing at all rather
than degrading gracefully, which would blank real content on a machine without
working GL. `Glow` uses a three-stop radial gradient, which every renderer
draws. Verified by rendering both paths side by side.

### Intensity tokens

| Token | Value | Use |
|---|---|---|
| `Theme.glowSubtle` | 0.16 | Ambient fields, panel edges, resting states |
| `Theme.glowNormal` | 0.30 | The wordmark, breathing peaks |
| `Theme.glowStrong` | 0.48 | Hot cores — the single brightest point of an element |
| `Theme.glowScale` | 1.0 | Master multiplier; set to 0 to extinguish all bloom |

Always multiply by `Theme.glowScale`, never hardcode an intensity.

### Rules

1. **Glow is decorative and never load-bearing.** Every element must remain
   fully legible with `glowScale` at 0. A glow may reinforce a meaning that is
   already carried by shape, colour or text — it may never be the only carrier.
2. **Emissive elements must be translucent.** An opaque fill over a bloom
   punches a dark hole through the centre of its own light. Core discs use
   alpha so the glow reads through them.
3. **Brightness may encode magnitude, never invent it.** The gauge backlight
   scales with the measured value and emits nothing when the reading is
   unavailable. Do not animate brightness to imply activity that is not
   happening (D20).
4. **Faults dim rather than flare.** A faulted core uses `glowSubtle`, not
   `glowStrong`: a fault is not a mood, and a bright red bloom reads as power
   rather than failure.


## Where light is allowed

Bloom is a signal, not a surface treatment. If everything glows, the glow says
nothing and the display's noise floor simply rises.

**Lit by default** — elements that genuinely emit:

- the assistant orb's ambient field and hot core;
- the reactor core's aperture and breathing halo;
- the wordmark;
- a gauge's dial, scaled by its measured value.

**Lit only on an event** — `Panel.attention`, off by default:

- the vitals rail, while a condition is escalated;
- the console, briefly after a line is appended.

**Never lit** — everything structural: corner brackets, the grid, panel frames
at rest, the fact list, tick scales, the outer boundary ring.

Before adding a glow, answer: *what does it mean when this is lit, and what
does it mean when it is not?* If the second answer is "nothing, it is always
lit", it is decoration and does not belong.

## Softness

Uniform strokes are what make a Qt Quick HUD look rigid. A `PathAngleArc` with
one `strokeColor` has identical weight at both ends, so it reads as a machined
part and its start and end points -- which are arbitrary -- become the most
conspicuous thing about it.

`TaperedArc` fades a stroke along its length:

```qml
TaperedArc {
    anchors.fill: parent
    arcRadius: radius * 0.8
    startAngle: 24
    sweepAngle: 132
    color: Theme.primary
    peakPosition: 0.62   // 0.5 symmetric, near 1.0 for a comet profile
    falloff: 1.2         // higher concentrates the light
}
```

Rules:

1. **One dimming factor, not two.** A tapered arc uses the full tint. Applying
   `primaryDim` *and* a taper stacks two falloffs and the arc disappears.
2. **Leave one fixed reference.** The orb's outer dashed ring stays uniform on
   purpose: everything inside it moves and fades against it, and if that also
   tapered there would be nothing steady to read the motion against.
3. **Comet profiles carry direction.** `peakPosition` near 1.0 puts the light at
   the leading end, so rotation direction is legible from a still frame.

### What multisampling does and does not do

`QSurfaceFormat.setSamples(4)` at startup helps `Rectangle` borders and rotated
edges **on the hardware path only**. It is inert under
`QT_QUICK_BACKEND=software`, and `Shape` with `CurveRenderer` antialiases
independently of it. It is not the source of the HUD's softness -- the taper is.
