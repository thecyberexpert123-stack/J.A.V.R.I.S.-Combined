pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import javris.ui

/*!
    The power-on sequence: streaks converge from beyond the frame, rings trace
    themselves in, and the name assembles letter by letter.

    This is the HUD's "alpha event" (docs/RESEARCH.md, D16) — the one moment
    the interface is allowed to be theatrical, because it is the moment the
    system is genuinely coming up and there is no data to obscure yet.

    Two research principles drive the choreography:

    \list
    \li \b{D15, motion creates depth.} The original HUD team's rule was to let
        the Z-axis work by having elements arrive from beyond the frame. There
        is no 3D here and none is needed: streaks fly in from well outside the
        radius, and each layer runs on its own clock, which is what actually
        reads as depth.
    \li \b{D17, nothing snaps.} Every element traces, converges or fades. None
        of them simply appear.
    \endlist

    The sequence is driven by a single \l progress value rather than by a chain
    of timers, so it is deterministic, seekable and testable: setting
    \c progress to 0.5 always produces the exact same frame.
*/
Item {
    id: root

    /*! 0.0-1.0 through the sequence. Drive this; do not drive the children. */
    property real progress: 0
    /*! Text assembled letter by letter in the final phase. */
    property string title: "J.A.V.R.I.S."
    /*! Number of converging streaks. Scales down on small surfaces. */
    property int streakCount: Math.max(18, Math.min(56, Math.round(width / 12)))

    /*! Phase boundaries, exposed so tests assert the order rather than timings. */
    readonly property real phaseStreaks: 0.45
    readonly property real phaseRings: 0.68

    /*! Sub-progress of each phase, each 0.0-1.0. Read by tests. */
    readonly property real streakProgress: Math.min(1, root.progress / root.phaseStreaks)
    readonly property real ringProgress: Math.max(0, Math.min(
        1, (root.progress - 0.15) / (root.phaseRings - 0.15)))
    readonly property real titleProgress: Math.max(0, Math.min(
        1, (root.progress - root.phaseRings) / (1 - root.phaseRings)))

    // Opaque backdrop. Without it the live HUD shows through the sequence and
    // the two compete - the boot moment has to own the screen to read as one.
    // It clears just before the title lands, so the HUD is revealed underneath
    // rather than the overlay simply vanishing.
    Rectangle {
        anchors.fill: parent
        color: Theme.backgroundDeep
        opacity: 1 - Math.max(0, Math.min(1, (root.progress - 0.55) / 0.35))
    }

    readonly property real centreX: width / 2
    readonly property real centreY: height / 2
    readonly property real coreRadius: Math.min(width, height) * 0.22

    // -- converging streaks ------------------------------------------------
    // They start at 2.6x the core radius, which is outside the visible group
    // for typical geometry - the "arriving from beyond the frame" read.
    Item {
        anchors.fill: parent
        opacity: root.streakProgress * (1 - root.titleProgress * 0.7)

        Repeater {
            model: root.streakCount

            delegate: Rectangle {
                id: streak

                required property int index

                // Deterministic pseudo-scatter: a golden-angle walk gives an
                // even, non-repeating distribution without a random seed, so
                // the sequence renders identically every run.
                readonly property real angle: streak.index * 2.399963
                readonly property real phase: (streak.index % 7) / 7
                readonly property real travel: Math.max(
                    0, Math.min(1, (root.streakProgress - streak.phase * 0.35) / 0.65))
                readonly property real distance: root.coreRadius
                    * (2.6 - 1.5 * streak.travel)

                // Long and thin so it reads as a streak of energy in motion,
                // not a tick mark. Length also tapers as it arrives.
                width: root.coreRadius * (0.34 - 0.22 * streak.travel)
                height: Theme.strokeMedium
                color: Theme.accent
                antialiasing: true

                x: root.centreX + Math.cos(streak.angle) * streak.distance - width / 2
                y: root.centreY + Math.sin(streak.angle) * streak.distance - height / 2
                rotation: streak.angle * 180 / Math.PI

                // Fade in on arrival and out again at the core, so streaks
                // read as energy being drawn in rather than as debris landing.
                opacity: streak.travel <= 0 ? 0
                         : (streak.travel < 0.75 ? streak.travel : (1 - streak.travel) * 4)
            }
        }
    }

    // -- tracing rings -----------------------------------------------------
    // Each ring traces at its own rate and to its own extent. Qt has no
    // stroke-dashoffset animation, so the equivalent is sweeping the arc.
    Shape {
        anchors.fill: parent
        asynchronous: true
        preferredRendererType: Shape.CurveRenderer
        opacity: root.ringProgress

        ShapePath {
            strokeColor: Theme.primary
            strokeWidth: Theme.strokeMedium
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap

            PathAngleArc {
                centerX: root.centreX; centerY: root.centreY
                radiusX: root.coreRadius; radiusY: root.coreRadius
                startAngle: -90
                sweepAngle: 360 * root.ringProgress
            }
        }

        ShapePath {
            strokeColor: Theme.primaryDim
            strokeWidth: Theme.strokeThin
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap

            PathAngleArc {
                centerX: root.centreX; centerY: root.centreY
                radiusX: root.coreRadius * 1.28; radiusY: root.coreRadius * 1.28
                startAngle: 90
                sweepAngle: -300 * Math.min(1, root.ringProgress * 1.2)
            }
        }

        ShapePath {
            strokeColor: Theme.accent
            strokeWidth: Theme.strokeThin
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap

            PathAngleArc {
                centerX: root.centreX; centerY: root.centreY
                radiusX: root.coreRadius * 0.66; radiusY: root.coreRadius * 0.66
                startAngle: 200
                sweepAngle: 260 * Math.max(0, Math.min(1, (root.ringProgress - 0.3) / 0.7))
            }
        }
    }

    // -- core spark --------------------------------------------------------
    Rectangle {
        width: root.coreRadius * 0.16 * root.ringProgress
        height: width
        radius: width / 2
        x: root.centreX - width / 2
        y: root.centreY - height / 2
        color: Theme.primary
        opacity: root.ringProgress * (1 - root.titleProgress * 0.5)
    }

    // -- title assembly ----------------------------------------------------
    // Letters are laid out at fixed positions rather than in a Row: a Row
    // sizes itself to its visible children, so as letters revealed the whole
    // word crept sideways instead of staying centred.
    Item {
        id: titleBlock

        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.verticalCenter
        anchors.topMargin: root.coreRadius * 1.25
        width: root.title.length * titleBlock.cellWidth
        height: Theme.fontSizeXl * 1.4
        opacity: root.titleProgress > 0 ? 1 : 0

        // Measured from the font rather than guessed, so the spacing holds if
        // the type scale or the family changes.
        readonly property real cellWidth: titleMetrics.width + Theme.letterSpacingWide

        Text {
            id: titleMetrics
            visible: false
            text: "W"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeXl
        }

        Repeater {
            model: root.title.length

            delegate: Text {
                id: glyph

                required property int index

                // Each letter has its own slice of the title phase, so they
                // resolve in sequence. The overlap (0.55 of the window) keeps
                // it flowing rather than metronomic.
                readonly property real slice: glyph.index / Math.max(1, root.title.length)
                readonly property real reveal: Math.max(0, Math.min(
                    1, (root.titleProgress - slice * 0.55) / 0.45))

                text: root.title.charAt(glyph.index)
                color: Theme.primary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeXl

                x: glyph.index * titleBlock.cellWidth
                opacity: glyph.reveal
                // Rise into place: the reference motion has letters translate
                // up as they sharpen.
                y: (1 - glyph.reveal) * Theme.spaceMd
                scale: 0.8 + 0.2 * glyph.reveal
            }
        }
    }
}
