pragma Singleton
import QtQuick

/*!
    The single source of truth for every colour, dimension, duration and type
    setting in the HUD. No component may declare a literal colour or magic
    number; changing the design language happens here and nowhere else.

    Palette rationale (see docs/RESEARCH.md, principle D1): cyan wireframe on
    near-black, as documented by the designers of the original HUD.
*/
QtObject {
    id: theme

    // -- colour -----------------------------------------------------------
    readonly property color background:    "#04080c"
    readonly property color backgroundDeep: "#010305"
    readonly property color panel:         "#0a1620"
    readonly property color grid:          "#0e2735"

    readonly property color primary:       "#3fe0ff"
    readonly property color primaryDim:    "#1c7d96"
    readonly property color primaryFaint:  "#0f3d4a"
    readonly property color accent:        "#ffb648"

    readonly property color textPrimary:   "#c8f4ff"
    readonly property color textSecondary: "#6f9fb0"
    readonly property color textMuted:     "#40606d"

    readonly property color ok:            "#4dffb8"
    readonly property color warn:          "#ffb648"
    readonly property color error:         "#ff5f6d"
    readonly property color unavailable:   "#4a5a63"

    // -- light --------------------------------------------------------------
    // Bloom intensities, matching the 0.1-0.5 alpha range the reference web
    // HUD uses for its 15-25px glows. Kept as tokens so the whole HUD can be
    // dimmed from one place rather than per component.
    readonly property real glowSubtle: 0.16
    readonly property real glowNormal: 0.30
    readonly property real glowStrong: 0.48

    //! Multiplier applied to every bloom. Set to 0 to disable all glow.
    readonly property real glowScale: 1.0

    // -- spacing (4px base grid) -------------------------------------------
    readonly property int spaceXs: 4
    readonly property int spaceSm: 8
    readonly property int spaceMd: 16
    readonly property int spaceLg: 24
    readonly property int spaceXl: 40

    // -- geometry ----------------------------------------------------------
    readonly property int strokeThin:   1
    readonly property int strokeMedium: 2
    readonly property int strokeThick:  3
    readonly property int cornerCut:    14

    // -- motion ------------------------------------------------------------
    // Durations are deliberately short: the HUD must feel instrument-grade,
    // not decorative. Mode changes stay within the 300ms budget in PLAN R2.
    readonly property int durationFast:   120
    readonly property int durationNormal: 220
    readonly property int durationSlow:   300
    readonly property int durationBoot:   1800
    readonly property int easing:         Easing.OutCubic

    /*!
        Easing for large or slow moves.

        OutCubic decelerates hard and then stops, which is right for a 120ms
        state flick but reads as mechanical over a long travel -- the element
        visibly arrives. OutQuint keeps a longer, softer tail, so big entrances
        settle instead of landing. Used where the eye can follow the whole
        movement.
    */
    readonly property int easingSoft:     Easing.OutQuint

    // -- ambient motion (docs/RESEARCH.md, D15-D19) -------------------------
    // Depth in the reference HUD is created by *motion*, not perspective:
    // layers moving at different rates read as separate distances. These
    // periods are deliberately long and mutually non-harmonic, so the field
    // never visibly loops or beats.
    readonly property int periodDrift:     22000
    readonly property int periodScanline:  9000
    readonly property int periodBreath:    4200
    readonly property int periodSweep:     3600

    // Stagger between successive elements in an entrance sequence. Nothing
    // arrives at once; that is what makes it read as an assembly rather than
    // a page load.
    readonly property int staggerStep:     70

    // Parallax depth factors. Larger = nearer the viewer = moves more.
    readonly property real parallaxNear:  1.0
    readonly property real parallaxMid:   0.55
    readonly property real parallaxFar:   0.22
    // Maximum parallax excursion in pixels. Small on purpose: D18 forbids
    // motion that could startle or displace something being read.
    readonly property real parallaxRange: 14

    /*!
        Master switch for ambient, non-informational motion.

        Set false to stop every decorative animation - drift, scanlines,
        breathing, parallax, ring rotation. Motion that carries *information*
        (escalation, gauge transitions, state colour) is unaffected, because
        suppressing it would hide data rather than reduce distraction.

        Exists because the source material's own critique is that a HUD of this
        kind is "a massive distraction" (D18/D19), and because a reading must
        never be late on account of decoration.
    */
    property bool ambientMotion: true

    // -- typography --------------------------------------------------------
    // Monospace throughout: telemetry columns must not reflow as digits change.
    readonly property string fontFamily: monoFont.font.family
    readonly property int fontSizeSm: 10
    readonly property int fontSizeMd: 12
    readonly property int fontSizeLg: 16
    readonly property int fontSizeXl: 28
    // Reserved for escalated alerts: research D10 calls for high contrast and
    // large type in the periphery, not more detail.
    readonly property int fontSizeHero: 64
    readonly property real letterSpacingWide: 3.0
    readonly property real letterSpacingLabel: 1.4

    readonly property Text monoFont: Text {
        font.family: "monospace"
        font.styleName: "Regular"
    }

    /*!
        Maps a normalised 0.0-1.0 load to the palette: calm cyan under load,
        amber approaching saturation, red at saturation. This is information,
        not decoration - an operator should read pressure without reading digits.
    */
    function loadColor(fraction) {
        if (fraction < 0)
            return theme.unavailable;
        if (fraction >= 0.9)
            return theme.error;
        if (fraction >= 0.7)
            return theme.warn;
        return theme.primary;
    }

    /*! Maps a log severity token to its colour. */
    function severityColor(severity) {
        switch (severity) {
        case "OK":
            return theme.ok;
        case "WARN":
            return theme.warn;
        case "ERROR":
            return theme.error;
        default:
            return theme.textSecondary;
        }
    }
}
