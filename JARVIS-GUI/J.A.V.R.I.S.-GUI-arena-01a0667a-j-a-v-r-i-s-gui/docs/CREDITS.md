# Credits and Attribution

No third-party source code is copied into this repository. What follows credits the
ideas, research and prior art that informed the design, as required by the project's
guidelines.

## Design language research

The visual system is derived from the published accounts of the people who created the
original Iron Man HUD, not from imitation of screenshots. Principles D1–D8 in
[`RESEARCH.md`](./RESEARCH.md) cite these directly:

- **Jayse Hansen** — lead designer of the Mark VII HUD and Avengers screen graphics.
  His account of the "HUD Bible" and of designing each screen to carry a single clear
  message shaped our component-bible approach and the rule that every element must
  carry information.
  [Interview, The Next Web](https://thenextweb.com/news/jayse-hansen-on-creating-tools-the-avengers-use-to-fight-evil-touch-interfaces-and-project-glass)
- **Kent Seki** — HUD visual effects supervisor on the first film. His description of
  the three input paths and of the HUD converting between Analysis and Flight modes is
  the origin of our mode-driven layout requirement.
  [Oral history, vfxblog](https://vfxblog.com/ironman/)
- **Cantina Creative** — on the shift toward a volumetric, holographic treatment with
  light interaction as a design motif.
  [Maxon](https://www.maxon.net/en/article/cantina-creative-gives-iron-man-3-a-heads-up-with-maxon-cinema-4d)
- **Prologue** — process and design-test work on the Iron Man 2 HUD.
  [HUDS+GUIS](https://www.hudsandguis.com/home/2011/02/20/ironman-hud-part-3)
- **scifiinterfaces.com** — critical analysis of the HUD as an interface. Its
  identification of unlabelled cryptic telemetry as a cognitive-load failure is the
  reason every readout in this project carries a name and a unit.
  [Analysis](https://scifiinterfaces.com/2015/07/21/iron-man-hud-1-person-view/)

## Architectural patterns adapted from open-source projects

Patterns only — re-implemented from scratch in Python and QML.

- **[Open.Jarvis](https://github.com/dmrr35/Open.Jarvis)** (MIT) — the explicit
  eight-state assistant runtime (`BOOTING`/`STANDBY`/`LISTENING`/`PROCESSING`/
  `EXECUTING`/`SPEAKING`/`ERROR`/`OFFLINE`) driving the UI from a structured event
  stream, and the "keyless degraded mode" posture in which the interface remains fully
  usable with no credentials configured. Our transition table and its enforcement are
  our own.
- **[hzaid01/Jarvis](https://github.com/hzaid01/Jarvis)** — the separation of HUD
  chrome, core visualiser, system statistics and status bar into distinct components.
- **[eadmin2/jarvis_ai](https://github.com/eadmin2/jarvis_ai)** (MIT) — the idea of
  deliberate entrance choreography for panels, which informed our boot-trace sequence.
- **[adityam1313/jarvis-hud](https://github.com/adityam1313/jarvis-hud)** and
  **[MuhammadFahru/jarvis-hud](https://github.com/MuhammadFahru/jarvis-hud)** — the
  central orb with rotating rings and tick marks, and the severity-coloured streaming
  diagnostic log.

## Technical references

- **Qt documentation** — `Shape`/`ShapePath` performance guidance (prefer one `Shape`
  with several paths), the Qt 6 shader pipeline and the removal of inline GLSL, and
  Qt Quick Test with `-platform offscreen`. https://doc.qt.io/qt-6/
- **Qt Test Best Practices** — the guidance to avoid bitmap comparison as a test gate,
  which is why our screenshots are review artefacts and our assertions are on
  properties. https://doc.qt.io/qt-5/qttest-best-practices-qdoc.html
- **GTK documentation** — the GTK 4.16 deprecation of `GskGLShader`, a decisive input
  into the toolkit evaluation. https://docs.gtk.org/gsk4/class.GLShader.html

## Trademark notice

J.A.R.V.I.S. and Iron Man are trademarks of Marvel Characters, Inc. This project is an
independent, non-commercial work inspired by a fictional interface. It is not
affiliated with, sponsored by, or endorsed by Marvel or The Walt Disney Company, and
contains no assets from the films.
